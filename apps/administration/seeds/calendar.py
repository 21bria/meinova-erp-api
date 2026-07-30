from calendar import monthrange
from datetime import date

from django.db import transaction

from apps.administration.models import (
    Company,
    FiscalYear,
    Holiday,
    PostingPeriod,
    Site,
    WorkCalendar,
)


@transaction.atomic
def seed():
    """Seed fiscal years, posting periods, work calendars, and holidays."""

    fiscal_year_count = 0
    posting_period_count = 0
    work_calendar_count = 0
    holiday_count = 0

    companies = Company.objects.filter(is_active=True)

    for company in companies:
        # ---------------------------------------------------------------------
        # Fiscal Year
        # ---------------------------------------------------------------------

        fiscal_year, _ = FiscalYear.objects.update_or_create(
            company=company,
            year=2026,
            defaults={
                "code": "FY2026",
                "name": "Fiscal Year 2026",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 12, 31),
                "is_closed": False,
                "closed_at": None,
                "closed_by": None,
            },
        )

        fiscal_year_count += 1

        # ---------------------------------------------------------------------
        # Posting Periods
        # ---------------------------------------------------------------------

        for month in range(1, 13):
            last_day = monthrange(2026, month)[1]

            PostingPeriod.objects.update_or_create(
                fiscal_year=fiscal_year,
                code=f"2026-{month:02d}",
                defaults={
                    "name": date(2026, month, 1).strftime("%B 2026"),
                    "start_date": date(2026, month, 1),
                    "end_date": date(2026, month, last_day),
                    "status": PostingPeriod.Status.OPEN,
                    "locked_at": None,
                    "locked_by": None,
                    "unlocked_at": None,
                    "unlocked_by": None,
                    "unlock_reason": "",
                },
            )

            posting_period_count += 1

        # ---------------------------------------------------------------------
        # Default Office Work Calendar
        # ---------------------------------------------------------------------

        WorkCalendar.objects.filter(
            company=company,
            is_default=True,
        ).update(is_default=False)

        office_calendar, _ = WorkCalendar.objects.update_or_create(
            company=company,
            code="OFFICE-2026",
            defaults={
                "name": "Office Calendar 2026",
                "site": None,
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
        # Company-level National Holidays
        # ---------------------------------------------------------------------

        national_holidays = [
            {
                "date": date(2026, 1, 1),
                "code": "NEW-YEAR-2026",
                "name": "New Year Holiday",
                "is_national": True,
                "is_recurring": False,
            },
            {
                "date": date(2026, 8, 17),
                "code": "INDEPENDENCE-2026",
                "name": "Indonesia Independence Day",
                "is_national": True,
                "is_recurring": False,
            },
            {
                "date": date(2026, 12, 25),
                "code": "CHRISTMAS-2026",
                "name": "Christmas Day",
                "is_national": True,
                "is_recurring": False,
            },
        ]

        for holiday_data in national_holidays:
            Holiday.objects.update_or_create(
                company=company,
                site=None,
                date=holiday_data["date"],
                defaults={
                    "code": holiday_data["code"],
                    "name": holiday_data["name"],
                    "is_national": holiday_data["is_national"],
                    "is_recurring": holiday_data["is_recurring"],
                },
            )

            holiday_count += 1

        # ---------------------------------------------------------------------
        # Site Work Calendars
        # ---------------------------------------------------------------------

        sites = Site.objects.filter(
            company=company,
            is_active=True,
        )

        for index, site in enumerate(sites, start=1):
            site_name = site.name.lower()

            if any(
                keyword in site_name
                for keyword in [
                    "mine",
                    "mining",
                    "site",
                    "pit",
                    "port",
                    "jetty",
                ]
            ):
                calendar_code = f"SITE-{site.pk}-2026"
                calendar_name = f"{site.name} Operational Calendar 2026"

                monday = True
                tuesday = True
                wednesday = True
                thursday = True
                friday = True
                saturday = True
                sunday = True

            elif any(
                keyword in site_name
                for keyword in [
                    "plant",
                    "factory",
                    "processing",
                    "smelter",
                    "warehouse",
                ]
            ):
                calendar_code = f"PLANT-{site.pk}-2026"
                calendar_name = f"{site.name} Plant Calendar 2026"

                monday = True
                tuesday = True
                wednesday = True
                thursday = True
                friday = True
                saturday = True
                sunday = False

            else:
                calendar_code = f"OFFICE-{site.pk}-2026"
                calendar_name = f"{site.name} Office Calendar 2026"

                monday = True
                tuesday = True
                wednesday = True
                thursday = True
                friday = True
                saturday = False
                sunday = False

            WorkCalendar.objects.update_or_create(
                company=company,
                code=calendar_code,
                defaults={
                    "name": calendar_name,
                    "site": site,
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
            # Site-specific Dummy Holiday
            # -----------------------------------------------------------------

            Holiday.objects.update_or_create(
                company=company,
                site=site,
                date=date(2026, 7, 1),
                defaults={
                    "code": f"SITE-DAY-{index:02d}-2026",
                    "name": f"{site.name} Operational Safety Day",
                    "is_national": False,
                    "is_recurring": False,
                },
            )

            holiday_count += 1

    return {
        "companies": companies.count(),
        "fiscal_years": fiscal_year_count,
        "posting_periods": posting_period_count,
        "work_calendars": work_calendar_count,
        "holidays": holiday_count,
    }