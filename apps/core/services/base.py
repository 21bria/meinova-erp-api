from typing import Any

from django.db import models, transaction
from django.shortcuts import get_object_or_404


class BaseService:
    """
    Base service umum untuk operasi CRUD model.
    Service turunan wajib menentukan:
        model = SomeModel
    """

    model: type[models.Model] | None = None

    @classmethod
    def get_model(cls) -> type[models.Model]:
        if cls.model is None:
            raise NotImplementedError(
                f"{cls.__name__} harus menentukan atribut 'model'."
            )

        return cls.model

    @classmethod
    def get_queryset(cls):
        return cls.get_model().objects.all()

    @classmethod
    def get_by_id(cls, pk: Any):
        return get_object_or_404(
            cls.get_queryset(),
            pk=pk,
        )

    @classmethod
    def before_create(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        return data

    @classmethod
    def after_create(
        cls,
        *,
        instance: models.Model,
        user=None,
        **kwargs,
    ) -> models.Model:
        return instance

    @classmethod
    @transaction.atomic
    def create(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ):
        model = cls.get_model()

        prepared_data = cls.before_create(
            data=dict(data),
            user=user,
            **kwargs,
        )

        instance = model(**prepared_data)

        if hasattr(instance, "full_clean"):
            instance.full_clean()

        instance.save()

        return cls.after_create(
            instance=instance,
            user=user,
            **kwargs,
        )

    @classmethod
    def before_update(
        cls,
        *,
        instance: models.Model,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        return data

    @classmethod
    def after_update(
        cls,
        *,
        instance: models.Model,
        user=None,
        **kwargs,
    ) -> models.Model:
        return instance

    @classmethod
    @transaction.atomic
    def update(
        cls,
        *,
        instance: models.Model,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ):
        prepared_data = cls.before_update(
            instance=instance,
            data=dict(data),
            user=user,
            **kwargs,
        )

        for field_name, value in prepared_data.items():
            setattr(instance, field_name, value)

        if hasattr(instance, "full_clean"):
            instance.full_clean()

        instance.save()

        return cls.after_update(
            instance=instance,
            user=user,
            **kwargs,
        )

    @classmethod
    def before_delete(
        cls,
        *,
        instance: models.Model,
        user=None,
        **kwargs,
    ) -> None:
        pass

    @classmethod
    def after_delete(
        cls,
        *,
        instance: models.Model,
        user=None,
        **kwargs,
    ) -> None:
        pass

    @classmethod
    @transaction.atomic
    def delete(
        cls,
        *,
        instance: models.Model,
        user=None,
        **kwargs,
    ) -> None:
        cls.before_delete(
            instance=instance,
            user=user,
            **kwargs,
        )

        instance.delete()

        cls.after_delete(
            instance=instance,
            user=user,
            **kwargs,
        )