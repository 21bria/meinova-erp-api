from django.core.exceptions import FieldDoesNotExist
from django.db.models import Q, QuerySet


class BaseLookupService:
    registry = {}

    default_value_key = "id"
    default_label_key = "name"
    default_page_size = 10
    max_page_size = 100

    def __init__(self, lookup_name: str):
        self.lookup_name = lookup_name
        self.config = self.registry.get(lookup_name)

        if self.config is None:
            raise KeyError(lookup_name)

        self.model = self.config["model"]

    def get_queryset(self, request) -> QuerySet:
        queryset = self.model.objects.all()

        if self.has_model_field("is_active"):
            queryset = queryset.filter(is_active=True)

        parent_field = self.config.get("parent")

        if parent_field:
            parent_value = request.query_params.get(parent_field)

            if parent_value:
                queryset = queryset.filter(
                    **{f"{parent_field}_id": parent_value}
                )

        search = request.query_params.get("search", "").strip()

        if search:
            search_fields = self.config.get(
                "search_fields",
                ["name", "code"],
            )

            query = Q()

            for field_name in search_fields:
                if self.has_model_field(field_name):
                    query |= Q(
                        **{f"{field_name}__icontains": search}
                    )

            if query.children:
                queryset = queryset.filter(query)

        ordering = self.config.get("ordering")

        if ordering:
            queryset = queryset.order_by(*ordering)
        elif self.has_model_field("name"):
            queryset = queryset.order_by("name")
        elif self.has_model_field("code"):
            queryset = queryset.order_by("code")
        else:
            queryset = queryset.order_by("pk")

        return queryset

    def serialize(
        self,
        instance,
        value_key: str,
        label_key: str,
    ) -> dict:
        return {
            "value": self.resolve_attribute(instance, value_key),
            "label": str(
                self.resolve_attribute(instance, label_key)
            ),
        }

    def has_model_field(self, field_name: str) -> bool:
        try:
            self.model._meta.get_field(field_name)
            return True
        except FieldDoesNotExist:
            return False

    @staticmethod
    def resolve_attribute(instance, key: str):
        value = instance

        for part in key.split("."):
            value = getattr(value, part, None)

            if value is None:
                break

        return value