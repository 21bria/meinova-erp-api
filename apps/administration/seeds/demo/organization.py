"""
Struktur organisasi tenant **peragaan** — dipakai untuk trial dan
tutorial, bukan untuk klien mana pun.

Tiga hal yang membedakannya dari seed lama, dan ketiganya disengaja:

**Namanya fiktif.** Seed sebelumnya membawa dua belas badan usaha milik
klien sungguhan ke setiap tenant yang pernah dibuat. Tenant peragaan
dipakai untuk demo ke calon klien dan tangkapan layarnya masuk ke Help
Center — nama klien di sana ikut tersebar ke orang yang tidak berhak
mengetahuinya.

**Departemennya tidak sama rata.** Seed lama mengalikan 38 nama
department ke setiap company: perusahaan induk yang isinya direksi dan
keuangan tetap kebagian Barging, Stockpile, dan Grade Control. Hasilnya
460 department, sebagian besar kosong selamanya, dan dropdown yang
tidak bisa dipakai siapa pun. Di sini tiap company hanya membawa
department yang memang ada di perusahaan sejenis itu.

**Hanya satu company yang berpenghuni.** Seluruh pegawai peragaan duduk
di `MMR` (perusahaan operasi), dan itu bukan kemalasan: batas yang tidak
pernah dilewati engine approval adalah **company** — approver dari
perusahaan lain terhitung kebocoran, bukan eskalasi. Kalau pegawai
kantor pusat ditaruh di `MNI` sementara pegawai site di `MMR`, meja
HRGA pada alur site (yang bercakupan company) tidak akan pernah
menemukan siapa pun, dan alur site mati tanpa satu pun pesan yang
menyebut sebabnya.

`MNI` dan `MLS` tetap ada dan tetap berisi struktur penuh. Keduanya yang
membuat penyaring berantai Company → Site → Department → Section punya
sesuatu untuk disaring, dan yang membuat aksi "Salin ke perusahaan lain"
punya tujuan yang masuk akal.
"""

from ..organization import (
    OrganizationDataset,
    seed_organization,
)


# ============================================================
# COMPANY
# ============================================================

COMPANIES = [
    {
        "code": "MNI",
        "name": "Meinova Nusantara",
        "legal_name": "PT MEINOVA NUSANTARA",
        "company_type": "COMP",
        "parent": None,
        "tax_number": "01.234.567.8-092.000",
        "country": "ID",
        "province": "DKI",
        "city": "JKT",
        "address": "Jl. Jenderal Sudirman Kav. 21, Jakarta Selatan",
        "postal_code": "12920",
        "phone": "021-5550100",
        "email": "corporate@meinova.example",
        "website": "https://meinova.example",
    },
    {
        "code": "MMR",
        "name": "Meinova Mineral Resources",
        "legal_name": "PT MEINOVA MINERAL RESOURCES",
        "company_type": "SUB",
        "parent": "MNI",
        "tax_number": "02.345.678.9-092.000",
        "country": "ID",
        "province": "DKI",
        "city": "JKT",
        "address": "Jl. Jenderal Sudirman Kav. 21, Jakarta Selatan",
        "postal_code": "12920",
        "phone": "021-5550200",
        "email": "info@mmr.meinova.example",
        "website": "",
    },
    {
        "code": "MLS",
        "name": "Meinova Logistik Samudra",
        "legal_name": "PT MEINOVA LOGISTIK SAMUDRA",
        "company_type": "SUB",
        "parent": "MNI",
        "tax_number": "03.456.789.0-092.000",
        "country": "ID",
        "province": "JI",
        "city": "SBY",
        "address": "Jl. Perak Timur No. 88, Surabaya",
        "postal_code": "60165",
        "phone": "031-5550300",
        "email": "info@mls.meinova.example",
        "website": "",
    },
]


BRANCHES = [
    {
        "company": company["code"],
        "code": "DEFAULT",
        "name": "Main Branch",
        "country": "ID",
        "province": company["province"],
        "city": company["city"],
        "address": company["address"],
        "postal_code": company["postal_code"],
        "phone": company["phone"],
        "email": "",
        "website": "",
    }
    for company in COMPANIES
]


