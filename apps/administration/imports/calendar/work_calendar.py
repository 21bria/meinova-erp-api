"""
Import Work Calendar lewat framework import yang sudah ada.

Satu baris file = satu **pola** hari kerja, bukan satu kalender tahunan
per company. File yang berisi satu baris `HO-STANDARD` bercakupan
GLOBAL menghasilkan satu record yang melayani seluruh perusahaan —
termasuk yang dibuat setelah import ini dijalankan.

Kunci bisnisnya `(scope, company, location, code)`, sama dengan
constraint di model. Baris yang kuncinya sudah ada **diperbarui**, dan
perbaruinya disebut di layar preview sebagai `UPDATE` — tidak ada
penimpaan yang diam.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.administration.models import CalendarScope, WorkCalendar
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


WEEKDAYS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

WEEKDAY_ALIASES_ID = {
    "monday": "senin",
    "tuesday": "selasa",
    "wednesday": "rabu",
    "thursday": "kamis",
    "friday": "jumat",
    "saturday": "sabtu",
    "sunday": "minggu",
}

# Bawaan tiap hari kalau kolomnya tidak ada di file sama sekali.
# Senin–Jumat, sama dengan bawaan model — file yang cuma berisi kode
# dan nama menghasilkan pola kantor, bukan kalender yang semua harinya
# mati (yang akan membuat setiap cuti memotong nol hari).
WEEKDAY_DEFAULTS = {
    "monday": True,
    "tuesday": True,
    "wednesday": True,
    "thursday": True,
    "friday": True,
    "saturday": False,
    "sunday": False,
}


WORK_CALENDAR_MAPPING: dict[str, list[str]] = {
    "code": CODE_ALIASES,
    "name": NAME_ALIASES,
    "scope": SCOPE_ALIASES,
    "company": COMPANY_ALIASES,
    "location": LOCATION_ALIASES,
    **{
        day: [
            day,
            WEEKDAY_ALIASES_ID[day],
            f"{day}_working",
            f"{day} working",
        ]
        for day in WEEKDAYS
    },
    "is_default": [
        "is_default",
        "is default",
        "default",
        "bawaan",
    ],
    "is_active": ACTIVE_ALIASES,
}


@register_importer
class WorkCalendarImporter(BaseImporter):
    module = "administration/calendar/work-calendar"
    label = "Work Calendar"

    source_types = ("csv",)

    mapping = WORK_CALENDAR_MAPPING

    required_fields = (
        "code",
        "name",
        "scope",
    )

    identity_field = "code"

    template_columns = (
        "code",
        "name",
        "scope",
        "company",
        "location",
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
        "is_default",
        "is_active",
    )

    # Tiga baris contoh, dan ketiganya menunjukkan satu hal masing-
    # masing: GLOBAL tanpa company (satu baris untuk semua), COMPANY
    # yang menimpanya, dan LOCATION yang menimpa keduanya. Yang mengisi
    # file perlu melihat ketiganya sebelum menerjemahkan daftarnya —
    # kolom company yang kosong di baris pertama adalah bagian yang
    # paling sering diisi "ALL" oleh yang belum pernah melihat
    # contohnya.
    template_sample_rows = (
        {
            "code": "HO-STANDARD",
            "name": "Head Office Standard",
            "scope": "GLOBAL",
            "company": "",
            "location": "",
            "monday": "Y",
            "tuesday": "Y",
            "wednesday": "Y",
            "thursday": "Y",
            "friday": "Y",
            "saturday": "N",
            "sunday": "N",
            "is_default": "Y",
            "is_active": "Y",
        },
        {
            "code": "MMR-OPS",
            "name": "MMR Operational",
            "scope": "COMPANY",
            "company": "MMR",
            "location": "",
            "monday": "Y",
            "tuesday": "Y",
            "wednesday": "Y",
            "thursday": "Y",
            "friday": "Y",
            "saturday": "Y",
            "sunday": "N",
            "is_default": "N",
            "is_active": "Y",
        },
        {
            "code": "SAGEA-MINE",
            "name": "Sagea Mine",
            "scope": "LOCATION",
            "company": "MMR",
            "location": "SAGEA-MINE",
            "monday": "Y",
            "tuesday": "Y",
            "wednesday": "Y",
            "thursday": "Y",
            "friday": "Y",
            "saturday": "Y",
            "sunday": "Y",
            "is_default": "N",
            "is_active": "Y",
        },
    )

    preview_columns = (
        {"key": "row_number", "label": "Row"},
        {"key": "code", "label": "Code"},
        {"key": "name", "label": "Name"},
        {"key": "scope", "label": "Scope"},
        {"key": "applies_to", "label": "Applies To"},
        {"key": "working_days", "label": "Working Days"},
        {"key": "is_default", "label": "Default"},
        {"key": "is_active", "label": "Active"},
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
            allowed_scopes=set(CalendarScope.values),
        )

        for day in WEEKDAYS:
            value = to_bool(
                normalized.get(day),
                default=WEEKDAY_DEFAULTS[day],
            )

            if value is None:
                errors.setdefault(day, []).append(
                    f"Nilai '{normalized.get(day)}' tidak dikenali. "
                    f"Pakai Y/N, TRUE/FALSE, atau 1/0.",
                )
            else:
                resolved[day] = value

        for flag, default in (("is_default", False), ("is_active", True)):
            value = to_bool(normalized.get(flag), default=default)

            if value is None:
                errors.setdefault(flag, []).append(
                    f"Nilai '{normalized.get(flag)}' tidak dikenali. "
                    f"Pakai Y/N, TRUE/FALSE, atau 1/0.",
                )
            else:
                resolved[flag] = value

        code = str(normalized.get("code") or "").strip()

        # Kalender yang seluruh harinya off hampir pasti salah isi, dan
        # akibatnya tidak terlihat: pemegangnya tidak punya satu pun
        # hari kerja, jadi setiap cuti memotong nol hari dan prorata
        # gajinya jadi nol. Ditolak di preview, bukan dibiarkan lolos.
        if not errors and not any(resolved.get(day) for day in WEEKDAYS):
            errors.setdefault("monday", []).append(
                "Seluruh hari ditandai off — kalender ini tidak punya "
                "satu pun hari kerja.",
            )

        if not errors:
            existing = cls._find_existing(code, resolved)

            resolved["_existing"] = existing
            resolved["_action"] = "UPDATE" if existing else "NEW"

        return resolved, errors

    @classmethod
    def _find_existing(cls, code: str, resolved: dict[str, Any]):
        """
        Baris yang kunci bisnisnya sama: cakupan + company + location +
        kode.

        **Bukan kode saja.** `HO-STANDARD` bercakupan GLOBAL dan
        `HO-STANDARD` milik satu perusahaan adalah dua master yang
        berbeda dan boleh hidup berdampingan; mencocokkan hanya lewat
        kode akan membuat import yang kedua menimpa yang pertama.
        """
        company = resolved.get("company")
        location = resolved.get("location")

        return (
            WorkCalendar.objects
            .filter(
                is_deleted=False,
                code__iexact=code,
                scope=resolved["scope"],
                company=company,
                location=location,
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
        from apps.administration.models.calendar import (
            scope_label,
            working_days_label,
        )

        scope = resolved.get("scope") or normalized.get("scope")

        applies_to = "-"

        if resolved.get("scope"):
            applies_to = scope_label(
                scope=resolved["scope"],
                company=resolved.get("company"),
                location=resolved.get("location"),
            )

        # Pola hari kerjanya ditampilkan sebagai satu sel — tujuh kolom
        # centang di layar preview membuat yang memeriksanya harus
        # menggulir menyamping untuk membaca satu baris.
        working_days = "-"

        if all(day in resolved for day in WEEKDAYS):
            working_days = working_days_label(
                {day: resolved[day] for day in WEEKDAYS},
            )

        return {
            "code": normalized.get("code"),
            "name": normalized.get("name"),
            "scope": scope,
            "applies_to": applies_to,
            "working_days": working_days,
            "is_default": resolved.get("is_default"),
            "is_active": resolved.get("is_active"),
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

        # Dicari ulang di sini, bukan memakai `_existing` dari preview:
        # dua baris untuk kunci yang sama di dalam **satu file** sama-
        # sama melihat "belum ada" saat preview dijalankan, karena saat
        # itu belum satu pun tertulis.
        instance = cls._find_existing(code, resolved)

        created = instance is None

        if created:
            instance = WorkCalendar(code=code)

        instance.name = str(normalized.get("name") or "").strip()
        instance.scope = resolved["scope"]
        instance.company = resolved.get("company")
        instance.location = resolved.get("location")

        for day in WEEKDAYS:
            setattr(instance, day, resolved[day])

        instance.is_default = resolved["is_default"]
        instance.is_active = resolved["is_active"]

        if user is not None and getattr(user, "is_authenticated", False):
            if created:
                instance.created_by = user

            instance.updated_by = user

        # `full_clean()` sebelum menyimpan — pola mutasi service yang
        # sama dipakai di seluruh repo ini. Validasi cakupan di model
        # adalah lapis terakhir kalau importer meleset.
        instance.full_clean(exclude=["created_by", "updated_by"])
        instance.save()

        return instance, created
