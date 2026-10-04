from __future__ import annotations

from datetime import datetime
from typing import Any

from django.db import transaction

from apps.hr.api.attendance.schedule import scheduled_window
from apps.hr.models import (
    AttendanceLogType,
    AttendanceSource,
    Employee,
    EmployeeAttendance,
    OrganizationAssignment,
)


def _moves(log_type: str | None) -> tuple[bool, bool]:
    """
    Sisi mana yang boleh digeser satu tap: `(masuk, pulang)`.

    `None` = tap mentah — perilaku asli writer ini: tap yang sama bisa
    menggeser jam masuk ke belakang **dan** jam pulang ke depan. Jalur
    import dan agent tidak pernah mengoper `log_type`, jadi tetap begitu.

    Tap bertipe (Self Service) hanya menyentuh sisinya sendiri. Tanpa
    ini, IN pertama pada baris yang sudah ada tapi belum punya jam
    (mis. baris BUSINESS_TRIP tulisan penutup hari) ikut mengisi
    `check_out` dengan jam masuknya.
    """
    if log_type == AttendanceLogType.IN:
        return True, False

    if log_type == AttendanceLogType.OUT:
        return False, True

    return True, True


class AttendanceImportWriter:
    @classmethod
    def get_assignment(
        cls,
        employee: Employee,
    ) -> OrganizationAssignment | None:
        return (
            OrganizationAssignment.objects
            .filter(
                employee=employee,
                is_active=True,
                is_deleted=False,
            )
            .select_related(
                "company",
                "branch",
                "location",
            )
            .order_by(
                "-organization_effective_date",
                "-id",
            )
            .first()
        )

    @classmethod
    def build_defaults(
        cls,
        *,
        employee: Employee,
        log_time: datetime,
        normalized: dict[str, Any],
        work_date=None,
        scheduled: tuple | None = None,
        source: str = AttendanceSource.IMPORT,
        log_type: str | None = None,
    ) -> dict[str, Any]:
        assignment = cls.get_assignment(
            employee,
        )

        moves_in, moves_out = _moves(log_type)

        # Tap mentah mengisi ketiganya seperti sebelumnya; tap bertipe
        # hanya sisinya sendiri.
        times: dict[str, Any] = {}

        if moves_in:
            times["check_in"] = log_time
            times["first_check_in"] = log_time

        if moves_out:
            times["last_check_out"] = log_time

        if log_type == AttendanceLogType.OUT:
            times["check_out"] = log_time

        defaults: dict[str, Any] = {
            "status":
                normalized.get("status")
                or "present",

            "source": source,

            **times,

            "external_id":
                normalized.get("external_id")
                or "",

            "device_code":
                normalized.get("device_code")
                or "",
        }

        if assignment is not None:
            defaults["company"] = (
                assignment.company
            )

            defaults["branch"] = (
                assignment.branch
            )

            defaults["location"] = (
                assignment.location
            )

        # Jadwal hari itu, dan ini yang selama ini hilang.
        #
        # `AttendancePolicyResolver.compute()` melewati baris yang
        # `scheduled_check_in`-nya kosong — dan tidak ada satu pun jalur
        # tulis yang mengisinya. Akibatnya toleransi keterlambatan yang
        # sudah diatur orang di layar Attendance Policy tidak pernah
        # dievaluasi untuk satu pun tap dari mesin fingerprint, dan
        # kolom Late di layar Attendance nol di semua baris tanpa ada
        # yang tahu kenapa.
        #
        # Pemanggil yang **sudah** menghitung jadwalnya mengopernya ke
        # sini (importer file: satu resolusi dipakai ulang untuk seluruh
        # baris pegawai yang sama, dan hari kerjanya bisa berbeda dari
        # tanggal tap-nya pada shift malam). Yang tidak mengoper apa-apa
        # — jalur agent on-premise — tetap dihitung di sini seperti
        # sebelumnya.
        if scheduled is not None:
            scheduled_in, scheduled_out = scheduled
        else:
            scheduled_in, scheduled_out = scheduled_window(
                employee,
                work_date or log_time.date(),
            )

        if scheduled_in is not None:
            defaults["scheduled_check_in"] = scheduled_in
            defaults["scheduled_check_out"] = scheduled_out

        return defaults

    @staticmethod
    def apply_policy(attendance: EmployeeAttendance) -> set[str]:
        """
        Hitung ulang angka turunannya, kembalikan kolom yang berubah.

        Dipanggil di kedua jalur — baris baru maupun tap susulan yang
        menggeser jam masuk/pulang. Tap kedua di hari yang sama mengubah
        `check_out`, dan tanpa hitung ulang, lembur serta penanda pulang
        cepatnya tetap memakai angka dari tap pertama.
        """
        from apps.hr.api.attendance.policy import AttendancePolicyResolver

        computed = AttendancePolicyResolver.compute(
            rules=AttendancePolicyResolver.rules_for(attendance.employee),
            scheduled_check_in=attendance.scheduled_check_in,
            scheduled_check_out=attendance.scheduled_check_out,
            check_in=attendance.check_in,
            check_out=attendance.check_out,
            status=attendance.status,
            break_minutes=None,
        )

        changed: set[str] = set()

        for key, value in computed.items():
            if getattr(attendance, key, None) != value:
                setattr(attendance, key, value)
                changed.add(key)

        return changed

    @classmethod
    @transaction.atomic
    def upsert(
        cls,
        *,
        employee: Employee,
        normalized: dict[str, Any],
        user=None,
        work_date=None,
        scheduled: tuple | None = None,
        source: str = AttendanceSource.IMPORT,
        log_type: str | None = None,
    ) -> tuple[
        EmployeeAttendance,
        bool,
    ]:
        """
        `source` hanya menandai baris yang **baru** dibuat; baris yang
        sudah ada tetap menyimpan sumber asalnya. `log_type` lihat
        `_moves()`. Bawaan keduanya = perilaku import/agent yang lama.
        """
        log_time: datetime = (
            normalized["log_time"]
        )

        # Hari kerja dioper pemanggil kalau ia memang tahu — dan
        # importer file tahu, lewat resolver jadwal. `log_time.date()`
        # cuma cadangan untuk pemanggil lama; pada shift malam angka itu
        # memecah satu hari kerja jadi dua baris presensi.
        if work_date is None:
            work_date = log_time.date()

        defaults = cls.build_defaults(
            employee=employee,
            log_time=log_time,
            normalized=normalized,
            work_date=work_date,
            scheduled=scheduled,
            source=source,
            log_type=log_type,
        )

        moves_in, moves_out = _moves(log_type)

        attendance, created = (
            EmployeeAttendance.objects
            .get_or_create(
                employee=employee,
                work_date=work_date,
                is_deleted=False,
                defaults=defaults,
            )
        )

        if created:
            if user is not None:
                attendance.created_by = user
                attendance.updated_by = user

            cls.apply_policy(attendance)

            attendance.full_clean()
            attendance.save()

            return attendance, True

        changed_fields: set[str] = set()

        if moves_in and (
            attendance.first_check_in is None
            or log_time
            < attendance.first_check_in
        ):
            attendance.first_check_in = (
                log_time
            )

            attendance.check_in = log_time

            changed_fields.update({
                "first_check_in",
                "check_in",
            })

        if moves_out and (
            attendance.last_check_out is None
            or log_time
            > attendance.last_check_out
        ):
            attendance.last_check_out = (
                log_time
            )

            attendance.check_out = log_time

            changed_fields.update({
                "last_check_out",
                "check_out",
            })

        external_id = str(
            normalized.get(
                "external_id",
            )
            or "",
        ).strip()

        if (
            external_id
            and not attendance.external_id
        ):
            attendance.external_id = (
                external_id
            )

            changed_fields.add(
                "external_id",
            )

        device_code = str(
            normalized.get(
                "device_code",
            )
            or "",
        ).strip()

        if (
            device_code
            and not attendance.device_code
        ):
            attendance.device_code = (
                device_code
            )

            changed_fields.add(
                "device_code",
            )

        if user is not None:
            attendance.updated_by = user

            changed_fields.add(
                "updated_by",
            )

        # Baris lama yang jadwalnya belum pernah terisi ikut dilengkapi.
        # Tanpa ini, tap susulan pada baris yang dibuat sebelum resolver
        # jadwal ada tetap tidak bisa dihitung keterlambatannya, dan
        # data lamanya diam-diam tertinggal selamanya.
        if attendance.scheduled_check_in is None:
            if scheduled is not None:
                scheduled_in, scheduled_out = scheduled
            else:
                scheduled_in, scheduled_out = scheduled_window(
                    employee,
                    work_date,
                )

            if scheduled_in is not None:
                attendance.scheduled_check_in = scheduled_in
                attendance.scheduled_check_out = scheduled_out

                changed_fields.update({
                    "scheduled_check_in",
                    "scheduled_check_out",
                })

        if changed_fields:
            changed_fields |= cls.apply_policy(attendance)

        if changed_fields:
            attendance.full_clean()

            changed_fields.add(
                "updated_at",
            )

            attendance.save(
                update_fields=list(
                    changed_fields,
                ),
            )

        return attendance, False