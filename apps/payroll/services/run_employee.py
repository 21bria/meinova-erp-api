"""
Service baris pegawai di dalam payroll run.

Baris ini **tidak diisi tangan** — ia lahir dari Generate Employees dan
diisi Calculate. Yang boleh disunting orang cuma dua hal: mengeluarkan
seorang pegawai dari run beserta alasannya, dan catatan.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError

from apps.core.services.master import BaseMasterService
from apps.payroll.models import (
    PayrollRunEmployee,
    PayrollRunEmployeeStatus,
    PayrollRunStatus,
)


EDITABLE_FIELDS = {"is_excluded", "exclusion_reason", "notes"}


class PayrollRunEmployeeService(BaseMasterService):
    model = PayrollRunEmployee

    @classmethod
    def get_queryset(cls):
        return (
            super()
            .get_queryset()
            .select_related(
                "run",
                "run__period",
                "employee",
                "company",
                "department",
                "section",
                "position",
                "payroll_group",
                "salary_grade",
                "salary_level",
                "tax_status",
                "currency",
            )
        )

    @classmethod
    def prepare_create_data(cls, *, data, user=None, **kwargs):
        raise ValidationError(
            {
                "run": (
                    "Baris pegawai dibuat lewat Generate Employees pada "
                    "payroll run, bukan ditambah satu per satu."
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
        if instance.run.status == PayrollRunStatus.FINALIZED:
            raise ValidationError(
                {
                    "run": (
                        "Payroll run ini sudah difinalisasi dan "
                        "terkunci."
                    ),
                },
            )

        payload = {
            key: value
            for key, value in data.items()
            if key in EDITABLE_FIELDS
        }

        if payload.get("is_excluded") and not payload.get(
            "exclusion_reason",
            instance.exclusion_reason,
        ):
            raise ValidationError(
                {
                    "exclusion_reason": (
                        "Sebutkan alasannya. Pegawai yang dikeluarkan "
                        "dari payroll tanpa alasan tidak bisa "
                        "dijelaskan siapa pun bulan depan."
                    ),
                },
            )

        if "is_excluded" in payload:
            payload["status"] = (
                PayrollRunEmployeeStatus.EXCLUDED
                if payload["is_excluded"]
                else PayrollRunEmployeeStatus.PENDING
            )

        return payload

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs):
        raise ValidationError(
            {
                "run": (
                    "Baris pegawai tidak dihapus. Tandai Excluded "
                    "beserta alasannya — jejaknya harus tetap ada di "
                    "dokumen."
                ),
            },
        )
