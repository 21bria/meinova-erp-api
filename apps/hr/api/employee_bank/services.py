from __future__ import annotations

from typing import Any

from apps.hr.models import EmployeeBankAccount


class EmployeeBankService:
    FIELDS = {
        "employee",
        "bank",
        "account_number",
        "account_name",
        "branch_name",
        "currency",
        "is_primary",
        "is_active",
        "notes",
    }

    @classmethod
    def extract(
        cls,
        validated_data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            key: validated_data.pop(key)
            for key in list(validated_data.keys())
            if key in cls.FIELDS
        }

    @classmethod
    def create(
        cls,
        *,
        data: dict[str, Any],
        user=None,
    ) -> EmployeeBankAccount:
        payload = dict(data)

        account = EmployeeBankAccount(
            **payload,
        )

        if user is not None:
            account.created_by = user
            account.updated_by = user

        account.full_clean()
        account.save()

        return account

    @classmethod
    def update(
        cls,
        *,
        instance: EmployeeBankAccount,
        data: dict[str, Any],
        user=None,
    ) -> EmployeeBankAccount:
        payload = dict(data)

        for key, value in payload.items():
            setattr(instance, key, value)

        if user is not None:
            instance.updated_by = user

        instance.full_clean()
        instance.save()

        return instance