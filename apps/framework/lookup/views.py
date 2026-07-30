from django.db.models import Q
from rest_framework.exceptions import NotFound
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .registry import registry


class LookupPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 100


class BaseLookupView(APIView):
    permission_classes = [
        IsAuthenticated,
    ]

    pagination_class = LookupPagination

    def get_lookup(self, lookup_name: str):
        lookup_class = registry.get(lookup_name)

        if lookup_class is None:
            raise NotFound(
                detail=f"Lookup '{lookup_name}' tidak ditemukan."
            )

        return lookup_class

    def apply_filters(
        self,
        queryset,
        lookup_class,
        request,
    ):
        filters = {}

        for field_name in lookup_class.filter_fields:
            value = request.query_params.get(field_name)

            if value in (None, ""):
                continue

            filters[field_name] = value

        if filters:
            queryset = queryset.filter(**filters)

        return queryset

    def apply_search(
        self,
        queryset,
        lookup_class,
        request,
    ):
        search = request.query_params.get("search", "").strip()

        if not search or not lookup_class.search_fields:
            return queryset

        query = Q()

        for field_name in lookup_class.search_fields:
            query |= Q(
                **{
                    f"{field_name}__icontains": search,
                }
            )

        return queryset.filter(query)

    def apply_ordering(
        self,
        queryset,
        lookup_class,
    ):
        if lookup_class.ordering:
            return queryset.order_by(
                *lookup_class.ordering
            )

        return queryset

    def get(
        self,
        request,
        lookup_name: str,
        pk: int | None = None,
    ):
        lookup_class = self.get_lookup(lookup_name)

        queryset = lookup_class.get_queryset()

        queryset = self.apply_filters(
            queryset,
            lookup_class,
            request,
        )

        queryset = self.apply_search(
            queryset,
            lookup_class,
            request,
        )

        queryset = self.apply_ordering(
            queryset,
            lookup_class,
        )

        if pk is not None:
            instance = queryset.filter(pk=pk).first()

            if instance is None:
                raise NotFound(
                    detail=(
                        f"Lookup '{lookup_name}' "
                        f"dengan id '{pk}' tidak ditemukan."
                    )
                )

            return Response(
                lookup_class.serialize(instance)
            )

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(
            queryset,
            request,
            view=self,
        )

        if page is not None:
            results = [
                lookup_class.serialize(item)
                for item in page
            ]

            return paginator.get_paginated_response(results)

        results = [
            lookup_class.serialize(item)
            for item in queryset
        ]

        return Response(
            {
                "count": len(results),
                "next": None,
                "previous": None,
                "results": results,
            }
        )