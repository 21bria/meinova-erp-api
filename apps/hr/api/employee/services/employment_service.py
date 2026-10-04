from __future__ import annotations

import logging

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.hr.models import (
    Employee,
    EmploymentAssignment,
)


logger = logging.getLogger(__name__)


# Kolom yang tidak boleh berubah lewat form Employee begitu pegawainya
# sudah ada. Semuanya adalah keadaan yang punya sejarah: mengubahnya
# berarti membuang nilai lama tanpa jejak, dan kartu kepegawaian
# seseorang jadi tidak bisa menjawab "sejak kapan".
#
# Saat **create** kolom ini bebas diisi — itu keadaan awal, belum ada
# sejarah yang bisa hilang. Yang dikunci hanya perubahan sesudahnya, dan
# jalurnya `EmployeeAction`.
#
# Sengaja tidak memuat `join_date`, `employee_group`, `job_location`,
# `point_of_hire`, dan seluruh work arrangement: itu koreksi data yang
# memang wajar dilakukan HR langsung, dan menguncinya berarti salah
# ketik satu huruf harus lewat persetujuan tiga meja.
PROTECTED_FIELDS = {
    "employment_type": "Employment Type",
    "employment_status": "Employment Status",
    "contract_type": "Contract Type",
    "contract_start": "Contract Start",
    "contract_end": "Contract End",
    "probation_type": "Probation Type",
    "probation_start": "Probation Start",
    "probation_end": "Probation End",
    "confirmation_date": "Confirmation Date",
    "termination_date": "Termination Date",
    "termination_reason": "Termination Reason",
}


# Jenis Employee Action yang menerbitkan tiap kolom terkunci — dipakai
# menyusun pesan penolakan. "Harus lewat Employee Action" tanpa
# menyebutkan action mana cuma memindahkan kebingungan satu layar lebih
# dalam.
PROTECTED_FIELD_ACTIONS = {
    "employment_type": "Employment Type Change",
    "employment_status": "Employment Status Change",
    "contract_type": "Contract Change",
    "contract_start": "Contract Change",
    "contract_end": "Contract Extension / Contract Change",
    "probation_type": "Probation Change",
    "probation_start": "Probation Change",
    "probation_end": "Probation Change",
    "confirmation_date": "Employment Type Change",
    "termination_date": "Resignation / Termination",
    "termination_reason": "Resignation / Termination",
}


