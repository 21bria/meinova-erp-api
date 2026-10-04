from __future__ import annotations

import csv
from math import ceil
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from django.db import connection
from django.http import HttpResponse
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.framework.imports import (
    ImportPipelineService,
    get_importer,
)
from apps.imports.services import ImportJobService
from apps.imports.tasks import run_import
from apps.uploads.services.upload_service import UploadService

from .import_serializers import (
    ImportConfirmSerializer,
    ImportPreviewSerializer,
)


def save_uploaded_file_to_temp(uploaded_file) -> Path:
    suffix = (
        Path(str(uploaded_file.name or ""))
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
            temporary_file.write(chunk)
    finally:
        temporary_file.close()

    return Path(temporary_file.name)


def remove_temp_file(file_path: Path | None) -> None:
    if file_path is None:
        return

    try:
        file_path.unlink(missing_ok=True)
    except OSError:
        pass


def get_pagination(request) -> tuple[int, int]:
    try:
        page = max(
            int(request.query_params.get("page", 1)),
            1,
        )

        page_size = min(
            max(
                int(request.query_params.get("page_size", 50)),
                1,
            ),
            200,
        )
    except (TypeError, ValueError):
        page = 1
        page_size = 50

    return page, page_size


def serialize_preview_result(
    result: dict[str, Any],
    *,
    page: int,
    page_size: int,
) -> dict[str, Any]:
    all_rows = result.get("rows", [])

    total_preview_rows = len(all_rows)

    start = (page - 1) * page_size
    end = start + page_size

    rows = []

    for row in all_rows[start:end]:
        payload = {
            key: value
            for key, value in row.items()
            if key not in {"normalized", "resolved"}
        }

        payload["rowNumber"] = row.get("row_number")

        rows.append(payload)

    total_pages = max(
        1,
        ceil(total_preview_rows / page_size),
    )

    return {
        "sourceType": result.get("source_type", "csv"),
        "duplicateRows": result.get("duplicate_rows", 0),
        "totalRows": result.get("total_rows", total_preview_rows),
        "validRows": result.get("valid_rows", 0),
        "invalidRows": result.get("invalid_rows", 0),
        "unmatchedRows": result.get("unmatched_rows", 0),

        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,

        "rows": rows,
    }


class BaseModuleImportAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get_importer(self, module: str):
        importer = get_importer(module)

        if importer is None:
            raise NotFound(
                f"No importer registered for module '{module}'.",
            )

        return importer


class ImportTemplateAPIView(BaseModuleImportAPIView):
    """
    GET /api/imports/<module>/template/

    Mengunduh file CSV kosong berisi header yang dikenali importer,
    supaya user tidak perlu menebak nama kolom.
    """

    def get(self, request, module: str):
        importer = self.get_importer(module)

        columns = importer.get_template_columns()

        slug = importer.module.strip("/").replace("/", "-")

        response = HttpResponse(content_type="text/csv")

        response["Content-Disposition"] = (
            f'attachment; filename="{slug}-import-template.csv"'
        )

        writer = csv.writer(response)

        writer.writerow(columns)

        for row in importer.get_template_rows():
            writer.writerow(row)

        return response


class ImportPreviewAPIView(BaseModuleImportAPIView):
    """
    POST /api/imports/<module>/preview/
    """

    def post(self, request, module: str) -> Response:
        importer = self.get_importer(module)

        serializer = ImportPreviewSerializer(
            data=request.data,
            module=importer.module,
        )

        serializer.is_valid(raise_exception=True)

        profile = serializer.validated_data["profile"]

        page, page_size = get_pagination(request)

        temporary_path: Path | None = None

        try:
            temporary_path = save_uploaded_file_to_temp(
                serializer.validated_data["file"],
            )

            result = ImportPipelineService.preview(
                module=importer,
                file_path=temporary_path,
                source_type=profile.source_type or "csv",
                parser_options=profile.parser_options,
                mapping=profile.mapping or None,
                defaults=profile.defaults or None,
                value_mapping=profile.value_mapping or None,
                date_formats=profile.datetime_formats or None,
                # Opsi profile ditimpa opsi unggahan. Itu yang membuat
                # satu profile bisa melayani beberapa mesin: format
                # filenya sama, `device_code`-nya yang berbeda.
                options={
                    **(profile.options or {}),
                    **(serializer.validated_data.get("options") or {}),
                },
                user=request.user,
                profile=profile,
            )

            return Response(
                {
                    "success": True,
                    "message": (
                        "Import preview generated successfully."
                    ),
                    "data": serialize_preview_result(
                        result,
                        page=page,
                        page_size=page_size,
                    ),
                },
                status=status.HTTP_200_OK,
            )
        finally:
            remove_temp_file(temporary_path)


class ImportConfirmAPIView(BaseModuleImportAPIView):
    """
    POST /api/imports/<module>/confirm/

    Mengantre job ke Celery lalu mengembalikan job public id supaya
    frontend bisa polling progresnya.
    """

    def post(self, request, module: str) -> Response:
        importer = self.get_importer(module)

        serializer = ImportConfirmSerializer(
            data=request.data,
            module=importer.module,
        )

        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data

        profile = validated_data["profile"]
        uploaded_file = validated_data["file"]

        job = None

        try:
            source_file = UploadService.create(
                uploaded_file=uploaded_file,
                user=request.user,
                metadata={
                    "category": "import",
                    "module": importer.module,
                    "profile_code": profile.code,
                },
                generate_preview=False,
            )

            job = ImportJobService.start(
                module=importer.module,
                user=request.user,
                profile_code=profile.code,
                profile_name=profile.name,
                filename=str(uploaded_file.name or ""),
                source_type=profile.source_type or "csv",
                source_file=source_file,
                metadata={
                    "endpoint": (
                        f"/api/imports/{importer.module}/confirm/"
                    ),
                },
            )

            task = run_import.delay(
                schema_name=connection.schema_name,
                job_public_id=str(job.public_id),
                module=importer.module,
                profile_id=profile.id,
                source_file_id=source_file.id,
                options=validated_data.get("options") or {},
                user_id=(
                    request.user.id
                    if request.user.is_authenticated
                    else None
                ),
                skip_invalid=validated_data.get(
                    "skip_invalid",
                    True,
                ),
            )

            job.metadata = {
                **(job.metadata or {}),
                "celery_task_id": task.id,
            }

            job.save(
                update_fields=["metadata", "updated_at"],
            )

            return Response(
                {
                    "success": True,
                    "message": "Import has been queued.",
                    "data": {
                        "jobPublicId": str(job.public_id),
                        "jobStatus": job.status,
                        "taskId": task.id,
                    },
                },
                status=status.HTTP_202_ACCEPTED,
            )

        except Exception as exc:
            if job is not None:
                ImportJobService.fail(
                    job,
                    error=exc,
                )

            raise
