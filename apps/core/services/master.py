from typing import Any

from django.db import transaction

from apps.core.services.base import BaseService


class BaseMasterService(BaseService):
    """
    Service dasar untuk master data yang memiliki:
    - relasi ke model lain;
    - child/detail;
    - validasi bisnis;
    - proses penyimpanan tambahan.
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
            queryset = queryset.filter(is_deleted=False)

        return queryset

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        return data

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        return data

    @classmethod
    def save_children(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> None:
        """
        Override pada service yang memiliki detail/child.

        Contoh:
        WorkScheduleService.save_children(...)
        """
        pass

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

        data = cls.prepare_create_data(
            data=data,
            user=user,
            **kwargs,
        )

        model = cls.get_model()
        field_names = {
            field.name
            for field in model._meta.get_fields()
        }

        if user is not None and "created_by" in field_names:
            data.setdefault("created_by", user)

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

        data = cls.prepare_update_data(
            instance=instance,
            data=data,
            user=user,
            **kwargs,
        )

        field_names = {
            field.name
            for field in instance._meta.get_fields()
        }

        if user is not None and "updated_by" in field_names:
            data["updated_by"] = user

        return data

    @classmethod
    @transaction.atomic
    def create_with_children(
        cls,
        *,
        data: dict[str, Any],
        children: dict[str, Any] | None = None,
        user=None,
        **kwargs,
    ):
        instance = cls.create(
            data=data,
            user=user,
            **kwargs,
        )

        cls.save_children(
            instance=instance,
            data=children or {},
            user=user,
            **kwargs,
        )

        return instance

    @classmethod
    @transaction.atomic
    def update_with_children(
        cls,
        *,
        instance,
        data: dict[str, Any],
        children: dict[str, Any] | None = None,
        user=None,
        **kwargs,
    ):
        instance = cls.update(
            instance=instance,
            data=data,
            user=user,
            **kwargs,
        )

        cls.save_children(
            instance=instance,
            data=children or {},
            user=user,
            **kwargs,
        )

        return instance