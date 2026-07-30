from typing import Any

from django.db import models


def model_field_names(
    model: type[models.Model],
) -> set[str]:
    return {
        field.name
        for field in model._meta.get_fields()
        if getattr(field, "concrete", False)
    }


def has_model_field(
    model: type[models.Model],
    field_name: str,
) -> bool:
    return field_name in model_field_names(model)


def model_to_choice(
    instance: models.Model,
    *,
    value_field: str = "pk",
    label_field: str = "name",
) -> dict[str, Any]:
    value = (
        instance.pk
        if value_field == "pk"
        else getattr(instance, value_field)
    )

    label = getattr(
        instance,
        label_field,
        str(instance),
    )

    return {
        "value": value,
        "label": label,
    }