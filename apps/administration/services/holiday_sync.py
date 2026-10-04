"""
Fondasi sinkronisasi hari libur dari sumber luar.

**Yang ada di sini titik sambungnya, bukan integrasinya.** Google
Calendar, feed pemerintah, dan file ICS belum diimplementasikan — dan
itu keputusan, bukan pekerjaan yang tertinggal. Menulis scraper untuk
halaman SK cuti bersama hari ini menghasilkan kode yang rusak diam-diam
begitu halamannya berubah tata letak, dan yang rusak diam-diam pada
kalender berarti hari kerja yang salah tanpa ada yang tahu.

Yang **sudah** berlaku penuh adalah jalur reviewnya, dan itu bagian
yang menentukan keamanannya:

    External Source → fetch() → normalize() → stage()
        → [PENDING, tidak dibaca resolver]
        → review HR/Admin → confirm()/reject()
        → [CONFIRMED, baru berlaku]
        → Work Calendar / Attendance / Leave / Payroll

`CalendarResolver.base_holiday_queryset()` hanya membaca baris
`CONFIRMED`. Karena itu penyedia dari luar **tidak bisa** menggeser
hari kerja siapa pun tanpa ada yang menekan Confirm lebih dulu — bahkan
kalau providernya nanti ditulis salah.

Menambahkan penyedia baru: turunkan `HolidayProvider`, implementasikan
`fetch()`, daftarkan lewat `register_provider`. Tidak ada bagian lain
yang perlu disentuh.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Type

from django.db import transaction
from django.utils import timezone

from apps.administration.models import (
    Holiday,
    HolidayScope,
    HolidaySource,
    HolidaySyncStatus,
)


@dataclass
class NormalizedHoliday:
    """
    Satu hari libur dari luar, **sesudah** diseragamkan.

    Bentuk perantara yang sengaja tidak menyentuh model: penyedia
    menghasilkan ini, `HolidaySyncService` yang memutuskan apa yang
    tersimpan. Tanpa lapisan ini, tiap penyedia baru ikut memutuskan
    cakupan dan status barisnya sendiri — dan salah satunya akan
    menulis `CONFIRMED`.
    """

    date: date
    name: str
    code: str

    country_code: str = ""
    external_id: str = ""
    source_url: str = ""

    is_national: bool = True
    is_recurring: bool = False

    raw: dict[str, Any] = field(default_factory=dict)


class HolidayProvider:
    """
    Kontrak satu sumber hari libur dari luar.

    Turunan wajib mengisi `source` (salah satu `HolidaySource`) dan
    mengimplementasikan `fetch()`.
    """

    source: str = ""
    label: str = ""

    def fetch(
        self,
        *,
        year: int,
        country_code: str,
        **options: Any,
    ) -> list[NormalizedHoliday]:
        raise NotImplementedError(
            f"{type(self).__name__} harus mengimplementasikan fetch().",
        )


_PROVIDERS: dict[str, Type[HolidayProvider]] = {}


def register_provider(
    provider_class: Type[HolidayProvider],
) -> Type[HolidayProvider]:
    source = str(getattr(provider_class, "source", "") or "").strip()

    if not source:
        raise ValueError(
            f"{provider_class.__name__} harus menentukan atribut "
            f"'source'.",
        )

    _PROVIDERS[source] = provider_class

    return provider_class


def get_provider(source: str) -> HolidayProvider | None:
    provider_class = _PROVIDERS.get(str(source or "").strip().upper())

    return provider_class() if provider_class is not None else None


def available_sources() -> list[str]:
    return sorted(_PROVIDERS)


class HolidaySyncService:
    """
    Menaruh hasil sync ke ruang tunggu, lalu memindahkannya setelah
    ditinjau.
    """

    @classmethod
    @transaction.atomic
    def stage(
        cls,
        holidays: list[NormalizedHoliday],
        *,
        source: str,
        user=None,
    ) -> dict[str, int]:
        """
        Menyimpan hasil fetch sebagai baris `PENDING`.

        Cakupannya selalu GLOBAL: yang datang dari kalender nasional
        memang berlaku nasional, dan menebak perusahaan mana yang
        terkena bukan wewenang penyedia luar. Yang perlu dipersempit
        disunting saat review.

        Baris yang sudah **CONFIRMED** tidak disentuh sama sekali —
        sync kedua tidak boleh mengembalikan tanggal yang sudah ditolak
        atau menimpa yang sudah dibetulkan tangan.
        """
        created = 0
        updated = 0
        skipped = 0

        now = timezone.now()

        for item in holidays:
            existing = (
                Holiday.objects
                .filter(is_deleted=False, date=item.date, code__iexact=item.code)
                .first()
            )

            if existing is not None and existing.sync_status != (
                HolidaySyncStatus.PENDING
            ):
                # Sudah pernah diputuskan orang. Keputusan itu yang
                # menang, bukan feed-nya.
                skipped += 1

                continue

            instance = existing or Holiday(
                code=item.code,
                scope=HolidayScope.GLOBAL,
            )

            instance.date = item.date
            instance.name = item.name
            instance.country_code = item.country_code
            instance.is_national = item.is_national
            instance.is_recurring = item.is_recurring
            instance.external_id = item.external_id
            instance.source_url = item.source_url
            instance.source = source
            instance.synced_at = now
            instance.sync_status = HolidaySyncStatus.PENDING

            if user is not None and getattr(user, "is_authenticated", False):
                if existing is None:
                    instance.created_by = user

                instance.updated_by = user

            instance.full_clean(exclude=["created_by", "updated_by"])
            instance.save()

            if existing is None:
                created += 1
            else:
                updated += 1

        return {
            "created": created,
            "updated": updated,
            "skipped": skipped,
        }

    @classmethod
    def confirm(cls, holiday: Holiday, *, user=None) -> Holiday:
        """Baris ini berlaku mulai sekarang — Attendance/Payroll ikut."""
        holiday.sync_status = HolidaySyncStatus.CONFIRMED

        fields = ["sync_status", "updated_at"]

        if user is not None and getattr(user, "is_authenticated", False):
            holiday.updated_by = user
            fields.append("updated_by")

        holiday.save(update_fields=fields)

        return holiday

    @classmethod
    def reject(cls, holiday: Holiday, *, user=None) -> Holiday:
        """
        Ditolak, dan **tidak dihapus**.

        Barisnya tetap ada supaya sync berikutnya mengenalinya dan
        tidak menawarkannya lagi — lihat `stage()`.
        """
        holiday.sync_status = HolidaySyncStatus.REJECTED

        fields = ["sync_status", "updated_at"]

        if user is not None and getattr(user, "is_authenticated", False):
            holiday.updated_by = user
            fields.append("updated_by")

        holiday.save(update_fields=fields)

        return holiday

    @classmethod
    def pending(cls):
        """Antrean review."""
        return Holiday.objects.filter(
            is_deleted=False,
            sync_status=HolidaySyncStatus.PENDING,
        ).order_by("date")


# ----------------------------------------------------------------------
# NEXT / PENDING — penyedia yang belum ditulis
# ----------------------------------------------------------------------
#
# `HolidaySource` sudah menyebut GOOGLE, GOVERNMENT, dan ICS, tapi
# `_PROVIDERS` sengaja masih kosong. Yang dibutuhkan masing-masing
# sebelum boleh ditulis:
#
# * GOOGLE — pola integrasi OAuth/service-account belum ada di repo ini
#   sama sekali. Menulisnya berarti memutuskan di mana kredensial per
#   tenant disimpan, dan itu keputusan keamanan tersendiri.
# * GOVERNMENT — tidak ada API resmi; yang tersedia halaman HTML SK
#   cuti bersama. Scraper-nya rapuh dan rusaknya diam.
# * ICS — butuh parser iCalendar. Belum ada dependensinya di
#   `requirements.txt`, dan menambah dependensi bukan bagian task ini.
#
# Ketiganya menunggu keputusan, bukan menunggu waktu. Titik sambungnya
# sudah siap: `register_provider` + `HolidaySyncService.stage()`.
