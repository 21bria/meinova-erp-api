from __future__ import annotations

from pathlib import Path

from django.db import transaction

from apps.uploads.models import UploadedFile
from apps.uploads.services.metadata_service import (
    build_file_metadata,
)
from apps.uploads.services.thumbnail_service import (
    generate_thumbnail,
)
from apps.uploads.validators import (
    validate_multiple_upload,
    validate_uploaded_file,
)


class UploadService:
    @classmethod
    def create(
        cls,
        *,
        uploaded_file,
        user=None,
        metadata: dict | None = None,
        generate_preview: bool = True,
    ) -> UploadedFile:
        validate_uploaded_file(uploaded_file)

        file_metadata = build_file_metadata(
            uploaded_file,
        )

        upload_metadata = dict(
            metadata or {},
        )

        allowed_categories = {
            value
            for value, _label
            in UploadedFile.Category.choices
        }

        category = upload_metadata.get(
            "category",
            UploadedFile.Category.GENERAL,
        )

        if category not in allowed_categories:
            category = UploadedFile.Category.GENERAL

        is_public = bool(
            upload_metadata.get(
                "is_public",
                False,
            )
        )

        instance = UploadedFile(
            file=uploaded_file,
            metadata=upload_metadata,
            category=category,
            is_public=is_public,
            status=UploadedFile.Status.PROCESSING,
            uploaded_by=user,
            updated_by=user,
            **file_metadata,
        )

        try:
            with transaction.atomic():
                instance.save()

                instance.stored_name = Path(
                    instance.file.name
                ).name

                instance.status = (
                    UploadedFile.Status.READY
                )

                instance.save(
                    update_fields=[
                        "stored_name",
                        "status",
                        "updated_at",
                    ]
                )

        except Exception:
            if (
                instance.file
                and instance.file.name
            ):
                instance.file.storage.delete(
                    instance.file.name
                )

            raise

        if generate_preview:
            generate_thumbnail(instance)

        return instance

    @classmethod
    def create_multiple(
        cls,
        *,
        files,
        user=None,
        metadata: dict | None = None,
        generate_preview: bool = True,
    ) -> list[UploadedFile]:
        validated_files = validate_multiple_upload(files)
        created_instances: list[UploadedFile] = []

        try:
            for uploaded_file in validated_files:
                instance = cls.create(
                    uploaded_file=uploaded_file,
                    user=user,
                    metadata=metadata,
                    generate_preview=generate_preview,
                )

                created_instances.append(instance)

            return created_instances

        except Exception:
            for instance in created_instances:
                cls._rollback_created_instance(instance)

            raise

    @staticmethod
    def _rollback_created_instance(
        instance: UploadedFile,
    ) -> None:
        storage_files = {
            instance.file.name if instance.file else None,
            (
                instance.thumbnail.name
                if instance.thumbnail
                else None
            ),
        }

        instance.delete()

        for filename in storage_files:
            if (
                filename
                and instance.file.storage.exists(filename)
            ):
                instance.file.storage.delete(filename)