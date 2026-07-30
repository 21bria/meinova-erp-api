from typing import TypeVar

from django.db import models

from apps.administration.models.organization import (
    Branch,
    Company,
    CostCenter,
    Department,
    Division,
    Position,
    Section,
    Site,
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
    SiteType,
)

from .base import seed_reference


ModelT = TypeVar("ModelT", bound=models.Model)


ORGANIZATION_REFERENCE_DATA = {
    CompanyType: [
        ("HO", "Head Office"),
        ("SITE", "Site"),
        ("SUB", "Subsidiary"),
    ],
    SiteType: [
        ("MINE", "Mining Site"),
        ("PORT", "Port"),
        ("OFFICE", "Office"),
    ],
}


COMPANIES = [
    {
        "code": "MNV",
        "name": "Meinova",
        "legal_name": "PT Meinova Id",
        "company_type": "HO",
        "parent": None,
        "tax_number": "",
        "country": "ID",
        "province": "DKI",
        "city": "JKT",
        "address": "Jakarta Selatan, Indonesia",
        "postal_code": "12950",
        "phone": "+62 21 5551000",
        "email": "info@meinova.com",
        "website": "https://meinova.com",
    },
    {
        "code": "SUN",
        "name": "Sigma Nusantara",
        "legal_name": "PT Sigma Utama Nusantara",
        "company_type": "SUB",
        "parent": "MNV",
        "tax_number": "",
        "country": "ID",
        "province": "DKI",
        "city": "JKT",
        "address": "Jakarta Selatan, Indonesia",
        "postal_code": "12950",
        "phone": "+62 21 5551001",
        "email": "info@sun.co.id",
        "website": "",
    },
    {
        "code": "KAWI",
        "name": "Karya Wijaya",
        "legal_name": "PT Karya Wijaya",
        "company_type": "SUB",
        "parent": "MNV",
        "tax_number": "",
        "country": "ID",
        "province": "DKI",
        "city": "JKT",
        "address": "Jakarta Selatan, Indonesia",
        "postal_code": "12950",
        "phone": "+62 21 5551002",
        "email": "info@kawi.co.id",
        "website": "",
    },
]


BRANCHES = [
    {
        "company": "MNV",
        "code": "JKT",
        "name": "Jakarta Head Office",
        "country": "ID",
        "province": "DKI",
        "city": "JKT",
        "address": "Jakarta Selatan",
        "postal_code": "12950",
        "phone": "+62 21 5551000",
        "email": "jakarta@meinova.com",
        "website": "https://meinova.com",
    },
    {
        "company": "SUN",
        "code": "JKT",
        "name": "SUN Jakarta Office",
        "country": "ID",
        "province": "DKI",
        "city": "JKT",
        "address": "Jakarta Selatan",
        "postal_code": "12950",
        "phone": "+62 21 5551001",
        "email": "jakarta@sun.co.id",
        "website": "",
    },
    {
        "company": "KMI",
        "code": "MOR",
        "name": "Morowali Branch",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "Morowali, Sulawesi Tengah",
        "postal_code": "",
        "phone": "",
        "email": "morowali@kawi.co.id",
        "website": "",
    },
]


SITES = [
    {
        "company": "MNV",
        "branch": "JKT",
        "site_type": "OFFICE",
        "code": "HO",
        "name": "Meinova Head Office",
        "country": "ID",
        "province": "DKI",
        "city": "JKT",
        "address": "Jakarta Selatan",
        "postal_code": "12950",
    },
    {
        "company": "KMI",
        "branch": "MOR",
        "site_type": "MINE",
        "code": "MINE01",
        "name": "Morowali Mine",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "Morowali, Sulawesi Tengah",
        "postal_code": "",
    },
    {
        "company": "KMI",
        "branch": "MOR",
        "site_type": "PORT",
        "code": "PORT01",
        "name": "Morowali Port",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "Morowali, Sulawesi Tengah",
        "postal_code": "",
    },
]


