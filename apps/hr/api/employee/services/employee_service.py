from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.hr.models import Employee

from .employment_service import EmploymentService
from .organization_service import OrganizationService
from .payroll_service import PayrollService


class EmployeeService:
    @staticmethod
    def list():
        return (
            Employee.objects
            .select_related(
                "user",
                "gender",
                "religion",
                "nationality",
                "blood_type",
                "marital_status",

                "organization",
                "organization__company",
                "organization__branch",
                "organization__site",
                "organization__division",
                "organization__department",
                "organization__section",
                "organization__position",
                "organization__job_level",
                "organization__job_grade",
                "organization__reports_to",
                "organization__cost_center",

                "employment",
                "employment__employment_status",
                "employment__employment_type",
                "employment__employee_group",
                "employment__contract_type",
                "employment__probation_type",
                "employment__termination_reason",
                "employment__work_schedule",
                "employment__working_calendar",
                "employment__shift",
            )
            .prefetch_related(
                "payroll_assignments",
            )
            .filter(is_deleted=False)
        )

    @classmethod
    def get_queryset(cls):
        return cls.list()

    @classmethod
    @transaction.atomic
    def create(
        cls,
        validated_data: dict[str, Any],
        *,
        user=None,
    ) -> Employee:
        payload = dict(validated_data)

        organization_data = payload.pop(
            "organization",
            {},
        )

        employment_data = payload.pop(
            "employment",
            {},
        )

        payroll_data = PayrollService.extract(
            payload,
        )

        employee = Employee(**payload)

        if user is not None:
            employee.created_by = user
            employee.updated_by = user

        employee.full_clean()
        employee.save()

        if organization_data:
            OrganizationService.save(
                employee=employee,
                data=organization_data,
                user=user,
            )

        if employment_data:
            EmploymentService.create_initial(
                employee=employee,
                data=employment_data,
                user=user,
            )

        if payroll_data:
            PayrollService.create_initial(
                employee=employee,
                data=payroll_data,
                user=user,
            )

        return employee

    @classmethod
    @transaction.atomic
    def update(
        cls,
        instance: Employee,
        validated_data: dict[str, Any],
        *,
        user=None,
    ) -> Employee:
        payload = dict(validated_data)

        organization_data = payload.pop(
            "organization",
            {},
        )

        employment_data = payload.pop(
            "employment",
            {},
        )

        payroll_data = PayrollService.extract(
            payload,
        )

        for field_name, value in payload.items():
            setattr(instance, field_name, value)

        if user is not None:
            instance.updated_by = user

        instance.full_clean()
        instance.save()

        if organization_data:
            OrganizationService.save(
                employee=instance,
                data=organization_data,
                user=user,
            )

        if employment_data:
            EmploymentService.update_current(
                employee=instance,
                data=employment_data,
                user=user,
            )

        if payroll_data:
            PayrollService.update_current(
                employee=instance,
                data=payroll_data,
                user=user,
            )

        return instance