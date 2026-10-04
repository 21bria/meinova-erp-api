from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from celery import shared_task
from django.contrib.auth import get_user_model
from django_tenants.utils import schema_context

from apps.framework.imports import ImportPipelineService
from apps.imports.models import ImportJob, ImportProfile
from apps.imports.services import ImportJobService
from apps.uploads.models import UploadedFile


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

    temporary_path = Path(temporary_file.name)

    try:
        with uploaded_file.file.open("rb") as source:
            while True:
                chunk = source.read(1024 * 1024)

                if not chunk:
                    break

                temporary_file.write(chunk)
    except Exception:
        temporary_file.close()
        temporary_path.unlink(missing_ok=True)
        raise
    finally:
        if not temporary_file.closed:
            temporary_file.close()

    return temporary_path


def remove_temp_file(file_path: Path | None) -> None:
    if file_path is None:
        return

    try:
        file_path.unlink(missing_ok=True)
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
def run_import(
    self,
    *,
    schema_name: str,
    job_public_id: str,
    module: str,
    profile_id: int,
    source_file_id: int,
    user_id: int | None = None,
    skip_invalid: bool = True,
    options: dict | None = None,
) -> dict[str, str]:
    """
    Menjalankan satu import job. Semua akses data tenant dibungkus
    schema_context sesuai schema pemanggil.
    """
    temporary_path: Path | None = None

    with schema_context(schema_name):
        job = ImportJob.objects.select_related(
            "source_file",
        ).get(
            public_id=job_public_id,
            is_deleted=False,
        )

        profile = ImportProfile.objects.get(
            pk=profile_id,
        )

        source_file = UploadedFile.objects.get(
            pk=source_file_id,
        )

        user = None

        if user_id:
            user = (
                get_user_model()
                .objects
                .filter(pk=user_id)
                .first()
            )

        try:
            ImportJobService.mark_processing(
                job,
                metadata={
                    "celery_task_id": self.request.id,
                },
            )

            temporary_path = copy_uploaded_file_to_temp(
                source_file,
            )

            result = ImportPipelineService.execute(
                module=module,
                file_path=temporary_path,
                source_type=profile.source_type or "csv",
                parser_options=profile.parser_options,
                mapping=profile.mapping or None,
                defaults=profile.defaults or None,
                value_mapping=profile.value_mapping or None,
                date_formats=profile.datetime_formats or None,
                # Sama dengan jalur preview: opsi profile lebih dulu,
                # opsi unggahan menimpanya. `import_batch_id` ikut
                # supaya baris yang lahir dari satu job bisa ditemukan
                # kembali tanpa menebak lewat timestamp.
                options={
                    **(profile.options or {}),
                    **(options or {}),
                    "import_batch_id": str(job.public_id),
                },
                user=user,
                profile=profile,
                skip_invalid=skip_invalid,
            )

            # Bersihkan error percobaan sebelumnya sebelum menulis ulang.
            ImportJobService.add_errors(
                job,
                [],
                replace=True,
            )

            for item in result.get("error_rows", []):
                ImportJobService.add_validation_errors(
                    job,
                    row_number=item.get("row_number"),
                    employee_code=item.get("identity", ""),
                    field_errors=item.get("errors", {}),
                    raw_data=item.get("raw_data", {}),
                )

            ImportJobService.complete(
                job,
                total_rows=result.get("total_rows", 0),
                valid_rows=result.get("valid_rows", 0),
                invalid_rows=result.get("invalid_rows", 0),
                created_rows=result.get("created_rows", 0),
                updated_rows=result.get("updated_rows", 0),
                duplicate_rows=result.get("duplicate_rows", 0),
                skipped_rows=result.get("skipped_rows", 0),
                failed_rows=result.get("failed_rows", 0),
            )

            return {
                "job_public_id": str(job.public_id),
                "status": job.status,
            }

        except Exception as exc:
            ImportJobService.fail(
                job,
                error=exc,
            )

            raise

        finally:
            remove_temp_file(temporary_path)
