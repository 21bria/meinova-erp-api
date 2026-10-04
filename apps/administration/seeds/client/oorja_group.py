"""
Struktur organisasi **milik satu klien** (grup Oorja Graoup, 12 badan
usaha) — diturunkan dari `Employee Database per August 2026.xlsx`.

Dulu isinya duduk di `seeds/organization.py` yang dipanggil
`seed_administration --only=organization`, jadi ia ikut ke **setiap**
tenant yang pernah dibuat. Tenant peragaan pun berisi nama perusahaan
klien sungguhan, dan tangkapan layar panduan ikut menyebarkannya.

Sekarang berdiri sendiri dan **tidak dijalankan otomatis**:

    python manage.py tenant_command seed_client_org --client=kw --schema=<tenant>

Datanya sengaja tidak dibuang — kalau tenant produksi grup ini dibuat,
strukturnya tinggal ditulis dari sini alih-alih di-import ulang dari
Excel.
"""

import hashlib

from ..organization import (
    OrganizationDataset,
    make_code,
    seed_organization,
)


# ============================================================
# COMPANY
# Source: Employee Database per August 2026.xlsx
# ============================================================

COMPANIES = [
    {
        "code": "KPB",
        "name": "Karya Putra Borneo",
        "legal_name": "PT KARYA PUTRA BORNEO",
        "company_type": "COMP",
        "parent": None,
        "tax_number": "",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "",
        "postal_code": "",
        "phone": "",
        "email": "",
        "website": "",
    },
    {
        "code": "IP",
        "name": "Indo Perkasa",
        "legal_name": "PT INDO PERKASA",
        "company_type": "COMP",
        "parent": None,
        "tax_number": "",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "",
        "postal_code": "",
        "phone": "",
        "email": "",
        "website": "",
    },
    {
        "code": "OIK",
        "name": "Oorja Indo KGS",
        "legal_name": "PT OORJA INDO KGS",
        "company_type": "COMP",
        "parent": None,
        "tax_number": "",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "",
        "postal_code": "",
        "phone": "",
        "email": "",
        "website": "",
    },
    {
        "code": "PBP",
        "name": "Purwo Bakti Pertiwi",
        "legal_name": "PT PURWO BAKTI PERTIWI",
        "company_type": "COMP",
        "parent": None,
        "tax_number": "",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "",
        "postal_code": "",
        "phone": "",
        "email": "",
        "website": "",
    },
    {
        "code": "VEP",
        "name": "Venus Energy Power",
        "legal_name": "PT VENUS ENERGY POWER",
        "company_type": "COMP",
        "parent": None,
        "tax_number": "",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "",
        "postal_code": "",
        "phone": "",
        "email": "",
        "website": "",
    },
    {
        "code": "EMM",
        "name": "Erza Mustika Mandiri",
        "legal_name": "PT ERZA MUSTIKA MANDIRI",
        "company_type": "COMP",
        "parent": None,
        "tax_number": "",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "",
        "postal_code": "",
        "phone": "",
        "email": "",
        "website": "",
    },
    {
        "code": "BKR",
        "name": "Bina Karya Rejeki",
        "legal_name": "PT BINA KARYA REJEKI",
        "company_type": "COMP",
        "parent": None,
        "tax_number": "",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "",
        "postal_code": "",
        "phone": "",
        "email": "",
        "website": "",
    },
    {
        "code": "BKI",
        "name": "Bara Komiditi Indonesia",
        "legal_name": "PT BARA KOMIDITI INDONESIA",
        "company_type": "COMP",
        "parent": None,
        "tax_number": "",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "",
        "postal_code": "",
        "phone": "",
        "email": "",
        "website": "",
    },
    {
        "code": "RJR",
        "name": "Raharja Jaya Rejeki",
        "legal_name": "PT RAHARJA JAYA REJEKI",
        "company_type": "COMP",
        "parent": None,
        "tax_number": "",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "",
        "postal_code": "",
        "phone": "",
        "email": "",
        "website": "",
    },
    {
        "code": "ETSI",
        "name": "Element Tujuh Sembilan Indonesia",
        "legal_name": "PT ELEMENT TUJUH SEMBILAN INDONESIA",
        "company_type": "COMP",
        "parent": None,
        "tax_number": "",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "",
        "postal_code": "",
        "phone": "",
        "email": "",
        "website": "",
    },
    {
        "code": "IMM",
        "name": "Indonesia Mas Mulia",
        "legal_name": "PT INDONESIA MAS MULIA",
        "company_type": "COMP",
        "parent": None,
        "tax_number": "",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "",
        "postal_code": "",
        "phone": "",
        "email": "",
        "website": "",
    },
    {
        "code": "KW",
        "name": "Karya Wijaya",
        "legal_name": "PT KARYA WIJAYA",
        "company_type": "COMP",
        "parent": None,
        "tax_number": "",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "",
        "postal_code": "",
        "phone": "",
        "email": "",
        "website": "",
    },
]



