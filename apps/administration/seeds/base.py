# apps/administration/seeds/base.py
from typing import Any

from django.db import models


def model_field_names(model: type[models.Model]) -> set[str]:
    return {
        field.name
        for field in model._meta.get_fields()
        if getattr(field, "concrete", False)
    }


def seed_reference(
    model: type[models.Model],
    rows: list[dict[str, Any]],
    lookup: str = "code",
) -> None:
    fields = model_field_names(model)

    for index, row in enumerate(rows, start=1):
        values = row.copy()

        if "sort_order" in fields:
            values.setdefault("sort_order", index * 10)

        if "is_active" in fields:
            values.setdefault("is_active", True)

        lookup_value = values.pop(lookup)

        defaults = {
            key: value
            for key, value in values.items()
            if key in fields
        }

        model.objects.update_or_create(
            **{lookup: lookup_value},
            defaults=defaults,
        )