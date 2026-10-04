from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.hr.models import (
    EmployeeAttendance,
    OrganizationAssignment,
)


class EmployeeAttendanceService:
    FIELDS = {
        "employee",
        "company",
        "branch",
        "location",
        "work_date",
        "shift",
        "status",
        "source",
        "approval_status",
        "scheduled_check_in",
        "scheduled_check_out",
        "check_in",
        "check_out",
        "first_check_in",
        "last_check_out",
        "worked_minutes",
        "break_minutes",
        "late_minutes",
        "early_leave_minutes",
        "overtime_minutes",
        "excused_late_minutes",
        "excused_early_leave_minutes",
        "permission_minutes",
        "is_excused_absence",
        "permission_state",
        "check_in_latitude",
        "check_in_longitude",
        "check_out_latitude",
        "check_out_longitude",
        "check_in_address",
        "check_out_address",
        "is_geofence_valid",
        "is_manual_adjustment",
        "adjustment_reason",
        "external_id",
        "device_code",
        "import_batch_id",
        "notes",
        # BT-3: ditulis penutup hari dari Business Trip yang disetujui.
        # Serializer menjadikannya read-only, jadi form tidak bisa
        # menempelkan perjalanan ke baris presensi.
        "business_trip",
    }

    @classmethod
    def build_payload(
        cls,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            key: value
            for key, value in data.items()
            if key in cls.FIELDS
        }

    @classmethod
    def apply_employee_assignment(
        cls,
        payload: dict[str, Any],
        *,
        fallback_employee=None,
    ) -> dict[str, Any]:
        employee = payload.get(
            "employee",
            fallback_employee,
        )

        if employee is None:
            return payload

        assignment = (
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

        if assignment is None:
            return payload

        payload["company"] = assignment.company
        payload["branch"] = assignment.branch
        payload["location"] = assignment.location

        return payload

    @classmethod
    def apply_policy(
        cls,
        payload: dict[str, Any],
        *,
        fallback_employee=None,
        instance: EmployeeAttendance | None = None,
    ) -> dict[str, Any]:
        """
        Menurunkan status dan menit-menitnya dari `AttendancePolicy`.

        **Menimpa nilai kiriman**, dan itu disengaja: toleransi telat
        adalah aturan perusahaan, bukan isian per baris. Kalau nilai
        kiriman dihormati, layar mana pun yang mengirim `late_minutes`
        hasil hitungannya sendiri diam-diam melewati kebijakan yang
        justru baru saja diatur orang.

        Baris yang tidak punya jadwal (`scheduled_check_in` kosong)
        tidak disentuh sama sekali. Itu keadaan yang lazim hari ini:
        jalur import fingerprint belum menuliskan jadwal, jadi
        keterlambatannya memang belum bisa dihitung siapa pun.
        """
        from apps.hr.api.attendance.policy import AttendancePolicyResolver

        employee = payload.get("employee", fallback_employee)

        if employee is None:
            return payload

        def current(key):
            if key in payload:
                return payload[key]

            return getattr(instance, key, None)

        computed = AttendancePolicyResolver.compute(
            rules=AttendancePolicyResolver.rules_for(employee),
            scheduled_check_in=current("scheduled_check_in"),
            scheduled_check_out=current("scheduled_check_out"),
            check_in=current("check_in"),
            check_out=current("check_out"),
            status=current("status"),
            break_minutes=payload.get("break_minutes"),
        )

        payload.update(computed)

        return payload

    @classmethod
    def apply_permissions(
        cls,
        payload: dict[str, Any],
        *,
        fallback_employee=None,
        instance: EmployeeAttendance | None = None,
    ) -> dict[str, Any]:
        """
        Menurunkan klasifikasi izin, **setelah** `apply_policy`.

        Urutannya wajib begitu: yang dimaafkan izin adalah menit
        keterlambatan menurut kebijakan, bukan selisih jam mentah.
        Dibalik, izin memaafkan angka yang belum dipotong toleransi dan
        hasilnya lebih besar daripada keterlambatan yang benar-benar
        tercatat.

        **Menimpa nilai kiriman**, alasan yang sama dengan
        `apply_policy`: dokumen izin yang disetujui adalah satu-satunya
        sumber pembebasan, dan layar yang mengirim `excused_late_minutes`
        hasil hitungannya sendiri diam-diam membebaskan orang tanpa satu
        pun tanda tangan.

        Pegawai atau tanggal yang belum diketahui dilewati **tanpa
        menulis apa pun** — bukan dinolkan. Payload parsial yang
        menyentuh satu kolom lain tidak boleh menghapus klasifikasi yang
        sudah benar.
        """
        from apps.hr.api.attendance.permission_effect import compute_for

        employee = payload.get("employee", fallback_employee)

        work_date = payload.get(
            "work_date",
            getattr(instance, "work_date", None),
        )

        if employee is None or work_date is None:
            return payload

        def current(key):
            if key in payload:
                return payload[key]

            return getattr(instance, key, None)

        payload.update(
            compute_for(
                employee=employee,
                work_date=work_date,
                status=current("status"),
                late_minutes=current("late_minutes") or 0,
                early_leave_minutes=current("early_leave_minutes") or 0,
                check_in=current("check_in"),
                check_out=current("check_out"),
            ),
        )

        return payload

    @classmethod
    @transaction.atomic
    def create(
        cls,
        *,
        data: dict[str, Any],
        user=None,
    ) -> EmployeeAttendance:
        payload = cls.build_payload(data)

        payload = cls.apply_employee_assignment(
            payload,
        )

        payload = cls.apply_policy(payload)

        payload = cls.apply_permissions(payload)

        attendance = EmployeeAttendance(
            **payload,
        )

        if user is not None:
            attendance.created_by = user
            attendance.updated_by = user

        attendance.full_clean()
        attendance.save()

        return attendance

    @classmethod
    @transaction.atomic
    def update(
        cls,
        *,
        instance: EmployeeAttendance,
        data: dict[str, Any],
        user=None,
    ) -> EmployeeAttendance:
        payload = cls.build_payload(data)

        payload = cls.apply_employee_assignment(
            payload,
            fallback_employee=instance.employee,
        )

        payload = cls.apply_policy(
            payload,
            fallback_employee=instance.employee,
            instance=instance,
        )

        payload = cls.apply_permissions(
            payload,
            fallback_employee=instance.employee,
            instance=instance,
        )

        for key, value in payload.items():
            setattr(
                instance,
                key,
                value,
            )

        update_fields = set(
            payload.keys(),
        )

        if user is not None:
            instance.updated_by = user
            update_fields.add(
                "updated_by",
            )

        instance.full_clean()

        if update_fields:
            update_fields.add(
                "updated_at",
            )

            instance.save(
                update_fields=list(
                    update_fields,
                ),
            )

        return instance

    @classmethod
    @transaction.atomic
    def soft_delete(
        cls,
        *,
        instance: EmployeeAttendance,
        user=None,
    ) -> EmployeeAttendance:
        instance.is_deleted = True
        instance.deleted_at = timezone.now()

        update_fields = {
            "is_deleted",
            "deleted_at",
            "updated_at",
        }

        if user is not None:
            instance.deleted_by = user
            instance.updated_by = user

            update_fields.update({
                "deleted_by",
                "updated_by",
            })

        instance.save(
            update_fields=list(
                update_fields,
            ),
        )

        return instance