from __future__ import annotations

import csv
import json

from django.db.models import Count
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.permissions import (
    IsAuthenticated,
)
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.imports.authority import readable_jobs
from apps.imports.models import (
    ImportJob,
    ImportJobError,
)

from .pagination import (
    ImportJobPagination,
)

from .serializers import (
    ImportJobDetailSerializer,
    ImportJobErrorSerializer,
    ImportJobListSerializer,
)


def build_success_response(
    *,
    data,
    message: str,
    status_code: int = status.HTTP_200_OK,
    meta: dict | None = None,
) -> Response:
    payload = {
        "success": True,
        "message": message,
        "data": data,
        "status_code": status_code,
    }

    if meta is not None:
        payload["meta"] = meta

    return Response(
        payload,
        status=status_code,
    )


class ImportJobListAPIView(
    APIView,
):
    permission_classes = [
        IsAuthenticated,
    ]

    pagination_class = (
        ImportJobPagination
    )

    def get(
        self,
        request,
    ) -> Response:
        queryset = readable_jobs(
            (
                ImportJob.objects
                .select_related(
                    "imported_by",
                )
                .annotate(
                    error_count=Count(
                        "errors",
                    ),
                )
                .filter(
                    is_deleted=False,
                )
            ),
            request.user,
        )

        module = str(
            request.query_params.get(
                "module",
                "",
            )
        ).strip()

        job_status = str(
            request.query_params.get(
                "status",
                "",
            )
        ).strip()

        source_type = str(
            request.query_params.get(
                "source_type",
                "",
            )
        ).strip()

        search = str(
            request.query_params.get(
                "search",
                "",
            )
        ).strip()

        if module:
            queryset = queryset.filter(
                module=module,
            )

        if job_status:
            queryset = queryset.filter(
                status=job_status,
            )

        if source_type:
            queryset = queryset.filter(
                source_type=source_type,
            )

        if search:
            queryset = queryset.filter(
                filename__icontains=search,
            )

        paginator = (
            self.pagination_class()
        )

        page = paginator.paginate_queryset(
            queryset,
            request,
            view=self,
        )

        serializer = (
            ImportJobListSerializer(
                page,
                many=True,
            )
        )

        return build_success_response(
            data=serializer.data,
            message=(
                "Import history retrieved "
                "successfully."
            ),
            meta={
                "count":
                    paginator.page
                    .paginator
                    .count,

                "total_pages":
                    paginator.page
                    .paginator
                    .num_pages,

                "page":
                    paginator.page.number,

                "page_size":
                    paginator.get_page_size(
                        request,
                    ),

                "next":
                    paginator.get_next_link(),

                "previous":
                    paginator
                    .get_previous_link(),
            },
        )


class ImportJobDetailAPIView(
    APIView,
):
    permission_classes = [
        IsAuthenticated,
    ]

    def get(
        self,
        request,
        public_id,
    ) -> Response:
        job = get_object_or_404(
            readable_jobs(
                (
                    ImportJob.objects
                    .select_related(
                        "imported_by",
                    )
                    .annotate(
                        error_count=Count(
                            "errors",
                        ),
                    )
                    .filter(
                        is_deleted=False,
                    )
                ),
                request.user,
            ),
            public_id=public_id,
        )

        serializer = (
            ImportJobDetailSerializer(
                job,
            )
        )

        return build_success_response(
            data=serializer.data,
            message=(
                "Import job retrieved "
                "successfully."
            ),
        )


class ImportJobErrorListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    pagination_class = (ImportJobPagination)

    def get(
        self,
        request,
        public_id,
    ) -> Response:
        job = get_object_or_404(
            readable_jobs(
                ImportJob.objects.filter(
                    public_id=public_id,
                    is_deleted=False,
                ),
                request.user,
            )
        )

        queryset = (
            ImportJobError.objects
            .filter(
                job=job,
                is_deleted=False,
            )
        )

        field_name = str(
            request.query_params.get(
                "field_name",
                "",
            )
        ).strip()

        employee_code = str(
            request.query_params.get(
                "employee_code",
                "",
            )
        ).strip()

        if field_name:
            queryset = queryset.filter(
                field_name=field_name,
            )

        if employee_code:
            queryset = queryset.filter(
                employee_code__icontains=
                    employee_code,
            )

        paginator = (self.pagination_class())

        page = paginator.paginate_queryset(
            queryset,
            request,
            view=self,
        )

        serializer = (
            ImportJobErrorSerializer(
                page,
                many=True,
            )
        )

        return build_success_response(
            data=serializer.data,
            message=(
                "Import errors retrieved "
                "successfully."
            ),
            meta={
                "count":
                    paginator.page
                    .paginator
                    .count,

                "total_pages":
                    paginator.page
                    .paginator
                    .num_pages,

                "page":
                    paginator.page.number,

                "page_size":
                    paginator.get_page_size(
                        request,
                    ),

                "next":
                    paginator.get_next_link(),

                "previous":
                    paginator
                    .get_previous_link(),
            },
        )


class ImportJobErrorReportAPIView(
    APIView,
):
    permission_classes = [
        IsAuthenticated,
    ]

    def get(
        self,
        request,
        public_id,
    ):
        job = get_object_or_404(
            readable_jobs(
                ImportJob.objects.filter(
                    public_id=public_id,
                    is_deleted=False,
                ),
                request.user,
            )
        )

        errors = (
            ImportJobError.objects
            .filter(
                job=job,
                is_deleted=False,
            )
            .order_by(
                "row_number",
                "id",
            )
        )

        filename = (
            f"import-errors-"
            f"{job.module}-"
            f"{job.public_id}.csv"
        )

        response = HttpResponse(
            content_type=(
                "text/csv; charset=utf-8"
            ),
        )

        response[
            "Content-Disposition"
        ] = (
            f'attachment; filename="{filename}"'
        )

        response.write(
            "\ufeff"
        )

        writer = csv.writer(
            response,
        )

        writer.writerow([
            "Row Number",
            "Employee Code",
            "Field",
            "Code",
            "Message",
            "Raw Data",
        ])

        for item in errors:
            writer.writerow([
                item.row_number or "",
                item.employee_code,
                item.field_name,
                item.code,
                item.message,
                json.dumps(
                    item.raw_data,
                    ensure_ascii=False,
                    default=str,
                ),
            ])

        return response


class ImportJobDeleteAPIView(
    APIView,
):
    permission_classes = [
        IsAuthenticated,
    ]

    def delete(
        self,
        request,
        public_id,
    ) -> Response:
        job = get_object_or_404(
            readable_jobs(
                ImportJob.objects.filter(
                    public_id=public_id,
                    is_deleted=False,
                ),
                request.user,
            )
        )

        job.is_deleted = True

        if hasattr(
            job,
            "deleted_by",
        ):
            job.deleted_by = (
                request.user
            )

        if hasattr(
            job,
            "deleted_at",
        ):
            from django.utils import timezone

            job.deleted_at = (
                timezone.now()
            )

        update_fields = [
            "is_deleted",
            "updated_at",
        ]

        if hasattr(
            job,
            "deleted_by",
        ):
            update_fields.append(
                "deleted_by",
            )

        if hasattr(
            job,
            "deleted_at",
        ):
            update_fields.append(
                "deleted_at",
            )

        job.save(
            update_fields=update_fields,
        )

        return build_success_response(
            data=None,
            message=(
                "Import history deleted "
                "successfully."
            ),
        )