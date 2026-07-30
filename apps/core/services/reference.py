from typing import Any

from django.core.exceptions import ValidationError

from apps.core.services.base import BaseService


class BaseReferenceService(BaseService):
    """
    Base service untuk master/reference.

    Standard fields:
    - code
    - name
    - description
    - is_active
    - sort_order
    """

    @classmethod
    def get_queryset(cls):
        queryset = super().get_queryset()

        model = cls.get_model()
        field_names = {
            field.name
            for field in model._meta.get_fields()
        }

        if "is_deleted" in field_names:
            queryset = queryset.filter(
                is_deleted=False,
            )

        return queryset

    # ---------------------------------------------------------
    # Standard API
    # ---------------------------------------------------------

    @classmethod
    def list(cls):
        return cls.get_queryset()

    @classmethod
    def retrieve(cls, pk):
        return cls.get_queryset().get(pk=pk)

    # ---------------------------------------------------------
    # Validation
    # ---------------------------------------------------------

    @classmethod
    def validate_unique_code(
        cls,
        *,
        code: str | None,
        instance=None,
    ) -> None:
        if not code:
            return

        queryset = cls.get_queryset().filter(
            code__iexact=code.strip(),
        )

        if instance is not None:
            queryset = queryset.exclude(pk=instance.pk)

        if queryset.exists():
            raise ValidationError({
                "code": (
                    f"Code '{code}' sudah digunakan."
                ),
            })

    # ---------------------------------------------------------
    # Hooks
    # ---------------------------------------------------------

    @classmethod
    def before_create(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = super().before_create(
            data=data,
            user=user,
            **kwargs,
        )

        code = data.get("code")

        if isinstance(code, str):
            data["code"] = code.strip().upper()

        name = data.get("name")

        if isinstance(name, str):
            data["name"] = name.strip()

        cls.validate_unique_code(
            code=data.get("code"),
        )

        if user is not None:
            model = cls.get_model()

            field_names = {
                field.name
                for field in model._meta.get_fields()
            }

            if "created_by" in field_names:
                data.setdefault(
                    "created_by",
                    user,
                )

        return data

    @classmethod
    def before_update(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = super().before_update(
            instance=instance,
            data=data,
            user=user,
            **kwargs,
        )

        code = data.get(
            "code",
            getattr(instance, "code", None),
        )

        if isinstance(code, str):
            code = code.strip().upper()

            if "code" in data:
                data["code"] = code

        name = data.get("name")

        if isinstance(name, str):
            data["name"] = name.strip()

        cls.validate_unique_code(
            code=code,
            instance=instance,
        )

        if user is not None:
            field_names = {
                field.name
                for field in instance._meta.get_fields()
            }

            if "updated_by" in field_names:
                data["updated_by"] = user

        return data