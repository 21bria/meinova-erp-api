from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.hr.models import Employee

from .employee_number_service import EmployeeNumberService
from .employment_service import EmploymentService
from .organization_service import OrganizationService


class EmployeeService:
    @staticmethod
    def list():
        return (
            Employee.objects
            .select_related(
                "user",
                "gender",
                "religion",
                "nationality",
                "blood_type",
                "marital_status",

                # Foto pegawai. `avatar_display` membaca berkasnya tiap
                # baris (`public_id`, `file`, `is_deleted`), jadi tanpa
                # baris ini satu halaman daftar pegawai menambah satu
                # query per pegawai — N+1 yang tidak terlihat sampai
                # tenant pertama benar-benar mengunggah foto.
                "avatar_file",

                # Alamat. Serializer mengirim `province_name` dkk., jadi
                # tanpa keempatnya setiap baris daftar pegawai menambah
                # empat query.
                "province",
                "city",
                "district",
                "village",

                "organization",
                "organization__company",
                "organization__branch",
                "organization__location",
                "organization__division",
                "organization__department",
                "organization__section",
                "organization__position",
                "organization__job_level",
                "organization__job_grade",
                "organization__reports_to",
                "organization__cost_center",

                "employment",
                "employment__employment_status",
                "employment__employment_type",
                "employment__employee_group",
                "employment__contract_type",
                "employment__probation_type",
                "employment__termination_reason",
                "employment__work_schedule",
                "employment__working_calendar",
                "employment__shift",
                "employment__point_of_hire",
            )
            .prefetch_related(
                "payroll_assignments",
            )
            .filter(
                is_deleted=False,
            )
        )

    @classmethod
    def get_queryset(cls):
        return cls.list()

    @staticmethod
    def generate_employee_number(*, company) -> str:
        """
        Nomor pegawai dari deret milik companynya.

        Melempar kalau companynya belum dipilih atau belum punya kode:
        nomor yang formatnya bergantung pada company tidak bisa dibuat
        tanpa company, dan menyimpan pegawai tanpa nomor berarti dua
        pegawai berikutnya bertabrakan di constraint uniknya.
        """
        if company is None:
            raise ValidationError(
                {
                    "company": (
                        "Company wajib dipilih kalau nomor pegawai "
                        "dibuat otomatis — kodenya yang jadi awalan "
                        "nomor."
                    ),
                },
            )

        number = EmployeeNumberService.next_number(company=company)

        if not number:
            raise ValidationError(
                {
                    "employee_number": (
                        f"Company {company} belum punya kode, jadi "
                        "nomor pegawai tidak bisa dibuat otomatis. "
                        "Isi kodenya di master Company, atau matikan "
                        "Auto Generate dan ketik nomornya."
                    ),
                },
            )

        return number

    @classmethod
    @transaction.atomic
    def create(
        cls,
        validated_data: dict[str, Any],
        *,
        user=None,
    ) -> Employee:
        payload = dict(
            validated_data,
        )

        organization_data = payload.pop(
            "organization",
            {},
        )

        employment_data = payload.pop(
            "employment",
            {},
        )

        auto_number = payload.pop(
            "auto_generate_employee_number",
            False,
        )

        if auto_number:
            payload["employee_number"] = cls.generate_employee_number(
                company=organization_data.get("company"),
            )

        employee = Employee(
            **payload,
        )

        if user is not None:
            employee.created_by = user
            employee.updated_by = user

        employee.full_clean()
        employee.save()

        # Dipanggil walau kiriman organisasinya kosong: pembuat yang
        # cakupannya satu lokasi mendapat lokasinya terisi dari sana
        # (`apply_scope_defaults`), dan tanpa panggilan ini pegawai yang
        # baru ia buat langsung hilang dari layarnya sendiri. Service-nya
        # tetap mengembalikan None kalau memang tidak ada yang ditulis.
        OrganizationService.save(
            employee=employee,
            data=organization_data,
            user=user,
        )

        if employment_data:
            EmploymentService.create_initial(
                employee=employee,
                data=employment_data,
                user=user,
            )

        return employee

    @classmethod
    @transaction.atomic
    def update(
        cls,
        instance: Employee,
        validated_data: dict[str, Any],
        *,
        user=None,
    ) -> Employee:
        payload = dict(
            validated_data,
        )

        organization_data = payload.pop(
            "organization",
            {},
        )

        employment_data = payload.pop(
            "employment",
            {},
        )

        # Nomor pegawai yang sudah terbit tidak pernah dihitung ulang.
        # Ia muncul di kontrak, slip gaji, dan mesin absensi — pegawai
        # yang dipindah ke company lain tetap memegang nomor yang sama,
        # dan mengubahnya butuh proses administratif tersendiri, bukan
        # efek samping dari menyimpan form.
        payload.pop("auto_generate_employee_number", None)

        for field_name, value in payload.items():
            setattr(
                instance,
                field_name,
                value,
            )

        if user is not None:
            instance.updated_by = user

        instance.full_clean()
        instance.save()

        if organization_data:
            OrganizationService.save(
                employee=instance,
                data=organization_data,
                user=user,
            )

        if employment_data:
            EmploymentService.update_current(
                employee=instance,
                data=employment_data,
                user=user,
            )

        return instance