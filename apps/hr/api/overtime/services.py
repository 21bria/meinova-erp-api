from __future__ import annotations

from typing import Any

from apps.core.services.master import BaseMasterService

from apps.hr.api.mixins import OrganizationDenormalizationMixin
from apps.hr.models import EmployeeOvertime


class EmployeeOvertimeService(
    OrganizationDenormalizationMixin,
    BaseMasterService,
):
    model = EmployeeOvertime

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = cls.apply_organization(data)

        return cls.apply_duration(data)

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = cls.apply_organization(
            data,
            fallback_employee=instance.employee,
        )

        return cls.apply_duration(
            data,
            instance=instance,
        )

    @staticmethod
    def apply_duration(
        data: dict[str, Any],
        *,
        instance: EmployeeOvertime | None = None,
    ) -> dict[str, Any]:
        """
        Durasi dihitung dari jam mulai/selesai kalau dibiarkan kosong.
        Diisi manual tetap dihormati — ada kasus lembur dipotong jam
        istirahat yang tidak bisa disimpulkan dari dua jam itu saja.
        """
        if data.get("duration_minutes") is not None:
            return data

        probe = EmployeeOvertime(
            start_time=data.get(
                "start_time",
                getattr(instance, "start_time", None),
            ),
            end_time=data.get(
                "end_time",
                getattr(instance, "end_time", None),
            ),
        )

        duration = probe.calculate_duration_minutes()

        if duration is not None:
            data["duration_minutes"] = duration

        return data
