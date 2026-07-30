from django.http import Http404
from django_filters.rest_framework import DjangoFilterBackend

from rest_framework import filters
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import ModelViewSet

from apps.core.pagination import StandardPagination
from apps.framework.introspection import build_ui_schema


class BaseMasterViewSet(ModelViewSet):
    schema_type = "crud"
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    search_fields = ["code", "name"]
    ordering_fields = "__all__"
    ordering = ["name"]

    service_class = None

    framework_module = None
    schema = {}

    def get_queryset(self):
        return self.service_class.list()

    @action(
        detail=False,
        methods=["get"],
        url_path="ui-schema",
        permission_classes=[AllowAny],
    )
    def ui_schema_view(self, request):
        return Response(build_ui_schema(self, request))

