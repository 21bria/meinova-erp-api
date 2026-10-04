from __future__ import annotations

import django_filters

from apps.hr.models import Employee


class EmployeeFilterSet(django_filters.FilterSet):
    """
    Filter penempatan organisasi untuk daftar karyawan.

    Datanya ada di `OrganizationAssignment` (relasi `organization`),
    bukan di Employee. Tanpa pemetaan ini, parameter seperti
    `?location=3` diterima tapi diabaikan diam-diam — user mengira sudah
    memfilter padahal hasilnya seluruh data.
    """

    ORGANIZATION_FILTERS = (
        "company",
        "branch",
        "location",
        "division",
        "department",
        "section",
        "position",
        "job_level",
        "job_grade",
        "cost_center",
    )

    class Meta:
        model = Employee
        fields = [
            "gender",
            "religion",
            "nationality",
            "blood_type",
            "marital_status",
            "is_active",
        ]


for _name in EmployeeFilterSet.ORGANIZATION_FILTERS:
    EmployeeFilterSet.base_filters[_name] = django_filters.NumberFilter(
        field_name=f"organization__{_name}",
        label=_name.replace("_", " ").title(),
    )
