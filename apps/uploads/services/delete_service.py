from __future__ import annotations

from django.conf import settings
from django.db import transaction

from apps.uploads.models import UploadedFile


class UploadDeleteService:
    @classmethod
    def soft_delete(
        cls,
        *,
        instance: UploadedFile,
        user=None,
    ) -> UploadedFile:
        instance.soft_delete(user=user)

        return instance

    @classmethod
    def restore(
        cls,
        *,
        instance: UploadedFile,
        user=None,
    ) -> UploadedFile:
        instance.restore(user=user)

        return instance

    @classmethod
    def purge(
        cls,
        *,
        instance: UploadedFile,
    ) -> None:
        storage = (
            instance.file.storage
            if instance.file
            else None
        )

        file_names = {
            instance.file.name if instance.file else None,
            (
                instance.thumbnail.name
                if instance.thumbnail
                else None
            ),
        }

        with transaction.atomic():
            instance.delete()

            def cleanup_storage():
                if not storage:
                    return

                for filename in file_names:
                    if filename and storage.exists(filename):
                        storage.delete(filename)

            transaction.on_commit(cleanup_storage)