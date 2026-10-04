from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.framework.imports import ImportNormalizer
from apps.hr.models import (
    Employee,
    EmployeeBankAccount,
    EmployeeEducation,
    EmploymentAssignment,
    OrganizationAssignment,
    PayrollAssignment,
)


TEXT_FIELDS = (
    "nik",
    "passport_number",
    "tax_number",
    "birth_place",
    "personal_email",
    "work_email",
    "phone",
    "mobile",
    "emergency_contact_name",
    "emergency_contact_phone",
    "notes",
)

REFERENCE_FIELDS = (
    "gender",
    "religion",
    "nationality",
    "blood_type",
    "marital_status",
)

ORGANIZATION_REFERENCE_FIELDS = (
    "branch",
    "location",
    "division",
    "department",
    "section",
    "position",
    "job_level",
    "job_grade",
    "cost_center",
)


class EmployeeImportWriter:
    """
    Menulis satu baris menjadi Employee beserta penempatan organisasi,
    rekening bank, dan riwayat pendidikan.

    Upsert berdasarkan `employee_number`: ada = update, belum ada = create.
    """

    # ------------------------------------------------------------------
    # Nama
    # ------------------------------------------------------------------

    @staticmethod
    def split_name(full_name: str) -> tuple[str, str]:
        parts = [
            part
            for part in full_name.split()
            if part
        ]

        if not parts:
            return "", ""

        if len(parts) == 1:
            return parts[0], ""

        return parts[0], " ".join(parts[1:])

    @classmethod
    def resolve_names(
        cls,
        normalized: dict[str, Any],
    ) -> tuple[str, str]:
        first_name = ImportNormalizer.clean_text(
            normalized.get("first_name"),
        )

        last_name = ImportNormalizer.clean_text(
            normalized.get("last_name"),
        )

        if first_name:
            return first_name, last_name

        return cls.split_name(
            ImportNormalizer.clean_text(
                normalized.get("full_name"),
            )
        )

    # ------------------------------------------------------------------
    # Employee
    # ------------------------------------------------------------------

    @classmethod
    def build_employee_values(
        cls,
        *,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
    ) -> dict[str, Any]:
        first_name, last_name = cls.resolve_names(normalized)

        values: dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
        }

        for field_name in TEXT_FIELDS:
            value = ImportNormalizer.clean_text(
                normalized.get(field_name),
            )

            # Kolom kosong tidak menimpa data yang sudah ada.
            if value:
                values[field_name] = value

        for field_name in REFERENCE_FIELDS:
            instance = resolved.get(field_name)

            if instance is not None:
                values[field_name] = instance

        birth_date = ImportNormalizer.to_date(
            normalized.get("birth_date"),
        )

        if birth_date is not None:
            values["birth_date"] = birth_date

        if normalized.get("is_active") not in (None, ""):
            values["is_active"] = ImportNormalizer.to_boolean(
                normalized.get("is_active"),
                default=True,
            )

        return values

    @classmethod
    def upsert_employee(
        cls,
        *,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
        user=None,
    ) -> tuple[Employee, bool]:
        employee_number = ImportNormalizer.clean_text(
            normalized.get("employee_number"),
        )

        values = cls.build_employee_values(
            normalized=normalized,
            resolved=resolved,
        )

        # Sengaja tidak menyaring is_deleted: nomor karyawan yang sama
        # harus dikenali walau record-nya sedang terhapus, supaya import
        # menghidupkannya kembali alih-alih diam-diam memperbarui data
        # yang tidak terlihat user — atau gagal karena bentrok unique.
        employee = (
            Employee.objects
            .filter(employee_number=employee_number)
            .first()
        )

        created = employee is None

        if employee is None:
            employee = Employee(
                employee_number=employee_number,
                created_by=user,
            )

        for field_name, value in values.items():
            setattr(employee, field_name, value)

        employee.updated_by = user

        employee.is_deleted = False
        employee.deleted_at = None
        employee.deleted_by = None

        employee.full_clean(
            exclude=["user", "avatar"],
        )

        employee.save()

        return employee, created

    # ------------------------------------------------------------------
    # Penempatan organisasi
    # ------------------------------------------------------------------

    @classmethod
    def upsert_organization(
        cls,
        *,
        employee: Employee,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
        user=None,
    ) -> None:
        company = resolved.get("company")

        if company is None:
            return

        effective_date = ImportNormalizer.to_date(
            normalized.get("organization_effective_date"),
        )

        if effective_date is None:
            return

        assignment = (
            OrganizationAssignment.objects
            .filter(employee=employee)
            .first()
        )

        if assignment is None:
            assignment = OrganizationAssignment(
                employee=employee,
                created_by=user,
            )

        assignment.company = company
        assignment.organization_effective_date = effective_date

        for field_name in ORGANIZATION_REFERENCE_FIELDS:
            instance = resolved.get(field_name)

            if instance is not None:
                setattr(assignment, field_name, instance)

        assignment.updated_by = user

        assignment.full_clean(
            exclude=["reports_to"],
        )

        assignment.save()

    # ------------------------------------------------------------------
    # Kepegawaian
    # ------------------------------------------------------------------

    @classmethod
    def upsert_employment(
        cls,
        *,
        employee: Employee,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
        user=None,
    ) -> None:
        """
        Menulis tanggal bergabung, masa kontrak, dan penempatan kerja
        ke `EmploymentAssignment`.

        Klasifikasi kepegawaian (status/tipe) ikut kalau ada di file,
        tapi tidak diwajibkan — file klien lazimnya cuma memuat tanggal.
        """
        date_values = {
            field_name: ImportNormalizer.to_date(
                normalized.get(field_name),
            )
            for field_name in (
                "join_date",
                "contract_start",
                "contract_end",
            )
        }

        job_location = ImportNormalizer.clean_text(
            normalized.get("job_location"),
        )

        # File klien lazimnya hanya memuat tanggal berakhirnya kontrak.
        # Model mewajibkan tanggal mulai begitu masa kontrak diisi, dan
        # tanggal bergabung adalah padanan yang paling masuk akal —
        # kalau ternyata perpanjangan, kolom `contract_start` bisa
        # diisi eksplisit di file.
        if (
            date_values.get("contract_end") is not None
            and date_values.get("contract_start") is None
        ):
            date_values["contract_start"] = date_values.get("join_date")

        reference_values = {
            field_name: resolved.get(field_name)
            for field_name in (
                "employment_status",
                "employment_type",
            )
        }

        # Contract type hanya ikut kalau barisnya memang punya masa
        # kontrak. Kalau tidak disaring, nilai `defaults` di
        # ImportProfile akan menandai karyawan tetap sebagai PKWT.
        if date_values.get("contract_end") is not None:
            reference_values["contract_type"] = resolved.get(
                "contract_type",
            )

        has_data = (
            any(value is not None for value in date_values.values())
            or bool(job_location)
            or any(
                value is not None
                for value in reference_values.values()
            )
        )

        if not has_data:
            return

        assignment = (
            EmploymentAssignment.objects
            .filter(employee=employee)
            .first()
        )

        if assignment is None:
            assignment = EmploymentAssignment(
                employee=employee,
                created_by=user,
            )

        for field_name, value in date_values.items():
            if value is not None:
                setattr(assignment, field_name, value)

        for field_name, instance in reference_values.items():
            if instance is not None:
                setattr(assignment, field_name, instance)

        if job_location:
            assignment.job_location = job_location

        assignment.updated_by = user

        assignment.full_clean()
        assignment.save()

    # ------------------------------------------------------------------
    # Payroll
    # ------------------------------------------------------------------

    @classmethod
    def upsert_payroll(
        cls,
        *,
        employee: Employee,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
        user=None,
    ) -> None:
        """
        Menulis status PTKP (`payroll.TaxStatus`) ke penempatan payroll
        yang sedang berlaku. Resolver sudah memastikan payroll group,
        mata uang, dan tanggal berlaku terisi bila kolom payroll dipakai.
        """
        payroll_group = resolved.get("payroll_group")

        if payroll_group is None:
            return

        currency = resolved.get("payroll_currency")

        effective_date = ImportNormalizer.to_date(
            normalized.get("organization_effective_date"),
        )

        if currency is None or effective_date is None:
            return

        # Satu karyawan hanya boleh punya satu assignment is_current
        # (lihat constraint uniq_current_employee_payroll_assignment),
        # jadi yang berjalan itulah yang diperbarui.
        assignment = (
            PayrollAssignment.objects
            .filter(
                employee=employee,
                is_current=True,
                is_deleted=False,
            )
            .first()
        )

        if assignment is None:
            assignment = PayrollAssignment(
                employee=employee,
                effective_from=effective_date,
                created_by=user,
            )

        assignment.payroll_group = payroll_group
        assignment.currency = currency
        assignment.is_current = True

        tax_status = resolved.get("tax_status")

        if tax_status is not None:
            assignment.tax_status = tax_status

        tax_number = ImportNormalizer.clean_text(
            normalized.get("tax_number"),
        )

        if tax_number:
            assignment.tax_number_payroll = tax_number

        assignment.updated_by = user

        assignment.full_clean()
        assignment.save()

    # ------------------------------------------------------------------
    # Rekening bank
    # ------------------------------------------------------------------

    @classmethod
    def upsert_bank_account(
        cls,
        *,
        employee: Employee,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
        user=None,
    ) -> None:
        bank = resolved.get("bank")

        account_number = ImportNormalizer.clean_text(
            normalized.get("bank_account_number"),
        )

        if bank is None or not account_number:
            return

        account_name = (
            ImportNormalizer.clean_text(
                normalized.get("bank_account_name"),
            )
            or employee.full_name
        )

        account = (
            EmployeeBankAccount.objects
            .filter(
                employee=employee,
                bank=bank,
                account_number=account_number,
                is_deleted=False,
            )
            .first()
        )

        if account is None:
            account = EmployeeBankAccount(
                employee=employee,
                bank=bank,
                account_number=account_number,
                created_by=user,
            )

            # Rekening pertama otomatis jadi rekening utama.
            account.is_primary = not (
                EmployeeBankAccount.objects
                .filter(
                    employee=employee,
                    is_deleted=False,
                )
                .exists()
            )

        account.account_name = account_name

        branch_name = ImportNormalizer.clean_text(
            normalized.get("bank_branch_name"),
        )

        if branch_name:
            account.branch_name = branch_name

        currency = resolved.get("bank_currency")

        if currency is not None:
            account.currency = currency

        account.updated_by = user

        account.full_clean()
        account.save()

    # ------------------------------------------------------------------
    # Pendidikan
    # ------------------------------------------------------------------

    @classmethod
    def upsert_education(
        cls,
        *,
        employee: Employee,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
        user=None,
    ) -> None:
        education = resolved.get("education")

        institution_name = ImportNormalizer.clean_text(
            normalized.get("institution_name"),
        )

        if education is None or not institution_name:
            return

        record = (
            EmployeeEducation.objects
            .filter(
                employee=employee,
                education=education,
                institution_name__iexact=institution_name,
                is_deleted=False,
            )
            .first()
        )

        if record is None:
            record = EmployeeEducation(
                employee=employee,
                education=education,
                institution_name=institution_name,
                created_by=user,
            )

            # Baris pendidikan pertama ditandai sebagai yang tertinggi.
            record.is_highest_education = not (
                EmployeeEducation.objects
                .filter(
                    employee=employee,
                    is_deleted=False,
                )
                .exists()
            )

        degree = resolved.get("degree")

        if degree is not None:
            record.degree = degree

        study_field = resolved.get("study_field")

        if study_field is not None:
            record.study_field = study_field

        graduation_year = ImportNormalizer.to_integer(
            normalized.get("graduation_year"),
        )

        if graduation_year is not None:
            record.graduation_year = graduation_year

        gpa = ImportNormalizer.to_decimal(
            normalized.get("gpa"),
        )

        if gpa is not None:
            record.gpa = gpa

        record.updated_by = user

        record.full_clean()
        record.save()

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def write(
        cls,
        *,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
        user=None,
    ) -> tuple[Employee, bool]:
        employee, created = cls.upsert_employee(
            normalized=normalized,
            resolved=resolved,
            user=user,
        )

        cls.upsert_organization(
            employee=employee,
            normalized=normalized,
            resolved=resolved,
            user=user,
        )

        cls.upsert_employment(
            employee=employee,
            normalized=normalized,
            resolved=resolved,
            user=user,
        )

        cls.upsert_payroll(
            employee=employee,
            normalized=normalized,
            resolved=resolved,
            user=user,
        )

        cls.upsert_bank_account(
            employee=employee,
            normalized=normalized,
            resolved=resolved,
            user=user,
        )

        cls.upsert_education(
            employee=employee,
            normalized=normalized,
            resolved=resolved,
            user=user,
        )

        return employee, created
