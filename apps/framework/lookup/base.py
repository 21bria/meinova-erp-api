from __future__ import annotations

from typing import Any, Mapping

from django.db import models
from django.db.models import QuerySet


class BaseLookup:
    """
    Base definition for every lookup.
    """

    name: str | None = None

    model: type[models.Model] | None = None
    queryset: QuerySet | None = None

    value_field = "id"
    label_field = "name"

    search_fields: list[str] = []
    filter_fields: list[str] = []
    ordering: list[str] = []

    page_size = 20
    max_page_size = 100

    @classmethod
    def get_key(cls) -> str:
        if not cls.name:
            raise ValueError(
                f"{cls.__name__}.name is required."
            )

        return cls.name

    @classmethod
    def get_queryset(cls) -> QuerySet:
        if cls.queryset is not None:
            return cls.queryset.all()

        if cls.model is None:
            raise ValueError(
                f"{cls.__name__}.model is required."
            )

        return cls.model.objects.all()

    @classmethod
    def apply_filters(
        cls,
        queryset: QuerySet,
        params: Mapping[str, Any],
    ) -> QuerySet:
        """
        Apply only explicitly allowed query parameters.

        Example:
            ?company_id=1
            ?branch_id=2
        """

        filters: dict[str, Any] = {}

        for field_name in cls.filter_fields:
            value = params.get(field_name)

            if value in (None, ""):
                continue

            filters[field_name] = value

        if filters:
            queryset = queryset.filter(**filters)

        return queryset

    @classmethod
    def apply_ordering(
        cls,
        queryset: QuerySet,
    ) -> QuerySet:
        if cls.ordering:
            return queryset.order_by(*cls.ordering)

        return queryset

    @classmethod
    def serialize(
        cls,
        instance: models.Model,
    ) -> dict[str, Any]:
        return {
            "value": getattr(
                instance,
                cls.value_field,
            ),
            "label": getattr(
                instance,
                cls.label_field,
            ),
        }