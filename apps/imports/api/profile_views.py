from __future__ import annotations

from django.db.models import Q
from rest_framework import filters
from rest_framework.permissions import IsAuthenticated
from rest_framework.viewsets import ReadOnlyModelViewSet

from apps.imports.models import ImportProfile

from .profile_serializers import ImportProfileLookupSerializer


class ImportProfileLookupViewSet(ReadOnlyModelViewSet):
    """
    Lookup profile import, difilter per module.

    GET /api/imports/profiles/lookup/?module=hr/employees
    """

    serializer_class = ImportProfileLookupSerializer

    permission_classes = [IsAuthenticated]

    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    search_fields = [
        "name",
        "code",
        "description",
    ]

    ordering = [
        "sort_order",
        "name",
    ]

    # query param -> kolom scope
    SCOPE_FILTERS = {
        "company_id": "company_id",
        "branch_id": "branch_id",
        "location_id": "location_id",
    }

    def get_queryset(self):
        queryset = ImportProfile.objects.filter(
            is_active=True,
            is_deleted=False,
        ).select_related(
            "company",
            "branch",
            "location",
        )

        module = str(
            self.request.query_params.get("module", "")
            or "",
        ).strip().strip("/")

        if module:
            queryset = queryset.filter(module=module)

        # Profile tanpa scope berlaku untuk semua, jadi tetap ikut
        # muncul saat user menyaring per company/branch/location.
        for param, column in self.SCOPE_FILTERS.items():
            value = self.request.query_params.get(param)

            if not value:
                continue

            queryset = queryset.filter(
                Q(**{column: value})
                | Q(**{f"{column}__isnull": True})
            )

        return queryset
