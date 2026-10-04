from __future__ import annotations

from typing import Any

from apps.hr.models import OrganizationAssignment


class OrganizationDenormalizationMixin:
    """
    Menyalin company/branch/location dari OrganizationAssignment aktif
    milik pegawai ke record transaksi.

    Polanya sama dengan `EmployeeAttendanceService`: rekap per unit
    kerja jadi satu join, bukan dua. Nilai yang sudah diisi eksplisit
    oleh pemanggil tidak ditimpa, supaya koreksi manual tetap mungkin.
    """

    @staticmethod
    def apply_organization(
        data: dict[str, Any],
        *,
        fallback_employee=None,
    ) -> dict[str, Any]:
        employee = data.get("employee", fallback_employee)

        if employee is None:
            return data

        already_filled = all(
            data.get(field) is not None
            for field in ("company", "branch", "location")
        )

        if already_filled:
            return data

        assignment = (
            OrganizationAssignment.objects
            .filter(
                employee=employee,
                is_active=True,
                is_deleted=False,
            )
            .select_related(
                "company",
                "branch",
                "location",
            )
            .order_by(
                "-organization_effective_date",
                "-id",
            )
            .first()
        )

        if assignment is None:
            return data

        data.setdefault("company", assignment.company)
        data.setdefault("branch", assignment.branch)
        data.setdefault("location", assignment.location)

        return data
