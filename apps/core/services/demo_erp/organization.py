"""
Workbook → `OrganizationDataset` (mesin tulis organisasi yang sudah ada).

Tidak ada penulis organisasi tandingan. DEMO-1B menyerahkan dataset ini
ke `apps.administration.seeds.organization.seed_organization()` — mesin
yang sama yang dulu menulis MNI/MMR/MLS (dibuang DEMO-1F). Di sini hanya datanya disusun.

Dataset hanya berisi company milik dataset ini (GRP/MMN/MIN). Perencana
menolak dataset yang menyebut kode company terlindung, karena
`seed_organization()` mencari Company **hanya dengan `code`** dan akan
menimpa company mana pun yang kodenya sama.
"""

from __future__ import annotations

from apps.administration.seeds.organization import OrganizationDataset

from . import mapping
from .workbook import Workbook


BRANCH_CODE = "DEFAULT"
BRANCH_NAME = "Main Branch"


def _geography(location_code: str) -> dict:
    """Negara/provinsi/kota/alamat lokasi dataset (`mapping.LOCATION_GEOGRAPHY`)."""
    return dict(mapping.LOCATION_GEOGRAPHY[location_code])


def build_dataset(workbook: Workbook) -> OrganizationDataset:
    companies = []

    for row in workbook.companies:
        companies.append(
            {
                "code": row.code,
                "name": mapping.company_name(row),
                "legal_name": f"PT {mapping.company_name(row).upper()}",
                "company_type": mapping.COMPANY_TYPE[row.entity_type],
                "parent": row.parent,
                "tax_number": "",
                "country": "ID",
                "province": "DKI",
                "city": "JKT",
                "address": "",
                "postal_code": "",
                "phone": "",
                "email": mapping.company_email(row.code),
                "website": "",
            }
        )

    branches = [
        {"company": row.code, "code": BRANCH_CODE, "name": BRANCH_NAME, "country": "ID"}
        for row in workbook.companies
    ]

    # Lokasi = pasangan (company, lokasi) yang benar-benar dipakai unit
    # lembar 02 atau pegawai lembar 03. Company tanpa satu pun unit/pegawai
    # di sebuah lokasi tidak mendapat lokasi itu.
    used_locations = sorted(
        {(row.company, row.location) for row in workbook.org_units
         if (row.company, row.code) not in mapping.EXCLUDED_UNITS}
        | {(row.company, row.location) for row in workbook.employees}
    )

    locations = []

    for company, name in used_locations:
        code, display, location_type = mapping.LOCATIONS[name]

        locations.append(
            {
                "company": company,
                "branch": BRANCH_CODE,
                "location_type": location_type,
                "code": code,
                "name": display,
                **_geography(code),
            }
        )

    location_types = {(row["company"], row["code"]): row["location_type"] for row in locations}

    divisions = []

    for (company, code), location_type in sorted(location_types.items()):
        division_code, division_name = mapping.DIVISION_BY_LOCATION_TYPE[location_type]

        divisions.append((company, BRANCH_CODE, code, division_code, division_name))

    departments = []
    cost_centers = []

    for unit in workbook.org_units:
        if (unit.company, unit.code) in mapping.EXCLUDED_UNITS:
            continue

        location = mapping.location_code(unit.location)
        division = mapping.DIVISION_BY_LOCATION_TYPE[
            location_types[(unit.company, location)]
        ][0]

        departments.append(
            (unit.company, BRANCH_CODE, location, division, unit.code, unit.name)
        )
        # Konvensi dataset peragaan: satu cost center per department,
        # kodenya diturunkan dari kode department.
        cost_centers.append(
            (
                unit.company,
                BRANCH_CODE,
                location,
                division,
                unit.code,
                f"{unit.company}-{unit.code}",
                unit.name,
            )
        )

    positions = _positions(workbook, location_types)

    return OrganizationDataset(
        name="Meinova ERP demo (GRP/MMN/MIN)",
        companies=companies,
        branches=branches,
        locations=locations,
        divisions=divisions,
        departments=departments,
        sections=[],
        positions=positions,
        cost_centers=cost_centers,
    )


def _positions(workbook: Workbook, location_types) -> list[dict]:
    by_id = {row.employee_id: row for row in workbook.employees}
    positions: dict[str, dict] = {}

    for row in workbook.employees:
        code = mapping.position_code(row)

        if code in positions:
            continue

        location = mapping.location_code(row.location)
        division = mapping.DIVISION_BY_LOCATION_TYPE[
            location_types[(row.company, location)]
        ][0]

        manager = by_id.get(row.reports_to) if row.reports_to else None

        # Pohon jabatan hanya di dalam satu company — `seed_organization`
        # mencari atasan jabatan di company yang sama. Garis pelaporan
        # lintas company tetap hidup di tingkat orang (reports_to).
        reports_to = (
            mapping.position_code(manager)
            if manager is not None and manager.company == row.company
            else None
        )

        positions[code] = {
            "company": row.company,
            "branch": BRANCH_CODE,
            "location": location,
            "division": division,
            "department": mapping.department_code(row),
            "section": None,
            "code": code,
            "name": row.position,
            "job_category": mapping.job_category(row),
            "job_level": mapping.job_level(row),
            "is_manager": mapping.is_manager_position(row),
            "headcount": sum(
                1 for other in workbook.employees
                if mapping.position_code(other) == code
            ),
            "reports_to": reports_to,
            "description": "",
        }

    return list(positions.values())