# ============================================================
# LOCATION
#
# Location = tempat orang bekerja, dan itu yang membedakannya dari
# Branch: absensi, shift, dan kalender libur menempel ke sini.
#
# `JKT-HO` milik MMR bertipe HO, bukan OFFICE. Pegawai kantor pusat
# perusahaan operasi memang duduk di sana, dan `visibility_rule`
# pada menu membedakan mereka dari pegawai site lewat pola kerjanya —
# bukan lewat tipe lokasinya.
# ============================================================

LOCATIONS = [
    # --- MNI: satu kantor pusat, tanpa lapangan ---
    {
        "company": "MNI",
        "branch": "DEFAULT",
        "location_type": "HO",
        "code": "JKT-HO",
        "name": "Jakarta Head Office",
        "country": "ID",
        "province": "DKI",
        "city": "JKT",
        "address": "Jl. Jenderal Sudirman Kav. 21, Jakarta Selatan",
        "postal_code": "12920",
    },

    # --- MMR: kantor pusat + dua lokasi lapangan ---
    {
        "company": "MMR",
        "branch": "DEFAULT",
        "location_type": "HO",
        "code": "JKT-HO",
        "name": "Jakarta Head Office",
        "country": "ID",
        "province": "DKI",
        "city": "JKT",
        "address": "Jl. Jenderal Sudirman Kav. 21, Jakarta Selatan",
        "postal_code": "12920",
    },
    {
        "company": "MMR",
        "branch": "DEFAULT",
        "location_type": "MINE",
        "code": "SAGEA-MINE",
        "name": "Sagea Mine",
        "country": "ID",
        "province": "MALUKU-UTARA",
        "city": "TERNATE",
        "address": "Blok Sagea, Halmahera Tengah",
        "postal_code": "",
    },
    # {
    #     "company": "MMR",
    #     "branch": "DEFAULT",
    #     "location_type": "PORT",
    #     "code": "SAGEA-PORT",
    #     "name": "Sagea Port",
    #     "country": "ID",
    #     "province": "MALUKU-UTARA",
    #     "city": "TERNATE",
    #     "address": "Pelabuhan Sagea, Halmahera Tengah",
    #     "postal_code": "",
    # },

    # --- MLS: kantor Surabaya + jetty di dekat site MMR ---
    {
        "company": "MLS",
        "branch": "DEFAULT",
        "location_type": "OFFICE",
        "code": "SBY-OFFICE",
        "name": "Surabaya Office",
        "country": "ID",
        "province": "JI",
        "city": "SBY",
        "address": "Jl. Perak Timur No. 88, Surabaya",
        "postal_code": "60165",
    },
    {
        "company": "MLS",
        "branch": "DEFAULT",
        "location_type": "PORT",
        "code": "SAGEA-JETTY",
        "name": "Sagea Jetty",
        "country": "ID",
        "province": "MALUKU-UTARA",
        "city": "TERNATE",
        "address": "Dermaga Sagea, Halmahera Tengah",
        "postal_code": "",
    },
]


# ============================================================
# FACILITY
#
# Hanya di site: itu satu-satunya lokasi yang bangunannya memang
# dirujuk dokumen roster dan travel request. Kantor tidak diberi
# fasilitas karangan — master yang terlihat terisi padahal barisnya
# tidak menunjuk bangunan mana pun lebih menyesatkan daripada kosong.
# ============================================================

FACILITIES = [
    {
        "company": "MMR",
        "location": "SAGEA-MINE",
        "facility_type": "WORKSHOP",
        "code": "SGA-WS",
        "name": "Workshop Sagea",
        "description": "Bengkel alat berat di area site.",
    },
    {
        "company": "MMR",
        "location": "SAGEA-MINE",
        "facility_type": "WAREHOUSE",
        "code": "SGA-WH",
        "name": "Warehouse Sagea",
        "description": "Gudang sparepart dan consumable.",
    },
    {
        "company": "MMR",
        "location": "SAGEA-MINE",
        "facility_type": "CAMP",
        "code": "SGA-CP",
        "name": "Camp Sagea",
        "description": "Mess dan fasilitas akomodasi crew.",
    },
    # {
    #     "company": "MMR",
    #     "location": "SAGEA-PORT",
    #     "facility_type": "JETTY",
    #     "code": "SGA-JT",
    #     "name": "Jetty Sagea",
    #     "description": "Dermaga muat dan titik keluar-masuk crew.",
    # },
]


