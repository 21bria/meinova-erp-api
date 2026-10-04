from __future__ import annotations
from django.db import connection

from math import ceil
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from rest_framework import status
from rest_framework.permissions import (
    IsAuthenticated,
)
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.hr.imports.services import (
    AttendanceImportService,
)

from .import_serializers import (
    AttendanceImportConfirmSerializer,
    AttendanceImportPreviewSerializer,
)

from apps.imports.services import (
    ImportJobService,
)

from apps.uploads.services.upload_service import (
    UploadService,
)
from apps.hr.imports.tasks import (
    run_attendance_import,
)
def save_uploaded_file_to_temp(
    uploaded_file,
) -> Path:
    suffix = (
        Path(
            str(
                uploaded_file.name
                or "",
            )
        )
        .suffix
        .lower()
    )

    temporary_file = NamedTemporaryFile(
        mode="wb",
        suffix=suffix,
        delete=False,
    )

    try:
        for chunk in uploaded_file.chunks():
            temporary_file.write(chunk,)
    finally:
        temporary_file.close()

    return Path(
        temporary_file.name,
    )


def remove_temp_file(
    file_path: Path | None,
) -> None:
    if file_path is None:
        return

    try:
        file_path.unlink(missing_ok=True,)
    except OSError:
        pass


def get_pagination(
    request,
) -> tuple[int, int]:
    try:
        page = max(
            int(request.query_params.get("page",1,)),
            1,
        )

        page_size = min(
            max(int(request.query_params.get("page_size",50,)),
                1,
            ),
            200,
        )
    except (
        TypeError,
        ValueError,
    ):
        page = 1
        page_size = 50

    return page, page_size


