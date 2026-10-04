from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from celery import shared_task
from django.contrib.auth import (
    get_user_model,
)
from django_tenants.utils import (
    schema_context,
)

from apps.hr.imports.services import (
    AttendanceImportService,
)
from apps.hr.models import (
    AttendanceImportProfile,
)
from apps.imports.models import (
    ImportJob,
)
from apps.imports.services import (
    ImportJobService,
)
from apps.uploads.models import (
    UploadedFile,
)


def copy_uploaded_file_to_temp(
    uploaded_file: UploadedFile,
) -> Path:
    extension = str(
        uploaded_file.extension
        or Path(
            uploaded_file.original_name
            or uploaded_file.file.name
        ).suffix
        or ".csv"
    ).strip()

    if extension and not extension.startswith("."):
        extension = f".{extension}"

    temporary_file = NamedTemporaryFile(
        mode="wb",
        suffix=extension or ".csv",
        delete=False,
    )

    temporary_path = Path(
        temporary_file.name,
    )

    try:
        with uploaded_file.file.open(
            "rb",
        ) as source:
            while True:
                chunk = source.read(
                    1024 * 1024,
                )

                if not chunk:
                    break

                temporary_file.write(
                    chunk,
                )
    except Exception:
        temporary_file.close()

        temporary_path.unlink(
            missing_ok=True,
        )

        raise
    finally:
        if not temporary_file.closed:
            temporary_file.close()

    return temporary_path


def remove_temp_file(
    file_path: Path | None,
) -> None:
    if file_path is None:
        return

    try:
        file_path.unlink(
            missing_ok=True,
        )
    except OSError:
        pass


@shared_task(
    bind=True,
    autoretry_for=(
        ConnectionError,
        TimeoutError,
    ),
    retry_backoff=True,
    retry_jitter=True,
    retry_kwargs={
        "max_retries": 5,
    },
)
def run_attendance_import(
    self,
    *,
    schema_name: str,
    job_public_id: str,
    profile_id: int,
    source_file_id: int,
    user_id: int | None = None,
    skip_invalid: bool = True,
) -> dict[str, str]:
    temporary_path: Path | None = None

    with schema_context(
        schema_name,
    ):
        job = (
            ImportJob.objects
            .select_related(
                "source_file",
            )
            .get(
                public_id=job_public_id,
                is_deleted=False,
            )
        )

        profile = (
            AttendanceImportProfile.objects
            .get(
                pk=profile_id,
                is_active=True,
                is_deleted=False,
            )
        )

        source_file = (
            UploadedFile.objects
            .get(
                pk=source_file_id,
                is_deleted=False,
            )
        )

        user = None

        if user_id is not None:
            User = get_user_model()

            user = (
                User.objects
                .filter(
                    pk=user_id,
                )
                .first()
            )

        try:
            ImportJobService.mark_processing(
                job,
                metadata={
                    "celery_task_id":
                        self.request.id,
                },
            )

            temporary_path = (
                copy_uploaded_file_to_temp(
                    source_file,
                )
            )

            result = (
                AttendanceImportService
                .import_file(
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
                    user=user,
                    skip_invalid=skip_invalid,
                )
            )

            ImportJobService.add_errors(
                job,
                [],
                replace=True,
            )

            for item in result.get(
                "error_rows",
                [],
            ):
                ImportJobService.add_validation_errors(
                    job,
                    row_number=item.get(
                        "row_number",
                    ),
                    employee_code=item.get(
                        "employee_code",
                        "",
                    ),
                    field_errors=item.get(
                        "errors",
                        {},
                    ),
                    raw_data=item.get(
                        "raw_data",
                        {},
                    ),
                )

            ImportJobService.complete(
                job,
                total_rows=result.get(
                    "total_rows",
                    0,
                ),
                valid_rows=result.get(
                    "valid_rows",
                    0,
                ),
                invalid_rows=result.get(
                    "invalid_rows",
                    0,
                ),
                created_rows=result.get(
                    "created_rows",
                    0,
                ),
                updated_rows=result.get(
                    "updated_rows",
                    0,
                ),
                duplicate_rows=result.get(
                    "duplicate_rows",
                    0,
                ),
                skipped_rows=result.get(
                    "skipped_rows",
                    0,
                ),
                failed_rows=result.get(
                    "failed_rows",
                    0,
                ),
                metadata={
                    "celery_task_id":
                        self.request.id,

                    "source_file_id":
                        source_file.id,
                },
            )

            return {
                "job_public_id":
                    str(job.public_id),

                "status":
                    job.status,
            }

        except Exception as exc:
            ImportJobService.fail(
                job,
                error=exc,
                metadata={
                    "celery_task_id":
                        self.request.id,
                },
            )

            raise

        finally:
            remove_temp_file(
                temporary_path,
            )