# ============================================================
# DIVISION
#
# Dua saja per company yang punya lapangan: yang mengurus pekerjaannya
# dan yang menopangnya. Division bukan tingkat yang wajib di sistem ini
# — memecahnya lebih halus hanya menambah satu dropdown lagi yang harus
# diisi setiap kali orang membuat department.
# ============================================================

DIVISIONS = [
    # (company, branch, location, code, name)
    ("MNI", "DEFAULT", "JKT-HO", "CORP", "Corporate"),

    ("MMR", "DEFAULT", "JKT-HO", "CORP", "Corporate"),
    ("MMR", "DEFAULT", "SAGEA-MINE", "OPS", "Operations"),

    ("MLS", "DEFAULT", "SBY-OFFICE", "CORP", "Corporate"),
    ("MLS", "DEFAULT", "SAGEA-JETTY", "OPS", "Operations"),
]


# ============================================================
# DEPARTMENT
#
# Set standar tambang/kontraktor, dan **tiap company hanya membawa yang
# memang ada padanya**. Perusahaan induk tidak punya Grade Control;
# perusahaan pelayaran tidak punya Mine Planning.
#
# Kode sengaja pendek dan berulang lintas company (`HRD` ada di
# ketiganya): kode hanya unik **per company**, dan menyeragamkannya
# membuat aksi "Salin ke perusahaan lain" menghasilkan pasangan yang
# bisa dibandingkan.
# ============================================================

DEPARTMENT_ROWS = [
    # (company, location, division, code, name)

    # --- MNI: perusahaan induk, seluruhnya di kantor pusat ---
    ("MNI", "JKT-HO", "CORP", "BOD", "Board of Directors"),
    ("MNI", "JKT-HO", "CORP", "HRD", "Human Resources"),
    ("MNI", "JKT-HO", "CORP", "FIN", "Finance"),
    ("MNI", "JKT-HO", "CORP", "ACC", "Accounting"),
    ("MNI", "JKT-HO", "CORP", "LEGAL", "Legal"),
    ("MNI", "JKT-HO", "CORP", "IT", "Information Technology"),
    ("MNI", "JKT-HO", "CORP", "PROC", "Procurement"),
    ("MNI", "JKT-HO", "CORP", "GA", "General Affairs"),

    # --- MMR: kantor pusat ---
    #
    # `BOD` ada supaya rantai kantor pusat punya ujung. Tanpa jabatan di
    # atas HR Manager dan Finance Manager, keduanya tidak punya atasan —
    # dan step "Atasan Langsung" pada alur cuti tidak punya cadangan,
    # jadi pengajuan cuti mereka sendiri gagal seluruhnya dengan pesan
    # yang menyebut kolom yang memang sengaja dikosongkan.
    #
    # HRD dan OPS **wajib department yang berbeda**, dan itu bukan
    # kerapian. Approver bertipe `department_head` mencari pemegang
    # jabatan manajerial di department pegawainya, dan department itulah
    # cakupannya — tidak ada kenop untuk mempersempitnya. Waktu pegawai
    # kantor dan pegawai site pernah ditaruh di satu department,
    # meja "Kepala Departemen" pada cuti pegawai Jakarta jatuh ke
    # manajer di site, dan tidak ada satu pesan pun yang menyebutnya
    # karena konfigurasinya memang benar.
    ("MMR", "JKT-HO", "CORP", "BOD", "Board of Directors"),
    ("MMR", "JKT-HO", "CORP", "HRD", "Human Resources"),
    ("MMR", "JKT-HO", "CORP", "FIN", "Finance"),
    ("MMR", "JKT-HO", "CORP", "ACC", "Accounting"),
    ("MMR", "JKT-HO", "CORP", "PROC", "Procurement"),
    ("MMR", "JKT-HO", "CORP", "IT", "Information Technology"),
    ("MMR", "JKT-HO", "CORP", "GA", "General Affairs"),

    # --- MMR: site ---
    ("MMR", "SAGEA-MINE", "OPS", "OPS", "Site Operations"),
    ("MMR", "SAGEA-MINE", "OPS", "ENG", "Engineering"),
    ("MMR", "SAGEA-MINE", "OPS", "PLANT", "Plant & Maintenance"),
    ("MMR", "SAGEA-MINE", "OPS", "HSE", "Health, Safety & Environment"),
    ("MMR", "SAGEA-MINE", "OPS", "LOG", "Logistics"),
    # Department Port & Stockpile ikut dicabut bersama lokasi
    # `SAGEA-PORT`. Tiap tingkat menunjuk induknya lewat kode, jadi
    # department yang lokasinya tidak ada lagi menggagalkan **seluruh**
    # seed organisasi ("Location 'SAGEA-PORT' was not found") — dan
    # gagalnya di tengah, sesudah company dan lokasi tertulis.
    # ("MMR", "SAGEA-PORT", "OPS", "PORT", "Port & Stockpile"),

    # --- MLS ---
    ("MLS", "SBY-OFFICE", "CORP", "HRD", "Human Resources"),
    ("MLS", "SBY-OFFICE", "CORP", "FIN", "Finance"),
    ("MLS", "SBY-OFFICE", "CORP", "GA", "General Affairs"),
    ("MLS", "SAGEA-JETTY", "OPS", "MARINE", "Marine Operations"),
    ("MLS", "SAGEA-JETTY", "OPS", "PLANT", "Plant & Maintenance"),
    ("MLS", "SAGEA-JETTY", "OPS", "HSE", "Health, Safety & Environment"),
]


