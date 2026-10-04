from __future__ import annotations

import logging

from rest_framework import filters


logger = logging.getLogger(__name__)


class SafeSearchFilter(filters.SearchFilter):
    """
    SearchFilter yang mengabaikan entri `search_fields` yang tidak ada
    pada model.

    `BaseMasterViewSet` memberi default `search_fields = ["code", "name"]`.
    Viewset untuk model tanpa kolom itu — dan yang lupa menimpanya —
    dulu membalas HTTP 500 setiap kali user mengetik di kotak pencarian.
    Kesalahan konfigurasi seperti itu seharusnya tidak menjatuhkan
    endpoint; cukup dicatat di log lalu field-nya dilewati.
    """

    # (model, tuple(fields)) -> tuple(field yang valid)
    _resolved_cache: dict = {}

    @staticmethod
    def resolve_model(view):
        queryset = getattr(view, "queryset", None)

        if queryset is not None:
            return queryset.model

        serializer_class = getattr(view, "serializer_class", None)

        return getattr(
            getattr(serializer_class, "Meta", None),
            "model",
            None,
        )

    @staticmethod
    def is_searchable(model, field_name: str) -> bool:
        # Buang prefix lookup milik DRF: ^ = @ $
        normalized = field_name.lstrip("^=@$")

        try:
            # .none() membangun query tanpa menyentuh database,
            # tapi tetap memvalidasi nama field.
            model.objects.none().filter(
                **{f"{normalized}__icontains": ""}
            )
        except Exception:
            return False

        return True

    def get_search_fields(self, view, request):
        fields = super().get_search_fields(view, request)

        if not fields:
            return fields

        model = self.resolve_model(view)

        if model is None:
            return fields

        key = (model, tuple(fields))

        cached = self._resolved_cache.get(key)

        if cached is None:
            cached = tuple(
                field
                for field in fields
                if self.is_searchable(model, field)
            )

            dropped = [
                field
                for field in fields
                if field not in cached
            ]

            if dropped:
                logger.warning(
                    "%s: search_fields %s tidak ada pada %s dan "
                    "diabaikan.",
                    view.__class__.__name__,
                    dropped,
                    model.__name__,
                )

            self._resolved_cache[key] = cached

        return list(cached)