# ============================================================
# DEFAULT BRANCH
#
# Excel tidak menyediakan master Branch.
# DEFAULT adalah baseline/default organization.
#
# Namanya **Main Branch**, bukan "Default Location". Dulu keduanya —
# Branch bawaan dan Location bawaan — diberi nama yang sama persis, jadi
# di layar Locations kolom Branch dan kolom Location Name berbunyi
# identik. Dropdown filter Branch yang isinya "Default Location" terbaca
# seperti filter yang belum menyaring apa pun, padahal memang cuma ada
# satu. Seed mencocokkan lewat `code`, jadi mengganti nama memperbarui
# baris yang sudah ada, bukan membuat baris baru.
# ============================================================

BRANCHES = [
    {
        "company": company["code"],
        "code": "DEFAULT",
        "name": "Main Branch",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "",
        "postal_code": "",
        "phone": "",
        "email": "",
        "website": "",
    }
    for company in COMPANIES
]


# ============================================================
# DEFAULT LOCATION
#
# JOB LOC dari Excel tidak masuk Location.
# JOB LOC nanti masuk Employee.work_location.
# ============================================================

LOCATIONS = [
    {
        "company": company["code"],
        "branch": "DEFAULT",
        "location_type": "OFFICE",
        "code": "DEFAULT",
        "name": "Default Location",
        "country": "ID",
        "province": None,
        "city": None,
        "address": "",
        "postal_code": "",
    }
    for company in COMPANIES
]


# ============================================================
# FACILITY
#
# Hanya yang benar-benar diketahui ada. Site Gebe memang punya
# workshop, gudang, jetty, dan camp — nama-nama itu sudah dipakai
# klien di dokumen roster dan travel request-nya.
#
# Lokasi lain sengaja tidak diberi fasilitas apa pun: mengarang
# "Warehouse Default" untuk setiap company membuat master ini terlihat
# terisi padahal isinya tidak menunjuk bangunan mana pun, dan angka
# yang mengarang lebih berbahaya daripada tabel yang kosong.
# ============================================================

FACILITIES = [
    {
        "company": "KW",
        "location": "GEBE",
        "facility_type": "WORKSHOP",
        "code": "GBE-WS",
        "name": "Workshop Gebe",
        "description": "Bengkel alat berat di area site.",
    },
    {
        "company": "KW",
        "location": "GEBE",
        "facility_type": "WAREHOUSE",
        "code": "GBE-WH",
        "name": "Warehouse Gebe",
        "description": "Gudang sparepart dan consumable.",
    },
    {
        "company": "KW",
        "location": "GEBE",
        "facility_type": "JETTY",
        "code": "GBE-JT",
        "name": "Jetty Gebe",
        "description": "Dermaga muat dan titik keluar-masuk crew.",
    },
    {
        "company": "KW",
        "location": "GEBE",
        "facility_type": "CAMP",
        "code": "GBE-CP",
        "name": "Camp Gebe",
        "description": "Mess dan fasilitas akomodasi crew.",
    },
]


# ============================================================
# DIVISION
# ============================================================

DIVISIONS = [
    (
        company["code"],
        "DEFAULT",
        "DEFAULT",
        "GENERAL",
        "General",
    )
    for company in COMPANIES
]


# ============================================================
# DEPARTMENT
# ============================================================

