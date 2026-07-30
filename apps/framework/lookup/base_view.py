from django.core.paginator import EmptyPage, Paginator
from django.shortcuts import get_object_or_404

from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


class BaseLookupView(APIView):
    permission_classes = [IsAuthenticated]
    service_class = None

    def get_service(self, lookup_name: str):
        if self.service_class is None:
            raise RuntimeError(
                f"{self.__class__.__name__} must define service_class."
            )

        try:
            return self.service_class(lookup_name)
        except KeyError:
            raise NotFound(
                detail=f"Lookup '{lookup_name}' not found."
            )

    def get_lookup_keys(self, request, service):
        value_key = request.query_params.get(
            "value_key",
            service.config.get(
                "value_key",
                service.default_value_key,
            ),
        )

        label_key = request.query_params.get(
            "label_key",
            service.config.get(
                "label_key",
                service.default_label_key,
            ),
        )

        return value_key, label_key

    def retrieve(
        self,
        request,
        lookup_name: str,
        pk,
    ):
        service = self.get_service(lookup_name)
        queryset = service.get_queryset(request)

        value_key, label_key = self.get_lookup_keys(
            request,
            service,
        )

        instance = get_object_or_404(
            queryset,
            pk=pk,
        )

        return Response(
            service.serialize(
                instance,
                value_key=value_key,
                label_key=label_key,
            )
        )

    def list(
        self,
        request,
        lookup_name: str,
    ):
        service = self.get_service(lookup_name)
        queryset = service.get_queryset(request)

        value_key, label_key = self.get_lookup_keys(
            request,
            service,
        )

        try:
            page = max(
                int(request.query_params.get("page", 1)),
                1,
            )
        except (TypeError, ValueError):
            page = 1

        try:
            page_size = int(
                request.query_params.get(
                    "page_size",
                    service.default_page_size,
                )
            )
        except (TypeError, ValueError):
            page_size = service.default_page_size

        page_size = max(
            1,
            min(
                page_size,
                service.max_page_size,
            ),
        )

        paginator = Paginator(
            queryset,
            page_size,
        )

        try:
            page_object = paginator.page(page)
        except EmptyPage:
            page_object = paginator.page(
                paginator.num_pages
            )

        results = [
            service.serialize(
                instance,
                value_key=value_key,
                label_key=label_key,
            )
            for instance in page_object.object_list
        ]

        return Response(
            {
                "count": paginator.count,
                "page": page_object.number,
                "page_size": page_size,
                "total_pages": paginator.num_pages,
                "next": (
                    page_object.next_page_number()
                    if page_object.has_next()
                    else None
                ),
                "previous": (
                    page_object.previous_page_number()
                    if page_object.has_previous()
                    else None
                ),
                "results": results,
            }
        )

    def get(
        self,
        request,
        lookup_name: str,
        pk=None,
    ):
        if pk is not None:
            return self.retrieve(
                request,
                lookup_name,
                pk,
            )

        return self.list(
            request,
            lookup_name,
        )