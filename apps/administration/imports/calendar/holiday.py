"""
Import Holiday lewat framework import yang sudah ada.

Yang membedakannya dari import master biasa: **satu baris file yang
bercakupan GLOBAL menghasilkan satu record**, bukan satu record per
perusahaan. File berisi lima belas tanggal merah untuk tenant berisi
dua puluh perusahaan menghasilkan lima belas baris, bukan tiga ratus.

Kunci bisnisnya `(scope, company, location, date, code)` — identitas
peristiwanya, bukan sekadar perusahaannya. Mengunggah ulang file yang
sama tidak menerbitkan salinan: barisnya dikenali dan ditandai
`UPDATE` di preview.
"""

from __future__ import annotations

from datetime import date as date_type
from typing import Any

from django.db import transaction

from apps.administration.models import (
    Holiday,
    HolidayCompany,
    HolidayScope,
    HolidaySource,
    HolidaySyncStatus,
)
from apps.framework.imports import BaseImporter, register_importer

from .common import (
    ACTIVE_ALIASES,
    CODE_ALIASES,
    COMPANY_ALIASES,
    LOCATION_ALIASES,
    NAME_ALIASES,
    SCOPE_ALIASES,
    resolve_scope_target,
    to_bool,
)


HOLIDAY_MAPPING: dict[str, list[str]] = {
    "date": [
        "date",
        "holiday_date",
        "holiday date",
        "tanggal",
        "tgl",
    ],
    "code": CODE_ALIASES,
    "name": NAME_ALIASES,
    "scope": SCOPE_ALIASES,
    "country_code": [
        "country_code",
        "country code",
        "country",
        "negara",
        "kode_negara",
    ],
    "company": COMPANY_ALIASES,
    "location": LOCATION_ALIASES,
    "is_national": [
        "is_national",
        "is national",
        "national",
        "nasional",
    ],
    "is_recurring": [
        "is_recurring",
        "is recurring",
        "recurring",
        "berulang",
        "tahunan",
    ],
    "is_active": ACTIVE_ALIASES,
    "source": [
        "source",
        "sumber",
        "asal",
    ],
}