DEPARTMENT_NAMES = [
    ("GENERAL", "General"),
    ("BOD", "Board of Directors"),
    ("CORPORATE", "Corporate"),
    ("HR", "Human Resources"),
    ("GA", "General Affairs"),
    ("FINANCE", "Finance"),
    ("ACCOUNTING", "Accounting"),
    ("TAX", "Tax"),
    ("LEGAL", "Legal"),
    ("COMMERCIAL", "Commercial"),
    ("PROCUREMENT", "Procurement"),
    ("PURCHASING", "Purchasing"),
    ("SUPPLY_CHAIN", "Supply Chain"),
    ("LOGISTICS", "Logistics"),
    ("WAREHOUSE", "Warehouse"),
    ("IT", "Information Technology"),
    ("ENGINEERING", "Engineering"),
    ("MINING", "Mining"),
    ("MINE_PLANNING", "Mine Planning"),
    ("GEOLOGY", "Geology"),
    ("GRADE_CONTROL", "Grade Control"),
    ("SURVEY", "Survey"),
    ("PRODUCTION", "Production"),
    ("OPERATIONS", "Operations"),
    ("HSE", "Health Safety Environment"),
    ("LABORATORY", "Laboratory"),
    ("QUALITY_CONTROL", "Quality Control"),
    ("MAINTENANCE", "Maintenance"),
    ("MECHANICAL", "Mechanical"),
    ("ELECTRICAL", "Electrical"),
    ("PLANT", "Plant"),
    ("STOCKPILE", "Stockpile"),
    ("BARGING", "Barging"),
    ("PORT", "Port"),
    ("SECURITY", "Security"),
    ("CAMP", "Camp"),
    (
        "COMMUNITY_DEVELOPMENT",
        "Community Development",
    ),
    ("ADMINISTRATION", "Administration"),
]


DEPARTMENTS = [
    (
        company["code"],
        "DEFAULT",
        "DEFAULT",
        "GENERAL",
        department_code,
        department_name,
    )
    for company in COMPANIES
    for (
        department_code,
        department_name,
    ) in DEPARTMENT_NAMES
]


# ============================================================
# SECTION
#
# Setiap department mempunyai General Section.
# Section code dibuat unik dalam Company.
# ============================================================

def make_general_section_code(
    department_code: str,
) -> str:
    if department_code == "GENERAL":
        return "GENERAL"

    return f"{department_code}_GENERAL"


SECTIONS = [
    (
        company["code"],
        "DEFAULT",
        "DEFAULT",
        "GENERAL",
        department_code,
        make_general_section_code(
            department_code
        ),
        "General",
    )
    for company in COMPANIES
    for (
        department_code,
        _department_name,
    ) in DEPARTMENT_NAMES
]


# ============================================================
# POSITION
# Source: Employee Database per August 2026.xlsx
#
# Nama dipertahankan agar import Employee bisa match
# langsung terhadap nama Position dari Excel.
# ============================================================

POSITION_NAMES = [
    "Acct & Finance Staff.",
    "Analyst",
    "BOD",
    "Civil Engineer",
    "Commercial Manager",
    "Commercial Staff",
    "Commercial Staff/Admin",
    "Commercial Supervisor",
    "Community Development Supervisor",
    "Corporate Legal Staff",
    "Corporate Secretary & Legal Mgr.",
    "Database Developer",
    "Driver",
    "Executive Assistant",
    "External Supervisor",
    "Finance & Accounts Staff",
    "Finance Staff",
    "Finance Staff/Admin",
    "Foreman Electrical Mechanical",
    "Foreman GA",
    "Foreman Grade Control",
    "Foreman Prep (Maintenance)",
    "Foreman Stockpile",
    "Foreman Stockpile & Barging",
    "Foreman Stockpile and Barging",
    "GA Admin",
    "GA Crew",
    "GA Foreman",
    "GA Helper",
    "GC Crew",
    "GGC Admin",
    "General Affairs",
    "Geologist",
    "Grade Control Crew",
    "Grade Control Foreman",
    "HR Manager",
    "HR Superintendent",
    "HRGA Manager",
    "HSE Officer / Foreman",
    "HSE Supervisor",
    "Head Geologist",
    "Housekeeping - Laundry",
    "IT Support Staff",
    "Jr. Mine Plan Engineer",
    "KTT",
    "LV Driver",
    "Laboratory Analyst",
    "Laboratory Analyst- Foreman",
    "Legal Staff",
    "Logistik Crew",
    "Messenger",
    "Mine Crew",
    "Mine Ops Superintendent",
    "Mine Plan Engineer",
    "Mine Support Supervisor",
    "Mine Surveyor Assistant (Foreman)",
    "Mine Technical Compliance",
    "OB / Messenger",
    "OB/Messenger/Driver",
    "Office Boy / Messenger",
    "Office Girl",
    "Operation Foreman",
    "Operation General Manager",
    "Operation Superintendent",
    "Operational Foreman",
    "Paramedic (HSE)",
    "Personal Assistant",
    "Preparation Crew",
    "Production Admin",
    "Purchasing",
    "Receptionist",
    "Safety Crew",
    "Sampler",
    "Security",
    "Spv Geology and QC",
    "Spv. Laboratory & Preparation",
    "Sr. Geologist",
    "Sr. Tax Staff",
    "Staff Teknis Pertambangan",
    "Stockpile & Barging Foreman",
    "Stockpile and Barging Supervisor",
    "Survey Crew",
    "Surveyor Assistant",
    "Tax Staff/Admin",
    "Tax Supervisor",
    "Team Leader Preparation Crew",
]


