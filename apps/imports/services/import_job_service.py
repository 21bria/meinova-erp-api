from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from time import monotonic
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.imports.models import (
    ImportJob,
    ImportJobError,
    ImportJobStatus,
)


class ImportJobService:
    """
    Global service for recording import history.

    This service does not parse files and does not write
    module-specific records. It only manages:

    - Import job lifecycle
    - Import statistics
    - Import errors
    - Duration
    - Status
    - Audit metadata
    """

    @staticmethod
    def normalize_text(
        value: Any,
    ) -> str:
        return str(
            value or "",
        ).strip()

    @staticmethod
    def normalize_count(
        value: Any,
    ) -> int:
        try:
            normalized = int(
                value or 0,
            )
        except (
            TypeError,
            ValueError,
        ):
            return 0

        return max(
            normalized,
            0,
        )

    @staticmethod
    def calculate_duration_ms(
        *,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> int:
        if (
            started_at is None
            or finished_at is None
        ):
            return 0

        duration = (
            finished_at
            - started_at
        ).total_seconds()

        return max(
            int(
                duration * 1000,
            ),
            0,
        )

    @classmethod
    @transaction.atomic
    def start(
        cls,
        *,
        module: str,
        user=None,
        profile_code: str = "",
        profile_name: str = "",
        filename: str = "",
        source_type: str = "",
        source_file=None,
        metadata:
            dict[str, Any]
            | None = None,
    ) -> ImportJob:
        """
        Create a new processing import job.
        """

        started_at = timezone.now()

        create_payload: dict[
            str,
            Any,
        ] = {
            "module":
                cls.normalize_text(module,),

            "profile_code":
                cls.normalize_text(profile_code,),

            "profile_name":
                cls.normalize_text(profile_name,),

            "filename":
                cls.normalize_text(filename,),

            "source_type":
                cls.normalize_text(source_type,),

            "status":
                ImportJobStatus.PROCESSING,

            "started_at":
                started_at,

            "metadata":
                dict(
                    metadata
                    or {},
                ),

            "imported_by":
                user,
        }

        # Keep this optional so the service works even
        # before source_file is added to ImportJob.
        if (
            source_file is not None
            and hasattr(
                ImportJob,
                "source_file",
            )
        ):
            create_payload[
                "source_file"
            ] = source_file

        job = ImportJob.objects.create(
            **create_payload,
        )

        return job

    @classmethod
    @transaction.atomic
    def mark_processing(
        cls,
        job: ImportJob,
        *,
        metadata:
            dict[str, Any]
            | None = None,
    ) -> ImportJob:
        """
        Mark an existing job as processing.
        """

        changed_fields = {
            "status",
            "updated_at",
        }

        job.status = (
            ImportJobStatus.PROCESSING
        )

        if job.started_at is None:
            job.started_at = timezone.now()

            changed_fields.add(
                "started_at",
            )

        if metadata:
            job.metadata = {
                **(
                    job.metadata
                    or {}
                ),
                **metadata,
            }

            changed_fields.add("metadata",)

        job.save(
            update_fields=list(changed_fields,),
        )

        return job

    @classmethod
    @transaction.atomic
    def update_preview(
        cls,
        job: ImportJob,
        *,
        total_rows: int,
        valid_rows: int,
        invalid_rows: int,
        metadata:
            dict[str, Any]
            | None = None,
    ) -> ImportJob:
        """
        Store preview or validation statistics.
        """

        job.total_rows = (
            cls.normalize_count(
                total_rows,
            )
        )

        job.valid_rows = (
            cls.normalize_count(
                valid_rows,
            )
        )

        job.invalid_rows = (
            cls.normalize_count(
                invalid_rows,
            )
        )

        changed_fields = {
            "total_rows",
            "valid_rows",
            "invalid_rows",
            "updated_at",
        }

        if metadata:
            job.metadata = {
                **(
                    job.metadata
                    or {}
                ),
                **metadata,
            }

            changed_fields.add("metadata",)

        job.save(
            update_fields=list(
                changed_fields,
            ),
        )

        return job

    @classmethod
    @transaction.atomic
    def complete(
        cls,
        job: ImportJob,
        *,
        total_rows: int | None = None,
        valid_rows: int | None = None,
        invalid_rows: int | None = None,
        created_rows: int = 0,
        updated_rows: int = 0,
        duplicate_rows: int = 0,
        skipped_rows: int = 0,
        failed_rows: int = 0,
        metadata:
            dict[str, Any]
            | None = None,
    ) -> ImportJob:
        """
        Complete an import job and save final statistics.
        """

        finished_at = timezone.now()

        if total_rows is not None:
            job.total_rows = (
                cls.normalize_count(
                    total_rows,
                )
            )

        if valid_rows is not None:
            job.valid_rows = (
                cls.normalize_count(
                    valid_rows,
                )
            )

        if invalid_rows is not None:
            job.invalid_rows = (
                cls.normalize_count(
                    invalid_rows,
                )
            )

        job.created_rows = (
            cls.normalize_count(
                created_rows,
            )
        )

        job.updated_rows = (
            cls.normalize_count(
                updated_rows,
            )
        )

        job.duplicate_rows = (
            cls.normalize_count(
                duplicate_rows,
            )
        )

        job.skipped_rows = (
            cls.normalize_count(
                skipped_rows,
            )
        )

        job.failed_rows = (
            cls.normalize_count(
                failed_rows,
            )
        )

        job.finished_at = (
            finished_at
        )

        job.duration_ms = (
            cls.calculate_duration_ms(
                started_at=job.started_at,
                finished_at=finished_at,
            )
        )

        job.error_message = ""

        if (
            job.failed_rows > 0
            or job.invalid_rows > 0
        ):
            job.status = (
                ImportJobStatus.PARTIAL
            )
        else:
            job.status = (
                ImportJobStatus.COMPLETED
            )

        if metadata:
            job.metadata = {
                **(
                    job.metadata
                    or {}
                ),
                **metadata,
            }

        job.save(
            update_fields=[
                "status",
                "total_rows",
                "valid_rows",
                "invalid_rows",
                "created_rows",
                "updated_rows",
                "duplicate_rows",
                "skipped_rows",
                "failed_rows",
                "finished_at",
                "duration_ms",
                "error_message",
                "metadata",
                "updated_at",
            ],
        )

        return job

    @classmethod
    @transaction.atomic
    def fail(
        cls,
        job: ImportJob,
        *,
        error: Exception | str,
        failed_rows: int | None = None,
        metadata:
            dict[str, Any]
            | None = None,
    ) -> ImportJob:
        """
        Mark a job as failed.
        """

        finished_at = timezone.now()

        job.status = (
            ImportJobStatus.FAILED
        )

        job.finished_at = (
            finished_at
        )

        job.duration_ms = (
            cls.calculate_duration_ms(
                started_at=job.started_at,
                finished_at=finished_at,
            )
        )

        job.error_message = (
            cls.normalize_text(
                error,
            )
        )

        if failed_rows is not None:
            job.failed_rows = (
                cls.normalize_count(
                    failed_rows,
                )
            )

        if metadata:
            job.metadata = {
                **(
                    job.metadata
                    or {}
                ),
                **metadata,
            }

        job.save(
            update_fields=[
                "status",
                "finished_at",
                "duration_ms",
                "failed_rows",
                "error_message",
                "metadata",
                "updated_at",
            ],
        )

        return job

    @classmethod
    @transaction.atomic
    def add_error(
        cls,
        job: ImportJob,
        *,
        message: str,
        row_number: int | None = None,
        field_name: str = "",
        code: str = "",
        employee_code: str = "",
        raw_data:
            dict[str, Any]
            | None = None,
    ) -> ImportJobError:
        """
        Store one import row error.
        """

        error = (
            ImportJobError.objects.create(
                job=job,

                row_number=(
                    cls.normalize_count(
                        row_number,
                    )
                    if row_number
                    is not None
                    else None
                ),

                field_name=
                    cls.normalize_text(
                        field_name,
                    ),

                code=
                    cls.normalize_text(
                        code,
                    ),

                message=
                    cls.normalize_text(
                        message,
                    )
                    or "Import row failed.",

                employee_code=
                    cls.normalize_text(
                        employee_code,
                    ),

                raw_data=dict(
                    raw_data
                    or {},
                ),
            )
        )

        return error

    @classmethod
    @transaction.atomic
    def add_errors(
        cls,
        job: ImportJob,
        errors:
            Iterable[
                dict[str, Any]
            ],
        *,
        replace: bool = False,
        batch_size: int = 500,
    ) -> int:
        """
        Store many row errors using bulk_create.

        Expected error dictionary:

        {
            "row_number": 2,
            "field_name": "employee_code",
            "code": "not_found",
            "message": "Employee not found.",
            "employee_code": "EMP001",
            "raw_data": {...},
        }
        """

        if replace:
            ImportJobError.objects.filter(
                job=job,
            ).delete()

        objects: list[
            ImportJobError
        ] = []

        for item in errors:
            row_number = item.get(
                "row_number",
            )

            normalized_row_number = None

            if row_number not in (
                None,
                "",
            ):
                normalized_row_number = (
                    cls.normalize_count(
                        row_number,
                    )
                )

            objects.append(
                ImportJobError(
                    job=job,

                    row_number=
                        normalized_row_number,

                    field_name=
                        cls.normalize_text(
                            item.get(
                                "field_name",
                            )
                        ),

                    code=
                        cls.normalize_text(
                            item.get(
                                "code",
                            )
                        ),

                    message=
                        cls.normalize_text(
                            item.get(
                                "message",
                            )
                        )
                        or (
                            "Import row "
                            "failed."
                        ),

                    employee_code=
                        cls.normalize_text(
                            item.get(
                                "employee_code",
                            )
                        ),

                    raw_data=dict(
                        item.get(
                            "raw_data",
                        )
                        or {},
                    ),
                )
            )

        if not objects:
            return 0

        ImportJobError.objects.bulk_create(
            objects,
            batch_size=max(
                int(
                    batch_size
                    or 500,
                ),
                1,
            ),
        )

        return len(
            objects,
        )

    @classmethod
    @transaction.atomic
    def add_validation_errors(
        cls,
        job: ImportJob,
        *,
        row_number: int | None,
        employee_code: str = "",
        field_errors:
            dict[
                str,
                list[str] | str
            ],
        raw_data:
            dict[str, Any]
            | None = None,
    ) -> int:
        """
        Convert a field error dictionary into ImportJobError rows.

        Example input:

        {
            "employee_code": [
                "Employee not found.",
            ],
            "check_in": [
                "Invalid check-in time.",
            ],
        }
        """

        error_rows: list[
            dict[str, Any]
        ] = []

        for (
            field_name,
            messages,
        ) in field_errors.items():
            message_list = (
                messages
                if isinstance(
                    messages,
                    list,
                )
                else [messages]
            )

            for message in message_list:
                error_rows.append({
                    "row_number":
                        row_number,

                    "field_name":
                        field_name,

                    "message":
                        cls.normalize_text(
                            message,
                        ),

                    "employee_code":
                        employee_code,

                    "raw_data":
                        raw_data
                        or {},
                })

        return cls.add_errors(
            job,
            error_rows,
        )

    @classmethod
    def get_by_public_id(
        cls,
        public_id,
    ) -> ImportJob:
        """
        Retrieve an active job by public UUID.
        """

        return (
            ImportJob.objects
            .select_related(
                "imported_by",
            )
            .prefetch_related(
                "errors",
            )
            .get(
                public_id=public_id,
                is_deleted=False,
            )
        )

    @classmethod
    def list_jobs(
        cls,
        *,
        module: str | None = None,
        status: str | None = None,
        user=None,
    ):
        """
        Return import jobs queryset with optional filters.
        """

        queryset = (
            ImportJob.objects
            .select_related(
                "imported_by",
            )
            .filter(
                is_deleted=False,
            )
        )

        if module:
            queryset = queryset.filter(
                module=module,
            )

        if status:
            queryset = queryset.filter(
                status=status,
            )

        if user is not None:
            queryset = queryset.filter(
                imported_by=user,
            )

        return queryset

    @classmethod
    @transaction.atomic
    def delete_job(
        cls,
        job: ImportJob,
        *,
        user=None,
    ) -> ImportJob:
        """
        Soft-delete a job when supported by BaseModel.
        """

        if hasattr(
            job,
            "is_deleted",
        ):
            job.is_deleted = True

            update_fields = {
                "is_deleted",
                "updated_at",
            }

            if hasattr(
                job,
                "deleted_at",
            ):
                job.deleted_at = (
                    timezone.now()
                )

                update_fields.add(
                    "deleted_at",
                )

            if (
                user is not None
                and hasattr(
                    job,
                    "deleted_by",
                )
            ):
                job.deleted_by = user

                update_fields.add(
                    "deleted_by",
                )

            job.save(
                update_fields=list(
                    update_fields,
                ),
            )

            return job

        job.delete()

        return job


class ImportJobTimer:
    """
    Optional utility for measuring import duration before
    an ImportJob has been saved or when a custom timer is needed.
    """

    def __init__(self):
        self._started_at = (
            monotonic()
        )

    def elapsed_ms(self) -> int:
        elapsed = (
            monotonic()
            - self._started_at
        )

        return max(
            int(
                elapsed * 1000,
            ),
            0,
        )