DEPARTMENTS = [
    (company, "DEFAULT", location, division, code, name)
    for company, location, division, code, name in DEPARTMENT_ROWS
]


# ============================================================
# SECTION
#
# Tiap department dapat satu General Section, plus section bernama di
# site. Yang bernama itu bukan hiasan: step pertama alur travel request
# site bercakupan **section**, jadi tanpa section yang benar-benar
# menampung orang, meja Admin Section tidak menemukan siapa pun.
# ============================================================

def general_section_code(department_code: str) -> str:
    return f"{department_code}_GENERAL"


NAMED_SECTIONS = [
    # (company, department, code, name)
    ("MMR", "OPS", "OPS_SITE", "Site Operations"),
    ("MMR", "OPS", "OPS_HAULING", "Hauling"),
    ("MMR", "ENG", "ENG_SURVEY", "Survey"),
    ("MMR", "ENG", "ENG_GRADE", "Grade Control"),
    ("MMR", "PLANT", "PLANT_MECH", "Mechanical"),
    ("MMR", "PLANT", "PLANT_ELEC", "Electrical"),
    ("MLS", "MARINE", "MARINE_BARGE", "Barging"),
]


_DEPARTMENT_INDEX = {
    (company, code): (location, division)
    for company, location, division, code, _ in DEPARTMENT_ROWS
}


SECTIONS = [
    (
        company,
        "DEFAULT",
        location,
        division,
        code,
        general_section_code(code),
        "General",
    )
    for company, location, division, code, _ in DEPARTMENT_ROWS
] + [
    (
        company,
        "DEFAULT",
        _DEPARTMENT_INDEX[(company, department)][0],
        _DEPARTMENT_INDEX[(company, department)][1],
        department,
        code,
        name,
    )
    for company, department, code, name in NAMED_SECTIONS
]


# ============================================================
# POSITION
#
# Cukup untuk membentuk garis komando yang bisa diuji, tidak lebih.
# Seribu jabatan yang tidak dipegang siapa pun membuat dropdown
# Position tidak bisa dipakai dan tidak membuktikan apa pun.
#
# `is_manager` yang menentukan siapa "Kepala Departemen" di engine
# approval — bukan nama jabatannya, dan bukan job level-nya.
# ============================================================

