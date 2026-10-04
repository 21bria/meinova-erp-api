from __future__ import annotations

from typing import Any

from apps.framework.imports import (
    BaseImporter,
    ImportNormalizer,
    register_importer,
)

from .mapping import EMPLOYEE_IMPORT_MAPPING
from .resolver import EmployeeReferenceResolver
from .writer import EmployeeImportWriter


@register_importer
class EmployeeImporter(BaseImporter):
    module = "hr/employees"
    label = "Employee"

    source_types = ("csv",)

    mapping = EMPLOYEE_IMPORT_MAPPING

    required_fields = ("employee_number",)

    identity_field = "employee_number"

    date_fields = (
        "birth_date",
        "organization_effective_date",
        "join_date",
        "contract_start",
        "contract_end",
    )

    # Header pada file template yang diunduh user. Sengaja tidak
    # memuat seluruh alias — cukup satu kolom per data, dengan nama
    # yang paling umum dipakai file klien.
    template_columns = (
        "employee_number",
        "nama_lengkap",
        "nik",
        "jenis_kelamin",
        "agama",
        "tempat_lahir",
        "tanggal_lahir",
        "email",
        "no_hp",
        "perusahaan",
        "cabang",
        "departemen",
        "jabatan",
        "tanggal_masuk",
        "bank",
        "no_rekening",
        "atas_nama",
        "pendidikan",
        "universitas",
        "tahun_lulus",
        "ipk",
    )

    template_sample_rows = (
        {
            "employee_number": "EMP-0001",
            "nama_lengkap": "Budi Santoso",
            "nik": "3201010101900001",
            "jenis_kelamin": "M",
            "agama": "Islam",
            "tempat_lahir": "Bandung",
            "tanggal_lahir": "1990-01-01",
            "email": "budi@example.com",
            "no_hp": "081200000001",
            "perusahaan": "MNV",
            "cabang": "JKT",
            "departemen": "ENG",
            "jabatan": "MINE-OPR",
            "tanggal_masuk": "2024-01-15",
            "bank": "BCA",
            "no_rekening": "1234567890",
            "atas_nama": "Budi Santoso",
            "pendidikan": "S1",
            "universitas": "Institut Teknologi Bandung",
            "tahun_lulus": "2012",
            "ipk": "3.45",
        },
    )

    preview_columns = (
        {"key": "row_number", "label": "Row"},
        {"key": "employee_number", "label": "Employee Number"},
        {"key": "display_name", "label": "Name"},
        {"key": "nik", "label": "NIK"},
        {"key": "company", "label": "Company"},
        {"key": "department", "label": "Department"},
        {"key": "position", "label": "Position"},
        {"key": "bank_account_number", "label": "Bank Account"},
        {"key": "education", "label": "Education"},
        {"key": "action", "label": "Action"},
    )

    # ------------------------------------------------------------------
    # Validasi
    # ------------------------------------------------------------------

    @classmethod
    def validate(
        cls,
        normalized: dict[str, Any],
    ) -> dict[str, list[str]]:
        errors = super().validate(normalized)

        first_name, _last_name = EmployeeImportWriter.resolve_names(
            normalized,
        )

        if not first_name:
            errors.setdefault("first_name", []).append(
                "Name is required. Provide first_name or full_name.",
            )

        # Seluruh kolom tanggal diperiksa, bukan cuma dua yang dulu
        # ditulis manual. Normalisasi sudah mengubah tanggal yang bisa
        # dibaca menjadi ISO, jadi nilai yang tersisa apa adanya berarti
        # gagal diparse — kalau dibiarkan, writer memanggil to_date()
        # lagi, dapat None, dan kolomnya hilang tanpa peringatan.
        for field_name in cls.date_fields:
            raw_value = ImportNormalizer.clean_text(
                normalized.get(field_name),
            )

            if not raw_value:
                continue

            if ImportNormalizer.to_date(raw_value) is None:
                errors.setdefault(field_name, []).append(
                    f"Invalid date: '{raw_value}'.",
                )

        return errors

    # ------------------------------------------------------------------
    # Resolusi relasi
    # ------------------------------------------------------------------

    @classmethod
    def resolve(
        cls,
        normalized: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        return EmployeeReferenceResolver.resolve(normalized)

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    @classmethod
    def build_preview_row(
        cls,
        *,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
    ) -> dict[str, Any]:
        from apps.hr.models import Employee

        employee_number = ImportNormalizer.clean_text(
            normalized.get("employee_number"),
        )

        first_name, last_name = EmployeeImportWriter.resolve_names(
            normalized,
        )

        existing = (
            Employee.objects
            .filter(employee_number=employee_number)
            .only("id", "is_deleted")
            .first()
            if employee_number
            else None
        )

        if existing is None:
            action = "create"
        elif existing.is_deleted:
            # Beda dari "update": barisnya akan menghidupkan kembali
            # karyawan yang sebelumnya dihapus.
            action = "restore"
        else:
            action = "update"

        def label(field_name: str) -> str:
            instance = resolved.get(field_name)

            if instance is not None:
                return getattr(instance, "name", "") or ""

            return ImportNormalizer.clean_text(
                normalized.get(field_name),
            )

        return {
            "employee_number": employee_number,
            "display_name": " ".join(
                part
                for part in (first_name, last_name)
                if part
            ),
            "nik": ImportNormalizer.clean_text(
                normalized.get("nik"),
            ),
            "company": label("company"),
            "department": label("department"),
            "position": label("position"),
            "bank_account_number": ImportNormalizer.clean_text(
                normalized.get("bank_account_number"),
            ),
            "education": label("education"),
            "action": action,
        }

    # ------------------------------------------------------------------
    # Penulisan
    # ------------------------------------------------------------------

    @classmethod
    def write(
        cls,
        *,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
        user=None,
    ):
        return EmployeeImportWriter.write(
            normalized=normalized,
            resolved=resolved,
            user=user,
        )
