from __future__ import annotations

from typing import Any

from django.db.models import Q

from apps.administration.models import (
    Bank,
    BloodType,
    Branch,
    Company,
    ContractType,
    CostCenter,
    Currency,
    Degree,
    Department,
    Division,
    Education,
    EmploymentStatus,
    EmploymentType,
    Gender,
    JobGrade,
    JobLevel,
    MaritalStatus,
    Nationality,
    Position,
    Religion,
    Section,
    Location,
    StudyField,
)
from apps.framework.imports import ImportNormalizer
from apps.payroll.models import PayrollGroup, TaxStatus


# Referensi global: kodenya unik di seluruh tenant.
GLOBAL_REFERENCES: dict[str, tuple[Any, str]] = {
    "gender": (Gender, "Gender"),
    "religion": (Religion, "Religion"),
    "nationality": (Nationality, "Nationality"),
    "blood_type": (BloodType, "Blood Type"),
    "marital_status": (MaritalStatus, "Marital Status"),

    "job_level": (JobLevel, "Job Level"),
    "job_grade": (JobGrade, "Job Grade"),

    "bank": (Bank, "Bank"),
    "bank_currency": (Currency, "Currency"),

    "tax_status": (TaxStatus, "Tax Status"),
    "payroll_group": (PayrollGroup, "Payroll Group"),
    "payroll_currency": (Currency, "Currency"),

    "employment_status": (EmploymentStatus, "Employment Status"),
    "employment_type": (EmploymentType, "Employment Type"),
    "contract_type": (ContractType, "Contract Type"),

    "education": (Education, "Education"),
    "degree": (Degree, "Degree"),
    "study_field": (StudyField, "Study Field"),
}


"""
Rantai organisasi.

Kode Branch/Location/Department/dst hanya unik PER COMPANY
(lihat constraint `uniq_core_<model>_company_code`), jadi mencarinya
secara global bisa salah perusahaan tanpa ketahuan. Tiap level
disaring memakai induk yang sudah berhasil di-resolve sebelumnya.

Induk di master bersifat opsional (mis. Location.branch boleh kosong),
maka penyaringan memakai pola "cocok dengan induk ATAU induknya kosong".
"""
ORGANIZATION_CHAIN: list[tuple[str, Any, str, tuple[str, ...]]] = [
    # (field, model, label, induk yang dipakai menyaring)
    ("company", Company, "Company", ()),
    ("branch", Branch, "Branch", ("company",)),
    ("location", Location, "Location", ("company", "branch")),
    ("division", Division, "Division", ("company", "branch", "location")),
    ("department", Department, "Department", ("company", "branch", "location")),
    ("section", Section, "Section", ("company", "branch", "location")),
    ("position", Position, "Position", ("company", "branch", "location")),
    ("cost_center", CostCenter, "Cost Center", ("company", "branch", "location")),
]

ORGANIZATION_DETAIL_FIELDS = tuple(
    field_name
    for field_name, _model, _label, parents in ORGANIZATION_CHAIN
    if parents
)