# ============================================================
# POSITION CODE
#
# Ada nama berbeda yang dapat menghasilkan code sama.
# Contoh:
#
# Foreman Stockpile & Barging
# Foreman Stockpile and Barging
#
# Collision diberi suffix hash yang deterministic.
# ============================================================

def build_position_codes(
    names: list[str],
) -> dict[str, str]:
    result: dict[str, str] = {}
    used_codes: dict[str, str] = {}

    for name in names:
        base_code = make_code(name)
        code = base_code

        existing_name = used_codes.get(code)

        if (
            existing_name is not None
            and existing_name != name
        ):
            digest = hashlib.sha1(
                name.encode("utf-8")
            ).hexdigest()[:6].upper()

            code = f"{base_code}_{digest}"

        used_codes[code] = name
        result[name] = code

    return result


POSITION_CODES = build_position_codes(
    POSITION_NAMES
)


# ============================================================
# POSITION -> DEPARTMENT
# ============================================================

def get_position_department(
    name: str,
) -> str:
    value = name.lower().strip()

    # Board
    if value == "bod":
        return "BOD"

    # Corporate
    if any(
        key in value
        for key in [
            "personal assistant",
            "executive assistant",
        ]
    ):
        return "CORPORATE"

    # HR
    if (
        value.startswith("hr ")
        or value.startswith("hrga")
        or "human resource" in value
    ):
        return "HR"

    # General Affairs
    if any(
        key in value
        for key in [
            "general affairs",
            "ga admin",
            "ga crew",
            "ga foreman",
            "ga helper",
            "foreman ga",
            "housekeeping",
            "office boy",
            "office girl",
            "messenger",
            "driver",
            "receptionist",
        ]
    ):
        return "GA"

    # Finance
    if "finance" in value:
        return "FINANCE"

    # Accounting
    if any(
        key in value
        for key in [
            "account",
            "acct",
        ]
    ):
        return "ACCOUNTING"

    # Tax
    if "tax" in value:
        return "TAX"

    # Legal
    if "legal" in value:
        return "LEGAL"

    # Commercial
    if "commercial" in value:
        return "COMMERCIAL"

    # Purchasing
    if "purchasing" in value:
        return "PURCHASING"

    # Procurement
    if "procurement" in value:
        return "PROCUREMENT"

    # Logistics
    if any(
        key in value
        for key in [
            "logistik",
            "logistic",
        ]
    ):
        return "LOGISTICS"

    # IT
    if any(
        key in value
        for key in [
            "it support",
            "database",
        ]
    ):
        return "IT"

    # Engineering
    if any(
        key in value
        for key in [
            "civil engineer",
            "engineering",
        ]
    ):
        return "ENGINEERING"

    # Mine Planning
    if "mine plan" in value:
        return "MINE_PLANNING"

    # Grade Control
    if any(
        key in value
        for key in [
            "grade control",
            "gc crew",
            "ggc",
        ]
    ):
        return "GRADE_CONTROL"

    # Geology
    if any(
        key in value
        for key in [
            "geologist",
            "geology",
        ]
    ):
        return "GEOLOGY"

    # Survey
    if any(
        key in value
        for key in [
            "survey",
            "surveyor",
        ]
    ):
        return "SURVEY"

    # HSE
    if any(
        key in value
        for key in [
            "hse",
            "safety",
            "paramedic",
        ]
    ):
        return "HSE"

    # Laboratory
    if any(
        key in value
        for key in [
            "laboratory",
            "sampler",
            "preparation",
        ]
    ):
        return "LABORATORY"

    # Stockpile + Barging
    if (
        "stockpile" in value
        and "barging" in value
    ):
        return "STOCKPILE"

    # Stockpile
    if "stockpile" in value:
        return "STOCKPILE"

    # Barging
    if "barging" in value:
        return "BARGING"

    # Maintenance
    if any(
        key in value
        for key in [
            "maintenance",
            "electrical mechanical",
        ]
    ):
        return "MAINTENANCE"

    # Security
    if "security" in value:
        return "SECURITY"

    # Community Development
    if "community development" in value:
        return "COMMUNITY_DEVELOPMENT"

    # Production
    if "production" in value:
        return "PRODUCTION"

    # Mining
    if any(
        key in value
        for key in [
            "mine ops",
            "mine crew",
            "mine support",
            "mine technical",
            "staff teknis pertambangan",
            "ktt",
        ]
    ):
        return "MINING"

    # Operations
    if any(
        key in value
        for key in [
            "operation",
            "operational",
        ]
    ):
        return "OPERATIONS"

    return "GENERAL"