def serialize_preview_result(
    result: dict[str, Any],
    *,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    all_rows = result.get(
        "rows",
        [],
    )

    total_preview_rows = len(all_rows)
    start = (page - 1) * page_size
    end = start + page_size

    page_rows = all_rows[start:end]

    rows: list[dict[str, Any]] = []

    for row in page_rows:
        rows.append({
            "rowNumber": row.get("row_number",),
            "row_number": row.get("row_number",),

            "sourceType": row.get("source_type",),
            "source_type": row.get("source_type",),

            "employeeCode": row.get("employee_code",),
            "employee_code": row.get("employee_code",),

            "employeeId": row.get("employee_id",),
            "employee_id": row.get("employee_id",),

            "employeeName": row.get("employee_name",),
            "employee_name": row.get("employee_name",),

            "logTime": row.get("log_time",),
            "log_time": row.get("log_time",),

            "logType": row.get("log_type",),
            "log_type": row.get("log_type",),

            "deviceCode": row.get("device_code",),
            "device_code": row.get("device_code",),

            "externalId": row.get("external_id",),
            "external_id": row.get("external_id"),

            "valid": row.get("valid",False,),

            "errors": row.get("errors",{},),
        })

    total_pages = max(
        1,
        ceil(
            total_preview_rows
            / page_size,
        ),
    )

    return {
        "sourceType": result.get("source_type","csv"),
        "totalRows": result.get("total_rows",total_preview_rows),
        "validRows": result.get("valid_rows",0),
        "invalidRows": result.get("invalid_rows",0),
        "unmatchedRows": result.get("unmatched_rows",0),

        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,

        "rows": rows,
    }


def serialize_confirm_result(
    result: dict[str, Any],
) -> dict[str, Any]:
    rows = []

    for row in result.get(
        "rows",
        [],
    ):
        rows.append({
            "rowNumber":
                row.get("row_number"),

            "recordId":
                row.get("attendance_id"),

            "attendanceId":
                row.get("attendance_id"),

            "employeeId":
                row.get("employee_id"),

            "created":
                row.get("created",False),

            "duplicate":
                row.get("duplicate",False),
        })

    return {
        "sourceType":
            result.get("source_type"),

        "totalRows":
            result.get("total_rows",0),

        "validRows":
            result.get("valid_rows",0),

        "invalidRows":
            result.get("invalid_rows",0),

        "createdRows":
            result.get("created_rows",0),

        "updatedRows":
            result.get("updated_rows",0),

        "duplicateRows":
            result.get("duplicate_rows",0),

        "skippedRows":
            result.get("skipped_rows",0),

        "failedRows":
            result.get("failed_rows",0),

        "rows":
            rows,
    }


class AttendanceImportPreviewAPIView(APIView,):
    permission_classes = [IsAuthenticated]

    def post(
        self,
        request,
    ) -> Response:
        serializer = (
            AttendanceImportPreviewSerializer(data=request.data)
        )

        serializer.is_valid(raise_exception=True,)

        validated_data = (serializer.validated_data)

        profile = validated_data["profile"]

        page, page_size = (get_pagination(request))

        temporary_path: Path | None = None

        try:
            temporary_path = (
                save_uploaded_file_to_temp(
                    validated_data["file"],
                )
            )

            result = (
                AttendanceImportService
                .preview(
                    source_type="csv",
                    file_path=temporary_path,
                    parser_options={
                        "encoding":
                            profile.encoding,

                        "delimiter":
                            profile.delimiter,
                    },
                    mapping=(
                        profile.mapping
                        or None
                    ),
                )
            )

            return Response(
                {
                    "success": True,
                    "message": (
                        "Attendance import preview "
                        "generated successfully."
                    ),
                    "data":
                        serialize_preview_result(
                            result,
                            page=page,
                            page_size=page_size,
                        ),
                },
                status=status.HTTP_200_OK,
            )
        finally:
            remove_temp_file(temporary_path)


class AttendanceImportConfirmAPIView(
    APIView,
):
    permission_classes = [IsAuthenticated]

    def post(
        self,
        request,
    ) -> Response:
        serializer = (
            AttendanceImportConfirmSerializer(
                data=request.data,
            )
        )

        serializer.is_valid(
            raise_exception=True,
        )

        validated_data = (
            serializer.validated_data
        )

        profile = validated_data[
            "profile"
        ]

        uploaded_file = validated_data[
            "file"
        ]

        source_file = None
        job = None

        try:
            source_file = (
                UploadService.create(
                    uploaded_file=
                        uploaded_file,

                    user=
                        request.user,

                    metadata={
                        "category":
                            "import",

                        "module":
                            "attendance",

                        "profile_code":
                            profile.code,
                    },

                    generate_preview=False,
                )
            )

            job = ImportJobService.start(
                module="attendance",
                user=request.user,
                profile_code=profile.code,
                profile_name=profile.name,
                filename=str(uploaded_file.name or "",),
                source_type="csv",
                source_file=source_file,
                metadata={
                    "endpoint": ("/api/hr/attendance/""import/confirm/"),
                    },
            )

            task = (
                run_attendance_import
                .delay(
                    schema_name=
                        connection.schema_name,

                    job_public_id=str(job.public_id,),

                    profile_id=profile.id,

                    source_file_id=source_file.id,

                    user_id=(
                        request.user.id
                        if request.user
                        .is_authenticated
                        else None
                    ),

                    skip_invalid=(
                        validated_data.get(
                            "skip_invalid",
                            True,
                        )
                    ),
                )
            )

            job.metadata = {
                **(
                    job.metadata
                    or {}
                ),

                "celery_task_id":
                    task.id,
            }

            job.save(
                update_fields=["metadata","updated_at"],
            )

            return Response(
                {
                    "success": True,

                    "message": (
                        "Attendance import "
                        "has been queued."
                    ),

                    "data": {
                        "jobPublicId":
                            str(job.public_id),

                        "jobStatus":
                            job.status,
                        "taskId":
                            task.id,
                    },
                },

                status=(
                    status.HTTP_202_ACCEPTED
                ),
            )

        except Exception as exc:
            if job is not None:
                ImportJobService.fail(
                    job,
                    error=exc,
                )

            raise