class EmploymentService:
    FIELDS = {
        "employment_status",
        "employment_type",
        "employee_group",
        "contract_type",
        "probation_type",
        "join_date",
        "employment_effective_date",
        "confirmation_date",
        "probation_start",
        "probation_end",
        "contract_start",
        "contract_end",
        "job_location",
        "point_of_hire",
        "termination_date",
        "termination_reason",
        "retirement_date",
        "work_schedule",
        "working_calendar",
        "shift",
        # Nama kolom model, bukan nama field serializer — `EmployeeService`
        # mem-pop dict `employment` dan setattr apa adanya.
        "roster_crew",
        "roster_start_override",
        "travel_days_override",
        "roster_policy",
        "roster_cycle_start",
        "back_to_back_partner",
        "notice_period_days",
        "employment_notes",
    }

    @classmethod
    def extract(
        cls,
        validated_data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            key: validated_data.pop(key)
            for key in list(validated_data.keys())
            if key in cls.FIELDS
        }

    @classmethod
    def assert_not_protected(
        cls,
        *,
        assignment: EmploymentAssignment,
        payload: dict[str, Any],
    ) -> None:
        """
        Menolak perubahan kolom bersejarah lewat form Employee.

        Diperiksa dengan **membandingkan**, bukan dengan melihat kunci
        mana yang dikirim: form mengirim seluruh isi tab apa adanya,
        termasuk nilai yang barusan dibacanya dari API. Menolak setiap
        kiriman yang memuat kuncinya akan membuat menyimpan perubahan
        Job Location pun ditolak dengan alasan kontrak.
        """
        blocked = []

        for field_name, label in PROTECTED_FIELDS.items():
            if field_name not in payload:
                continue

            proposed = payload[field_name]

            current = getattr(assignment, field_name, None)

            # FK dibandingkan lewat pk — instance-nya berbeda objek
            # walau menunjuk baris yang sama.
            if hasattr(proposed, "pk") or hasattr(current, "pk"):
                changed = (
                    getattr(proposed, "pk", None)
                    != getattr(current, "pk", None)
                )
            else:
                changed = proposed != current

            if changed:
                blocked.append((field_name, label))

        if not blocked:
            return

        raise ValidationError(
            {
                field_name: (
                    f"{label} tidak bisa diubah langsung dari form "
                    "Employee — nilai lamanya akan hilang tanpa jejak. "
                    "Ajukan lewat Employee Action "
                    f"({PROTECTED_FIELD_ACTIONS[field_name]})."
                )
                for field_name, label in blocked
            },
        )

    @classmethod
    @transaction.atomic
    def save(
        cls,
        *,
        employee: Employee,
        data: dict[str, Any],
        user=None,
        via_action: bool = False,
    ) -> EmploymentAssignment | None:
        """
        `via_action=True` melewati penjagaan kolom terkunci.

        Dipakai **hanya** oleh `EmployeeActionService.apply()`, yaitu
        jalur yang memang sudah menyimpan nilai sebelumnya di
        `values_before` dan sudah melewati persetujuan. Jangan dipakai
        untuk memuluskan jalur lain — itu mengembalikan overwrite diam
        yang justru mau dihilangkan.
        """
        if not data:
            return None

        payload = dict(data)

        if not payload.get("employment_effective_date"):
            payload["employment_effective_date"] = (
                payload.get("join_date")
                or timezone.localdate()
            )

        assignment = (
            EmploymentAssignment.objects
            .select_for_update()
            .filter(employee=employee)
            .first()
        )

        if assignment is None:
            assignment = EmploymentAssignment(
                employee=employee,
            )

            if user is not None:
                assignment.created_by = user

        elif not via_action:
            # Hanya untuk assignment yang sudah ada. Pegawai baru boleh
            # membawa kontrak/probation awalnya — belum ada sejarah yang
            # bisa hilang.
            cls.assert_not_protected(
                assignment=assignment,
                payload=payload,
            )

        for key, value in payload.items():
            setattr(assignment, key, value)

        if user is not None:
            assignment.updated_by = user

        assignment.full_clean()
        assignment.save()

        cls.sync_leave_balances(
            employee=employee,
            assignment=assignment,
            user=user,
        )

        return assignment

    # Kolom yang menentukan jatah cuti seseorang. Berubahnya salah satu
    # membuat saldo yang tersimpan tidak lagi menggambarkan aturan yang
    # berlaku.
    ENTITLEMENT_FIELDS = {
        "join_date",
        "employee_group",
        "employment_type",
    }

    @classmethod
    def sync_leave_balances(cls, *, employee, assignment, user=None) -> None:
        """
        Menerbitkan ulang saldo cuti begitu data yang menentukannya
        berubah.

        Tanpa ini, mengisi Join Date pegawai baru tidak menghasilkan
        apa-apa sampai ada yang ingat menjalankan
        `generate_leave_balances` — dan saldo yang kosong terbaca
        sebagai "pegawai ini tidak punya jatah", bukan sebagai
        "angkanya belum dihitung".

        Sengaja dijalankan tanpa syarat, bukan hanya saat kolomnya
        berubah: `save()` di atas meng-`setattr` seluruh payload ke
        instance sebelum menyimpan, jadi nilai lamanya sudah tidak bisa
        dibandingkan di sini. Ongkosnya kecil — dua tahun × jenis cuti
        yang punya policy, dan baris yang angkanya sama tidak ditulis
        ulang.

        Kegagalannya tidak boleh menggagalkan penyimpanan data
        pegawai: master cuti yang belum diseed adalah keadaan yang sah,
        dan orang yang sedang mengoreksi tanggal masuk tidak bisa
        berbuat apa-apa soal itu.
        """
        if assignment is None or not assignment.join_date:
            return

        from apps.hr.api.leave.entitlement import LeaveBalanceGenerator

        try:
            LeaveBalanceGenerator.sync_employee(
                employee=employee,
                user=user,
            )
        except Exception:
            logger.exception(
                "Gagal menerbitkan ulang saldo cuti pegawai %s.",
                employee.pk,
            )

    @classmethod
    def create_initial(
        cls,
        *,
        employee: Employee,
        data: dict[str, Any],
        user=None,
    ) -> EmploymentAssignment | None:
        return cls.save(
            employee=employee,
            data=data,
            user=user,
        )

    @classmethod
    def update_current(
        cls,
        *,
        employee: Employee,
        data: dict[str, Any],
        user=None,
        via_action: bool = False,
    ) -> EmploymentAssignment | None:
        return cls.save(
            employee=employee,
            data=data,
            user=user,
            via_action=via_action,
        )