# company, branch, site, code, name
DIVISIONS = [
    ("MNV", "JKT", "HO", "CORP", "Corporate Services"),
    ("KMI", "MOR", "MINE01", "OPS", "Operations"),
    ("KMI", "MOR", "MINE01", "TECH", "Technical Services"),
]


# company, branch, site, division, code, name
DEPARTMENTS = [
    ("MNV", "JKT", "HO", "CORP", "FIN", "Finance"),
    ("MNV", "JKT", "HO", "CORP", "HR", "Human Resources"),
    ("MNV", "JKT", "HO", "CORP", "IT", "Information Technology"),

    ("KMI", "MOR", "MINE01", "OPS", "MINE", "Mining Operation"),
    ("KMI", "MOR", "MINE01", "OPS", "PLANT", "Processing Plant"),
    ("KMI", "MOR", "MINE01", "TECH", "ENG", "Engineering"),
    ("KMI", "MOR", "MINE01", "TECH", "GEO", "Geology"),
    ("KMI", "MOR", "MINE01", "TECH", "HSE", "Health Safety Environment"),
]


# company, branch, site, division, department, code, name
SECTIONS = [
    ("MNV", "JKT", "HO", "CORP", "FIN", "AP", "Accounts Payable"),
    ("MNV", "JKT", "HO", "CORP", "FIN", "AR", "Accounts Receivable"),
    ("MNV", "JKT", "HO", "CORP", "HR", "PAY", "Payroll"),
    ("MNV", "JKT", "HO", "CORP", "HR", "REC", "Recruitment"),

    ("KMI", "MOR", "MINE01", "OPS", "MINE", "PROD", "Production"),
    ("KMI", "MOR", "MINE01", "OPS", "MINE", "DISP", "Dispatch"),
    ("KMI", "MOR", "MINE01", "TECH", "GEO", "GC", "Grade Control"),
]


POSITIONS = [
    {
        "company": "MNV",
        "branch": "JKT",
        "site": "HO",
        "division": "CORP",
        "department": None,
        "section": None,
        "job_category": "MGMT",
        "job_level": "DIR",
        "code": "PRES-DIR",
        "name": "President Director",
        "headcount": 1,
        "description": "",
        "is_manager": True,
        "reports_to": None,
    },
    {
        "company": "MNV",
        "branch": "JKT",
        "site": "HO",
        "division": "CORP",
        "department": "HR",
        "section": None,
        "job_category": "MGMT",
        "job_level": "MGR",
        "code": "HR-MGR",
        "name": "HR Manager",
        "headcount": 1,
        "description": "",
        "is_manager": True,
        "reports_to": "PRES-DIR",
    },
    {
        "company": "MNV",
        "branch": "JKT",
        "site": "HO",
        "division": "CORP",
        "department": "HR",
        "section": "PAY",
        "job_category": "SUPPORT",
        "job_level": "STAFF",
        "code": "PAY-STAFF",
        "name": "Payroll Staff",
        "headcount": 3,
        "description": "",
        "is_manager": False,
        "reports_to": "HR-MGR",
    },
    {
        "company": "KMI",
        "branch": "MOR",
        "site": "MINE01",
        "division": "OPS",
        "department": "MINE",
        "section": "PROD",
        "job_category": "OPS",
        "job_level": "SUP",
        "code": "MINE-SUP",
        "name": "Mine Production Supervisor",
        "headcount": 4,
        "description": "",
        "is_manager": True,
        "reports_to": None,
    },
    {
        "company": "KMI",
        "branch": "MOR",
        "site": "MINE01",
        "division": "OPS",
        "department": "MINE",
        "section": "PROD",
        "job_category": "OPS",
        "job_level": "STAFF",
        "code": "MINE-OPR",
        "name": "Mining Operator",
        "headcount": 30,
        "description": "",
        "is_manager": False,
        "reports_to": "MINE-SUP",
    },
]