def get_position_section(
    name: str,
) -> str:
    department_code = get_position_department(
        name
    )

    return make_general_section_code(
        department_code
    )


# ============================================================
# POSITION -> JOB LEVEL
#
# Assumption:
# JobLevel seed memiliki:
# MGR, SUP, STAFF
# ============================================================

def get_position_job_level(
    name: str,
) -> str:
    value = name.lower().strip()

    if (
        value == "bod"
        or "general manager" in value
        or "manager" in value
    ):
        return "MGR"

    if any(
        key in value
        for key in [
            "superintendent",
            "supervisor",
            "spv",
            "foreman",
            "team leader",
            "head ",
            "ktt",
        ]
    ):
        return "SUP"

    return "STAFF"


# ============================================================
# POSITION -> JOB CATEGORY
#
# Assumption:
# JobCategory seed memiliki:
# MGMT, OPS, SUPPORT
# ============================================================

def get_position_job_category(
    name: str,
) -> str:
    value = name.lower().strip()

    if (
        value == "bod"
        or any(
            key in value
            for key in [
                "manager",
                "superintendent",
                "supervisor",
                "spv",
                "foreman",
                "team leader",
                "head ",
                "ktt",
            ]
        )
    ):
        return "MGMT"

    if any(
        key in value
        for key in [
            "mine",
            "geolog",
            "grade control",
            "survey",
            "operation",
            "operational",
            "production",
            "stockpile",
            "barging",
            "laboratory",
            "sampler",
            "preparation",
            "safety",
            "hse",
        ]
    ):
        return "OPS"

    return "SUPPORT"


def is_manager_position(
    name: str,
) -> bool:
    value = name.lower().strip()

    return (
        value == "bod"
        or value == "ktt"
        or any(
            key in value
            for key in [
                "manager",
                "superintendent",
                "supervisor",
                "spv",
                "foreman",
                "team leader",
                "head ",
            ]
        )
    )


# ============================================================
# POSITION DATA
# ============================================================

POSITIONS = [
    {
        "company": company["code"],
        "branch": "DEFAULT",
        "location": "DEFAULT",
        "division": "GENERAL",
        "department": get_position_department(
            position_name
        ),
        "section": get_position_section(
            position_name
        ),
        "job_category": get_position_job_category(
            position_name
        ),
        "job_level": get_position_job_level(
            position_name
        ),
        "code": POSITION_CODES[
            position_name
        ],
        "name": position_name,
        "headcount": 1,
        "description": "",
        "is_manager": is_manager_position(
            position_name
        ),
        "reports_to": None,
    }
    for company in COMPANIES
    for position_name in POSITION_NAMES
]


# ============================================================
# COST CENTER
#
# Satu Cost Center default per Department.
#
# 1000 General
# 1010 Board of Directors
# 1020 Corporate
# ...
# ============================================================

COST_CENTERS = [
    (
        company["code"],
        "DEFAULT",
        "DEFAULT",
        "GENERAL",
        department_code,
        str(
            1000
            + (index * 10)
        ),
        department_name,
    )
    for company in COMPANIES
    for index, (
        department_code,
        department_name,
    ) in enumerate(
        DEPARTMENT_NAMES
    )
]


# ============================================================
# REFERENCE SEED
# ============================================================



# ============================================================
# DATASET
# ============================================================

DATASET = OrganizationDataset(
    name="Karya Wijaya Group",
    companies=COMPANIES,
    branches=BRANCHES,
    locations=LOCATIONS,
    facilities=FACILITIES,
    divisions=DIVISIONS,
    departments=DEPARTMENTS,
    sections=SECTIONS,
    positions=POSITIONS,
    cost_centers=COST_CENTERS,
)


def seed() -> None:
    seed_organization(DATASET)
