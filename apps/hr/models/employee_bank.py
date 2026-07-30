from django.db import models

from apps.core.models.base import BaseModel

from apps.administration.models import (
    Bank,
    Currency,
)

from .employee import Employee


class EmployeeBankAccount(BaseModel):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="bank_accounts",
    )

    bank = models.ForeignKey(
        Bank,
        on_delete=models.PROTECT,
        related_name="employee_bank_accounts",
    )

    account_name = models.CharField(
        max_length=200,
    )

    account_number = models.CharField(
        max_length=100,
    )

    branch_name = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_bank_accounts",
    )

    swift_code = models.CharField(
        max_length=30,
        blank=True,
        default="",
    )

    iban = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    is_primary = models.BooleanField(
        default=False,
    )

    is_active = models.BooleanField(
        default=True,
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_employee_bank_account"
        ordering = [
            "-is_primary",
            "bank__name",
            "account_name",
        ]
        indexes = [
            models.Index(
                fields=["employee"],
                name="idx_emp_bank_employee",
            ),
            models.Index(
                fields=["is_primary"],
                name="idx_emp_bank_primary",
            ),
            models.Index(
                fields=["is_active"],
                name="idx_emp_bank_active",
            ),
        ]

    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"{self.bank.name} "
            f"({self.account_number})"
        )