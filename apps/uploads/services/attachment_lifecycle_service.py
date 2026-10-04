from __future__ import annotations

from django.db import models, transaction
from django.utils import timezone

from apps.uploads.models import UploadedFile
from apps.uploads.services.delete_service import (
    UploadDeleteService,
)


class AttachmentLifecycleService:
    attachment_fields: tuple[str, ...] = ()

    @classmethod
    def get_attachments(
        cls,
        instance: models.Model,
    ) -> list[UploadedFile]:
        attachments: list[UploadedFile] = []

        for field_name in cls.attachment_fields:
            attachment = getattr(
                instance,
                field_name,
                None,
            )

            if isinstance(
                attachment,
                UploadedFile,
            ):
                attachments.append(
                    attachment,
                )

        return attachments

    @staticmethod
    def soft_delete_resource(
        *,
        instance: models.Model,
        user=None,
    ) -> None:
        if hasattr(instance, "soft_delete"):
            instance.soft_delete(
                user=user,
            )
            return

        update_fields: list[str] = []

        if hasattr(instance, "is_deleted"):
            instance.is_deleted = True
            update_fields.append(
                "is_deleted",
            )

        if hasattr(instance, "deleted_at"):
            instance.deleted_at = timezone.now()
            update_fields.append(
                "deleted_at",
            )

        if hasattr(instance, "deleted_by"):
            instance.deleted_by = user
            update_fields.append(
                "deleted_by",
            )

        if hasattr(instance, "updated_by"):
            instance.updated_by = user
            update_fields.append(
                "updated_by",
            )

        if hasattr(instance, "updated_at"):
            update_fields.append(
                "updated_at",
            )

        if update_fields:
            instance.save(
                update_fields=list(
                    dict.fromkeys(
                        update_fields,
                    )
                )
            )
            return

        instance.delete()

    @staticmethod
    def restore_resource(
        *,
        instance: models.Model,
        user=None,
    ) -> None:
        if hasattr(instance, "restore"):
            instance.restore(
                user=user,
            )
            return

        update_fields: list[str] = []

        if hasattr(instance, "is_deleted"):
            instance.is_deleted = False
            update_fields.append(
                "is_deleted",
            )

        if hasattr(instance, "deleted_at"):
            instance.deleted_at = None
            update_fields.append(
                "deleted_at",
            )

        if hasattr(instance, "deleted_by"):
            instance.deleted_by = None
            update_fields.append(
                "deleted_by",
            )

        if hasattr(instance, "updated_by"):
            instance.updated_by = user
            update_fields.append(
                "updated_by",
            )

        if hasattr(instance, "updated_at"):
            update_fields.append(
                "updated_at",
            )

        if update_fields:
            instance.save(
                update_fields=list(
                    dict.fromkeys(
                        update_fields,
                    )
                )
            )

    @classmethod
    def soft_delete(
        cls,
        *,
        instance: models.Model,
        user=None,
    ):
        attachments = cls.get_attachments(
            instance,
        )

        with transaction.atomic():
            cls.soft_delete_resource(
                instance=instance,
                user=user,
            )

            for attachment in attachments:
                if not attachment.is_deleted:
                    UploadDeleteService.soft_delete(
                        instance=attachment,
                        user=user,
                    )

        return instance

    @classmethod
    def restore(
        cls,
        *,
        instance: models.Model,
        user=None,
    ):
        attachments = cls.get_attachments(
            instance,
        )

        with transaction.atomic():
            cls.restore_resource(
                instance=instance,
                user=user,
            )

            for attachment in attachments:
                if attachment.is_deleted:
                    UploadDeleteService.restore(
                        instance=attachment,
                        user=user,
                    )

        return instance

    @classmethod
    def purge(
        cls,
        *,
        instance: models.Model,
    ) -> None:
        attachments = cls.get_attachments(
            instance,
        )

        with transaction.atomic():
            instance.delete()

            for attachment in attachments:
                UploadDeleteService.purge(
                    instance=attachment,
                )