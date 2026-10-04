"""
Data pegawai peragaan — **hanya master pegawai**, tanpa satu pun transaksi.

Bedanya dengan `demo_workforce.py`, dan itu yang menentukan kapan
masing-masing dipakai:

* `seed_demo_workforce` menyiapkan **panggung untuk dokumen** — sebelas
  orang secukupnya, langsung dengan crew roster dan dokumen rencananya,
  supaya seed cuti/TR/presensi punya sesuatu untuk dijalankan.
* `seed_demo_employees` (berkas ini) menyiapkan **tenant untuk diisi
  tangan**. Kartu pegawainya lengkap sampai rekening bank, keluarga,
  pendidikan, dan payroll; tapi cuti, saldo, roster, presensi, dan
  seluruh dokumen sengaja **kosong**. Itu keadaan yang dibutuhkan untuk
  menelusuri alur entry dari awal: buat pegawai → terbitkan saldo cuti →
  setup roster → ajukan cuti.

Karena itu berkas ini **tidak pernah** menulis `roster_crew`,
`roster_policy`, maupun `roster_cycle_start` — ketiganya justru yang
diisi dokumen Roster Setup, dan mengisinya di sini membuat layar yang
mau diuji berhenti menampilkan kandidat.

Tiga golongan, dan pemisahannya bukan kosmetik
----------------------------------------------
* `HO…`  — kantor pusat Jakarta. Tanpa roster, ikut kalender Senin–Jumat,
  hari cutinya dihitung dari `WorkCalendar`.
* `SGA…` — site Sagea, **Point of Hire** (didatangkan dari luar daerah).
  Merekalah yang punya blok kerja/off, tiket pulang, dan hari perjalanan
  yang berbeda-beda menurut kota asalnya.
* `LOK…` — site Sagea, **tenaga lokal**. Tinggal di sekitar site, jadi
  tidak punya POH, tidak punya hari perjalanan, dan tidak masuk roster.
  Golongan ini yang paling sering luput dari data uji, padahal di tambang
  jumlahnya justru terbesar — dan aturan yang benar untuk pegawai roster
  hampir selalu salah untuk mereka.

Nomor pegawainya sengaja berawalan `HO`/`SGA`/`LOK`, bukan meniru pola
klien (`KW`, `IP`, `KPB`, …): data uji harus bisa dibedakan sekilas, dan
tidak boleh bertabrakan saat berkas master klien diimpor.

Identitas `HO001`–`HO005` dan `SGA001`–`SGA006` **sengaja dibuat sama
persis** dengan `demo_workforce` — nomor, nama, jabatan, dan role-nya.
Seed dokumen lain (`seed_demo_workflow`, `seed_demo_site_travel`,
`seed_demo_hr_records`) menyebut nomor-nomor itu apa adanya; kalau
identitasnya bergeser, dokumen yang dihasilkannya mendarat di orang yang
salah tanpa satu pun pesan.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.accounts.models import Role
from apps.accounts.seeds.role_authority import authority_entries
from apps.accounts.services.role_assignment import assign_roles
from apps.administration.models import (
    Bank,
    Company,
    CostCenter,
    Currency,
    JobGrade,
    Location,
    Position,
    RosterTravelDay,
    Shift,
    Village,
    WorkCalendar,
    WorkSchedule,
)
from apps.administration.models.references.hr import (
    BloodType,
    CertificateType,
    ContractType,
    Degree,
    DocumentType,
    Education,
    EmployeeGroup,
    EmploymentStatus,
    EmploymentType,
    FamilyRelationship,
    Gender,
    MaritalStatus,
    Nationality,
    ProbationType,
    Religion,
    StudyField,
    TrainingCategory,
    TrainingProvider,
)
from apps.hr.models import (
    Employee,
    EmployeeBankAccount,
    EmployeeCertificate,
    EmployeeDocument,
    EmployeeEducation,
    EmployeeExperience,
    EmployeeFamily,
    EmployeeMedicalEvent,
    EmployeeTraining,
    EmploymentAssignment,
    OrganizationAssignment,
    PayrollAssignment,
)
from apps.core.services.demo_password import demo_password
from apps.hr.seeds.demo_accounts import demo_email
from apps.payroll.models import PayrollGroup, TaxStatus


# Tanggal acuan. Dipatok, bukan `today()`: masa kerja menentukan jatah
# cuti, dan data uji yang jawabannya berubah tiap hari tidak bisa
# dipakai membandingkan apa pun.
TODAY = date(2026, 8, 9)


COMPANY_CODE = "MMR"
HO_LOCATION_CODE = "JKT-HO"
SITE_LOCATION_CODE = "SAGEA-MINE"

OFFICE_SHIFT_CODE = "OFFICE-10"
SITE_SHIFT_CODE = "SITE"

OFFICE_SCHEDULE_CODE = "REG5"


# ======================================================================
# Alamat
#
# Dikunci lewat **kode wilayah kelurahan** (`Village.aid`), bukan lewat
# nama. Nama wilayah berulang di seluruh Indonesia — ada puluhan
# "Sukamaju" — dan pencocokan nama tetap menghasilkan baris yang
# terlihat masuk akal; itu yang membuatnya berbahaya.
#
# Kecamatan, Kabupaten/Kota, dan Provinsi **diturunkan dari kelurahannya**,
# tidak ditulis ulang. `Employee.clean()` menolak rantai yang tidak
# konsisten, dan menuliskan keempatnya tangan berarti empat kesempatan
# salah ketik untuk satu alamat.
#
# (aid kelurahan, alamat detail, kode pos)
# ======================================================================

ADDRESSES = {
    "jaksel":   ("31.74.01.1001", "Jl. Tebet Timur Dalam III No. 12, RT 004/RW 002", "12820"),
    "jaktim":   ("31.75.02.1001", "Jl. Balai Pustaka Timur No. 8, RT 007/RW 003", "13220"),
    "bekasi":   ("32.75.02.1001", "Jl. Bintara Jaya IX No. 45, RT 002/RW 009", "17136"),
    "depok":    ("32.76.02.1007", "Jl. Radar Auri No. 27, RT 003/RW 006", "16454"),
    "tangsel":  ("36.74.02.1001", "Jl. Alam Sutera Boulevard No. 3, RT 001/RW 004", "15325"),
    "bandung":  ("32.73.01.1001", "Jl. Gegerkalong Girang No. 18, RT 002/RW 005", "40153"),
    "yogya":    ("34.71.01.1001", "Jl. Magelang KM 3 No. 21, RT 010/RW 003", "55241"),
    "makassar": ("73.71.01.1001", "Jl. Rajawali I No. 9, RT 002/RW 001", "90125"),
    "banggai":  ("72.01.02.1014", "Jl. Trans Sulawesi No. 14", "94711"),
    "sorong":   ("96.71.02.1008", "Jl. Klamono KM 12 No. 6", "98416"),
    "ternate":  ("82.71.02.1001", "Jl. Raya Sasa No. 22, RT 003/RW 002", "97716"),
    "sagea":    ("82.02.04.2002", "Desa Sagea, RT 002/RW 001", "97853"),
    "weda":     ("82.02.01.2004", "Desa Nusliko, RT 001/RW 001", "97853"),
    "gebe":     ("82.02.03.2002", "Desa Kacepi, RT 002/RW 001", "97854"),
    "kobe":     ("82.02.07.2004", "Desa Kobe, RT 001/RW 002", "97853"),
    "lelilef":  ("82.02.07.2002", "Desa Lililef Sawai, RT 003/RW 001", "97853"),
}


# Nama kota Point of Hire, **dicocokkan ke baris `RosterTravelDay`**
# milik policy site — bukan ke master City lewat nama.
#
# Kedua daftar itu bisa berbeda dan memang pernah berbeda: import
# geografi menulis "Kota Makassar" sementara seed policy menulis
# "Makassar" sebagai baris tersendiri. POH yang menunjuk baris yang
# salah tetap tersimpan dan tetap terlihat benar di layar — yang hilang
# cuma hari perjalanannya, diam-diam jatuh ke nol.
POH_MAKASSAR = "Makassar"
POH_YOGYA = "Yogyakarta"
POH_BANDUNG = "Bandung"
POH_BANGGAI = "Luwuk Banggai"
POH_SORONG = "Sorong"
POH_TERNATE = "Ternate"


@dataclass(frozen=True)
class Person:
    """Satu baris cast. Urutan kolomnya mengikuti urutan tab di layar."""

    number: str
    name: str
    position: str                      # kode Position milik seed organisasi
    join: date
    birth: date
    gender: str                        # kode Gender
    marital: str                       # kode MaritalStatus
    religion: str
    blood: str
    group: str                         # kode EmployeeGroup
    status: str                        # kode EmploymentStatus
    employment_type: str               # kode EmploymentType
    address: str                       # kunci ADDRESSES
    education: tuple                   # (level, degree, study, institusi, tahun, ipk)
    salary: int                        # basic salary bulanan (IDR)
    poh: str | None = None             # nama kota Point of Hire (SGA saja)
    reports_to: str | None = None
    username: str | None = None
    roles: tuple[str, ...] = ()
    probation_end: int | None = None   # offset hari dari TODAY
    # Offset hari dari TODAY. Lima pegawai berkontrak di cast ini
    # sengaja menempati **lima bucket Contract Expiry yang berbeda**
    # (Expired / ≤30 / 31–60 / 61–90 / >90), supaya layar
    # Reports → HR → Contract Expiry punya satu contoh per kartu KPI
    # tanpa data tambahan. Menggesernya menghilangkan satu bucket dari
    # peragaan — lihat `docs/claude/reports.md`.
    contract_end: int | None = None
    note: str = ""
    experience: tuple | None = None    # (perusahaan, jabatan, mulai, selesai)
    certificates: tuple = ()           # (kode tipe, nama, tahun terbit, masa berlaku th)
    trainings: tuple = ()              # (kode kategori, nama, tahun, wajib?)


# ======================================================================
# KANTOR PUSAT JAKARTA
#
# `HO006` (General Manager) adalah ujung rantainya, dan itu bukan
# hiasan: step "Atasan Langsung" pada alur cuti tidak punya cadangan,
# jadi manajer yang tidak punya atasan tidak bisa mengajukan cuti untuk
# dirinya sendiri — dan gagalnya baru terbaca saat orangnya mencoba.
# ======================================================================

HEAD_OFFICE = [
    Person(
        number="HO006", name="Adrian Mahendra", position="MMR-GM",
        join=date(2017, 2, 1), birth=date(1978, 5, 19),
        gender="M", marital="M", religion="ISLAM", blood="O",
        group="MANAGEMENT", status="ACTIVE", employment_type="PERM",
        address="tangsel",
        education=("S2", "MT", "MINING", "Institut Teknologi Bandung", 2005, "3.62"),
        salary=95_000_000,
        reports_to=None, username="demo.gm", roles=("EMPLOYEE",),
        note="puncak rantai kantor pusat — atasan HR Manager & Finance Manager",
        experience=("PT Nusantara Mining", "Operation Manager", date(2009, 3, 1), date(2017, 1, 31)),
    ),
    Person(
        number="HO001", name="Sarah Wibowo", position="MMR-HRM",
        join=date(2019, 1, 7), birth=date(1985, 3, 12),
        gender="F", marital="M", religion="CATHOLIC", blood="A",
        group="MANAGEMENT", status="ACTIVE", employment_type="PERM",
        address="jaksel",
        education=("S2", None, "MANAGEMENT", "Universitas Indonesia", 2011, "3.71"),
        salary=52_000_000,
        reports_to="HO006", username="demo.hrmanager",
        roles=("HR-MANAGER", "WORKFLOW-ADMIN"),
        note="HR-MANAGER kantor pusat — meja #3 alur cuti HO",
        experience=("PT Sinar Abadi", "HR Supervisor", date(2012, 2, 1), date(2018, 12, 31)),
    ),
    Person(
        number="HO002", name="Hesti Rahayu", position="MMR-HRO",
        join=date(2021, 6, 1), birth=date(1992, 8, 14),
        gender="F", marital="S", religion="ISLAM", blood="B",
        group="OFFICE", status="ACTIVE", employment_type="PERM",
        address="depok",
        education=("S1", "SE", "MANAGEMENT", "Universitas Padjadjaran", 2015, "3.42"),
        salary=11_500_000,
        reports_to="HO001", username="demo.hradmin", roles=("HR-ADMIN",),
        note="HR-ADMIN kantor pusat — cadangan meja HR Manager alur cuti HO",
    ),
    Person(
        number="HO004", name="Clara Wijaya", position="MMR-HRGA",
        join=date(2026, 3, 2), birth=date(2000, 1, 8),
        gender="F", marital="S", religion="PROTESTANT", blood="O",
        group="OFFICE", status="PROBATION", employment_type="CONT",
        address="jaktim",
        education=("S1", "SE", "MANAGEMENT", "Universitas Trisakti", 2023, "3.29"),
        salary=8_500_000,
        reports_to="HO001", username="demo.hrga", roles=("HRGA",),
        probation_end=5, contract_end=40,
        note="HRGA — meja terakhir alur site (terbitkan tiket); probation H-5",
    ),
    Person(
        number="HO005", name="Farah Anindita", position="MMR-FINM",
        join=date(2018, 4, 16), birth=date(1983, 6, 21),
        gender="F", marital="M", religion="ISLAM", blood="AB",
        group="MANAGEMENT", status="ACTIVE", employment_type="PERM",
        address="bekasi",
        education=("S2", None, "ACCOUNTING", "Universitas Gadjah Mada", 2010, "3.80"),
        salary=48_000_000,
        reports_to="HO006", username="demo.homanager", roles=("EMPLOYEE",),
        note="atasan langsung HO003/HO007 — meja #1 alur cuti HO",
        experience=("KAP Wijaya & Rekan", "Senior Auditor", date(2008, 7, 1), date(2018, 4, 15)),
    ),
    Person(
        number="HO003", name="Bimo Nugroho", position="MMR-FINS",
        join=date(2025, 8, 15), birth=date(1998, 11, 30),
        gender="M", marital="S", religion="ISLAM", blood="B",
        group="OFFICE", status="ACTIVE", employment_type="PERM",
        address="jaksel",
        education=("S1", "SE", "ACCOUNTING", "Universitas Brawijaya", 2021, "3.36"),
        salary=9_800_000,
        reports_to="HO005", username="demo.hostaff", roles=("EMPLOYEE",),
        note="pengaju cuti HO — berhak 15 Ags 2026, jatah 2026 prorata",
    ),
    Person(
        number="HO007", name="Rangga Pratomo", position="MMR-ACCS",
        join=date(2023, 9, 11), birth=date(1996, 4, 25),
        gender="M", marital="M", religion="ISLAM", blood="A",
        group="OFFICE", status="ACTIVE", employment_type="PERM",
        address="bekasi",
        education=("S1", "SE", "ACCOUNTING", "Universitas Diponegoro", 2019, "3.48"),
        salary=10_200_000,
        reports_to="HO005", username="demo.accstaff", roles=("EMPLOYEE",),
        note="pegawai kantor dengan tanggungan — PTKP K/1",
    ),
    Person(
        number="HO008", name="Yulia Kartika", position="MMR-GAS",
        join=date(2024, 1, 15), birth=date(1995, 9, 7),
        gender="F", marital="D", religion="ISLAM", blood="O",
        group="OFFICE", status="ACTIVE", employment_type="PERM",
        address="depok",
        education=("D3", "AMD", "MANAGEMENT", "Politeknik Negeri Jakarta", 2016, "3.18"),
        salary=8_900_000,
        reports_to="HO001", username="demo.gastaff", roles=("EMPLOYEE",),
        note="status kawin Cerai — menguji PTKP TK/1 dan kolom keluarga",
    ),
]


# ======================================================================
# SITE SAGEA — POINT OF HIRE
#
# Didatangkan dari luar daerah, jadi merekalah yang punya blok kerja/off,
# tiket pulang, dan hari perjalanan. `point_of_hire` diisi di sini karena
# itu properti **pegawainya** (dari mana ia direkrut), bukan properti
# dokumen roster — yang diisi lewat Roster Setup nanti cuma polanya dan
# tanggal mulai siklusnya.
#
# Lima meja pertama alur site ada di golongan ini, jadi dokumen site
# tidak menyeberang ke Jakarta sampai tiketnya benar-benar dibeli.
# ======================================================================

SITE_POH = [
    Person(
        number="SGA001", name="Rinaldo Saputra", position="MMR-SSPV",
        join=date(2020, 2, 3), birth=date(1988, 9, 2),
        gender="M", marital="M", religion="ISLAM", blood="O",
        group="MANAGEMENT", status="ACTIVE", employment_type="PERM",
        address="makassar", poh=POH_MAKASSAR,
        education=("S1", "ST", "MINING", "Institut Teknologi Bandung", 2012, "3.28"),
        salary=42_000_000,
        # Melapor ke General Manager di kantor pusat, bukan ke sesama
        # meja site. Versi sebelumnya membuat Site Superintendent dan
        # Site HR Manager saling melapor — lingkaran yang membuat
        # "atasan langsung siapa" tidak punya jawaban untuk keduanya.
        reports_to="HO006", username="demo.sitespv", roles=("EMPLOYEE",),
        note="Project Manager site (is_manager) — atasan seluruh meja site",
        certificates=(("BNSP", "Pengawas Operasional Madya (POM)", 2021, 5),),
        trainings=(("MINE_SAFE", "Mine Safety Leadership", 2024, True),),
    ),
    Person(
        number="SGA004", name="Citra Halimah", position="MMR-SHRM",
        join=date(2021, 11, 1), birth=date(1990, 12, 5),
        gender="F", marital="M", religion="ISLAM", blood="A",
        group="MANAGEMENT", status="ACTIVE", employment_type="PERM",
        address="yogya", poh=POH_YOGYA,
        education=("S1", "SE", "MANAGEMENT", "Universitas Hasanuddin", 2014, "3.51"),
        salary=33_000_000,
        reports_to="SGA001", username="demo.sitehrmanager", roles=("HR-MANAGER",),
        note="HR-MANAGER site — meja #4 alur site",
        certificates=(("BNSP", "Sertifikasi Manajemen SDM", 2022, 3),),
    ),
    Person(
        number="SGA005", name="Dedi Kurniawan", position="MMR-KTT",
        join=date(2024, 4, 22), birth=date(1996, 2, 29),
        gender="M", marital="M", religion="ISLAM", blood="B",
        group="MANAGEMENT", status="ACTIVE", employment_type="PERM",
        address="makassar", poh=POH_MAKASSAR,
        education=("S2", "MT", "MINING", "Institut Teknologi Bandung", 2016, "3.66"),
        salary=38_000_000,
        reports_to="SGA001", username="demo.ktt", roles=("KTT",),
        note="KTT — meja #5 alur site; lahir 29 Feb (menguji pergeseran ulang tahun)",
        certificates=(("BNSP", "Kepala Teknik Tambang (POU)", 2023, 5),),
    ),
    Person(
        number="SGA006", name="Eko Prasetyo", position="MMR-SHRO",
        join=date(2026, 7, 1), birth=date(2001, 7, 23),
        gender="M", marital="S", religion="ISLAM", blood="O",
        group="FIELD", status="PROBATION", employment_type="CONT",
        address="bandung", poh=POH_BANDUNG,
        education=("D3", "AMD", "MANAGEMENT", "Politeknik Negeri Bandung", 2022, "3.11"),
        salary=9_200_000,
        reports_to="SGA004", username="demo.sitehradmin", roles=("HR-ADMIN",),
        probation_end=12, contract_end=75,
        note="HR-ADMIN site — meja #2 alur site; jatah 2026 nol, 2027 prorata",
    ),
    Person(
        number="SGA003", name="Bayu Prakoso", position="MMR-SADM",
        join=date(2025, 8, 15), birth=date(1999, 4, 17),
        gender="M", marital="S", religion="ISLAM", blood="B",
        group="FIELD", status="ACTIVE", employment_type="CONT",
        address="bandung", poh=POH_BANDUNG,
        education=("D3", "AMD", "MANAGEMENT", "Politeknik Negeri Ambon", 2021, "3.05"),
        salary=8_400_000,
        reports_to="SGA001", username="demo.siteadmin", roles=("ADMIN-SECTION",),
        contract_end=9,
        note="ADMIN-SECTION (section Site Operations) — meja #1 alur site; kontrak H-9",
    ),
    Person(
        number="SGA002", name="Ahmad Sudrajat", position="MMR-GCFRM",
        join=date(2022, 5, 9), birth=date(1994, 8, 12),
        gender="M", marital="M", religion="ISLAM", blood="A",
        group="FIELD", status="ACTIVE", employment_type="PERM",
        address="banggai", poh=POH_BANGGAI,
        education=("S1", "ST", "GEOLOGY", "UPN Veteran Yogyakarta", 2018, "3.15"),
        salary=16_500_000,
        reports_to="SGA001", username="demo.sitestaff", roles=("EMPLOYEE",),
        note="pengaju cuti/TR site — POH Luwuk Banggai (hari perjalanan terpanjang)",
        certificates=(("K3", "K3 Umum — Kemnaker", 2023, 3),),
        trainings=(("SAFETY_IND", "Safety Induction Sagea", 2025, True),),
    ),
    Person(
        number="SGA007", name="Ferry Wibisono", position="MMR-PSPV",
        join=date(2021, 3, 8), birth=date(1989, 1, 14),
        gender="M", marital="M", religion="ISLAM", blood="O",
        group="FIELD", status="ACTIVE", employment_type="PERM",
        address="sorong", poh=POH_SORONG,
        education=("S1", "ST", "MECHANICAL", "Universitas Brawijaya", 2013, "3.22"),
        salary=19_500_000,
        reports_to="SGA001", username="demo.plantspv", roles=("EMPLOYEE",),
        note="supervisor Plant (SUP) — atasan mekanik & elektrik lokal",
        certificates=(("K3", "K3 Listrik", 2022, 3),),
        trainings=(("HEAVY_EQUIP", "Heavy Equipment Maintenance", 2024, False),),
    ),
    Person(
        number="SGA010", name="Yusuf Maulana", position="MMR-HFRM",
        join=date(2019, 7, 22), birth=date(1991, 10, 30),
        gender="M", marital="M", religion="ISLAM", blood="B",
        group="FIELD", status="ACTIVE", employment_type="PERM",
        address="makassar", poh=POH_MAKASSAR,
        education=("SMA", None, None, "SMA Negeri 3 Makassar", 2009, None),
        salary=15_800_000,
        reports_to="SGA001", username="demo.haulingspv", roles=("EMPLOYEE",),
        note="supervisor Hauling — atasan operator lokal",
        certificates=(("K3", "K3 Pertambangan", 2023, 3),),
        trainings=(("DEF_DRIVE", "Defensive Driving", 2025, True),),
    ),
    Person(
        number="SGA008", name="Gilang Ramadhan", position="MMR-SRV",
        join=date(2023, 6, 19), birth=date(1997, 3, 3),
        gender="M", marital="S", religion="ISLAM", blood="A",
        group="FIELD", status="ACTIVE", employment_type="PERM",
        address="yogya", poh=POH_YOGYA,
        education=("S1", "ST", "GEOLOGY", "UPN Veteran Yogyakarta", 2020, "3.31"),
        salary=13_400_000,
        reports_to="SGA001", username="demo.surveyor", roles=("EMPLOYEE",),
        note="Engineering — section Survey",
        trainings=(("WORK_HEIGHT", "Bekerja di Ketinggian", 2024, True),),
    ),
    Person(
        number="SGA009", name="Novita Sari", position="MMR-HSEO",
        join=date(2022, 10, 3), birth=date(1993, 7, 11),
        gender="F", marital="M", religion="CATHOLIC", blood="O",
        group="FIELD", status="ACTIVE", employment_type="PERM",
        address="makassar", poh=POH_MAKASSAR,
        education=("S1", "ST", "CIVIL", "Universitas Hasanuddin", 2016, "3.44"),
        salary=14_200_000,
        reports_to="SGA001", username="demo.hse", roles=("EMPLOYEE",),
        note="HSE — department tanpa kepala, menguji step Kepala Departemen yang dilewati",
        certificates=(("K3", "Ahli K3 Umum", 2021, 3), ("FIRSTAID", "First Aid & CPR", 2024, 2)),
        trainings=(("FIRST_AID", "Pertolongan Pertama", 2024, True),),
    ),
]


# ======================================================================
# SITE SAGEA — TENAGA LOKAL
#
# Tinggal di sekitar site (Weda, Sagea, Gebe, Kobe), jadi **tidak punya
# Point of Hire, tidak punya hari perjalanan, dan tidak masuk roster**.
# Golongan ini paling sering luput dari data uji, padahal jumlahnya di
# tambang justru terbesar — dan aturan yang benar untuk pegawai roster
# hampir selalu salah untuk mereka: hari cuti mereka dihitung dari
# kalender kerja site, bukan dari blok on/off.
#
# Rantainya sengaja tiga tingkat: crew → supervisor (POH) → kepala site.
# ======================================================================

SITE_LOCAL = [
    Person(
        number="LOK001", name="Rustam Hasan", position="MMR-DADM",
        join=date(2022, 2, 14), birth=date(1990, 6, 8),
        gender="M", marital="M", religion="ISLAM", blood="B",
        group="LOCAL", status="ACTIVE", employment_type="PERM",
        address="weda",
        education=("S1", "SE", "MANAGEMENT", "Universitas Khairun", 2014, "3.20"),
        salary=9_600_000,
        reports_to="SGA001", username="demo.deptadmin", roles=("ADMIN-DEPARTMENT",),
        note="ADMIN-DEPARTMENT — turunan meja #1 untuk section tanpa admin sendiri",
    ),
    Person(
        number="LOK002", name="Jufri Sangaji", position="MMR-OPR",
        join=date(2023, 4, 3), birth=date(1995, 2, 17),
        gender="M", marital="M", religion="ISLAM", blood="O",
        group="LOCAL", status="ACTIVE", employment_type="PERM",
        address="sagea",
        education=("SMA", None, None, "SMA Negeri 1 Weda", 2013, None),
        salary=6_800_000,
        reports_to="SGA010", username="demo.opr1", roles=("EMPLOYEE",),
        note="crew hauling lokal — pengaju cuti jalur site tanpa POH",
        certificates=(("K3", "SIO Operator Alat Berat", 2023, 5),),
        trainings=(("HEAVY_EQUIP", "Operator Excavator Kelas II", 2023, True),),
    ),
    Person(
        number="LOK003", name="Rahmat Tidore", position="MMR-OPR",
        join=date(2024, 8, 19), birth=date(1998, 12, 2),
        gender="M", marital="S", religion="ISLAM", blood="A",
        group="LOCAL", status="ACTIVE", employment_type="PERM",
        address="gebe",
        education=("SMA", None, None, "SMA Negeri 1 Pulau Gebe", 2016, None),
        salary=6_300_000,
        reports_to="SGA010", username="demo.opr2", roles=("EMPLOYEE",),
        note="crew hauling lokal",
        certificates=(("K3", "SIO Operator Dump Truck", 2024, 5),),
    ),
    Person(
        number="LOK004", name="Sultan Ahmad", position="MMR-OPR",
        join=date(2025, 11, 10), birth=date(2000, 8, 21),
        gender="M", marital="S", religion="ISLAM", blood="B",
        group="LOCAL", status="ACTIVE", employment_type="CONT",
        address="kobe",
        education=("SMA", None, None, "SMK Negeri 1 Weda Tengah", 2018, None),
        salary=5_900_000,
        reports_to="SGA010", username="demo.opr3", roles=("EMPLOYEE",),
        contract_end=-6,
        note="kontrak SUDAH lewat 6 hari — keadaan yang harus terlihat di layar",
    ),
    Person(
        number="LOK005", name="Umar Sahdan", position="MMR-MECH",
        join=date(2021, 9, 6), birth=date(1992, 5, 4),
        gender="M", marital="M", religion="ISLAM", blood="AB",
        group="LOCAL", status="ACTIVE", employment_type="PERM",
        address="lelilef",
        education=("D3", "AMD", "MECHANICAL", "Politeknik Negeri Ambon", 2013, "3.02"),
        salary=8_100_000,
        reports_to="SGA007", username="demo.mech1", roles=("EMPLOYEE",),
        note="crew Plant lokal — section Mechanical",
        trainings=(("SAFETY_IND", "Safety Induction Sagea", 2024, True),),
    ),
    Person(
        number="LOK006", name="Taufik Ode", position="MMR-ELEC",
        join=date(2023, 1, 23), birth=date(1996, 11, 15),
        gender="M", marital="M", religion="ISLAM", blood="O",
        group="LOCAL", status="ACTIVE", employment_type="PERM",
        address="weda",
        education=("D3", "AMD", "ELECTRICAL", "Politeknik Negeri Ambon", 2017, "3.09"),
        salary=7_900_000,
        reports_to="SGA007", username="demo.elec1", roles=("EMPLOYEE",),
        note="crew Plant lokal — section Electrical",
        certificates=(("K3", "K3 Listrik", 2024, 3),),
    ),
    Person(
        number="LOK007", name="Hamid Latif", position="MMR-LOGS",
        join=date(2024, 5, 27), birth=date(1994, 3, 28),
        gender="M", marital="M", religion="ISLAM", blood="A",
        group="LOCAL", status="ACTIVE", employment_type="PERM",
        address="sagea",
        education=("SMA", None, None, "SMA Negeri 1 Weda Utara", 2012, None),
        salary=6_500_000,
        reports_to="SGA001", username="demo.log1", roles=("EMPLOYEE",),
        note="Logistics — department tanpa section bernama",
    ),
    Person(
        number="LOK008", name="Nurlela Wahab", position="MMR-SRV",
        join=date(2026, 4, 6), birth=date(2002, 1, 9),
        gender="F", marital="S", religion="ISLAM", blood="B",
        group="LOCAL", status="PROBATION", employment_type="CONT",
        address="ternate",
        education=("D3", "AMD", "GEOLOGY", "Politeknik Negeri Ambon", 2023, "3.24"),
        salary=6_900_000,
        reports_to="SGA008", username="demo.survey2", roles=("EMPLOYEE",),
        probation_end=22, contract_end=300,
        note="pegawai lokal terbaru — jatah cuti 2026 nol, 2027 prorata",
    ),
]


PEOPLE = HEAD_OFFICE + SITE_POH + SITE_LOCAL


# ======================================================================
# HELPER
# ======================================================================

# Bank yang dipakai bergantian. Bukan satu bank untuk semua orang: kolom
# yang isinya seragam tidak membuktikan kolomnya benar-benar membaca
# data per baris — dan layar payroll yang mengelompokkan per bank tidak
# punya apa pun untuk dikelompokkan.
BANK_CODES = ["BCA", "MANDIRI", "BNI", "BRI", "DANAMON", "MEGA"]

# Pemetaan job level → job grade. Ditulis di sini, bukan di master:
# yang menentukan grade sesungguhnya adalah kebijakan tiap klien, dan
# data uji cuma perlu angkanya terisi supaya kolomnya tidak kosong.
GRADE_BY_LEVEL = {
    "STAFF": "G03",
    "SUP": "G05",
    "SPV": "G07",
    "MGR": "G09",
    "GM": "G11",
    "DIR": "G12",
}


def _days(offset: int) -> timedelta:
    return timedelta(days=offset)


def _slug(name: str) -> str:
    return name.lower().replace(" ", ".")


def _digits(seed: str, length: int) -> str:
    """
    Deret angka yang **selalu sama** untuk kunci yang sama.

    Bukan `random`: nomor rekening dan NIK data uji harus identik tiap
    kali seed dijalankan, kalau tidak dua tangkapan layar dari hari
    berbeda tidak bisa dibandingkan, dan pengujian import yang
    mencocokkan nomor selalu meleset.
    """
    value = 0

    for char in seed:
        value = (value * 131 + ord(char)) % (10 ** 12)

    return str(value).rjust(length, "7")[-length:]


def _nik(person: Person, village) -> str:
    """
    NIK 16 digit berbentuk sungguhan: 6 digit kode wilayah + tanggal
    lahir + 4 digit urut.

    Perempuan ditambah 40 pada tanggalnya, persis aturan Dukcapil —
    NIK data uji yang polanya salah membuat validator import terlihat
    rusak padahal yang salah datanya.
    """
    if village is None or not village.aid:
        region = "317400"
    else:
        region = village.aid.replace(".", "")[:6]

    day = person.birth.day + (40 if person.gender == "F" else 0)

    return (
        f"{region}"
        f"{day:02d}{person.birth.month:02d}{person.birth.year % 100:02d}"
        f"{_digits(person.number, 4)}"
    )


def _npwp(person: Person) -> str:
    raw = _digits(f"npwp{person.number}", 12)

    return (
        f"{raw[0:2]}.{raw[2:5]}.{raw[5:8]}.{raw[8]}-{raw[9:12]}.000"
    )


def _children_count(person: Person) -> int:
    """
    Jumlah anak diturunkan dari usia, bukan diketik satu per satu.

    Yang dibutuhkan cuma sebaran yang masuk akal supaya PTKP-nya
    berbeda-beda (TK/0 sampai K/2); mendaftarnya per orang berarti dua
    puluh enam baris lagi yang harus dijaga tetap sejalan dengan tanggal
    lahirnya.
    """
    if person.marital == "S":
        return 0

    age = TODAY.year - person.birth.year

    if age >= 35:
        return 2

    if age >= 29:
        return 1

    return 0


def _tax_status_code(person: Person) -> str:
    prefix = "K" if person.marital == "M" else "TK"

    return f"{prefix}/{min(_children_count(person), 3)}"


def _codes(model):
    return {row.code: row for row in model.objects.filter(is_deleted=False)}


def _resolve_company() -> Company:
    company = Company.objects.filter(
        code=COMPANY_CODE, is_deleted=False,
    ).first()

    if company is None:
        raise RuntimeError(
            f"Company {COMPANY_CODE} belum ada. Jalankan "
            "`tenant_command seed_demo_organization` lebih dulu.",
        )

    return company


def _resolve_location(*, company: Company, code: str) -> Location:
    """
    Lokasi kerja fisik — **dicari, tidak dibuat**.

    Seed ini menempatkan orang di struktur yang sudah ada; kalau ia ikut
    membuat lokasi saat tidak ketemu, dua seed sama-sama merasa memiliki
    struktur organisasi dan lokasi mana yang menempel ke pegawai
    ditentukan seed mana yang kebetulan jalan terakhir.
    """
    location = Location.objects.filter(
        company=company, code=code, is_deleted=False,
    ).first()

    if location is None:
        raise RuntimeError(
            f"Location {code} belum ada di company {company.code}. "
            "Jalankan `tenant_command seed_demo_organization` lebih dulu.",
        )

    return location


def _resolve_poh_cities():
    """
    Kota Point of Hire, diambil dari baris `RosterTravelDay`.

    **Bukan** dari master City lewat nama, dan itu bukan kerapian: master
    kota bawaan memuat "Kota Makassar" hasil import Kemendagri sementara
    seed policy roster menulis "Makassar" sebagai barisnya sendiri. POH
    yang menunjuk baris yang salah tetap tersimpan dan tetap terlihat
    benar di kartu pegawai — yang hilang cuma hari perjalanannya, dan
    hilangnya diam.
    """
    cities = {}

    for row in (
        RosterTravelDay.objects
        .filter(is_deleted=False)
        .select_related("point_of_hire")
    ):
        if row.point_of_hire_id:
            cities.setdefault(row.point_of_hire.name, row.point_of_hire)

    return cities


@transaction.atomic
def seed(*, log=None) -> dict:
    log = log or (lambda *args: None)

    # Gagal di sini, sebelum satu baris pun ditulis, kalau DEMO_PASSWORD kosong.
    demo_password()

    company = _resolve_company()

    jakarta = _resolve_location(company=company, code=HO_LOCATION_CODE)
    site = _resolve_location(company=company, code=SITE_LOCATION_CODE)

    branch = company.branches.filter(is_deleted=False).order_by("code").first()

    # ------------------------------------------------------------------
    # Master. Dibaca, tidak pernah dibuat: data uji tidak boleh diam-diam
    # menambah baris ke master yang dipakai semua orang di dropdown.
    # ------------------------------------------------------------------
    genders = _codes(Gender)
    religions = _codes(Religion)
    bloods = _codes(BloodType)
    maritals = _codes(MaritalStatus)
    nationalities = _codes(Nationality)
    groups = _codes(EmployeeGroup)
    statuses = _codes(EmploymentStatus)
    types = _codes(EmploymentType)
    contract_types = _codes(ContractType)
    probation_types = _codes(ProbationType)
    educations = _codes(Education)
    degrees = _codes(Degree)
    studies = _codes(StudyField)
    relationships = _codes(FamilyRelationship)
    certificate_types = _codes(CertificateType)
    document_types = _codes(DocumentType)
    training_categories = _codes(TrainingCategory)
    training_providers = _codes(TrainingProvider)
    grades = _codes(JobGrade)
    banks = _codes(Bank)
    payroll_groups = _codes(PayrollGroup)
    tax_statuses = _codes(TaxStatus)

    currency = Currency.objects.filter(
        is_base_currency=True, is_deleted=False,
    ).first() or Currency.objects.filter(
        code="IDR", is_deleted=False,
    ).first()

    # Jabatan milik seed organisasi. Dibaca sekali di depan supaya
    # kekurangannya ketahuan **sebelum** satu pegawai pun ditulis —
    # jabatan yang hilang di tengah jalan meninggalkan separuh cast
    # berdiri dan separuhnya tidak, dan itu keadaan yang paling sulit
    # dibaca dari layar.
    positions = {
        row.code: row
        for row in (
            Position.objects
            .select_related("department", "section", "division", "job_level")
            .filter(company=company, is_deleted=False)
        )
    }

    missing = sorted({p.position for p in PEOPLE} - set(positions))

    if missing:
        raise RuntimeError(
            f"Jabatan berikut belum ada di company {company.code}: "
            f"{', '.join(missing)}. Jalankan "
            "`tenant_command seed_demo_organization` lebih dulu.",
        )

    cost_centers = {
        row.department_id: row
        for row in CostCenter.objects.filter(
            company=company, is_deleted=False, department__isnull=False,
        )
    }

    # Alamat. Satu query untuk seluruh kelurahan yang dipakai, lalu
    # induknya dibaca dari relasi — bukan satu query per pegawai.
    villages = {
        row.aid: row
        for row in (
            Village.objects
            .select_related("district", "district__city", "district__city__province")
            .filter(
                aid__in=[aid for aid, _, _ in ADDRESSES.values()],
                is_deleted=False,
            )
        )
    }

    poh_cities = _resolve_poh_cities()

    # Kalender kantor dan kalender site, lewat resolver bersama —
    # bukan query yang ditulis ulang di sini.
    #
    # Versi sebelumnya menyaring `company=company, location__isnull=True`
    # sendiri. Itu benar selama seluruh kalender wajib punya company;
    # begitu cakupan GLOBAL masuk, penyaring itu justru membuang
    # `HO-STANDARD` (company-nya NULL) dan seed melaporkan tenant tanpa
    # kalender kantor. `CalendarResolver` yang tahu presedennya.
    from apps.administration.services.calendar_resolver import (
        CalendarResolver,
    )

    office_calendar = CalendarResolver.resolve_work_calendar(
        company_id=company.id,
    )

    site_calendar = CalendarResolver.resolve_work_calendar(
        company_id=company.id,
        location_id=site.id if site is not None else None,
    ) or office_calendar

    office_shift = Shift.objects.filter(
        code=OFFICE_SHIFT_CODE, is_deleted=False,
    ).first()

    site_shift = Shift.objects.filter(
        code=SITE_SHIFT_CODE, is_deleted=False,
    ).first()

    office_schedule = WorkSchedule.objects.filter(
        code=OFFICE_SCHEDULE_CODE, is_deleted=False,
    ).first()

    warnings: list[str] = []

    for label, value in [
        (f"Shift {OFFICE_SHIFT_CODE}", office_shift),
        (f"Shift {SITE_SHIFT_CODE}", site_shift),
        (f"Work Schedule {OFFICE_SCHEDULE_CODE}", office_schedule),
        ("Kalender kantor", office_calendar),
    ]:
        if value is None:
            warnings.append(
                f"{label} belum ada — kolomnya dikosongkan. "
                "Jalankan `tenant_command seed_hr_attendance` / "
                "`seed_administration --only=calendar`.",
            )

    for name in {p.poh for p in PEOPLE if p.poh}:
        if name not in poh_cities:
            warnings.append(
                f"Point of Hire '{name}' tidak ada di tabel hari "
                "perjalanan policy roster — kolomnya dikosongkan. "
                "Jalankan `tenant_command seed_roster_policy`.",
            )

    # ------------------------------------------------------------------
    # Pegawai + penempatan + kepegawaian
    # ------------------------------------------------------------------

    employees: dict[str, Employee] = {}

    for person in PEOPLE:
        position = positions[person.position]
        department = position.department
        section = position.section

        village_aid, street, postal = ADDRESSES[person.address]
        village = villages.get(village_aid)

        district = village.district if village else None
        city = district.city if district else None
        province = city.province if city else None

        first_name, _, last_name = person.name.partition(" ")
        slug = _slug(person.name)

        is_site = person.number.startswith(("SGA", "LOK"))
        location = site if is_site else jakarta

        employee, _ = Employee.objects.update_or_create(
            employee_number=person.number,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "nik": _nik(person, village),
                "tax_number": _npwp(person),
                "gender": genders.get(person.gender),
                "religion": religions.get(person.religion),
                "blood_type": bloods.get(person.blood),
                "marital_status": maritals.get(person.marital),
                "nationality": nationalities.get("ID"),
                "birth_place": city.name if city else "",
                "birth_date": person.birth,
                "address": f"{street}, Kode Pos {postal}",
                "province": province,
                "city": city,
                "district": district,
                "village": village,
                "work_email": f"{slug}@meinova.example",
                "personal_email": f"{slug}@mail.example",
                "mobile": f"08{_digits('hp' + person.number, 10)}",
                "phone": f"0{_digits('tel' + person.number, 9)}",
                "notes": person.note,
                "is_active": True,
                "is_deleted": False,
            },
        )

        job_level = position.job_level
        grade_code = GRADE_BY_LEVEL.get(
            job_level.code if job_level else "STAFF",
        )

        OrganizationAssignment.objects.update_or_create(
            employee=employee,
            defaults={
                "company": company,
                "branch": branch,
                "location": location,
                "division": position.division,
                "department": department,
                "section": section,
                "position": position,
                "job_level": job_level,
                "job_grade": grades.get(grade_code),
                "cost_center": cost_centers.get(
                    department.id if department else None,
                ),
                "organization_effective_date": person.join,
                "is_active": True,
                "is_deleted": False,
            },
        )

        # Kontrak & probation. `clean()` menolak tanggal akhir tanpa
        # tanggal mulai dan tanpa jenisnya, jadi ketiganya diisi bersama
        # — seed menulis lewat `save()` yang tidak memanggil
        # `full_clean()`, jadi barisnya tetap tersimpan dan kegagalannya
        # baru muncul saat orang lain membuka kartunya lalu menekan
        # Simpan, dengan alasan kolom yang tidak pernah ia sentuh.
        has_contract = person.contract_end is not None
        has_probation = person.probation_end is not None

        EmploymentAssignment.objects.update_or_create(
            employee=employee,
            defaults={
                "employment_status": statuses.get(person.status),
                "employment_type": types.get(person.employment_type),
                "employee_group": groups.get(person.group),
                "join_date": person.join,
                "employment_effective_date": person.join,
                "probation_type": (
                    probation_types.get("STANDARD") if has_probation else None
                ),
                "probation_start": person.join if has_probation else None,
                "probation_end": (
                    TODAY + _days(person.probation_end) if has_probation else None
                ),
                "contract_type": (
                    contract_types.get("PKWT") if has_contract else None
                ),
                "contract_start": person.join if has_contract else None,
                "contract_end": (
                    TODAY + _days(person.contract_end) if has_contract else None
                ),
                # Pola kerja. Pegawai roster (POH) **sengaja dibiarkan
                # kosong**: pola siklus dan tanggal mulainya dibawa
                # `RosterPolicy` dan diisi dokumen Roster Setup. Mengisi
                # `work_schedule` di sini membuat `clean()` menolak
                # begitu policy-nya ditempelkan nanti.
                "work_schedule": None if is_site and person.poh else office_schedule,
                "working_calendar": (
                    site_calendar if is_site else office_calendar
                ),
                "shift": site_shift if is_site else office_shift,
                # Tiga kolom roster tetap kosong — lihat docstring modul.
                "roster_crew": None,
                "roster_policy": None,
                "roster_cycle_start": None,
                "point_of_hire": poh_cities.get(person.poh) if person.poh else None,
                "job_location": location.name,
                "notice_period_days": 30,
                "is_deleted": False,
            },
        )

        employees[person.number] = employee

    # Garis pelaporan dipasang setelah semua pegawai ada: atasan harus
    # sudah tersimpan sebelum bisa ditunjuk bawahannya.
    for person in PEOPLE:
        if not person.reports_to:
            continue

        OrganizationAssignment.objects.filter(
            employee=employees[person.number],
        ).update(reports_to=employees[person.reports_to])

    # ------------------------------------------------------------------
    # Akun + role
    # ------------------------------------------------------------------

    User = get_user_model()

    accounts = 0

    for person in PEOPLE:
        if not person.username:
            continue

        employee = employees[person.number]

        email = demo_email(person.username)

        user, _ = User.objects.get_or_create(
            username=person.username,
            defaults={"email": email},
        )

        # Password dipasang setiap kali, bukan cuma saat akunnya baru:
        # tiap meja harus bisa dicoba login sendiri, dan akun lama yang
        # password-nya tidak pernah diset menolak login tanpa sebab yang
        # terlihat di layar mana pun.
        user.set_password(demo_password())
        user.first_name = employee.first_name
        user.last_name = employee.last_name or ""

        # Alamatnya dari `demo_accounts`, bukan diturunkan lagi di sini.
        # Berkas ini dan `demo_workforce` membentuk akun yang sama
        # dengan username yang sama; dua rumus alamat berarti seed mana
        # yang dijalankan terakhir menentukan siapa yang menerima surat
        # approval, dan bedanya tidak terlihat di layar mana pun.
        user.email = email

        user.save(update_fields=["password", "first_name", "last_name", "email"])

        if employee.user_id != user.pk:
            employee.user = user
            employee.save(update_fields=["user"])

        # Daftar **utuh**, bukan tambahan. Kalau ditambah saja, orang
        # yang perannya diubah tetap memegang role lamanya dan satu meja
        # diam-diam punya dua approver — dan itu baru terlihat saat ada
        # dokumen yang diajukan.
        #
        # WHERE-nya ikut disebut di sini: sejak Stage 4H tidak ada yang
        # menurunkannya dari `Role`, dan role tanpa kewenangan berarti
        # pemegangnya tidak melihat apa pun.
        assign_roles(
            user,
            authority_entries(
                Role.objects.filter(
                    code__in=person.roles, is_deleted=False),
            ),
        )

        accounts += 1

    # ------------------------------------------------------------------
    # Isi tab: bank, keluarga, pendidikan, pengalaman, sertifikat,
    # dokumen, pelatihan, medical, payroll
    # ------------------------------------------------------------------

    counts = {
        "bank": 0, "family": 0, "education": 0, "experience": 0,
        "certificate": 0, "document": 0, "training": 0,
        "medical": 0, "payroll": 0,
    }

    for index, person in enumerate(PEOPLE):
        employee = employees[person.number]
        is_site = person.number.startswith(("SGA", "LOK"))

        # --- Rekening bank -------------------------------------------
        bank = None

        for code in BANK_CODES[index % len(BANK_CODES):] + BANK_CODES:
            if code in banks:
                bank = banks[code]
                break

        if bank is not None:
            EmployeeBankAccount.objects.update_or_create(
                employee=employee,
                account_number=_digits(f"rek{person.number}", 10),
                defaults={
                    "bank": bank,
                    "account_name": person.name.upper(),
                    "branch_name": "Jakarta Sudirman" if not is_site else "Ternate",
                    "currency": currency,
                    "is_primary": True,
                    "is_active": True,
                    "is_deleted": False,
                },
            )
            counts["bank"] += 1

        # --- Keluarga -------------------------------------------------
        #
        # Sekaligus sumber kontak darurat di tab General. Menuliskannya
        # dua kali (kolom di Employee dan baris di tab Family) adalah
        # cara paling pasti membuat keduanya berbeda, jadi kolomnya
        # diisi **dari baris pertama** di sini.
        family_rows = []
        children = _children_count(person)

        if person.marital == "M":
            partner_gender = "F" if person.gender == "M" else "M"
            family_rows.append((
                "SPOUSE",
                f"{'Ratna' if partner_gender == 'F' else 'Andi'} "
                f"{person.name.split()[-1]}",
                partner_gender,
                date(person.birth.year + 2, 6, 14),
                True,
            ))

        for n in range(children):
            family_rows.append((
                "CHILD",
                f"{'Aditya' if n % 2 == 0 else 'Kayla'} "
                f"{person.name.split()[-1]}",
                "M" if n % 2 == 0 else "F",
                date(person.birth.year + 26 + n * 3, 3, 9),
                False,
            ))

        if not family_rows:
            family_rows.append((
                "PARENT",
                f"{'Bapak' if person.gender == 'F' else 'Ibu'} "
                f"{person.name.split()[-1]}",
                "M" if person.gender == "F" else "F",
                date(person.birth.year - 27, 4, 2),
                True,
            ))

        for relation, full_name, gender_code, birth, emergency in family_rows:
            EmployeeFamily.objects.update_or_create(
                employee=employee,
                full_name=full_name,
                defaults={
                    "relationship": relationships.get(relation),
                    "gender": genders.get(gender_code),
                    "birth_date": birth,
                    "birth_place": employee.birth_place,
                    "is_dependent": relation in {"SPOUSE", "CHILD"},
                    "is_emergency_contact": emergency,
                    "phone": f"08{_digits('kel' + full_name, 10)}",
                    "is_active": True,
                    "is_deleted": False,
                },
            )
            counts["family"] += 1

        emergency_name = next(
            (row[1] for row in family_rows if row[4]), family_rows[0][1],
        )

        Employee.objects.filter(pk=employee.pk).update(
            emergency_contact_name=emergency_name,
            emergency_contact_phone=f"08{_digits('kel' + emergency_name, 10)}",
        )

        # --- Pendidikan ----------------------------------------------
        level, degree, study, institution, year, gpa = person.education

        EmployeeEducation.objects.update_or_create(
            employee=employee,
            institution_name=institution,
            defaults={
                "education": educations.get(level),
                "degree": degrees.get(degree) if degree else None,
                "study_field": studies.get(study) if study else None,
                "graduation_year": year,
                "gpa": Decimal(gpa) if gpa else None,
                "city": employee.birth_place,
                "country": "Indonesia",
                "is_highest_education": True,
                "is_active": True,
                "is_deleted": False,
            },
        )
        counts["education"] += 1

        # --- Pengalaman kerja ----------------------------------------
        if person.experience:
            prev_company, prev_position, prev_start, prev_end = person.experience

            EmployeeExperience.objects.update_or_create(
                employee=employee,
                company_name=prev_company,
                defaults={
                    "position_name": prev_position,
                    "start_date": prev_start,
                    "end_date": prev_end,
                    "is_current": False,
                    "employment_type": "Permanent",
                    "location": "Jakarta",
                    "reason_for_leaving": "Pengembangan karier",
                    "is_active": True,
                    "is_deleted": False,
                },
            )
            counts["experience"] += 1

        # --- Sertifikat ----------------------------------------------
        for type_code, name, issued, valid_years in person.certificates:
            EmployeeCertificate.objects.update_or_create(
                employee=employee,
                certificate_name=name,
                defaults={
                    "certificate_type": certificate_types.get(type_code),
                    "certificate_number": _digits(f"cert{person.number}{name}", 8),
                    "issuing_organization": "Kementerian Ketenagakerjaan RI",
                    "issue_date": date(issued, 5, 20),
                    "expiry_date": date(issued + valid_years, 5, 20),
                    "is_verified": True,
                    "is_active": True,
                    "is_deleted": False,
                },
            )
            counts["certificate"] += 1

        # --- Dokumen --------------------------------------------------
        #
        # Metadata saja, tanpa berkas. Yang diuji di tab ini adalah
        # nomor, masa berlaku, dan penandanya; unggahan berkasnya justru
        # bagian yang harus dicoba tangan.
        for doc_code, doc_name, number in [
            ("KTP", "Kartu Tanda Penduduk", employee.nik),
            ("NPWP", "Nomor Pokok Wajib Pajak", employee.tax_number),
            ("FAMILY_CARD", "Kartu Keluarga", _digits(f"kk{person.number}", 16)),
        ]:
            if doc_code not in document_types:
                continue

            EmployeeDocument.objects.update_or_create(
                employee=employee,
                document_type=document_types[doc_code],
                defaults={
                    "document_name": doc_name,
                    "document_number": number,
                    "issuing_authority": "Dinas Kependudukan dan Catatan Sipil",
                    "issue_date": person.join,
                    "is_required": True,
                    "is_verified": doc_code == "KTP",
                    "is_active": True,
                    "is_deleted": False,
                },
            )
            counts["document"] += 1

        # --- Pelatihan ------------------------------------------------
        for category_code, name, year_taken, mandatory in person.trainings:
            EmployeeTraining.objects.update_or_create(
                employee=employee,
                training_name=name,
                defaults={
                    "training_category": training_categories.get(category_code),
                    "provider": training_providers.get("INTERNAL"),
                    "start_date": date(year_taken, 3, 4),
                    "end_date": date(year_taken, 3, 6),
                    "duration_hours": Decimal("16.00"),
                    "score": Decimal("85.00"),
                    "certificate_number": _digits(f"trn{person.number}{name}", 8),
                    "is_mandatory": mandatory,
                    "is_completed": True,
                    "is_active": True,
                    "is_deleted": False,
                },
            )
            counts["training"] += 1

        # --- Medical --------------------------------------------------
        #
        # Hanya pegawai site: MCU adalah syarat masuk area tambang, dan
        # menuliskannya untuk pegawai kantor membuat kolom "berlaku
        # sampai" terisi untuk orang yang tidak pernah diperiksa.
        if is_site:
            EmployeeMedicalEvent.objects.update_or_create(
                employee=employee,
                medical_type=EmployeeMedicalEvent.MedicalType.MEDICAL_CHECKUP,
                event_date=date(TODAY.year, 2, 12),
                defaults={
                    "provider_name": "Klinik Pratama Sagea",
                    "doctor_name": "dr. Wulandari",
                    "result": "Dalam batas normal",
                    "fitness_status": (
                        EmployeeMedicalEvent.FitnessStatus.FIT
                    ),
                    "next_due_date": date(TODAY.year + 1, 2, 12),
                    "is_confidential": True,
                    "is_verified": True,
                    "is_active": True,
                    "is_deleted": False,
                },
            )
            counts["medical"] += 1

        # --- Payroll --------------------------------------------------
        if payroll_groups and currency is not None:
            PayrollAssignment.objects.update_or_create(
                employee=employee,
                effective_from=person.join,
                defaults={
                    "payroll_group": (
                        payroll_groups.get("MONTHLY")
                        or next(iter(payroll_groups.values()))
                    ),
                    "currency": currency,
                    "payment_method": (
                        PayrollAssignment.PaymentMethod.BANK_TRANSFER
                    ),
                    "tax_status": tax_statuses.get(_tax_status_code(person)),
                    "tax_number_payroll": employee.tax_number,
                    "bpjs_kesehatan_number": _digits(f"bpjsk{person.number}", 13),
                    "bpjs_ketenagakerjaan_number": _digits(f"bpjst{person.number}", 11),
                    "basic_salary": Decimal(person.salary),
                    "overtime_eligible": person.group not in {"MANAGEMENT"},
                    "is_current": True,
                    "is_deleted": False,
                },
            )
            counts["payroll"] += 1

    # ------------------------------------------------------------------
    # Ringkasan
    # ------------------------------------------------------------------
    #
    # Susunan site dilaporkan per department **dan** per section, karena
    # dua-duanya menentukan ke meja siapa dokumennya mendarat: step
    # pertama alur site dicari per section, turunan pertamanya per
    # department. Daftar jumlah pegawai saja tidak memberi tahu apa pun
    # tentang itu.

    site_breakdown: dict[str, dict] = {}

    for person in PEOPLE:
        if not person.number.startswith(("SGA", "LOK")):
            continue

        position = positions[person.position]
        department = position.department
        section = position.section

        dept_key = department.name if department else "(tanpa department)"
        sect_key = section.name if section else "(tanpa section)"

        bucket = site_breakdown.setdefault(
            dept_key, {"total": 0, "poh": 0, "local": 0, "sections": {}},
        )

        bucket["total"] += 1
        bucket["poh" if person.poh else "local"] += 1

        row = bucket["sections"].setdefault(
            sect_key, {"total": 0, "poh": 0, "local": 0},
        )

        row["total"] += 1
        row["poh" if person.poh else "local"] += 1

    # Tidak ada backfill di sini: kewenangan sudah disebut saat tiap
    # penugasan dibuat (`authority_entries`). Perkakas backfill-nya
    # sendiri sudah dihapus di gelombang C — ia menurunkan WHERE dari
    # konfigurasi cakupan lama, dan konfigurasi itu tidak ada lagi.

    return {
        "company": company.name,
        "total": len(PEOPLE),
        "head_office": len(HEAD_OFFICE),
        "site_poh": len(SITE_POH),
        "site_local": len(SITE_LOCAL),
        "accounts": accounts,
        "records": counts,
        "site_breakdown": site_breakdown,
        "warnings": warnings,
        "office_calendar": office_calendar.code if office_calendar else None,
        "site_calendar": site_calendar.code if site_calendar else None,
    }
