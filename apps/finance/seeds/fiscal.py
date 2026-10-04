"""
Tahun buku dan periodenya.

Pindah ke sini dari `apps/administration/seeds/calendar.py` bersama
kepemilikan modelnya. Yang berubah selain rumahnya: tahunnya tidak lagi
ditanam sebagai `2026`, melainkan diturunkan dari tanggal berjalan —
seed yang menerbitkan tahun buku yang sudah lewat membuat tenant baru
mendarat di sistem yang tidak bisa memposting apa pun hari ini, dan
kegagalannya baru terbaca sebagai "belum ada tahun buku yang memuat
tanggal ini" saat jurnal pertama dibuat.
"""

from __future__ import annotations

from datetime import date

from django.utils import timezone

from apps.finance.models import FiscalYear
from apps.finance.services import FiscalYearService


def seed_fiscal_years(*, companies, year: int | None = None, user=None) -> dict:
    """
    Satu tahun buku kalender + dua belas periode per perusahaan.

    Januari–Desember dipakai di sini karena itu yang paling lazim,
    **bukan karena sistemnya mengasumsikannya**. Tenant yang tahun
    bukunya April–Maret mengubah tanggalnya dari layar, atau memanggil
    `FiscalYearService.generate_periods` dengan rentang lain.
    """
    year = year or timezone.localdate().year

    created = 0
    periods = 0
    skipped = 0

    for company in companies:
        existing = FiscalYear.objects.filter(
            company=company,
            is_deleted=False,
            start_date__lte=date(year, 12, 31),
            end_date__gte=date(year, 1, 1),
        ).first()

        if existing is not None:
            skipped += 1

            continue

        fiscal_year = FiscalYearService.create(
            data={
                "company": company,
                "code": f"FY{year}",
                "name": f"Fiscal Year {year}",
                "start_date": date(year, 1, 1),
                "end_date": date(year, 12, 31),
                "status": "open",
                "is_current": True,
            },
            user=user,
        )

        created += 1

        periods += len(
            FiscalYearService.generate_periods(
                fiscal_year=fiscal_year,
                count=12,
                user=user,
            )
        )

    return {
        "fiscal_years": created,
        "periods": periods,
        "skipped": skipped,
    }