@register_importer
class HolidayImporter(BaseImporter):
    module = "administration/calendar/holiday"
    label = "Holiday"

    source_types = ("csv",)

    mapping = HOLIDAY_MAPPING

    date_fields = ("date",)

    required_fields = (
        "date",
        "code",
        "name",
        "scope",
    )

    identity_field = "code"

    template_columns = (
        "date",
        "code",
        "name",
        "scope",
        "country_code",
        "company",
        "location",
        "is_national",
        "is_recurring",
        "is_active",
        "source",
    )

    # Tiga baris contoh yang mewakili tiga bentuk yang berbeda, dan
    # yang pertama adalah inti seluruh perubahan ini: satu baris untuk
    # 17 Agustus, tanpa company, berlaku ke semua.
    template_sample_rows = (
        {
            "date": "2026-08-17",
            "code": "INDEPENDENCE-2026",
            "name": "Indonesia Independence Day",
            "scope": "NATIONAL",
            "country_code": "ID",
            "company": "",
            "location": "",
            "is_national": "Y",
            "is_recurring": "N",
            "is_active": "Y",
            "source": "IMPORT",
        },
        {
            "date": "2026-07-01",
            "code": "SAFETY-DAY-PORT-2026",
            "name": "Sagea Port Operational Safety Day",
            "scope": "LOCATION",
            "country_code": "",
            "company": "MMR",
            "location": "SAGEA-PORT",
            "is_national": "N",
            "is_recurring": "N",
            "is_active": "Y",
            "source": "IMPORT",
        },
        {
            "date": "2026-12-24",
            "code": "CUTI-BERSAMA-2026",
            "name": "Cuti Bersama Natal",
            "scope": "SELECTED_COMPANIES",
            "country_code": "ID",
            # Dipisah koma di satu sel — bentuk yang paling wajar di
            # Excel, dan satu-satunya yang tidak memaksa orang membuat
            # tiga baris identik.
            "company": "MMR,MLS",
            "location": "",
            "is_national": "N",
            "is_recurring": "N",
            "is_active": "Y",
            "source": "IMPORT",
        },
    )

    preview_columns = (
        {"key": "row_number", "label": "Row"},
        {"key": "date", "label": "Date"},
        {"key": "code", "label": "Code"},
        {"key": "name", "label": "Name"},
        {"key": "scope", "label": "Scope"},
        {"key": "applies_to", "label": "Applies To"},
        {"key": "is_national", "label": "National"},
        {"key": "is_recurring", "label": "Recurring"},
        {"key": "action", "label": "Action"},
    )

    # ------------------------------------------------------------------
    # Resolusi
    # ------------------------------------------------------------------

    @classmethod
    def resolve(
        cls,
        normalized: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        resolved, errors = resolve_scope_target(
            normalized,
            allowed_scopes=set(HolidayScope.values),
            selected_scope=HolidayScope.SELECTED_COMPANIES,
        )

        holiday_date = cls._to_date(normalized.get("date"))

        if holiday_date is None:
            errors.setdefault("date", []).append(
                f"Tanggal '{normalized.get('date')}' tidak bisa dibaca. "
                f"Pakai format YYYY-MM-DD, atau isi datetime_formats di "
                f"Import Profile.",
            )
        else:
            resolved["date"] = holiday_date

        for flag, default in (
            ("is_national", False),
            ("is_recurring", False),
            ("is_active", True),
        ):
            value = to_bool(normalized.get(flag), default=default)

            if value is None:
                errors.setdefault(flag, []).append(
                    f"Nilai '{normalized.get(flag)}' tidak dikenali. "
                    f"Pakai Y/N, TRUE/FALSE, atau 1/0.",
                )
            else:
                resolved[flag] = value

        country_code = str(
            normalized.get("country_code") or "",
        ).strip().upper()

        if country_code and len(country_code) != 2:
            errors.setdefault("country_code", []).append(
                f"'{country_code}' bukan kode negara ISO dua huruf "
                f"(mis. ID).",
            )
        else:
            resolved["country_code"] = country_code

        source = str(normalized.get("source") or "").strip().upper()

        if source and source not in set(HolidaySource.values):
            errors.setdefault("source", []).append(
                f"Source '{source}' tidak dikenali. Pilihannya: "
                f"{', '.join(sorted(HolidaySource.values))}.",
            )
        else:
            # Kosong = IMPORT. Barisnya memang datang dari file, dan
            # menandainya MANUAL akan membuat jejak asal-usulnya bohong.
            resolved["source"] = source or HolidaySource.IMPORT

        if not errors:
            existing = cls._find_existing(normalized, resolved)

            resolved["_existing"] = existing
            resolved["_action"] = "UPDATE" if existing else "NEW"

        return resolved, errors

    @classmethod
    def _find_existing(cls, normalized: dict[str, Any], resolved: dict[str, Any]):
        """
        Identitas bisnis satu hari libur: cakupan + tanggal + kode.

        **Bukan company saja**, dan bukan tanggal saja. Libur nasional
        yang sudah ada tidak boleh dianggap baris baru cuma karena file
        berikutnya menuliskan perusahaan yang berbeda — itu persis
        duplikasi yang sedang dihapus task ini.
        """
        return (
            Holiday.objects
            .filter(
                is_deleted=False,
                code__iexact=str(normalized.get("code") or "").strip(),
                date=resolved.get("date"),
                scope=resolved["scope"],
                company=resolved.get("company"),
                location=resolved.get("location"),
            )
            .first()
        )

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
        from apps.administration.models.calendar import scope_label

        scope = resolved.get("scope") or normalized.get("scope")

        applies_to = "-"

        if resolved.get("scope") == HolidayScope.SELECTED_COMPANIES:
            companies = resolved.get("companies") or []

            applies_to = f"{len(companies)} companies"
        elif resolved.get("scope"):
            applies_to = scope_label(
                scope=resolved["scope"],
                company=resolved.get("company"),
                location=resolved.get("location"),
            )

        return {
            "date": resolved.get("date") or normalized.get("date"),
            "code": normalized.get("code"),
            "name": normalized.get("name"),
            "scope": scope,
            "applies_to": applies_to,
            "is_national": resolved.get("is_national"),
            "is_recurring": resolved.get("is_recurring"),
            "action": resolved.get("_action", "ERROR"),
        }

    # ------------------------------------------------------------------
    # Penulisan
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def write(
        cls,
        *,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
        user=None,
    ) -> tuple[Any, bool]:
        code = str(normalized.get("code") or "").strip()

        # Dicari ulang, bukan memakai `_existing` dari preview — dua
        # baris untuk kunci yang sama di dalam satu file sama-sama
        # melihat "belum ada" saat preview berjalan.
        instance = cls._find_existing(normalized, resolved)

        created = instance is None

        if created:
            instance = Holiday(code=code)

        instance.name = str(normalized.get("name") or "").strip()
        instance.date = resolved["date"]
        instance.scope = resolved["scope"]
        instance.company = resolved.get("company")
        instance.location = resolved.get("location")
        instance.country_code = resolved.get("country_code", "")
        instance.is_national = resolved["is_national"]
        instance.is_recurring = resolved["is_recurring"]
        instance.is_active = resolved["is_active"]
        instance.source = resolved["source"]

        # Import Excel/CSV **tidak** melewati gerbang review: yang
        # mengunggah filenya sudah membaca preview-nya baris per baris
        # sebelum menekan Confirm. Gerbang itu untuk sumber luar, yang
        # tidak ada manusianya di antara feed dan database.
        instance.sync_status = HolidaySyncStatus.CONFIRMED

        if user is not None and getattr(user, "is_authenticated", False):
            if created:
                instance.created_by = user

            instance.updated_by = user

        instance.full_clean(exclude=["created_by", "updated_by"])
        instance.save()

        if resolved["scope"] == HolidayScope.SELECTED_COMPANIES:
            cls._sync_companies(instance, resolved.get("companies") or [])

        return instance, created

    @staticmethod
    def _sync_companies(instance, companies):
        """
        Menyamakan daftar perusahaan dengan isi barisnya.

        Re-import yang menghapus satu perusahaan dari daftarnya harus
        benar-benar mencabutnya — daftar yang hanya bertambah membuat
        perusahaan yang sudah keluar tetap libur, dan tidak ada layar
        yang menunjukkan kenapa.
        """
        wanted = {company.id for company in companies}

        existing = {
            row.company_id: row
            for row in instance.companies.all()
        }

        for company_id, row in existing.items():
            should_be_active = company_id in wanted

            if row.is_deleted == should_be_active:
                row.is_deleted = not should_be_active
                row.save(update_fields=["is_deleted", "updated_at"])

        for company in companies:
            if company.id not in existing:
                HolidayCompany.objects.create(
                    holiday=instance,
                    company=company,
                )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _to_date(value: Any) -> date_type | None:
        if isinstance(value, date_type):
            return value

        text = str(value or "").strip()

        if not text:
            return None

        try:
            return date_type.fromisoformat(text)
        except ValueError:
            return None