# company, branch, site, division, department, code, name
COST_CENTERS = [
    ("MNV", "JKT", "HO", "CORP", None, "1000", "Corporate"),
    ("MNV", "JKT", "HO", "CORP", "FIN", "1100", "Finance"),
    ("MNV", "JKT", "HO", "CORP", "HR", "1200", "Human Resources"),
    ("MNV", "JKT", "HO", "CORP", "IT", "1300", "Information Technology"),

    ("KMI", "MOR", "MINE01", "OPS", "MINE", "2000", "Mining Operation"),
    ("KMI", "MOR", "MINE01", "TECH", "GEO", "2100", "Geology"),
    ("KMI", "MOR", "MINE01", "OPS", "PLANT", "2200", "Processing Plant"),
]


def optional_by_code(
    model: type[ModelT],
    code: str | None,
) -> ModelT | None:
    if not code:
        return None

    return model.objects.filter(code=code).first()


def require_reference(
    values: dict[str, ModelT],
    code: str,
    reference_name: str,
) -> ModelT:
    value = values.get(code)

    if value is None:
        raise RuntimeError(
            f"{reference_name} with code '{code}' is not available. "
            "Run the required reference seed first."
        )

    return value


def seed_organization_references() -> None:
    for model, rows in ORGANIZATION_REFERENCE_DATA.items():
        seed_reference(
            model,
            [
                {
                    "code": code,
                    "name": name,
                }
                for code, name in rows
            ],
        )


