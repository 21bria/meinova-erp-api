"""
Service periode payroll.

Status periode **dirangkum dari run-nya**, tidak diketik orang. Dua
mesin status yang sama-sama digerakkan tangan adalah cara membuat
periode berkata APPROVED sementara run-nya sedang dihitung ulang.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.services.master import BaseMasterService
from apps.payroll.models import (
    PayrollPeriod,
    PayrollPeriodStatus,
    PayrollRunStatus,
)


# Urutan kematangan: keadaan run yang paling "maju" menentukan status
# periode. Ditulis sebagai peringkat, bukan rantai `if`, supaya
# menambah satu status run tidak berarti membaca ulang seluruh cabang.
RUN_TO_PERIOD = {
    PayrollRunStatus.DRAFT: PayrollPeriodStatus.PROCESSING,
    PayrollRunStatus.PROCESSING: PayrollPeriodStatus.PROCESSING,
    PayrollRunStatus.REJECTED: PayrollPeriodStatus.PROCESSING,
    PayrollRunStatus.CANCELLED: None,
    PayrollRunStatus.REVIEW: PayrollPeriodStatus.REVIEW,
    PayrollRunStatus.SUBMITTED: PayrollPeriodStatus.REVIEW,
    PayrollRunStatus.APPROVED: PayrollPeriodStatus.APPROVED,
    PayrollRunStatus.FINALIZED: PayrollPeriodStatus.FINALIZED,
}

PERIOD_RANK = {
    PayrollPeriodStatus.DRAFT: 0,
    PayrollPeriodStatus.PROCESSING: 1,
    PayrollPeriodStatus.REVIEW: 2,
    PayrollPeriodStatus.APPROVED: 3,
    PayrollPeriodStatus.FINALIZED: 4,
}


class PayrollPeriodService(BaseMasterService):
    model = PayrollPeriod

    @classmethod
    def get_queryset(cls):
        return (
            super()
            .get_queryset()
            .select_related("company", "payroll_group")
        )

    @classmethod
    def assert_editable(cls, instance: PayrollPeriod) -> None:
        if instance.is_locked:
            raise ValidationError(
                {
                    "status": (
                        "Periode yang sudah Finalized tidak bisa "
                        "diubah. Koreksi lewat payroll run bertipe "
                        "Correction."
                    ),
                },
            )

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_editable(instance)

        return super().prepare_update_data(
            instance=instance,
            data=data,
            user=user,
            **kwargs,
        )

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs):
        cls.assert_editable(instance)

        if instance.runs.filter(is_deleted=False).exists():
            raise ValidationError(
                {
                    "period": (
                        "Periode ini sudah punya payroll run. Hapus "
                        "run-nya dulu."
                    ),
                },
            )

        return super().before_soft_delete(instance=instance, user=user, **kwargs)

    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def sync_status(cls, *, period: PayrollPeriod, user=None) -> PayrollPeriod:
        """
        Menyetel status periode dari run yang paling maju.

        Run yang dibatalkan tidak dihitung: periode yang seluruh run-nya
        dibatalkan kembali ke DRAFT, dan itu memang keadaannya —
        belum ada payroll yang berjalan di sana.
        """
        statuses = list(
            period.runs
            .filter(is_deleted=False)
            .values_list("status", flat=True)
        )

        target = PayrollPeriodStatus.DRAFT
        best = 0

        for status in statuses:
            mapped = RUN_TO_PERIOD.get(status)

            if mapped is None:
                continue

            rank = PERIOD_RANK.get(mapped, 0)

            if rank > best:
                best = rank
                target = mapped

        # FINALIZED hanya kalau **seluruh** run aktifnya sudah final.
        # Satu run koreksi yang masih berjalan berarti periodenya belum
        # boleh dikunci, walau run reguler-nya sudah terbit.
        if target == PayrollPeriodStatus.FINALIZED:
            unfinished = [
                status
                for status in statuses
                if status
                not in (
                    PayrollRunStatus.FINALIZED,
                    PayrollRunStatus.CANCELLED,
                )
            ]

            if unfinished:
                target = PayrollPeriodStatus.REVIEW

        if period.status == target:
            return period

        period.status = target

        fields = ["status", "updated_at"]

        if target == PayrollPeriodStatus.FINALIZED:
            period.locked_at = timezone.now()
            period.locked_by = user
            fields += ["locked_at", "locked_by"]
        elif period.locked_at is not None:
            period.locked_at = None
            period.locked_by = None
            fields += ["locked_at", "locked_by"]

        if user is not None:
            period.updated_by = user
            fields.append("updated_by")

        period.save(update_fields=fields)

        return period
