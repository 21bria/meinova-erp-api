from __future__ import annotations

from django.db.models import Q
from rest_framework import filters
from rest_framework.permissions import (
    IsAuthenticated,
)
from rest_framework.viewsets import (
    ReadOnlyModelViewSet,
)

from apps.hr.models import (
    AttendanceImportProfile,
)

from .profile_serializers import (
    AttendanceImportProfileLookupSerializer,
)


class AttendanceImportProfileLookupViewSet(
    ReadOnlyModelViewSet,
):
    serializer_class = (
        AttendanceImportProfileLookupSerializer
    )

    permission_classes = [
        IsAuthenticated,
    ]

    filter_backends = [
        filters.SearchFilter,
        filters.OrderingFilter,
    ]

    search_fields = [
        "name",
        "code",
        "description",
        "company__name",
        "branch__name",
        "location__name",
    ]

    ordering = [
        "name",
    ]

    def get_queryset(self):
        queryset = (
            AttendanceImportProfile.objects
            .filter(
                is_active=True,
                is_deleted=False,
            )
            .select_related(
                "company",
                "branch",
                "location",
            )
        )

        company_id = (
            self.request.query_params.get(
                "company_id",
            )
        )

        branch_id = (
            self.request.query_params.get(
                "branch_id",
            )
        )

        location_id = (
            self.request.query_params.get(
                "location_id",
            )
        )

        if company_id:
            queryset = queryset.filter(
                Q(company_id=company_id)
                | Q(company__isnull=True)
            )

        if branch_id:
            queryset = queryset.filter(
                Q(branch_id=branch_id)
                | Q(branch__isnull=True)
            )

        if location_id:
            queryset = queryset.filter(
                Q(location_id=location_id)
                | Q(location__isnull=True)
            )

        return queryset