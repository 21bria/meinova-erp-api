"""
Keputusan pemetaan workbook → master ERP yang **sudah ada**.

Semua fungsi di sini murni: masukannya baris workbook, keluarannya kode
master ERP. Tidak ada kueri, tidak ada tulisan. Perencana yang memeriksa
kode-kode ini benar-benar ada di tenant.

Aturan yang mengikat (DEMO-0 + persetujuan DEMO-1A):

* Tidak ada JobLevel baru. Executive/Statutory/Non-Staff dipetakan ke
  tingkat yang ada; label aslinya hanya disimpan sebagai rujukan.
* Locality **tidak** dipetakan ke apa pun — bukan EXPAT, bukan
  EmployeeGroup. Ia rujukan tampilan.
* Position ≠ Role. Tidak ada role yang diturunkan dari nama jabatan;
  role hanya dari lembar 12, dan hanya kode role yang sudah ada.
* Kode roster workbook (RST-6-2/RST-8-2) adalah **penugasan yang
  diinginkan**, dipetakan ke policy kanonik yang sudah ada dengan
  semantiknya sendiri (42/14, 56/14). Tidak didefinisikan ulang jadi
  6 hari / 2 hari.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from apps.administration.seeds.organization import make_code

from .constants import COMPANY_EMAIL_DOMAIN, EMPLOYEE_NOTE_PREFIX, USERNAME_PREFIX
from .workbook import EmployeeRow, Workbook


# ======================================================================
# Company / lokasi / unit
# ======================================================================

#: Jenis company dari lembar 01 → `CompanyType` yang ada (COMP/SUB).
COMPANY_TYPE = {
    "Parent / Group": "COMP",
    "Operating Company": "SUB",
}

#: Nama lokasi workbook → (kode, nama, LocationType). Kode dan geografi
#: mengikuti lokasi sejenis di dataset peragaan yang ada
#: (`seeds/demo/organization.py`) supaya tidak ada kode provinsi/kota
#: yang dikarang.
LOCATIONS = {
    "Jakarta HO": ("JKT-HO", "Jakarta Head Office", "HO"),
    "Sagea Mine Site": ("SAGEA-MINE", "Sagea Mine Site", "MINE"),
}

#: Geografi lokasi dataset. DEMO-1F: nilainya disalin **persis** dari lokasi
#: MMR sejenis di `apps/administration/seeds/demo/organization.py` (sumber
#: statis seed lama) supaya DEMOERP tidak lagi mengimpor dataset lama.
#: Nilai tidak diubah — kode provinsi/kota non-Kemendagri SAGEA-MINE adalah
#: utang teknis yang sudah ada, bukan dirancang ulang di sini.
LOCATION_GEOGRAPHY = {
    "JKT-HO": {
        "country": "ID", "province": "DKI", "city": "JKT",
        "address": "Jl. Jenderal Sudirman Kav. 21, Jakarta Selatan", "postal_code": "12920",
    },
    "SAGEA-MINE": {
        "country": "ID", "province": "MALUKU-UTARA", "city": "TERNATE",
        "address": "Blok Sagea, Halmahera Tengah", "postal_code": "",
    },
}

#: Division mengikuti konvensi dataset peragaan: kantor = CORP, site = OPS.
DIVISION_BY_LOCATION_TYPE = {
    "HO": ("CORP", "Corporate"),
    "MINE": ("OPS", "Operations"),
}

#: Unit lembar 02 yang **tidak** dibuat, beserta alasannya.
EXCLUDED_UNITS = {
    ("MMN", "PLANT"): (
        "Tidak ada pegawai di lembar 03, dan 'Plant Manager' termasuk "
        "asumsi lama yang diminta tidak dihidupkan kembali."
    ),
}

#: (company, departemen di lembar 03, lokasi) → kode unit lembar 02.
#: Lembar 03 memakai kode pendek (FIN/HR/OPS); lembar 02 memakai kode
#: unit (FIN-HO/HR-HO/IND-OPS). Kode lembar 02 yang jadi kode Department.
DEPARTMENT_OF = {
    ("GRP", "BOD", "Jakarta HO"): "BOD",
    ("GRP", "LEGAL", "Jakarta HO"): "LEGAL",
    ("MMN", "HR", "Jakarta HO"): "HR-HO",
    ("MMN", "HR", "Sagea Mine Site"): "SITE-HR",
    ("MMN", "FIN", "Jakarta HO"): "FIN-HO",
    ("MMN", "PROC", "Jakarta HO"): "PROC",
    ("MMN", "OPS", "Sagea Mine Site"): "OPS",
    ("MMN", "MINING", "Sagea Mine Site"): "MINING",
    ("MMN", "HSE", "Sagea Mine Site"): "HSE",
    ("MIN", "OPS", "Jakarta HO"): "IND-OPS",
    ("MIN", "FIN", "Jakarta HO"): "IND-FIN",
    ("MIN", "HR", "Jakarta HO"): "IND-HR",
}


#: Nama company yang ditetapkan persetujuan B1, menimpa nama lembar 01
#: ("Meinova" → "Meinova Group"). Company lain memakai nama workbook.
COMPANY_NAME = {"GRP": "Meinova Group"}


def company_name(row) -> str:
    return COMPANY_NAME.get(row.code, row.name)


def company_email(code: str) -> str:
    """Penanda kepemilikan Company (lihat `constants`)."""
    return f"{code.lower()}@{COMPANY_EMAIL_DOMAIN}"


def location_code(workbook_location: str) -> str:
    return LOCATIONS[workbook_location][0]


def department_code(row: EmployeeRow) -> str:
    return DEPARTMENT_OF[(row.company, row.department, row.location)]


# ======================================================================
# Jabatan & tingkat
# ======================================================================

#: Level workbook → JobLevel yang ada. `None` = ditentukan per jabatan.
#:
#: **Supervisor → SUP, bukan SPV.** Di master tenant ini SUP bernama
#: "Supervisor" dan SPV bernama "Superintendent"; jabatan supervisor
#: yang sudah ada (Plant Supervisor, foreman) memakai SUP. ERP menang.
LEVEL = {
    "Executive": None,
    "Statutory": "MGR",
    "Manager": "MGR",
    "Supervisor": "SUP",
    "Staff": "STAFF",
    "Non-Staff": "STAFF",
}

#: Level workbook yang tidak punya padanan persis. Labelnya tetap
#: terbaca di catatan pegawai sebagai rujukan, tidak jadi master baru.
LEVEL_REFERENCE_ONLY = {"Executive", "Statutory", "Non-Staff"}


def job_level(row: EmployeeRow) -> str:
    mapped = LEVEL[row.level]

    if mapped is not None:
        return mapped

    # Executive: Group CEO = direksi, GM = General Manager.
    return "DIR" if "CEO" in row.position.upper() else "GM"


#: JobCategory yang ada: OPS, TECH, ADMIN, SUPPORT, MGMT.
TECHNICAL_POSITIONS = {
    "Surveyor", "Survey Helper", "Grade Control", "Sampling Crew",
    "Sampling Helper",
}
OPERATIONS_POSITIONS = {
    "Mine Supervisor", "Production Checker", "Hauling Checker",
    "Operations Staff", "Operations Officer",
}
SUPPORT_DEPARTMENTS = {"HSE"}


def job_category(row: EmployeeRow) -> str:
    if job_level(row) in ("DIR", "GM", "MGR"):
        return "MGMT"

    if row.position in TECHNICAL_POSITIONS:
        return "TECH"

    if row.position in OPERATIONS_POSITIONS:
        return "OPS"

    if row.department in SUPPORT_DEPARTMENTS:
        return "SUPPORT"

    return "ADMIN"


def position_code(row: EmployeeRow) -> str:
    return f"{row.company}-{make_code(row.position)}"[:50]


def is_manager_position(row: EmployeeRow) -> bool:
    return job_level(row) in ("DIR", "GM", "MGR", "SUP")


# ======================================================================
# Kepegawaian
# ======================================================================

EMPLOYMENT_TYPE = {"Permanent": "PERM", "Contract": "CONT"}
EMPLOYMENT_STATUS = {"Active": "ACTIVE"}

#: Kontrak berdurasi (PKWT) — satu-satunya jenis kontrak yang cocok
#: untuk kontrak kerja waktu tertentu di workbook.
CONTRACT_TYPE = "PKWT"


def employee_group(row: EmployeeRow) -> str:
    """
    Kelompok pegawai mengikuti konvensi pemeran HR-DEMO yang ada —
    **tidak** dari Locality:

    * direksi → BOARD (seperti BOD001/BOD002)
    * GM → EXECUTIVE (seperti HO009/SGA011)
    * manajer (termasuk KTT) → MANAGEMENT
    * selebihnya kantor → OFFICE, site → FIELD
    """
    level = job_level(row)

    if level == "DIR":
        return "BOARD"

    if level == "GM":
        return "EXECUTIVE"

    if level == "MGR":
        return "MANAGEMENT"

    return "OFFICE" if row.ho_site == "HO" else "FIELD"


def employee_note(row: EmployeeRow) -> str:
    """
    Penanda kepemilikan + label workbook yang **tidak** punya master.
    Rujukan tampilan saja; tidak dibaca mesin mana pun.
    """
    return (
        f"{EMPLOYEE_NOTE_PREFIX}{row.employee_id}] "
        f"Workbook reference — Level: {row.level}; Locality: {row.locality}; "
        f"HO/Site: {row.ho_site}."
    )


def username(row: EmployeeRow) -> str:
    return f"{USERNAME_PREFIX}{row.first_name.lower()}"


#: Alamat akun peragaan (DEMO-1E): subaddress kotak masuk peragaan yang sama
#: dengan akun HR-DEMO (`apps.hr.seeds.demo_accounts.demo_address`), satu alias
#: per pegawai, dibaca manusia saat login peragaan manajemen. Peran yang sama
#: di company berbeda diberi akhiran company; peran kembar di site diberi
#: nomor urut menurut nomor pegawai. Alias ditulis tangan — bukan diturunkan —
#: supaya pergantian jabatan di workbook tidak diam-diam memindahkan kotak masuk.
#:
#: `User.email` = `Employee.work_email` = alamat ini (kontrak DEMOERP sejak
#: DEMO-1B; ERP tidak menyinkronkan keduanya, notifikasi membaca `User.email`
#: lebih dulu). Login tetap lewat username `demoerp.<nama>`.
LOGIN_ALIASES = {
    "EMP001": "ceo",                     # GRP Group CEO
    "EMP002": "gmhr",                    # MMN HR GM
    "EMP003": "financemanager.mmn",      # MMN Finance Manager
    "EMP004": "gmlegal",                 # GRP Legal GM
    "EMP005": "gmops",                   # MMN GM Operations
    "EMP006": "ktt",                     # MMN KTT (Kepala Teknik Tambang)
    "EMP007": "miningmanager",           # MMN Mining Manager
    "EMP008": "supervisor",              # MMN Mine Supervisor
    "EMP009": "productionchecker.1",     # MMN Production Checker
    "EMP010": "haulingchecker.1",        # MMN Hauling Checker
    "EMP011": "surveyor",                # MMN Surveyor
    "EMP012": "surveyhelper.1",          # MMN Survey Helper
    "EMP013": "hrsupervisor.site",       # MMN HR Site Supervisor
    "EMP014": "hrstaff.site",            # MMN HR Site Staff
    "EMP015": "hsemanager",              # MMN HSE Manager
    "EMP016": "safetyofficer",           # MMN Safety Officer
    "EMP017": "hrofficer.mmn",           # MMN HR Officer (HO)
    "EMP018": "procurementmanager.mmn",  # MMN Procurement Manager
    "EMP019": "industrialmanager.min",   # MIN Industrial Manager
    "EMP020": "hrmanager.min",           # MIN HR Manager
    "EMP021": "opsstaff.min",            # MIN Operations Staff
    "EMP022": "financestaff.min",        # MIN Finance Staff
    "EMP023": "gradecontrol",            # MMN Grade Control
    "EMP024": "samplingcrew",            # MMN Sampling Crew
    "EMP025": "productionchecker.2",     # MMN Production Checker
    "EMP026": "haulingchecker.2",        # MMN Hauling Checker
    "EMP027": "surveyhelper.2",          # MMN Survey Helper
    "EMP028": "samplinghelper",          # MMN Sampling Helper
    "EMP029": "financeofficer.mmn",      # MMN Finance Officer
    "EMP030": "financestaff.mmn",        # MMN Finance Staff
    "EMP031": "hrstaff.mmn",             # MMN HR Staff (HO)
    "EMP032": "procurementofficer.mmn",  # MMN Procurement Officer
    "EMP033": "procurementstaff.mmn",    # MMN Procurement Staff
    "EMP034": "legalofficer.grp",        # GRP Legal Officer
    "EMP035": "legalstaff.grp",          # GRP Legal Staff
    "EMP036": "opsofficer.min",          # MIN Operations Officer
    "EMP037": "hrofficer.min",           # MIN HR Officer
    "EMP038": "financemanager.min",      # MIN Finance Manager
    "EMP039": "financeofficer.min",      # MIN Finance Officer
    "EMP040": "hrmanager.mmn",           # MMN HR Manager
}


def user_email(row: EmployeeRow) -> str:
    """Alamat akun & email kerja pegawai dataset (`LOGIN_ALIASES`)."""
    from apps.hr.seeds.demo_accounts import demo_address

    return demo_address(LOGIN_ALIASES[row.employee_id])


# ======================================================================
# Kalender / roster (H7)
# ======================================================================


@dataclass(frozen=True)
class ScheduleMapping:
    """Penugasan jadwal kanonik untuk satu kode workbook."""

    workbook_code: str
    roster_policy: str | None
    working_calendar: str | None
    shift: str | None
    semantics: str
    note: str


#: Kode workbook → master kanonik. Kalender & shift = master GLOBAL yang
#: sudah ada; `roster_policy` = kode policy MMN milik dataset
#: (`roster_policy.POLICIES`, DEMO-1F), diresolusi company + kode.
SCHEDULE = {
    "CAL-HO": ScheduleMapping(
        "CAL-HO",
        roster_policy=None,
        working_calendar="OFFICE-2026",
        shift="OFFICE-10",
        semantics="Senin–Jumat (kalender GLOBAL), shift kantor 10:00–18:00",
        note=(
            "Workbook menyebut 08:00–17:00. Shift OFFICE 08:00–17:00 sudah "
            "dihapus di tenant ini; pemeran HO memakai OFFICE-10."
        ),
    ),
    "EXEC": ScheduleMapping(
        "EXEC",
        roster_policy=None,
        working_calendar="OFFICE-2026",
        shift="OFFICE-10",
        semantics="Senin–Jumat (kalender GLOBAL); 'flexible' tidak dibaca mesin",
        note=(
            "Tidak ada konsep jam kerja fleksibel per pegawai. Direksi "
            "(BOARD) memang tidak berlaku presensi; GM/KTT tetap berjadwal."
        ),
    ),
    "RST-6-2": ScheduleMapping(
        "RST-6-2",
        roster_policy="ROSTER-SAGEA-MINE-6-2-2-SHIFT",
        working_calendar=None,
        shift=None,
        semantics="42 hari kerja / 14 hari off, rotasi SHIFT-1/3/2 per 7 hari",
        note=(
            "Workbook membacanya 6 hari/2 hari siang-malam 12 jam. ERP "
            "mendefinisikan 6-2 sebagai 42/14 dan semantik itu dipertahankan."
        ),
    ),
    "RST-8-2": ScheduleMapping(
        "RST-8-2",
        roster_policy="ROSTER-SAGEA MINE-8-2",
        working_calendar=None,
        shift=None,
        semantics="56 hari kerja / 14 hari off, rotasi SHIFT-1/3/2 per 7 hari",
        note=(
            "Workbook membacanya 8 hari/2 hari. ERP mendefinisikan 8-2 "
            "sebagai 56/14. Kode policy kanonik memang mengandung spasi."
        ),
    ),
}


# ======================================================================
# Cuti / izin
# ======================================================================

#: Jenis di lembar 07 → model + kode ERP. Permit/Ijin **bukan** jenis
#: cuti: ia `AttendancePermission` bertipe FULL_DAY.
LEAVE_KIND = {
    "Annual Leave": ("leave", "ANNUAL"),
    "Sick Leave": ("leave", "SICK"),
    "Permit / Ijin": ("attendance_permission", "full_day"),
}

#: Status workbook → status ERP beserta jalan kanoniknya.
LEAVE_STATUS = {
    "APPROVED": ("approved", "create → submit → approver nyata menyetujui"),
    "PENDING": ("submitted", "create → submit, dibiarkan menunggu"),
    "REJECTED": ("rejected", "create → submit → approver nyata menolak"),
    "RECORDED": ("recorded", "POST /api/hr/leaves/record/ oleh pemegang hr.record_employeeleave"),
}


# ======================================================================
# Role & cakupan (lembar 12)
# ======================================================================


@dataclass(frozen=True)
class RoleGrant:
    role: str
    mode: str                       # unrestricted | placement | explicit
    level: str | None = None        # untuk placement
    authorities: tuple[tuple[str, str | None], ...] = ()   # (resource_type, kunci)
    note: str = ""


#: Setiap akun dataset ini memegang EMPLOYEE (own) — menutup celah
#: "akun tanpa penugasan membaca layar tak berpenjaga tanpa batas".
#: Bentuknya persis bawaan `seed_security_roles`: `("own", None)`.
BASE_GRANT = RoleGrant("EMPLOYEE", "explicit", authorities=(("own", None),))


def scope_grants(workbook: Workbook) -> dict[str, list[RoleGrant]]:
    """
    Lembar 12 → role **yang sudah ada**. Kunci authority berbentuk kode
    bisnis (`company:MMN`, `location:MMN/SAGEA-MINE`,
    `department:MMN/MINING`); perencana menerjemahkannya ke PK setelah
    master dibuat, dan melaporkannya kalau belum ada.
    """
    table = {
        "MULTI_COMPANY": lambda r: RoleGrant(
            "HR-MANAGER",
            "explicit",
            authorities=tuple(("company", code) for code in r.company_scope),
            note="Multi-company lewat authority explicit (mekanisme yang ada).",
        ),
        "COMPANY": lambda r: (
            RoleGrant(
                "FINANCE-MANAGER",
                "placement",
                level="company",
                note="Bawaan seed FINANCE-MANAGER: placement@company.",
            )
            if "Finance" in r.role_position
            else RoleGrant(
                "HR-ADMIN" if "Officer" in r.role_position else "HR-MANAGER",
                "explicit",
                authorities=tuple(("company", code) for code in r.company_scope)
                + (
                    (("location", f"{r.company_scope[0]}/{location_code(r.location_scope)}"),)
                    if r.location_scope in LOCATIONS
                    else ()
                ),
                note="Cakupan company (+lokasi bila lembar 12 menyebutnya).",
            )
        ),
        "LOCATION": lambda r: RoleGrant(
            "HR-ADMIN",
            "placement",
            level="location",
            note="Meja HR Admin site: placement@location.",
        ),
        "DEPARTMENT": lambda r: RoleGrant(
            "EXECUTIVE",
            "explicit",
            authorities=(
                ("company", r.company_scope[0]),
                ("department", f"{r.company_scope[0]}/MINING"),
            ),
            note=(
                "Lihat-saja. ADMIN-DEPARTMENT sengaja tidak dipakai: ia meja "
                "'Prepared by', bukan peran manajer."
            ),
        ),
        "TEAM": lambda r: None,
    }

    grants: dict[str, list[RoleGrant]] = {}

    for row in workbook.scopes:
        grant = table[row.scope_type](row)

        if grant is not None:
            grants.setdefault(row.employee_id, []).append(grant)

    return grants


#: Tipe cakupan lembar 12 yang tidak punya mekanisme — dilaporkan.
UNSUPPORTED_SCOPE_TYPES = {
    "TEAM": (
        "Tidak ada cakupan data bawahan/tim. Supervisor melihat dokumen "
        "timnya hanya sebagai approver, atau di layar ber-reporting_line."
    ),
}


# ======================================================================
# Pengganti skenario (B4)
# ======================================================================

#: Skenario yang ditolak mesin apa adanya, dipindah ke pegawai lain yang
#: memperagakan fitur yang sama lewat alur yang sama (unit, atasan, dan
#: tanggal sama). Ditetapkan dari hasil gladi DEMO-1B: EmployeeLeaveService
#: menolak keduanya karena saldo cuti tahunan 2026 = 0 — Join Date pegawai
#: kontrak = Contract Start 2026-04-01, belum 12 bulan (ANNUAL-STD).
SCENARIO_SUBSTITUTES = {
    "LV-001": (
        "EMP010",
        "EMP009 kontrak sejak 2026-06-01 → saldo cuti tahunan 0 (ANNUAL-STD 12 bulan); "
        "gladi DEMO-1C: EmployeeLeaveService menolak 4 hari. EMP010 (MMN MINING, Non-Staff "
        "site, RST-6-2, atasan EMP008, masuk 2025-01-01) memakai alur dan roster yang sama.",
    ),
    "LV-004": (
        "EMP036",
        "EMP021 kontrak sejak 2026-04-01 → saldo cuti tahunan 0 (ANNUAL-STD 12 bulan). "
        "EMP036 (MIN IND-OPS, tetap, atasan EMP019) memakai alur yang sama.",
    ),
    "LV-006": (
        "EMP029",
        "EMP030 kontrak sejak 2026-04-01 → saldo cuti tahunan 0 (ANNUAL-STD 12 bulan). "
        "EMP029 (MMN FIN-HO, tetap, atasan EMP003) memakai alur yang sama.",
    ),
}


def scenario_employee(row) -> str:
    """Pegawai yang benar-benar menjalankan skenario cuti/izin ini."""
    return SCENARIO_SUBSTITUTES.get(row.request_id, (row.employee_id, ""))[0]


# ======================================================================
# Matriks gaji peragaan (DEMO-1C)
# ======================================================================

#: Gaji pokok per tingkat. **Data bisnis peragaan**, bukan konfigurasi
#: mesin payroll. Jangkarnya enam gaji workbook (lembar 09) yang tetap
#: berlaku apa adanya untuk pemiliknya; tingkat tanpa jangkar diturunkan
#: dari rasio antartingkat pemeran HR-DEMO yang ada (rata-rata SUP ≈ 17,3
#: jt, MGR ≈ 42,8 jt, GM ≈ 68,5 jt → MGR/SUP ≈ 2,5; GM/MGR ≈ 1,6). Tidak
#: ada angka acak.
#:
#: `(tier, amount, basis)`; tier STAFF dipecah menurut label tanggung
#: jawab workbook (Non-Staff / Staff / Officer) karena tiga jangkarnya
#: memang berbeda di situ.
SALARY_MATRIX = {
    "DIR": (54_000_000, "GM × 1,5 — tidak ada jangkar direksi (BOD pemeran tanpa PayrollAssignment)"),
    "GM": (36_000_000, "MGR × 1,6 (rasio GM/MGR pemeran HR-DEMO)"),
    "MGR": (22_500_000, "SUP × 2,5 (rasio MGR/SUP pemeran HR-DEMO)"),
    "SUP": (9_000_000, "jangkar EMP013 HR Site Supervisor (workbook)"),
    "STAFF/Officer": (8_500_000, "jangkar EMP017 HR Officer (workbook)"),
    "STAFF/Staff": (8_000_000, "jangkar EMP030 Finance Staff (workbook)"),
    "STAFF/Non-Staff": (6_000_000, "jangkar EMP024 Sampling Crew (workbook)"),
}


def salary_tier(row: EmployeeRow) -> str:
    level = job_level(row)

    if level != "STAFF":
        return level

    if row.level == "Non-Staff":
        return "STAFF/Non-Staff"

    return "STAFF/Officer" if "Officer" in row.position else "STAFF/Staff"


def basic_salary(row: EmployeeRow, workbook: Workbook):
    """(gaji pokok, asal-usul). Gaji workbook menang untuk pemiliknya."""
    from decimal import Decimal

    for payroll in workbook.payroll:
        if payroll.employee_id == row.employee_id:
            return payroll.basic_salary, "workbook 09_Payroll_2M (sumber)"

    tier = salary_tier(row)
    amount, basis = SALARY_MATRIX[tier]

    return Decimal(amount), f"matriks {tier}: {basis}"


def overtime_eligible(row: EmployeeRow) -> bool:
    """
    Aturan DEMO-1B, tidak dilonggarkan: hanya pegawai site tingkat STAFF
    dan SUP (sama dengan pemeran HR-DEMO: FIELD/LOCAL/SUP berhak, manajer
    tidak). Kantor pusat dan eksekutif tidak berhak lembur.
    """
    return row.ho_site == "Site" and job_level(row) in ("STAFF", "SUP")


# ======================================================================
# Presensi pegawai etalase payroll (DEMO-1C)
# ======================================================================

#: Enam pegawai sumber payroll workbook. Presensinya hanya digerakkan
#: skenario yang disengaja — tidak ada undian mangkir acak.
SHOWCASE_EMPLOYEES = frozenset({"EMP009", "EMP013", "EMP017", "EMP021", "EMP024", "EMP030"})


def intentional_absences(workbook: Workbook) -> dict[tuple[str, str], int]:
    """Mangkir yang disebut workbook (lembar 08) untuk pegawai etalase."""
    return {
        (row.employee_id, row.period): row.absent
        for row in workbook.attendance
        if row.employee_id in SHOWCASE_EMPLOYEES and row.absent
    }


# ======================================================================
# Tanggal skenario (DEMO-1C)
# ======================================================================

#: Tanggal bisnis yang dipindah supaya skenario memperagakan sesuatu.
#: Mesin cuti, roster, dan kebijakan cuti tidak disentuh.
SCENARIO_DATES = {
    "LV-001": (
        date(2026, 9, 9),
        date(2026, 9, 12),
        "Tanggal workbook 15–18 Sep jatuh di field break roster EMP009 (42/14), "
        "jadi cuti bernilai 0 hari. Dipindah ke 9–12 Sep: empat hari kerja "
        "terjadwal berurutan di blok kerja yang sama (8 Sep hari pemulihan "
        "pergantian shift), masih September. Dijalankan pengganti EMP010 "
        "(roster dan siklus sama).",
    ),
}


def scenario_dates(row):
    """(mulai, selesai) yang benar-benar dipakai skenario ini."""
    override = SCENARIO_DATES.get(row.request_id)

    return (override[0], override[1]) if override else (row.start, row.end)