POSITION_ROWS = [
    # (company, department, section, code, name, job_level,
    #  job_category, is_manager, reports_to)

    # --- MNI ---
    ("MNI", "BOD", None, "MNI-DIR", "Director", "DIR", "MGMT", True, None),
    ("MNI", "HRD", None, "MNI-HRM", "HR Manager", "MGR", "MGMT", True, "MNI-DIR"),
    ("MNI", "HRD", None, "MNI-HRO", "HR Officer", "STAFF", "ADMIN", False, "MNI-HRM"),
    ("MNI", "FIN", None, "MNI-FINM", "Finance Manager", "MGR", "MGMT", True, "MNI-DIR"),
    ("MNI", "ACC", None, "MNI-ACCS", "Accounting Staff", "STAFF", "ADMIN", False, "MNI-FINM"),
    ("MNI", "LEGAL", None, "MNI-LGLS", "Legal Officer", "STAFF", "SUPPORT", False, "MNI-DIR"),
    ("MNI", "IT", None, "MNI-ITS", "IT Support", "STAFF", "TECH", False, "MNI-DIR"),
    ("MNI", "PROC", None, "MNI-PRCS", "Procurement Staff", "STAFF", "ADMIN", False, "MNI-DIR"),
    ("MNI", "GA", None, "MNI-GAS", "GA Staff", "STAFF", "SUPPORT", False, "MNI-DIR"),

    # --- MMR kantor pusat ---
    ("MMR", "BOD", None, "MMR-GM", "General Manager", "GM", "MGMT", True, None),
    # GM kantor pusat untuk menguji Organization Scope lintas company.
    #
    # **`is_manager=False`, dan itu bukan kelalaian.** Approver bertipe
    # Kepala Departemen mengambil pemegang jabatan bermanajer di
    # department pegawainya dengan urutan "yang terbaru menang"
    # (`_department_manager`), jadi jabatan bermanajer kedua di
    # department `BOD` akan mengambil alih meja itu dari `MMR-GM` untuk
    # dokumen yang sudah berjalan. Cakupan data tidak butuh penanda ini
    # sama sekali — yang menentukannya kewenangan `RoleAssignment`.
    ("MMR", "BOD", None, "MMR-GMHO", "General Manager — Head Office", "GM", "MGMT", False, "MMR-GM"),
    ("MMR", "HRD", None, "MMR-HRM", "HR Manager", "MGR", "MGMT", True, "MMR-GM"),
    ("MMR", "HRD", None, "MMR-HRO", "HR Officer", "STAFF", "ADMIN", False, "MMR-HRM"),
    ("MMR", "HRD", None, "MMR-HRGA", "HRGA Officer", "STAFF", "ADMIN", False, "MMR-HRM"),
    ("MMR", "FIN", None, "MMR-FINM", "Finance Manager", "MGR", "MGMT", True, "MMR-GM"),
    ("MMR", "FIN", None, "MMR-FINS", "Finance Staff", "STAFF", "ADMIN", False, "MMR-FINM"),
    ("MMR", "ACC", None, "MMR-ACCS", "Accounting Staff", "STAFF", "ADMIN", False, "MMR-FINM"),
    ("MMR", "PROC", None, "MMR-PRCS", "Procurement Staff", "STAFF", "ADMIN", False, None),
    ("MMR", "IT", None, "MMR-ITS", "IT Support", "STAFF", "TECH", False, None),
    ("MMR", "GA", None, "MMR-GAS", "GA Staff", "STAFF", "SUPPORT", False, None),

    # --- MMR site ---
    #
    # Site Superintendent yang jadi kepala department site, dan Site HR
    # Manager berada di bawahnya. Garis pelaporan sebenarnya di data uji
    # justru kebalikannya untuk satu orang — itu memang bentuk yang mau
    # diuji, dan `reports_to` antarorang di `OrganizationAssignment`
    # yang menentukan, bukan hierarki jabatan ini.
    # Pimpinan site, dan **levelnya wajib di atas MGR**. Versi pertama
    # menamainya "Site Superintendent" pada level `SPV` — satu tingkat
    # di BAWAH Kepala Teknik Tambang dan Site HR Manager yang keduanya
    # `MGR`, padahal keduanya melapor kepadanya. Terbalik, dan untuk KTT
    # salahnya dobel: KTT diangkat dan disahkan Kepala Inspektur Tambang
    # sebagai pemegang otoritas teknis tertinggi di site — secara
    # administratif boleh berada di bawah pimpinan site, tidak pernah di
    # bawah seorang Superintendent.
    #
    # Kodenya sengaja **tidak** ikut diganti. `MMR-SSPV` memang terbaca
    # seperti singkatan jabatan lamanya, tapi kode Position dirujuk
    # `EMPLOYEE_POSITION` di seed pegawai dan menggantinya menyisakan
    # baris yatim di master setiap tenant yang sudah pernah diseed —
    # baris yang tetap muncul di dropdown dan tidak ada yang membuangnya.
    ("MMR", "OPS", "OPS_SITE", "MMR-SSPV", "Project Manager", "GM", "MGMT", True, None),
    ("MMR", "OPS", "OPS_SITE", "MMR-SHRM", "Site HR Manager", "MGR", "MGMT", False, "MMR-SSPV"),
    ("MMR", "OPS", "OPS_SITE", "MMR-SHRO", "Site HR Officer", "STAFF", "ADMIN", False, "MMR-SHRM"),
    ("MMR", "OPS", "OPS_SITE", "MMR-SADM", "Section Admin", "STAFF", "ADMIN", False, "MMR-SSPV"),
    # GM site — pasangan `MMR-GMHO` di lapangan, dan `is_manager=False`
    # karena alasan yang sama: department `OPS` sudah punya kepalanya
    # (`MMR-SSPV`), dan menambah jabatan bermanajer kedua di sana akan
    # memindahkan meja Kepala Departemen seluruh pegawai site.
    ("MMR", "OPS", "OPS_SITE", "MMR-GMSITE", "General Manager — Site", "GM", "MGMT", False, "MMR-SSPV"),
    # Admin tingkat department, bukan section. Meja pertama alur site
    # dicari per **section**, dan turunan pertamanya per **department**
    # (lihat rantai `WorkflowStepFallback` di `seed_workflows`). Tanpa
    # jabatan ini, tingkat tengah rantai itu tidak pernah punya
    # pemegang, dan setiap pengajuan dari section yang belum punya
    # adminnya sendiri melompat langsung ke HR — turunan bertingkat yang
    # sengaja dibangun jadi tidak pernah teruji.
    ("MMR", "OPS", None, "MMR-DADM", "Department Admin", "STAFF", "ADMIN", False, "MMR-SSPV"),
    ("MMR", "OPS", "OPS_SITE", "MMR-KTT", "Kepala Teknik Tambang", "MGR", "MGMT", False, "MMR-SSPV"),
    ("MMR", "OPS", "OPS_HAULING", "MMR-HFRM", "Hauling Foreman", "SUP", "OPS", False, "MMR-SSPV"),
    ("MMR", "OPS", "OPS_HAULING", "MMR-OPR", "Heavy Equipment Operator", "STAFF", "OPS", False, "MMR-HFRM"),
    # Grade Control Foreman sengaja duduk di OPS/OPS_SITE, bukan di
    # department Engineering tempat namanya seolah lebih pas. Meja
    # pertama alur travel request site bercakupan **section**, jadi
    # pengaju dan Admin Section-nya harus duduk di section yang sama —
    # kalau tidak, meja itu diam-diam jatuh ke role cadangan dan
    # cakupan section-nya tidak pernah teruji oleh data uji mana pun.
    ("MMR", "OPS", "OPS_SITE", "MMR-GCFRM", "Grade Control Foreman", "SUP", "TECH", False, "MMR-SSPV"),
    ("MMR", "ENG", "ENG_SURVEY", "MMR-SRV", "Surveyor", "STAFF", "TECH", False, None),
    # Plant punya kepalanya sendiri, dan itu bukan kerapian: mekanik dan
    # elektrik adalah dua section yang paling banyak diisi tenaga lokal,
    # jadi rantai crew → supervisor → manager di sini yang paling sering
    # dijalankan. `is_manager` juga membuat department PLANT punya
    # Kepala Departemen — tanpanya step bertipe `department_head` pada
    # alur kantor pusat dilewati untuk seluruh pegawai plant.
    # Levelnya `SUP`, bukan `SPV`: di master ini `SUP` = Supervisor dan
    # `SPV` = **Superintendent**, dua tingkat yang berbeda. Sejajar
    # dengan Hauling Foreman yang memang `SUP` — keduanya memimpin crew
    # di sectionnya masing-masing.
    ("MMR", "PLANT", "PLANT_MECH", "MMR-PSPV", "Plant Supervisor", "SUP", "TECH", True, "MMR-SSPV"),
    ("MMR", "PLANT", "PLANT_MECH", "MMR-MECH", "Mechanic", "STAFF", "TECH", False, "MMR-PSPV"),
    ("MMR", "PLANT", "PLANT_ELEC", "MMR-ELEC", "Electrician", "STAFF", "TECH", False, "MMR-PSPV"),
    ("MMR", "HSE", None, "MMR-HSEO", "HSE Officer", "STAFF", "SUPPORT", False, None),
    ("MMR", "LOG", None, "MMR-LOGS", "Logistic Staff", "STAFF", "ADMIN", False, None),
    # Menyusul department-nya yang dicabut di atas.
    # ("MMR", "PORT", None, "MMR-PRTS", "Port Supervisor", "SUP", "OPS", True, None),

    # --- MLS ---
    ("MLS", "HRD", None, "MLS-HRM", "HR Manager", "MGR", "MGMT", True, None),
    ("MLS", "FIN", None, "MLS-FINS", "Finance Staff", "STAFF", "ADMIN", False, None),
    ("MLS", "GA", None, "MLS-GAS", "GA Staff", "STAFF", "SUPPORT", False, None),
    ("MLS", "MARINE", "MARINE_BARGE", "MLS-BSPV", "Barging Supervisor", "SUP", "OPS", True, None),
    ("MLS", "MARINE", "MARINE_BARGE", "MLS-CRW", "Barge Crew", "STAFF", "OPS", False, "MLS-BSPV"),
    ("MLS", "PLANT", None, "MLS-MECH", "Mechanic", "STAFF", "TECH", False, None),
    ("MLS", "HSE", None, "MLS-HSEO", "HSE Officer", "STAFF", "SUPPORT", False, None),
]


