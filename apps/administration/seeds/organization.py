"""
Penulis struktur organisasi — **mesinnya, bukan datanya**.

Modul ini dulu memegang keduanya sekaligus: 800 baris logika tulis
berdampingan dengan 12 perusahaan milik satu klien (`Source: Employee
Database per August 2026.xlsx`). Karena ia duduk di jalur seed static
(`seed_administration --only=organization`), **setiap** tenant baru —
termasuk calon tenant produksi klien lain — ikut mendapat dua belas
perusahaan yang bukan miliknya, lengkap dengan 460 department dan
1.049 position.

Sekarang datanya di luar:

- `seeds/client/…`  struktur milik klien tertentu, dijalankan sadar
- `seeds/demo/…`    tenant peragaan (trial & tutorial)

Menambah tenant baru berarti menulis satu `OrganizationDataset` baru,
bukan menyunting mesin ini.
"""

import re
from dataclasses import dataclass, field
from typing import Any, TypeVar

from django.db import models, transaction

from apps.administration.models.organization import (
    Branch,
    Company,
    CostCenter,
    Department,
    Division,
    Facility,
    Position,
    Section,
    Location,
)
from apps.administration.models.references.geography import (
    City,
    Country,
    Province,
)
from apps.administration.models.references.hr import (
    JobCategory,
    JobLevel,
)
from apps.administration.models.references.organization import (
    CompanyType,
    FacilityType,
    LocationType,
)

from .base import seed_reference
from .reference.organization import (
    ORGANIZATION_REFERENCE_DATA,
    retire_obsolete_location_types,
)


ModelT = TypeVar("ModelT", bound=models.Model)


# ============================================================
# DATASET
# ============================================================

@dataclass(frozen=True)
class OrganizationDataset:
    """
    Satu struktur organisasi utuh, siap ditulis.

    Urutan fieldnya = urutan tulisnya, dan itu bukan kebetulan:
    tiap tingkat menunjuk induknya lewat kode, jadi Section tidak bisa
    ditulis sebelum Department ada. `facilities` boleh kosong — lokasi
    yang tidak punya bangunan terdaftar adalah keadaan yang sah, dan
    mengarang "Warehouse Default" untuk tiap company membuat master ini
    terlihat terisi padahal tidak menunjuk bangunan mana pun.
    """

    name: str
    companies: list[dict[str, Any]]
    branches: list[dict[str, Any]]
    locations: list[dict[str, Any]]
    divisions: list[tuple]
    departments: list[tuple]
    sections: list[tuple]
    positions: list[dict[str, Any]]
    cost_centers: list[tuple]
    facilities: list[dict[str, Any]] = field(default_factory=list)


# ============================================================
# HELPERS
# ============================================================

def make_code(value: str) -> str:
    value = value.upper().strip()

    value = value.replace("&", " AND ")
    value = value.replace("/", " ")
    value = value.replace(".", "")
    value = value.replace("(", " ")
    value = value.replace(")", " ")
    value = value.replace("-", " ")

    value = re.sub(
        r"[^A-Z0-9]+",
        "_",
        value,
    )
    value = re.sub(
        r"_+",
        "_",
        value,
    )

    return value.strip("_")


def require_reference(
    values: dict[str, ModelT],
    code: str,
    reference_name: str,
) -> ModelT:
    value = values.get(code)

    if value is None:
        raise RuntimeError(
            f"{reference_name} with code '{code}' "
            "is not available. "
            "Run the required reference seed first."
        )

    return value


def require_organization(
    values: dict[tuple[str, str], ModelT],
    company_code: str,
    code: str,
    reference_name: str,
) -> ModelT:
    value = values.get(
        (
            company_code,
            code,
        )
    )

    if value is None:
        raise RuntimeError(
            f"{reference_name} '{code}' "
            f"was not found for company "
            f"'{company_code}'."
        )

    return value



def seed_organization_references() -> None:
    for (
        model,
        rows,
    ) in ORGANIZATION_REFERENCE_DATA.items():
        seed_reference(
            model,
            [
                {
                    "code": code,
                    "name": name,
                    "sort_order": sort_order,
                    "is_deleted": False,
                    "is_active": True,
                }
                for code, name, sort_order in rows
            ],
        )

    retire_obsolete_location_types()


