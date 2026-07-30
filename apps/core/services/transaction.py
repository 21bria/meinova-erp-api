from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.services.base import BaseService


class BaseTransactionService(BaseService):
    """
    Base service untuk transaksi yang mempunyai lifecycle:

    DRAFT -> SUBMITTED -> APPROVED
          -> REJECTED
          -> CANCELLED
    """

    STATUS_DRAFT = "DRAFT"
    STATUS_SUBMITTED = "SUBMITTED"
    STATUS_APPROVED = "APPROVED"
    STATUS_REJECTED = "REJECTED"
    STATUS_CANCELLED = "CANCELLED"

    @classmethod
    def get_status(cls, instance) -> str | None:
        return getattr(instance, "status", None)

    @classmethod
    def ensure_status(
        cls,
        *,
        instance,
        allowed_statuses: set[str] | list[str] | tuple[str, ...],
        action: str,
    ) -> None:
        current_status = cls.get_status(instance)

        if current_status not in allowed_statuses:
            raise ValidationError(
                {
                    "status": (
                        f"Transaksi dengan status "
                        f"'{current_status}' tidak dapat {action}."
                    )
                }
            )

    @classmethod
    def apply_user_field(
        cls,
        *,
        instance,
        field_name: str,
        user,
    ) -> None:
        if user is None:
            return

        field_names = {
            field.name
            for field in instance._meta.get_fields()
        }

        if field_name in field_names:
            setattr(instance, field_name, user)

    @classmethod
    def apply_datetime_field(
        cls,
        *,
        instance,
        field_name: str,
    ) -> None:
        field_names = {
            field.name
            for field in instance._meta.get_fields()
        }

        if field_name in field_names:
            setattr(instance, field_name, timezone.now())

    @classmethod
    def before_submit(
        cls,
        *,
        instance,
        user=None,
        **kwargs,
    ) -> None:
        pass

    @classmethod
    def after_submit(
        cls,
        *,
        instance,
        user=None,
        **kwargs,
    ) -> None:
        pass

    @classmethod
    @transaction.atomic
    def submit(
        cls,
        *,
        instance,
        user=None,
        **kwargs,
    ):
        cls.ensure_status(
            instance=instance,
            allowed_statuses={
                cls.STATUS_DRAFT,
                cls.STATUS_REJECTED,
            },
            action="diajukan",
        )

        cls.before_submit(
            instance=instance,
            user=user,
            **kwargs,
        )

        instance.status = cls.STATUS_SUBMITTED

        cls.apply_user_field(
            instance=instance,
            field_name="submitted_by",
            user=user,
        )
        cls.apply_datetime_field(
            instance=instance,
            field_name="submitted_at",
        )

        instance.full_clean()
        instance.save()

        cls.after_submit(
            instance=instance,
            user=user,
            **kwargs,
        )

        return instance

    @classmethod
    def before_approve(
        cls,
        *,
        instance,
        user=None,
        **kwargs,
    ) -> None:
        pass

    @classmethod
    def after_approve(
        cls,
        *,
        instance,
        user=None,
        **kwargs,
    ) -> None:
        pass

    @classmethod
    @transaction.atomic
    def approve(
        cls,
        *,
        instance,
        user=None,
        **kwargs,
    ):
        cls.ensure_status(
            instance=instance,
            allowed_statuses={
                cls.STATUS_SUBMITTED,
            },
            action="disetujui",
        )

        cls.before_approve(
            instance=instance,
            user=user,
            **kwargs,
        )

        instance.status = cls.STATUS_APPROVED

        cls.apply_user_field(
            instance=instance,
            field_name="approved_by",
            user=user,
        )
        cls.apply_datetime_field(
            instance=instance,
            field_name="approved_at",
        )

        instance.full_clean()
        instance.save()

        cls.after_approve(
            instance=instance,
            user=user,
            **kwargs,
        )

        return instance

    @classmethod
    def before_reject(
        cls,
        *,
        instance,
        reason: str,
        user=None,
        **kwargs,
    ) -> None:
        pass

    @classmethod
    def after_reject(
        cls,
        *,
        instance,
        reason: str,
        user=None,
        **kwargs,
    ) -> None:
        pass

    @classmethod
    @transaction.atomic
    def reject(
        cls,
        *,
        instance,
        reason: str,
        user=None,
        **kwargs,
    ):
        cls.ensure_status(
            instance=instance,
            allowed_statuses={
                cls.STATUS_SUBMITTED,
            },
            action="ditolak",
        )

        reason = reason.strip()

        if not reason:
            raise ValidationError(
                {
                    "reason": "Alasan penolakan wajib diisi."
                }
            )

        cls.before_reject(
            instance=instance,
            reason=reason,
            user=user,
            **kwargs,
        )

        instance.status = cls.STATUS_REJECTED

        field_names = {
            field.name
            for field in instance._meta.get_fields()
        }

        if "rejection_reason" in field_names:
            instance.rejection_reason = reason

        cls.apply_user_field(
            instance=instance,
            field_name="rejected_by",
            user=user,
        )
        cls.apply_datetime_field(
            instance=instance,
            field_name="rejected_at",
        )

        instance.full_clean()
        instance.save()

        cls.after_reject(
            instance=instance,
            reason=reason,
            user=user,
            **kwargs,
        )

        return instance

    @classmethod
    def before_cancel(
        cls,
        *,
        instance,
        reason: str | None = None,
        user=None,
        **kwargs,
    ) -> None:
        pass

    @classmethod
    def after_cancel(
        cls,
        *,
        instance,
        reason: str | None = None,
        user=None,
        **kwargs,
    ) -> None:
        pass

    @classmethod
    @transaction.atomic
    def cancel(
        cls,
        *,
        instance,
        reason: str | None = None,
        user=None,
        **kwargs,
    ):
        cls.ensure_status(
            instance=instance,
            allowed_statuses={
                cls.STATUS_DRAFT,
                cls.STATUS_SUBMITTED,
                cls.STATUS_APPROVED,
            },
            action="dibatalkan",
        )

        reason = reason.strip() if reason else None

        cls.before_cancel(
            instance=instance,
            reason=reason,
            user=user,
            **kwargs,
        )

        instance.status = cls.STATUS_CANCELLED

        field_names = {
            field.name
            for field in instance._meta.get_fields()
        }

        if reason and "cancellation_reason" in field_names:
            instance.cancellation_reason = reason

        cls.apply_user_field(
            instance=instance,
            field_name="cancelled_by",
            user=user,
        )
        cls.apply_datetime_field(
            instance=instance,
            field_name="cancelled_at",
        )

        instance.full_clean()
        instance.save()

        cls.after_cancel(
            instance=instance,
            reason=reason,
            user=user,
            **kwargs,
        )

        return instance