from django.conf import settings
from django.db import models

from apps.core.models.base import BaseModel
from .organization import Company, Site

# OPEN → CLOSING → LOCKED
# LOCKED → OPEN/CLOSING pakai unlock_reason

class FiscalYear(BaseModel):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="fiscal_years",
    )

    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)

    year = models.PositiveIntegerField()

    start_date = models.DateField()
    end_date = models.DateField()

    is_closed = models.BooleanField(default=False)

    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        db_table = "master_fiscal_year"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                name="uniq_core_fiscal_year_company_code",
            ),
            models.UniqueConstraint(
                fields=["company", "year"],
                name="uniq_core_fiscal_year_company_year",
            ),
        ]
        ordering = ["-year"]

    def __str__(self):
        return self.name


class PostingPeriod(BaseModel):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSING = "CLOSING", "Closing"
        LOCKED = "LOCKED", "Locked"

    fiscal_year = models.ForeignKey(
        FiscalYear,
        on_delete=models.CASCADE,
        related_name="periods",
    )

    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)

    start_date = models.DateField()
    end_date = models.DateField()

    status = models.CharField( max_length=20, choices=Status.choices, default=Status.OPEN)

    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    unlocked_at = models.DateTimeField(null=True, blank=True)
    unlocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    unlock_reason = models.TextField(blank=True)

    class Meta:
        db_table = "master_posting_period"
        constraints = [
            models.UniqueConstraint(
                fields=["fiscal_year", "code"],
                name="uniq_core_posting_period_fiscal_year_code",
            ),
        ]
        ordering = ["start_date"]

    def __str__(self):
        return self.name


class WorkCalendar(BaseModel):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="work_calendars",
    )

    site = models.ForeignKey(
        Site,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="work_calendars",
    )

    code = models.CharField(max_length=30)
    name = models.CharField(max_length=100)

    monday = models.BooleanField(default=True)
    tuesday = models.BooleanField(default=True)
    wednesday = models.BooleanField(default=True)
    thursday = models.BooleanField(default=True)
    friday = models.BooleanField(default=True)
    saturday = models.BooleanField(default=False)
    sunday = models.BooleanField(default=False)

    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "master_work_calendar"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                name="uniq_core_work_calendar_company_code",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Holiday(BaseModel):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="holidays",
    )

    site = models.ForeignKey(
        Site,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="holidays",
    )

    date = models.DateField()

    code = models.CharField(max_length=30)
    name = models.CharField(max_length=150)

    is_national = models.BooleanField(default=False)
    is_recurring = models.BooleanField(default=False)

    class Meta:
        db_table = "master_holiday"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "site", "date"],
                name="uniq_core_holiday_company_site_date",
            ),
        ]
        ordering = ["date"]

    def __str__(self):
        return self.name