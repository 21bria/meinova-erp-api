from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base import BaseModel

from apps.administration.models import (
    EmploymentStatus,
    EmploymentType,
    EmployeeGroup,
    ContractType,
    ProbationType,
    TerminationReason,
    WorkCalendar,
    WorkSchedule,
    Shift,
)

from .employee import Employee

class EmploymentAssignment(BaseModel):
    employee = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        related_name="employment",
    )

    employment_status = models.ForeignKey(
        EmploymentStatus,
        on_delete=models.PROTECT,
        related_name="employee_employments",
    )

    employment_type = models.ForeignKey(
        EmploymentType,
        on_delete=models.PROTECT,
        related_name="employee_employments",
    )

    employee_group = models.ForeignKey(
        EmployeeGroup,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    contract_type = models.ForeignKey(
        ContractType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    probation_type = models.ForeignKey(
        ProbationType,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    join_date = models.DateField(
        null=True,
        blank=True,
    )

    employment_effective_date = models.DateField(
        null=True,
        blank=True,
    )

    confirmation_date = models.DateField(
        null=True,
        blank=True,
    )

    probation_start = models.DateField(
        null=True,
        blank=True,
    )

    probation_end = models.DateField(
        null=True,
        blank=True,
    )

    contract_start = models.DateField(
        null=True,
        blank=True,
    )

    contract_end = models.DateField(
        null=True,
        blank=True,
    )

    termination_date = models.DateField(
        null=True,
        blank=True,
    )

    termination_reason = models.ForeignKey(
        TerminationReason,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    retirement_date = models.DateField(
        null=True,
        blank=True,
    )

    work_schedule = models.ForeignKey(
        WorkSchedule,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    working_calendar = models.ForeignKey(
        WorkCalendar,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    shift = models.ForeignKey(
        Shift,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_employments",
    )

    notice_period_days = models.PositiveIntegerField(
        default=0,
    )

    employment_notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_employee_employment"
        ordering = [
            "employee__employee_number",
        ]


    def clean(self):
        super().clean()

        errors = {}

        # ---------------------------------------------------------
        # Probation
        # ---------------------------------------------------------

        if (
            self.probation_start
            and not self.probation_end
        ):
            errors["probation_end"] = (
                "Probation End wajib diisi."
            )

        if (
            self.probation_end
            and not self.probation_start
        ):
            errors["probation_start"] = (
                "Probation Start wajib diisi."
            )

        if (
            self.probation_start
            and self.probation_end
            and self.probation_end < self.probation_start
        ):
            errors["probation_end"] = (
                "Probation End tidak boleh lebih awal "
                "dari Probation Start."
            )

        if (
            self.probation_type
            and (
                not self.probation_start
                or not self.probation_end
            )
        ):
            errors["probation_type"] = (
                "Probation Start dan Probation End "
                "wajib diisi jika Probation Type dipilih."
            )

        # ---------------------------------------------------------
        # Contract
        # ---------------------------------------------------------

        if (
            self.contract_start
            and not self.contract_end
        ):
            errors["contract_end"] = (
                "Contract End wajib diisi."
            )

        if (
            self.contract_end
            and not self.contract_start
        ):
            errors["contract_start"] = (
                "Contract Start wajib diisi."
            )

        if (
            self.contract_start
            and self.contract_end
            and self.contract_end < self.contract_start
        ):
            errors["contract_end"] = (
                "Contract End tidak boleh lebih awal "
                "dari Contract Start."
            )

        if (
            (
                self.contract_start
                or self.contract_end
            )
            and not self.contract_type
        ):
            errors["contract_type"] = (
                "Contract Type wajib dipilih "
                "jika Contract Start atau Contract End diisi."
            )

        # ---------------------------------------------------------
        # Confirmation
        # ---------------------------------------------------------

        if (
            self.confirmation_date
            and self.confirmation_date < self.join_date
        ):
            errors["confirmation_date"] = (
                "Confirmation Date tidak boleh lebih awal "
                "dari Join Date."
            )

        # ---------------------------------------------------------
        # Termination
        # ---------------------------------------------------------

        if (
            self.termination_date
            and self.termination_date < self.join_date
        ):
            errors["termination_date"] = (
                "Termination Date tidak boleh lebih awal "
                "dari Join Date."
            )

        if (
            self.termination_reason
            and not self.termination_date
        ):
            errors["termination_date"] = (
                "Termination Date wajib diisi jika "
                "Termination Reason dipilih."
            )

        if (
            self.termination_date
            and not self.termination_reason
        ):
            errors["termination_reason"] = (
                "Termination Reason wajib diisi jika "
                "Termination Date diisi."
            )

        # ---------------------------------------------------------
        # Retirement
        # ---------------------------------------------------------

        if (
            self.retirement_date
            and self.retirement_date < self.join_date
        ):
            errors["retirement_date"] = (
                "Retirement Date tidak boleh lebih awal "
                "dari Join Date."
            )

        if errors:
            raise ValidationError(errors)


    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"{self.employee.full_name}"
        )