def seed_organization() -> None:
    # Reference organisasi dijalankan otomatis terlebih dahulu.
    seed_organization_references()

    countries = {
        item.code: item
        for item in Country.objects.filter(
            code__in={
                row["country"]
                for row in COMPANIES + BRANCHES + SITES
                if row.get("country")
            },
        )
    }

    provinces = {
        item.code: item
        for item in Province.objects.filter(
            code__in={
                row["province"]
                for row in COMPANIES + BRANCHES + SITES
                if row.get("province")
            },
        )
    }

    cities = {
        item.code: item
        for item in City.objects.filter(
            code__in={
                row["city"]
                for row in COMPANIES + BRANCHES + SITES
                if row.get("city")
            },
        )
    }

    company_types = {
        item.code: item
        for item in CompanyType.objects.all()
    }

    site_types = {
        item.code: item
        for item in SiteType.objects.all()
    }

    job_categories = {
        item.code: item
        for item in JobCategory.objects.all()
    }

    job_levels = {
        item.code: item
        for item in JobLevel.objects.all()
    }

    companies: dict[str, Company] = {}

    # Pass pertama: buat Company tanpa parent.
    for row in COMPANIES:
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
                "legal_name": row["legal_name"],
                "tax_number": row.get("tax_number", ""),
                "country": (
                    require_reference(
                        countries,
                        row["country"],
                        "Country",
                    )
                    if row.get("country")
                    else None
                ),
                "province": provinces.get(row.get("province")),
                "city": cities.get(row.get("city")),
                "address": row.get("address", ""),
                "postal_code": row.get("postal_code", ""),
                "phone": row.get("phone", ""),
                "email": row.get("email", ""),
                "website": row.get("website", ""),
                "is_active": True,
            },
        )

        companies[row["code"]] = company

    # Pass kedua: isi parent Company.
    for row in COMPANIES:
        company = companies[row["code"]]
        parent_code = row.get("parent")
        parent = companies.get(parent_code) if parent_code else None

        if company.parent_id != getattr(parent, "id", None):
            company.parent = parent
            company.save(update_fields=["parent"])

    branches: dict[tuple[str, str], Branch] = {}

    for row in BRANCHES:
        company_code = row["company"]
        company = companies[company_code]

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
                "province": provinces.get(row.get("province")),
                "city": cities.get(row.get("city")),
                "address": row.get("address", ""),
                "postal_code": row.get("postal_code", ""),
                "phone": row.get("phone", ""),
                "email": row.get("email", ""),
                "website": row.get("website", ""),
                "is_active": True,
            },
        )

        branches[(company_code, row["code"])] = branch

    sites: dict[tuple[str, str], Site] = {}

    for row in SITES:
        company_code = row["company"]
        company = companies[company_code]
        branch = branches[(company_code, row["branch"])]

        site, _ = Site.objects.update_or_create(
            company=company,
            code=row["code"],
            defaults={
                "branch": branch,
                "name": row["name"],
                "site_type": require_reference(
                    site_types,
                    row["site_type"],
                    "SiteType",
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
                "province": provinces.get(row.get("province")),
                "city": cities.get(row.get("city")),
                "address": row.get("address", ""),
                "postal_code": row.get("postal_code", ""),
                "is_active": True,
            },
        )

        sites[(company_code, row["code"])] = site

    divisions: dict[tuple[str, str], Division] = {}

    for company_code, branch_code, site_code, code, name in DIVISIONS:
        division, _ = Division.objects.update_or_create(
            company=companies[company_code],
            code=code,
            defaults={
                "branch": branches[(company_code, branch_code)],
                "site": sites[(company_code, site_code)],
                "name": name,
                "is_active": True,
            },
        )

        divisions[(company_code, code)] = division

    departments: dict[tuple[str, str], Department] = {}

    for (
        company_code,
        branch_code,
        site_code,
        division_code,
        code,
        name,
    ) in DEPARTMENTS:
        department, _ = Department.objects.update_or_create(
            company=companies[company_code],
            code=code,
            defaults={
                "branch": branches[(company_code, branch_code)],
                "site": sites[(company_code, site_code)],
                "division": divisions[(company_code, division_code)],
                "name": name,
                "is_active": True,
            },
        )

        departments[(company_code, code)] = department

    sections: dict[tuple[str, str], Section] = {}

    for (
        company_code,
        branch_code,
        site_code,
        division_code,
        department_code,
        code,
        name,
    ) in SECTIONS:
        section, _ = Section.objects.update_or_create(
            company=companies[company_code],
            code=code,
            defaults={
                "branch": branches[(company_code, branch_code)],
                "site": sites[(company_code, site_code)],
                "division": divisions[(company_code, division_code)],
                "department": departments[
                    (company_code, department_code)
                ],
                "name": name,
                "is_active": True,
            },
        )

        sections[(company_code, code)] = section

    positions: dict[tuple[str, str], Position] = {}

    # Pass pertama: buat Position tanpa reports_to.
    for row in POSITIONS:
        company_code = row["company"]

        position, _ = Position.objects.update_or_create(
            company=companies[company_code],
            code=row["code"],
            defaults={
                "branch": branches[
                    (company_code, row["branch"])
                ],
                "site": sites[
                    (company_code, row["site"])
                ],
                "division": divisions[
                    (company_code, row["division"])
                ],
                "department": (
                    departments.get(
                        (company_code, row["department"])
                    )
                    if row.get("department")
                    else None
                ),
                "section": (
                    sections.get(
                        (company_code, row["section"])
                    )
                    if row.get("section")
                    else None
                ),
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
                "headcount": row.get("headcount", 1),
                "description": row.get("description", ""),
                "is_manager": row.get("is_manager", False),
                "is_active": True,
            },
        )

        positions[(company_code, row["code"])] = position

    # Pass kedua: isi reports_to.
    for row in POSITIONS:
        manager_code = row.get("reports_to")

        if not manager_code:
            continue

        key = (row["company"], row["code"])
        manager_key = (row["company"], manager_code)

        position = positions[key]
        manager = positions.get(manager_key)

        if manager is None:
            raise RuntimeError(
                f"Position manager '{manager_code}' was not found "
                f"for company '{row['company']}'."
            )

        if position.reports_to_id != manager.id:
            position.reports_to = manager
            position.save(update_fields=["reports_to"])

    for (
        company_code,
        branch_code,
        site_code,
        division_code,
        department_code,
        code,
        name,
    ) in COST_CENTERS:
        CostCenter.objects.update_or_create(
            company=companies[company_code],
            code=code,
            defaults={
                "branch": branches[(company_code, branch_code)],
                "site": sites[(company_code, site_code)],
                "division": divisions[(company_code, division_code)],
                "department": (
                    departments.get(
                        (company_code, department_code)
                    )
                    if department_code
                    else None
                ),
                "name": name,
                "is_active": True,
            },
        )