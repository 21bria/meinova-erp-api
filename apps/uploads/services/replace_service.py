from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.uploads.models import UploadedFile
from apps.uploads.services.metadata_service import (
    build_file_metadata,
)
from apps.uploads.services.thumbnail_service import (
    generate_thumbnail,
)
from apps.uploads.validators import validate_uploaded_file


class ReplaceService:
    @classmethod
    def replace(
        cls,
        *,
        instance: UploadedFile,
        uploaded_file,
        user=None,
        generate_preview: bool = True,
    ) -> UploadedFile:
        validate_uploaded_file(uploaded_file)

        new_metadata = build_file_metadata(uploaded_file)

        old_file_name = (
            instance.file.name
            if instance.file
            else None
        )

        old_thumbnail_name = (
            instance.thumbnail.name
            if instance.thumbnail
            else None
        )

        old_storage = (
            instance.file.storage
            if instance.file
            else None
        )

        with transaction.atomic():
            instance.file = uploaded_file
            instance.thumbnail = None
            instance.stored_name = ""
            instance.status = UploadedFile.Status.PROCESSING
            instance.updated_by = user
            instance.replaced_at = timezone.now()
            instance.version += 1

            for field_name, value in new_metadata.items():
                setattr(instance, field_name, value)

            instance.page_count = None
            instance.save()

            instance.stored_name = Path(
                instance.file.name
            ).name

            instance.status = UploadedFile.Status.READY

            instance.save(
                update_fields=[
                    "stored_name",
                    "status",
                    "updated_at",
                ]
            )

            new_file_name = instance.file.name

            def cleanup_old_files():
                if not getattr(
                    settings,
                    "UPLOAD_DELETE_OLD_FILE_ON_REPLACE",
                    True,
                ):
                    return

                for filename in {
                    old_file_name,
                    old_thumbnail_name,
                }:
                    if (
                        filename
                        and filename != new_file_name
                        and old_storage
                        and old_storage.exists(filename)
                    ):
                        old_storage.delete(filename)

            transaction.on_commit(cleanup_old_files)

        if generate_preview:
            generate_thumbnail(instance)

        return instance