POSITIONS = [
    {
        "company": company,
        "branch": "DEFAULT",
        "location": _DEPARTMENT_INDEX[(company, department)][0],
        "division": _DEPARTMENT_INDEX[(company, department)][1],
        "department": department,
        "section": section or general_section_code(department),
        "job_category": job_category,
        "job_level": job_level,
        "code": code,
        "name": name,
        "headcount": 1,
        "description": "",
        "is_manager": is_manager,
        "reports_to": reports_to,
    }
    for (
        company,
        department,
        section,
        code,
        name,
        job_level,
        job_category,
        is_manager,
        reports_to,
    ) in POSITION_ROWS
]


# ============================================================
# COST CENTER
#
# Satu per department. Nomornya berjenjang per company (1000, 1010, …)
# supaya kode yang sama tidak dipakai dua perusahaan untuk hal berbeda
# — kode cost center hanya unik per company, dan laporan gabungan yang
# menjumlahkan "1010" dari tiga perusahaan berbeda tidak berbunyi salah,
# cuma salah.
# ============================================================

COST_CENTERS = [
    (
        company,
        "DEFAULT",
        location,
        division,
        code,
        # Kode diturunkan dari **kode department**, bukan dari posisi
        # urutnya di daftar.
        #
        # Versi pertama memakai `1000 + index * 10`, dan itu salah dengan
        # cara yang tidak berbunyi: mencabut satu department menggeser
        # kode **semua** yang di bawahnya, jadi seed berikutnya menulis
        # ulang isi tiap baris ke kode tetangganya dan menyisakan satu
        # baris yatim di ujung. Nomor cost center juga hal yang dirujuk
        # jurnal dan laporan — ia tidak boleh berubah arti hanya karena
        # ada department baru disisipkan di atasnya.
        f"{company}-{code}",
        name,
    )
    for company, location, division, code, name in DEPARTMENT_ROWS
]


# ============================================================
# DATASET
# ============================================================

DATASET = OrganizationDataset(
    name="Meinova Demo Group",
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