# ============================================================
# ORGANIZATION SEED
# ============================================================

@transaction.atomic
def seed_organization(dataset: OrganizationDataset) -> None:
    """Tulis satu dataset organisasi ke tenant yang sedang aktif."""
    seed_organization_references()

    # --------------------------------------------------------
    # Geography References
    # --------------------------------------------------------

    country_codes = {
        row["country"]
        for row in (
            dataset.companies
            + dataset.branches
            + dataset.locations
        )
        if row.get("country")
    }

    province_codes = {
        row["province"]
        for row in (
            dataset.companies
            + dataset.branches
            + dataset.locations
        )
        if row.get("province")
    }

    city_codes = {
        row["city"]
        for row in (
            dataset.companies
            + dataset.branches
            + dataset.locations
        )
        if row.get("city")
    }

    countries = {
        item.code: item
        for item in Country.objects.filter(
            code__in=country_codes
        )
    }

    provinces = {
        item.code: item
        for item in Province.objects.filter(
            code__in=province_codes
        )
    }

    cities = {
        item.code: item
        for item in City.objects.filter(
            code__in=city_codes
        )
    }

    company_types = {
        item.code: item
        for item in CompanyType.objects.all()
    }

    location_types = {
        item.code: item
        for item in LocationType.objects.all()
    }

    job_categories = {
        item.code: item
        for item in JobCategory.objects.all()
    }

    job_levels = {
        item.code: item
        for item in JobLevel.objects.all()
    }

    # --------------------------------------------------------
    # Company
    # --------------------------------------------------------

    companies: dict[str, Company] = {}

    # Pass 1:
    # Create/update Company without parent.
    for row in dataset.companies:
        company, _ = Company.objects.update_or_create(
            code=row["code"],
            defaults={
                "parent": None,
                "company_type": require_reference(
                    company_types,
                    row["company_type"],
                    "CompanyType",
                ),
                "name": row["name"],
                "legal_name": row[
                    "legal_name"
                ],
                "tax_number": row.get(
                    "tax_number",
                    "",
                ),
                "country": (
                    require_reference(
                        countries,
                        row["country"],
                        "Country",
                    )
                    if row.get("country")
                    else None
                ),
                "province": provinces.get(
                    row.get("province")
                ),
                "city": cities.get(
                    row.get("city")
                ),
                "address": row.get(
                    "address",
                    "",
                ),
                "postal_code": row.get(
                    "postal_code",
                    "",
                ),
                "phone": row.get(
                    "phone",
                    "",
                ),
                "email": row.get(
                    "email",
                    "",
                ),
                "website": row.get(
                    "website",
                    "",
                ),
                "is_active": True,
            },
        )

        companies[
            row["code"]
        ] = company

    # Pass 2:
    # Set Company parent.
    for row in dataset.companies:
        company = companies[
            row["code"]
        ]

        parent_code = row.get(
            "parent"
        )

        parent = (
            companies.get(
                parent_code
            )
            if parent_code
            else None
        )

        parent_id = getattr(
            parent,
            "id",
            None,
        )

        if company.parent_id != parent_id:
            company.parent = parent
            company.save(
                update_fields=[
                    "parent",
                ]
            )

    # --------------------------------------------------------
    # Branch
    # --------------------------------------------------------

    branches: dict[
        tuple[str, str],
        Branch,
    ] = {}

    for row in dataset.branches:
        company_code = row[
            "company"
        ]

        company = require_reference(
            companies,
            company_code,
            "Company",
        )

        branch, _ = Branch.objects.update_or_create(
            company=company,
            code=row["code"],
            defaults={
                "name": row["name"],
                "country": (
                    require_reference(
                        countries,
                        row["country"],
                        "Country",
                    )
                    if row.get("country")
                    else None
                ),
                "province": provinces.get(
                    row.get("province")
                ),
                "city": cities.get(
                    row.get("city")
                ),
                "address": row.get(
                    "address",
                    "",
                ),
                "postal_code": row.get(
                    "postal_code",
                    "",
                ),
                "phone": row.get(
                    "phone",
                    "",
                ),
                "email": row.get(
                    "email",
                    "",
                ),
                "website": row.get(
                    "website",
                    "",
                ),
                "is_active": True,
            },
        )

        branches[
            (
                company_code,
                row["code"],
            )
        ] = branch

    # --------------------------------------------------------
    # Location
    # --------------------------------------------------------

    locations: dict[
        tuple[str, str],
        Location,
    ] = {}

    for row in dataset.locations:
        company_code = row[
            "company"
        ]

        company = require_reference(
            companies,
            company_code,
            "Company",
        )

        branch = require_organization(
            branches,
            company_code,
            row["branch"],
            "Branch",
        )

        location, _ = Location.objects.update_or_create(
            company=company,
            code=row["code"],
            defaults={
                "branch": branch,
                "name": row["name"],
                "location_type": require_reference(
                    location_types,
                    row["location_type"],
                    "LocationType",
                ),
                "country": (
                    require_reference(
                        countries,
                        row["country"],
                        "Country",
                    )
                    if row.get("country")
                    else None
                ),
                "province": provinces.get(
                    row.get("province")
                ),
                "city": cities.get(
                    row.get("city")
                ),
                "address": row.get(
                    "address",
                    "",
                ),
                "postal_code": row.get(
                    "postal_code",
                    "",
                ),
                "is_active": True,
            },
        )

        locations[
            (
                company_code,
                row["code"],
            )
        ] = location

    # --------------------------------------------------------
    # Facility
    # --------------------------------------------------------

    facility_types = {
        item.code: item
        for item in FacilityType.objects.all()
    }

    for row in dataset.facilities:
        company_code = row["company"]

        company = companies.get(company_code)

        if company is None:
            continue

        # Dicari juga di basis data, bukan cuma di lokasi yang barusan
        # dibuat seed ini: `GEBE` dan `JAKARTA HO` dibuat seed data uji,
        # sementara seed ini hanya membuat lokasi DEFAULT per company.
        # Tanpa jalur kedua ini seluruh daftar fasilitas dilewati tanpa
        # suara, dan tabelnya kosong seolah datanya memang belum ada.
        location = locations.get(
            (company_code, row["location"]),
        )

        if location is None:
            location = Location.objects.filter(
                company=company,
                code=row["location"],
                is_deleted=False,
            ).first()

        # Lokasinya memang belum ada di tenant ini — tenant lain tidak
        # punya Gebe, dan itu keadaan yang sah.
        if location is None:
            continue

        Facility.objects.update_or_create(
            company=company,
            code=row["code"],
            defaults={
                "branch": location.branch,
                "location": location,
                "facility_type": require_reference(
                    facility_types,
                    row["facility_type"],
                    "FacilityType",
                ),
                "name": row["name"],
                "description": row.get("description", ""),
                "is_active": True,
                "is_deleted": False,
            },
        )

    # --------------------------------------------------------
    # Division
    # --------------------------------------------------------

    divisions: dict[
        tuple[str, str],
        Division,
    ] = {}

    for (
        company_code,
        branch_code,
        location_code,
        code,
        name,
    ) in dataset.divisions:
        company = require_reference(
            companies,
            company_code,
            "Company",
        )

        branch = require_organization(
            branches,
            company_code,
            branch_code,
            "Branch",
        )

        location = require_organization(
            locations,
            company_code,
            location_code,
            "Location",
        )

        division, _ = Division.objects.update_or_create(
            company=company,
            code=code,
            defaults={
                "branch": branch,
                "location": location,
                "name": name,
                "is_active": True,
            },
        )

        divisions[
            (
                company_code,
                code,
            )
        ] = division

    # --------------------------------------------------------
    # Department
    # --------------------------------------------------------

    departments: dict[
        tuple[str, str],
        Department,
    ] = {}

    for (
        company_code,
        branch_code,
        location_code,
        division_code,
        code,
        name,
    ) in dataset.departments:
        company = require_reference(
            companies,
            company_code,
            "Company",
        )

        branch = require_organization(
            branches,
            company_code,
            branch_code,
            "Branch",
        )

        location = require_organization(
            locations,
            company_code,
            location_code,
            "Location",
        )

        division = require_organization(
            divisions,
            company_code,
            division_code,
            "Division",
        )

        department, _ = (
            Department.objects.update_or_create(
                company=company,
                code=code,
                defaults={
                    "branch": branch,
                    "location": location,
                    "division": division,
                    "name": name,
                    "is_active": True,
                },
            )
        )

        departments[
            (
                company_code,
                code,
            )
        ] = department

    # --------------------------------------------------------
    # Section
    # --------------------------------------------------------

    sections: dict[
        tuple[str, str],
        Section,
    ] = {}

    for (
        company_code,
        branch_code,
        location_code,
        division_code,
        department_code,
        code,
        name,
    ) in dataset.sections:
        company = require_reference(
            companies,
            company_code,
            "Company",
        )

        branch = require_organization(
            branches,
            company_code,
            branch_code,
            "Branch",
        )

        location = require_organization(
            locations,
            company_code,
            location_code,
            "Location",
        )

        division = require_organization(
            divisions,
            company_code,
            division_code,
            "Division",
        )

        department = require_organization(
            departments,
            company_code,
            department_code,
            "Department",
        )

        section, _ = Section.objects.update_or_create(
            company=company,
            code=code,
            defaults={
                "branch": branch,
                "location": location,
                "division": division,
                "department": department,
                "name": name,
                "is_active": True,
            },
        )

        sections[
            (
                company_code,
                code,
            )
        ] = section

    # --------------------------------------------------------
    # Position
    # --------------------------------------------------------

    positions: dict[
        tuple[str, str],
        Position,
    ] = {}

    # Pass 1:
    # Create Position without reports_to.
    for row in dataset.positions:
        company_code = row[
            "company"
        ]

        company = require_reference(
            companies,
            company_code,
            "Company",
        )

        branch = require_organization(
            branches,
            company_code,
            row["branch"],
            "Branch",
        )

        location = require_organization(
            locations,
            company_code,
            row["location"],
            "Location",
        )

        division = require_organization(
            divisions,
            company_code,
            row["division"],
            "Division",
        )

        department = (
            require_organization(
                departments,
                company_code,
                row["department"],
                "Department",
            )
            if row.get("department")
            else None
        )

        section = (
            require_organization(
                sections,
                company_code,
                row["section"],
                "Section",
            )
            if row.get("section")
            else None
        )

        position, _ = Position.objects.update_or_create(
            company=company,
            code=row["code"],
            defaults={
                "branch": branch,
                "location": location,
                "division": division,
                "department": department,
                "section": section,
                "job_category": require_reference(
                    job_categories,
                    row["job_category"],
                    "JobCategory",
                ),
                "job_level": require_reference(
                    job_levels,
                    row["job_level"],
                    "JobLevel",
                ),
                "reports_to": None,
                "name": row["name"],
                "headcount": row.get(
                    "headcount",
                    1,
                ),
                "description": row.get(
                    "description",
                    "",
                ),
                "is_manager": row.get(
                    "is_manager",
                    False,
                ),
                "is_active": True,
            },
        )

        positions[
            (
                company_code,
                row["code"],
            )
        ] = position

    # Pass 2:
    # Set reports_to.
    for row in dataset.positions:
        manager_code = row.get(
            "reports_to"
        )

        if not manager_code:
            continue

        company_code = row[
            "company"
        ]

        position = require_organization(
            positions,
            company_code,
            row["code"],
            "Position",
        )

        manager = require_organization(
            positions,
            company_code,
            manager_code,
            "Position Manager",
        )

        if (
            position.reports_to_id
            != manager.id
        ):
            position.reports_to = manager
            position.save(
                update_fields=[
                    "reports_to",
                ]
            )

    # --------------------------------------------------------
    # Cost Center
    # --------------------------------------------------------

    for (
        company_code,
        branch_code,
        location_code,
        division_code,
        department_code,
        code,
        name,
    ) in dataset.cost_centers:
        company = require_reference(
            companies,
            company_code,
            "Company",
        )

        branch = require_organization(
            branches,
            company_code,
            branch_code,
            "Branch",
        )

        location = require_organization(
            locations,
            company_code,
            location_code,
            "Location",
        )

        division = require_organization(
            divisions,
            company_code,
            division_code,
            "Division",
        )

        department = (
            require_organization(
                departments,
                company_code,
                department_code,
                "Department",
            )
            if department_code
            else None
        )

        CostCenter.objects.update_or_create(
            company=company,
            code=code,
            defaults={
                "branch": branch,
                "location": location,
                "division": division,
                "department": department,
                "name": name,
                "is_active": True,
            },
        )