class EmployeeReferenceResolver:
    """
    Mengubah kode/nama pada baris CSV menjadi objek referensi.

    Pencocokan: code (case-insensitive) lebih dulu, lalu name.
    Nilai yang diisi tapi tidak ketemu dianggap error — lebih baik
    baris ditolak daripada diam-diam tersimpan tanpa relasi atau,
    lebih buruk lagi, menempel ke perusahaan yang salah.
    """

    @staticmethod
    def base_queryset(model):
        return model.objects.filter(is_deleted=False)

    @classmethod
    def match(cls, queryset, value: str):
        text = ImportNormalizer.clean_text(value)

        if not text:
            return None, 0

        matches = list(
            queryset.filter(
                Q(code__iexact=text)
                | Q(name__iexact=text)
            ).order_by("code")[:2]
        )

        return (
            matches[0] if matches else None,
            len(matches),
        )

    @classmethod
    def find_global(cls, model, value: str):
        instance, _count = cls.match(
            cls.base_queryset(model),
            value,
        )

        return instance

    @classmethod
    def scoped_queryset(cls, model, *, parents, resolved):
        """
        Menyaring per induk yang sudah ketemu. Induk yang kosong di
        master tetap ikut, karena hierarkinya memang opsional.
        """
        queryset = cls.base_queryset(model)

        for parent in parents:
            parent_instance = resolved.get(parent)

            if parent_instance is None:
                continue

            queryset = queryset.filter(
                Q(**{parent: parent_instance})
                | Q(**{f"{parent}__isnull": True})
            )

        return queryset

    # ------------------------------------------------------------------
    # Kolom status: marital vs PTKP
    # ------------------------------------------------------------------

    # Awalan kode PTKP -> kandidat kode/nama MaritalStatus.
    PTKP_MARITAL_CANDIDATES: dict[str, tuple[str, ...]] = {
        "TK": ("S", "TK", "Single", "Tidak Kawin"),
        "K": ("M", "K", "Married", "Kawin"),
        "HB": ("M", "K", "Married", "Kawin"),
    }

    @classmethod
    def derive_marital_from_ptkp(cls, ptkp_code: str) -> str:
        prefix = (
            ptkp_code
            .split("/")[0]
            .strip()
            .upper()
        )

        for candidate in cls.PTKP_MARITAL_CANDIDATES.get(prefix, ()):
            if cls.find_global(MaritalStatus, candidate) is not None:
                return candidate

        return ""

    @classmethod
    def prepare_values(
        cls,
        normalized: dict[str, Any],
    ) -> dict[str, Any]:
        """
        File HR Indonesia lazim mengisi kolom bernama 'marital status'
        dengan kode PTKP (TK/0, K/1) — itu master `payroll.TaxStatus`,
        bukan `administration.MaritalStatus` yang isinya S/M/D/W.

        Nilai semacam itu dialihkan ke `tax_status`, dan status kawinnya
        diturunkan dari awalan kodenya (TK = belum kawin, K = kawin).
        Ini bukan tebakan: pengalihan hanya terjadi kalau nilainya gagal
        dicocokkan sebagai Marital Status TAPI ada di master Tax Status.
        """
        values = dict(normalized)

        raw_value = ImportNormalizer.clean_text(
            values.get("marital_status"),
        )

        if not raw_value:
            return values

        if cls.find_global(MaritalStatus, raw_value) is not None:
            return values

        if cls.find_global(TaxStatus, raw_value) is None:
            return values

        if not ImportNormalizer.clean_text(values.get("tax_status")):
            values["tax_status"] = raw_value

            # Ditandai supaya tidak ikut mewajibkan payroll group:
            # user tidak pernah minta data payroll diimport, kolomnya
            # cuma kebetulan berisi kode PTKP.
            values["_tax_status_auto"] = True

        values["marital_status"] = cls.derive_marital_from_ptkp(
            raw_value,
        )

        return values

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    @classmethod
    def resolve(
        cls,
        normalized: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        resolved: dict[str, Any] = {}
        errors: dict[str, list[str]] = {}

        values = cls.prepare_values(normalized)

        # --------------------------------------------------------------
        # Referensi global
        # --------------------------------------------------------------
        for field_name, (model, label) in GLOBAL_REFERENCES.items():
            raw_value = ImportNormalizer.clean_text(
                values.get(field_name),
            )

            if not raw_value:
                resolved[field_name] = None
                continue

            instance = cls.find_global(model, raw_value)

            if instance is None:
                errors.setdefault(field_name, []).append(
                    f"{label} '{raw_value}' not found.",
                )

            resolved[field_name] = instance

        # --------------------------------------------------------------
        # Rantai organisasi, dari atas ke bawah
        # --------------------------------------------------------------
        for field_name, model, label, parents in ORGANIZATION_CHAIN:
            raw_value = ImportNormalizer.clean_text(
                values.get(field_name),
            )

            if not raw_value:
                resolved[field_name] = None
                continue

            queryset = cls.scoped_queryset(
                model,
                parents=parents,
                resolved=resolved,
            )

            instance, match_count = cls.match(queryset, raw_value)

            if instance is None:
                scope = cls.describe_scope(parents, resolved)

                errors.setdefault(field_name, []).append(
                    f"{label} '{raw_value}' not found{scope}.",
                )
            elif match_count > 1:
                # Kode yang sama dipakai beberapa kali di lingkup ini.
                # Menebak salah satu berisiko salah tempat, jadi ditolak.
                scope = cls.describe_scope(parents, resolved)

                errors.setdefault(field_name, []).append(
                    f"{label} '{raw_value}' is ambiguous{scope}. "
                    f"Provide a more specific parent column.",
                )

                instance = None

            resolved[field_name] = instance

        cls.validate_groups(
            normalized=values,
            resolved=resolved,
            errors=errors,
        )

        return resolved, errors

    @staticmethod
    def describe_scope(parents, resolved) -> str:
        labels = [
            str(resolved[parent])
            for parent in parents
            if resolved.get(parent) is not None
        ]

        if not labels:
            return ""

        return f" within {' / '.join(labels)}"

    # ------------------------------------------------------------------
    # Aturan antar-kolom
    # ------------------------------------------------------------------

    @classmethod
    def validate_groups(
        cls,
        *,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
        errors: dict[str, list[str]],
    ) -> None:
        # Company wajib bila ada kolom penempatan lain terisi.
        has_organization_detail = any(
            resolved.get(field_name) is not None
            for field_name in ORGANIZATION_DETAIL_FIELDS
        )

        if has_organization_detail and resolved.get("company") is None:
            errors.setdefault("company", []).append(
                "Company is required when organization "
                "columns are filled.",
            )

        if resolved.get("company") is not None:
            if not normalized.get("organization_effective_date"):
                errors.setdefault(
                    "organization_effective_date",
                    [],
                ).append(
                    "Effective date is required when company is set.",
                )

        # Nomor rekening butuh bank.
        account_number = ImportNormalizer.clean_text(
            normalized.get("bank_account_number"),
        )

        if account_number and resolved.get("bank") is None:
            errors.setdefault("bank", []).append(
                "Bank is required when account number is filled.",
            )

        # Data payroll ditulis sebagai PayrollAssignment, yang wajib
        # punya payroll group, mata uang, dan tanggal berlaku. Kalau
        # salah satunya kurang, baris ditolak — lebih baik daripada
        # menebak grup payroll karyawan.
        # PTKP hasil pengalihan dari kolom marital status tidak dihitung:
        # baris seperti itu tetap boleh masuk, tax status-nya saja yang
        # tidak tersimpan karena tidak ada tempatnya tanpa payroll group.
        has_payroll_detail = (
            resolved.get("payroll_group") is not None
            or (
                resolved.get("tax_status") is not None
                and not normalized.get("_tax_status_auto")
            )
        )

        if has_payroll_detail:
            if resolved.get("payroll_group") is None:
                errors.setdefault("payroll_group", []).append(
                    "Payroll Group is required when payroll "
                    "columns are filled.",
                )

            if resolved.get("payroll_currency") is None:
                base_currency = (
                    cls.base_queryset(Currency)
                    .filter(is_base_currency=True)
                    .first()
                )

                if base_currency is None:
                    errors.setdefault("payroll_currency", []).append(
                        "Payroll currency is required: no base "
                        "currency is configured.",
                    )
                else:
                    resolved["payroll_currency"] = base_currency

            if not normalized.get("organization_effective_date"):
                errors.setdefault(
                    "organization_effective_date",
                    [],
                ).append(
                    "Effective date is required when payroll "
                    "columns are filled.",
                )

        # `EmploymentAssignment.clean()` mewajibkan contract type
        # begitu masa kontrak diisi. Diperiksa di sini supaya user
        # melihatnya sebagai error kolom di preview, bukan sebagai
        # ValidationError mentah yang baru meledak saat menulis.
        has_contract_period = any(
            ImportNormalizer.clean_text(normalized.get(field_name))
            for field_name in ("contract_start", "contract_end")
        )

        if has_contract_period and resolved.get("contract_type") is None:
            errors.setdefault("contract_type", []).append(
                "Contract Type is required when contract start or "
                "end date is filled.",
            )

        # Institusi butuh jenjang pendidikan.
        institution = ImportNormalizer.clean_text(
            normalized.get("institution_name"),
        )

        if institution and resolved.get("education") is None:
            errors.setdefault("education", []).append(
                "Education level is required when institution "
                "is filled.",
            )
