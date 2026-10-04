from calendar import monthrange
from datetime import date

from django.db import transaction

from apps.administration.models import (
    CalendarScope,
    Company,
    Holiday,
    HolidayScope,
    HolidaySource,
    Location,
    WorkCalendar,
)


@transaction.atomic
def seed():
    """
    Seed fiscal years, posting periods, work calendars, and holidays.

    **Yang bercakupan GLOBAL diseed sekali, di luar loop company.**
    Versi sebelumnya menaruh `OFFICE-2026` dan ketiga libur nasional di
    dalam loop, jadi tenant berisi dua puluh perusahaan mendapat dua
    puluh salinan masing-masing — dan itulah sumber duplikasi yang
    diperbaiki task ini. Fiscal Year dan Posting Period tetap per
    company: keduanya memang milik perusahaan (punya penutupan buku
    sendiri), bukan pola yang bisa dibagi.
    """

    work_calendar_count = 0
    holiday_count = 0

    companies = Company.objects.filter(is_active=True)

    # ---------------------------------------------------------------------
    # GLOBAL Work Calendar — satu baris untuk seluruh tenant
    # ---------------------------------------------------------------------
    #
    # Pola Senin–Jumat tidak berubah dari perusahaan ke perusahaan, jadi
    # tidak ada alasan menyimpannya berkali-kali. Kodenya `HO-STANDARD`
    # dan bukan `OFFICE-2026`: ini pola, bukan kalender tahunan, dan
    # tahun di dalam kode adalah undangan untuk menerbitkan
    # `OFFICE-2027` yang isinya sama persis.

    WorkCalendar.objects.update_or_create(
        scope=CalendarScope.GLOBAL,
        company=None,
        location=None,
        code="HO-STANDARD",
        defaults={
            "name": "Head Office Standard",
            "monday": True,
            "tuesday": True,
            "wednesday": True,
            "thursday": True,
            "friday": True,
            "saturday": False,
            "sunday": False,
            "is_default": True,
        },
    )

    work_calendar_count += 1

    # ---------------------------------------------------------------------
    # GLOBAL / National Holidays — satu baris masing-masing
    # ---------------------------------------------------------------------
    #
    # Perusahaan yang dibuat besok ikut mendapatkannya tanpa seed ulang:
    # yang tersimpan aturannya ("berlaku untuk semua"), bukan daftar
    # perusahaannya.

    national_holidays = [
        {
            "date": date(2026, 1, 1),
            "code": "NEW-YEAR-2026",
            "name": "New Year Holiday",
        },
        {
            "date": date(2026, 8, 17),
            "code": "INDEPENDENCE-2026",
            "name": "Indonesia Independence Day",
        },
        {
            "date": date(2026, 12, 25),
            "code": "CHRISTMAS-2026",
            "name": "Christmas Day",
        },
    ]

    for holiday_data in national_holidays:
        Holiday.objects.update_or_create(
            scope=HolidayScope.GLOBAL,
            company=None,
            location=None,
            date=holiday_data["date"],
            code=holiday_data["code"],
            defaults={
                "name": holiday_data["name"],
                "country_code": "ID",
                "is_national": True,
                "is_recurring": False,
                "source": HolidaySource.MANUAL,
            },
        )

        holiday_count += 1

    for company in companies:
        # Tahun buku dan periode akuntansi **tidak diseed di sini**
        # lagi — keduanya milik Finance. Lihat
        # `apps/finance/seeds/fiscal.py`, dipanggil
        # `tenant_command seed_finance`.

        # ---------------------------------------------------------------------
        # Location Work Calendars
        # ---------------------------------------------------------------------

        locations = Location.objects.filter(
            company=company,
            is_active=True,
        )

        for index, location in enumerate(locations, start=1):
            location_name = location.name.lower()

            if any(
                keyword in location_name
                for keyword in [
                    "mine",
                    "mining",
                    "location",
                    "pit",
                    "port",
                    "jetty",
                ]
            ):
                calendar_code = f"LOCATION-{location.pk}-2026"
                calendar_name = f"{location.name} Operational Calendar 2026"

                monday = True
                tuesday = True
                wednesday = True
                thursday = True
                friday = True
                saturday = True
                sunday = True

            elif any(
                keyword in location_name
                for keyword in [
                    "plant",
                    "factory",
                    "processing",
                    "smelter",
                    "warehouse",
                ]
            ):
                calendar_code = f"PLANT-{location.pk}-2026"
                calendar_name = f"{location.name} Plant Calendar 2026"

                monday = True
                tuesday = True
                wednesday = True
                thursday = True
                friday = True
                saturday = True
                sunday = False

            else:
                calendar_code = f"OFFICE-{location.pk}-2026"
                calendar_name = f"{location.name} Office Calendar 2026"

                monday = True
                tuesday = True
                wednesday = True
                thursday = True
                friday = True
                saturday = False
                sunday = False

            WorkCalendar.objects.update_or_create(
                company=company,
                location=location,
                code=calendar_code,
                defaults={
                    "name": calendar_name,
                    "scope": CalendarScope.LOCATION,
                    "monday": monday,
                    "tuesday": tuesday,
                    "wednesday": wednesday,
                    "thursday": thursday,
                    "friday": friday,
                    "saturday": saturday,
                    "sunday": sunday,
                    "is_default": False,
                },
            )

            work_calendar_count += 1

            # -----------------------------------------------------------------
            # Location-specific Dummy Holiday
            # -----------------------------------------------------------------

            Holiday.objects.update_or_create(
                company=company,
                location=location,
                date=date(2026, 7, 1),
                code=f"SAFETY-DAY-{location.pk}-2026",
                defaults={
                    "scope": HolidayScope.LOCATION,
                    "name": f"{location.name} Operational Safety Day",
                    "is_national": False,
                    "is_recurring": False,
                    "source": HolidaySource.MANUAL,
                },
            )

            holiday_count += 1

    return {
        "companies": companies.count(),
        "work_calendars": work_calendar_count,
        "holidays": holiday_count,
    }