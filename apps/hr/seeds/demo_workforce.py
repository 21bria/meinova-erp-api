"""
Tenaga kerja data uji: kantor pusat Jakarta + site Sagea.

Menggantikan `site_rotation.py` yang cakupannya cuma pegawai roster.
Yang dibutuhkan untuk menguji cuti, saldo, dan Travel Request bukan
hanya pegawai site — perbedaan perlakuan HO dan site justru baru
kelihatan kalau keduanya ada di tenant yang sama.

Nomor pegawainya sengaja berawalan `HO` dan `SGA`, bukan meniru pola
klien (`KW`, `IP`, `KPB`, …). Data uji harus bisa dibedakan sekilas
dari data sungguhan, dan tidak boleh bertabrakan saat file master klien
diimpor.

Tanggal masuk sengaja dibuat berjenjang
---------------------------------------
Jatah cuti bergantung pada masa tunggu 12 bulan sejak Join Date, jadi
satu tanggal untuk semua orang membuat separuh aturannya tidak pernah
teruji. Yang diseed mencakup keempat keadaan:

* sudah lama bekerja      → jatah penuh
* berhak pertengahan tahun → prorata
* belum genap setahun      → nol, dengan alasan yang bisa dibaca
* baru masuk bulan lalu    → nol tahun ini, prorata tahun depan
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.db import transaction

from apps.accounts.models import Role
from apps.accounts.seeds.role_authority import authority_entries
from apps.accounts.services.role_assignment import assign_roles
from apps.administration.models import (
    Company,
    Location,
    Position,
    RosterCrew,
    Shift,
    WorkCalendar,
    WorkSchedule,
)
from apps.administration.models.references.hr import (
    ContractType,
    EmploymentStatus,
    EmploymentType,
    Gender,
)
from apps.hr.api.site_rotation.services import SiteRotationService
from apps.core.services.demo_password import demo_password
from apps.hr.seeds.demo_accounts import demo_email
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    OrganizationAssignment,
    SiteRotation,
)


# Tanggal acuan seluruh data uji. Dipatok, bukan `today()`: hasil seed
# harus sama setiap kali dijalankan supaya angka yang diuji bisa
# dibandingkan antar-hari.
TODAY = date(2026, 8, 9)


# Dua gelombang di Sagea. Polanya diambil dari master
# (`seed_administration --only=hr-attendance`), tidak dibuat di sini.
CREWS = [
    {
        "code": "CREW-6W",
        "name": "Crew 6 Minggu — Sagea",
        "schedule": "ROS42",
        "work_days": 42,
        "off_days": 14,
        "travel_days": 2,
        "cycle_count": 7,
    },
    {
        "code": "CREW-8W",
        "name": "Crew 8 Minggu — Sagea",
        "schedule": "ROS56",
        "work_days": 56,
        "off_days": 14,
        "travel_days": 2,
        "cycle_count": 5,
    },
]


# Jabatannya bukan hiasan: tiap orang memegang **satu** meja di alur
# persetujuan, dan kalau ada dua meja jatuh ke orang yang sama, engine
# menandai yang belakangan SKIPPED ("sudah terwakili") — alur berlapis
# jadi tidak pernah teruji.
#
# Pembagiannya mengikuti dua alur yang berbeda, dan itu yang paling
# penting dijaga: **kantor pusat tidak ikut menandatangani dokumen
# site, dan sebaliknya.** Role yang sama (`HR-ADMIN`, `HR-MANAGER`)
# dipegang dua orang di dua lokasi; yang memisahkan mereka
# `WorkflowStep.approver_scope`, bukan nama role-nya.
#
# (nomor, nama, jabatan, tanggal masuk, crew, catatan pengujian)
WORKFORCE = [
    # ---------------------------------------------------------------
    # Kantor Pusat Jakarta — tanpa crew, ikut kalender Senin–Jumat.
    # Hanya mengurus cuti pegawai kantor; tidak ada meja site di sini
    # kecuali HRGA, yang memang membelikan tiket untuk semua orang.
    # ---------------------------------------------------------------
    (
        "HO001", "Sarah Wibowo", "HR Manager",
        date(2019, 1, 7), None,
        "HR-MANAGER kantor pusat — meja #3 alur cuti HO",
    ),
    (
        "HO002", "Hesti Rahayu", "HR Officer",
        date(2021, 6, 1), None,
        "HR-ADMIN kantor pusat, jatah penuh",
    ),
    (
        "HO003", "Bimo Nugroho", "Finance Staff",
        date(2025, 8, 15), None,
        "pengaju cuti HO — berhak 15 Ags 2026 → 2026 prorata",
    ),
    (
        "HO004", "Clara Wijaya", "HRGA Officer",
        date(2026, 3, 2), None,
        "HRGA — meja terakhir alur site, terbitkan tiket",
    ),
    (
        "HO005", "Farah Anindita", "Finance Manager",
        date(2018, 4, 16), None,
        "atasan langsung HO003 — meja #1 alur cuti HO",
    ),

    # ---------------------------------------------------------------
    # Site Sagea — pegawai roster. Lima meja pertama alur site ada di
    # sini semua, jadi dokumen site tidak perlu menyeberang ke Jakarta
    # sampai tiketnya benar-benar dibeli.
    # ---------------------------------------------------------------
    (
        "SGA001", "Rinaldo Saputra", "Site Superintendent",
        date(2020, 2, 3), "CREW-6W",
        "atasan langsung pegawai site — meja #3",
    ),
    (
        "SGA002", "Ahmad Sudrajat", "Grade Control Foreman",
        date(2022, 5, 9), "CREW-6W",
        "pengaju cuti/TR site — roster 42/14, jatah penuh",
    ),
    (
        "SGA003", "Bayu Prakoso", "Section Admin",
        date(2025, 8, 15), "CREW-6W",
        "ADMIN-SECTION — meja #1, jatah 2026 prorata",
    ),
    (
        "SGA004", "Citra Halimah", "Site HR Manager",
        date(2021, 11, 1), "CREW-8W",
        "HR-MANAGER site — meja #4, jatah penuh",
    ),
    (
        "SGA005", "Dedi Kurniawan", "Kepala Teknik Tambang",
        date(2024, 4, 22), "CREW-8W",
        "KTT — meja #5, jatah penuh",
    ),
    (
        "SGA006", "Eko Prasetyo", "Site HR Officer",
        date(2026, 7, 1), "CREW-6W",
        "HR-ADMIN site — meja #2, jatah 2026 nol, 2027 prorata",
    ),
]


# Akun + role. Semua yang punya meja butuh akun: approval dijalankan
# lewat akun, dan pegawai tanpa akun tidak pernah jadi approver.
#
# Password-nya diset (dari `DEMO_PASSWORD`) supaya tiap meja bisa dicoba login sendiri
# dari layar — akun tanpa password tidak bisa dipakai memverifikasi
# kotak masuknya benar-benar berisi dokumen yang seharusnya.
# Yang tidak memegang meja fungsional tetap diberi `EMPLOYEE`.
#
# Bukan kelengkapan: role di-`set` di sini, jadi daftar kosong mencabut
# `EMPLOYEE` yang diberikan `seed_security_roles` — dan akun **tanpa
# satu pun role berarti tanpa batasan**, persis kebalikan dari yang
# diinginkan untuk pegawai biasa. `EMPLOYEE` membawa cakupan `own`,
# jadi mereka hanya melihat datanya sendiri.
USERS = {
    "HO001": ("demo.hrmanager", ["HR-MANAGER", "WORKFLOW-ADMIN"]),
    "HO002": ("demo.hradmin", ["HR-ADMIN"]),
    "HO003": ("demo.hostaff", ["EMPLOYEE"]),
    "HO004": ("demo.hrga", ["HRGA"]),
    "HO005": ("demo.homanager", ["EMPLOYEE"]),

    # Meja site memegang role fungsional yang **sama** dengan kantor
    # pusat — `HR-ADMIN` dan `HR-MANAGER` — dan yang memisahkan mereka
    # `approver_scope` pada step, bukan kode role yang berbeda. Itu
    # justru yang dibuktikan `seed_demo_site_travel`: satu role, dua
    # pemegang, dua lokasi, dan dokumen Sagea tidak boleh mendarat di
    # meja Jakarta.
    #
    # Sempat diisi kembaran `HR-ADMIN-SITE`/`HR-MANAGER-SITE` demi
    # cakupan data, dan akibatnya alur site **tidak bisa diajukan sama
    # sekali**: step #4 (HR Manager Site) sengaja tanpa fallback, jadi
    # role yang tidak dipegang siapa pun di lokasi itu menggagalkan
    # seluruh pengajuan.
    #
    # Kedua kembaran itu sudah **dihapus dari katalog**: bedanya cuma
    # cakupan, dan cakupan tidak lagi tinggal di `Role`. Yang dulu
    # membutuhkannya — "HR Admin sebatas lokasinya" — sekarang
    # dinyatakan sebagai kewenangan pada penugasannya.
    "SGA001": ("demo.sitespv", ["EMPLOYEE"]),
    "SGA002": ("demo.sitestaff", ["EMPLOYEE"]),
    "SGA003": ("demo.siteadmin", ["ADMIN-SECTION"]),
    "SGA004": ("demo.sitehrmanager", ["HR-MANAGER"]),
    "SGA005": ("demo.ktt", ["KTT"]),
    "SGA006": ("demo.sitehradmin", ["HR-ADMIN"]),
}



# Kolom identitas dan klasifikasi kepegawaian.
#
# Diisi karena kolom kosong di layar tidak bisa dibedakan dari kolom
# yang **rusak**: "Gender: -" di sebelas baris terbaca seperti data
# yang gagal dimuat, dan itu sudah sempat dilaporkan sebagai bug
# padahal seed-nya memang tidak pernah mengisinya.
#
# Gender diselang-seling, bukan satu nilai untuk semua: kolom yang
# isinya seragam tidak membuktikan kolomnya benar-benar membaca data
# per baris.
#
# (nomor: (kode gender, kode status, kode tipe))
CLASSIFICATION = {
    "HO001": ("F", "ACTIVE", "PERM"),
    "HO002": ("F", "ACTIVE", "PERM"),
    "HO003": ("M", "ACTIVE", "PERM"),
    "HO004": ("F", "PROBATION", "CONT"),
    "HO005": ("F", "ACTIVE", "PERM"),

    "SGA001": ("M", "ACTIVE", "PERM"),
    "SGA002": ("M", "ACTIVE", "PERM"),
    "SGA003": ("M", "ACTIVE", "CONT"),
    "SGA004": ("F", "ACTIVE", "PERM"),
    "SGA005": ("M", "ACTIVE", "PERM"),
    "SGA006": ("M", "PROBATION", "CONT"),
}


# Tanggal lahir. Dua di antaranya sengaja berulang tahun dalam sepekan
# dari `TODAY` supaya widget pengingat ada isinya tanpa harus menunggu
# tanggal tertentu; sisanya tersebar sepanjang tahun.
BIRTH_DATES = {
    "HO001": date(1985, 3, 12),
    "HO002": date(1992, 8, 14),   # H-5 dari TODAY
    "HO003": date(1998, 11, 30),
    "HO004": date(2000, 1, 8),
    "HO005": date(1983, 6, 21),

    "SGA001": date(1988, 9, 2),
    "SGA002": date(1994, 8, 12),  # H-3 dari TODAY
    "SGA003": date(1999, 4, 17),
    "SGA004": date(1990, 12, 5),
    "SGA005": date(1996, 2, 29),  # kabisat — menguji pergeseran ke 1 Mar
    "SGA006": date(2001, 7, 23),
}


# Masa percobaan dan akhir kontrak, relatif terhadap `TODAY` supaya
# hasil seed-nya tidak bergantung tanggal dijalankan.
#
# Empat keadaan sengaja terwakili: masih jauh, mendekat, hari ini, dan
# **sudah lewat** — yang terakhir yang paling perlu terlihat di layar,
# karena orangnya masih masuk kerja tanpa dasar kontrak.
#
# (nomor: (offset probation_end, offset contract_end))
EMPLOYMENT_DATES = {
    "HO004": (5, 40),      # probation habis 5 hari lagi; bucket 31–60
    "SGA006": (12, 75),    # probation H-12; bucket 61–90
    "SGA003": (None, 9),   # kontrak habis 9 hari lagi; bucket ≤30
    "SGA002": (None, -6),  # kontrak SUDAH lewat 6 hari; bucket Expired
}


# Atasan langsung. Pegawai site melapor ke Site Superintendent, staf
# kantor ke manajer departemennya — tanpa ini `reports_to` kosong dan
# tidak ada satu pun pengajuan yang bisa diajukan.
#
# **SGA001 melapor ke SGA004, bukan ke HO001.** Site Superintendent
# yang melapor ke kantor pusat membuat dokumennya sendiri naik ke meja
# Jakarta — persis "nyasar" yang mau dihilangkan.
REPORTS_TO = {
    "HO002": "HO001",
    "HO003": "HO005",
    "HO004": "HO001",
    "HO005": "HO001",

    "SGA002": "SGA001",
    "SGA003": "SGA001",
    "SGA005": "SGA001",
    "SGA006": "SGA001",
    "SGA004": "SGA001",
    "SGA001": "SGA004",
}


# Company dan lokasi tempat seluruh data uji duduk.
#
# **Satu company untuk semuanya, dan itu bukan penyederhanaan.** Batas
# yang tidak pernah dilewati engine approval adalah company — approver
# dari perusahaan lain terhitung kebocoran, bukan eskalasi. Meja HRGA
# pada alur site bercakupan company; kalau pegawai kantor pusat ditaruh
# di perusahaan induk sementara pegawai site di perusahaan operasi,
# meja itu tidak akan pernah menemukan siapa pun dan alur site mati
# tanpa satu pun pesan yang menyebut sebabnya.
COMPANY_CODE = "MMR"

HO_LOCATION_CODE = "JKT-HO"
SITE_LOCATION_CODE = "SAGEA-MINE"

# Shift dari master (`seed_hr_attendance`), bukan dibuat di sini —
# data uji tidak boleh diam-diam menambah baris ke master yang dipakai
# semua orang di dropdown.
OFFICE_SHIFT_CODE = "OFFICE-10"

# **`SITE-DAY`, bukan `SITE`.** Kode yang lama sempat dipakai di sini
# sementara `seed_hr_attendance` justru men-soft-delete-nya, jadi
# pencariannya selalu mengembalikan `None` — seluruh pegawai site
# tersimpan tanpa shift, dan setiap tap-nya berstatus NO SCHEDULE tanpa
# satu pesan pun. Gagalnya diam, dan yang terlihat cuma layar Attendance
# yang kolom jadwalnya kosong.
#
# Ini shift **cadangan**, bukan jadwal sebenarnya: tanggal yang punya
# baris `EmployeeShiftAssignment` memakai shift itu. Yang di sini
# menjawab tanggal yang belum direncanakan.
SITE_SHIFT_CODE = "SITE-DAY"


# Jabatan per pegawai, ditunjuk lewat **kode Position** milik seed
# organisasi.
#
# Dulu tiap pegawai membuat Position-nya sendiri dari nama jabatannya
# (`job_title.upper().replace(" ", "-")`), jadi data uji melahirkan
# jabatan yang tidak ada di struktur mana pun — lengkap dengan
# department dan section yang tidak diisi. Department, section, dan
# garis komando pegawai sekarang **diturunkan dari jabatannya**, jadi
# ketiganya tidak bisa lagi bergeser sendiri-sendiri.
EMPLOYEE_POSITION = {
    "HO001": "MMR-HRM",     # HR Manager
    "HO002": "MMR-HRO",     # HR Officer
    "HO003": "MMR-FINS",    # Finance Staff
    "HO004": "MMR-HRGA",    # HRGA Officer
    "HO005": "MMR-FINM",    # Finance Manager

    "SGA001": "MMR-SSPV",   # Site Superintendent
    "SGA002": "MMR-GCFRM",  # Grade Control Foreman
    "SGA003": "MMR-SADM",   # Section Admin
    "SGA004": "MMR-SHRM",   # Site HR Manager
    "SGA005": "MMR-KTT",    # Kepala Teknik Tambang
    "SGA006": "MMR-SHRO",   # Site HR Officer
}


def resolve_company() -> Company:
    company = (
        Company.objects
        .filter(code=COMPANY_CODE, is_deleted=False)
        .first()
    )

    if company is None:
        raise RuntimeError(
            f"Company {COMPANY_CODE} belum ada di tenant ini. Jalankan "
            "`tenant_command seed_demo_organization` lebih dulu.",
        )

    return company


def resolve_location(*, company: Company, code: str) -> Location:
    """
    Lokasi kerja fisik — **dicari, tidak dibuat**.

    Dulu dibuat di sini kalau belum ada, dan itu yang membuat dua seed
    sama-sama merasa memiliki struktur organisasi: seed ini menulis
    "Jakarta HO"/"Gebe" sementara seed organisasi menulis miliknya
    sendiri, dan lokasi mana yang menempel ke pegawai ditentukan seed
    mana yang kebetulan jalan terakhir. Sekarang pemiliknya satu —
    `seeds/demo/organization.py` — dan seed ini hanya menempatkan orang
    di struktur yang sudah ada.
    """
    location = Location.objects.filter(
        company=company,
        code=code,
        is_deleted=False,
    ).first()

    if location is None:
        raise RuntimeError(
            f"Location {code} belum ada di company {company.code}. "
            "Jalankan `tenant_command seed_demo_organization` lebih dulu.",
        )

    return location


def resolve_office_calendar() -> WorkCalendar | None:
    """
    Kalender kantor Senin–Jumat.

    Wajib dipasang eksplisit ke pegawai HO. Tanpa itu mereka mewarisi
    kalender operasional milik location-nya — tujuh hari kerja seminggu
    — karena `LeaveDayCalculator.resolve_calendar` memenangkan kalender
    yang cocok location sebelum kalender company.
    """
    from apps.administration.services.calendar_resolver import (
        CalendarResolver,
    )

    # Tanpa company: yang dicari kalender kantor bersama, dan sejak
    # cakupan GLOBAL ada, itu persis yang dikembalikan resolver saat
    # company-nya tidak disebut.
    return CalendarResolver.resolve_work_calendar(company_id=None)


def ensure_user(*, employee, username: str, role_codes: list[str]) -> None:
    """
    Akun + role satu pegawai.

    Role-nya di-`set`, bukan di-`add`: kalau ditambah saja, orang yang
    perannya diubah di seed tetap memegang role lamanya, dan dua meja
    berbeda diam-diam jatuh ke orang yang sama. Yang tidak disebut di
    sini — `EMPLOYEE` dari `seed_security_roles`, misalnya — memang
    sengaja ikut tercabut supaya susunannya bisa ditebak.
    """
    User = get_user_model()

    email = demo_email(username)

    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            "email": email,
            "first_name": employee.first_name,
            "last_name": employee.last_name or "",
        },
    )

    # Password dipasang setiap kali, bukan cuma saat akunnya baru: data
    # uji harus bisa dipakai login untuk memeriksa kotak masuk tiap
    # meja, dan akun lama yang password-nya tidak pernah diset akan
    # menolak login tanpa sebab yang terlihat.
    user.set_password(demo_password())

    user.first_name = employee.first_name
    user.last_name = employee.last_name or ""

    # Email ikut ditulis ulang, bukan cuma diisi saat akunnya baru.
    # `defaults=` hanya berlaku untuk baris yang benar-benar dibuat,
    # jadi tenant peragaan yang sudah pernah diseed akan tetap memegang
    # alamat lamanya selamanya — dan surat approval yang sedang
    # diperiksa mendarat di domain yang memang tidak menerima apa pun,
    # tanpa satu pun pesan yang menyebutkannya.
    user.email = email

    user.save(
        update_fields=["password", "first_name", "last_name", "email"],
    )

    if employee.user_id != user.pk:
        employee.user = user
        employee.save(update_fields=["user"])

    roles = list(
        Role.objects.filter(code__in=role_codes, is_deleted=False)
    ) if role_codes else []

    # Keanggotaan **dan** WHERE-nya sekaligus. Sejak Stage 4H tidak ada
    # yang menurunkan kewenangan dari `Role`, jadi memberi role tanpa
    # menyebut cakupannya menghasilkan akun yang tidak melihat apa pun.
    # Maksudnya ada di `apps.accounts.seeds.role_authority`, satu tempat
    # untuk semua seed.
    assign_roles(user, authority_entries(roles))


@transaction.atomic
def seed() -> dict:
    # Gagal di sini, sebelum satu baris pun ditulis, kalau DEMO_PASSWORD kosong.
    demo_password()

    company = resolve_company()

    jakarta = resolve_location(company=company, code=HO_LOCATION_CODE)
    site = resolve_location(company=company, code=SITE_LOCATION_CODE)

    # Jam kerja peragaan: kantor 10:00–18:00, site 07:00–17:00 — sama
    # persis dengan jam tap yang diterbitkan `seed_demo_attendance`.
    # Kalau berbeda, seluruh pegawai kantor tampak telat dua jam setiap
    # hari dan angkanya terbaca seperti bug perhitungan.
    office_shift = Shift.objects.filter(
        code=OFFICE_SHIFT_CODE, is_deleted=False,
    ).first()

    site_shift = Shift.objects.filter(
        code=SITE_SHIFT_CODE, is_deleted=False,
    ).first()

    office_calendar = resolve_office_calendar()

    # Master referensi. Dibaca, bukan dibuat: kalau seed referensi HR
    # belum dijalankan, kolomnya dibiarkan kosong — data uji tidak
    # boleh diam-diam menambah baris ke master yang dipakai semua
    # orang di dropdown.
    genders = {
        row.code: row
        for row in Gender.objects.filter(is_deleted=False)
    }

    statuses = {
        row.code: row
        for row in EmploymentStatus.objects.filter(is_deleted=False)
    }

    types = {
        row.code: row
        for row in EmploymentType.objects.filter(is_deleted=False)
    }

    contract_types = {
        row.code: row
        for row in ContractType.objects.filter(is_deleted=False)
    }

    # Jabatan milik seed organisasi. Dibaca sekali di depan supaya
    # kekurangannya ketahuan sebelum satu pegawai pun ditulis — jabatan
    # yang hilang di tengah jalan meninggalkan separuh data uji berdiri
    # dan separuhnya tidak, dan itu keadaan yang paling sulit dibaca.
    positions = {
        row.code: row
        for row in (
            Position.objects
            .select_related("department", "section")
            .filter(company=company, is_deleted=False)
        )
    }

    missing = sorted(
        set(EMPLOYEE_POSITION.values()) - set(positions)
    )

    if missing:
        raise RuntimeError(
            "Jabatan berikut belum ada di company "
            f"{company.code}: {', '.join(missing)}. Jalankan "
            "`tenant_command seed_demo_organization` lebih dulu.",
        )

    # ------------------------------------------------------------------
    # Gelombang roster
    # ------------------------------------------------------------------

    crews: dict[str, RosterCrew] = {}

    for config in CREWS:
        schedule = WorkSchedule.objects.filter(
            code=config["schedule"],
            is_deleted=False,
        ).first()

        if schedule is None:
            raise RuntimeError(
                f"Work Schedule {config['schedule']} belum ada. "
                "Jalankan `tenant_command seed_hr_attendance` dulu.",
            )

        crew, _ = RosterCrew.objects.update_or_create(
            company=company,
            code=config["code"],
            defaults={
                "name": config["name"],
                "location": site,
                "work_schedule": schedule,
                "cycle_start_date": TODAY,
                "is_deleted": False,
            },
        )

        crews[config["code"]] = crew

    crew_config = {c["code"]: c for c in CREWS}

    # ------------------------------------------------------------------
    # Pegawai
    # ------------------------------------------------------------------

    employees: dict[str, Employee] = {}

    for number, full_name, _job_title, join_date, crew_code, _note in WORKFORCE:
        first_name, _, last_name = full_name.partition(" ")

        gender_code, status_code, type_code = CLASSIFICATION[number]

        slug = f"{first_name}.{last_name}".lower().replace(" ", "")

        employee, _ = Employee.objects.update_or_create(
            employee_number=number,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "gender": genders.get(gender_code),
                "birth_date": BIRTH_DATES.get(number),
                # NIK diturunkan dari nomor pegawai, bukan angka acak:
                # data uji harus sama tiap kali diseed supaya bisa
                # dibandingkan antar-hari.
                #
                # Kode wilayahnya ikut membedakan HO dan site — tanpa
                # itu `HO003` dan `SGA003` yang tanggal masuknya sama
                # menghasilkan NIK kembar, dan NIK kembar di data uji
                # adalah hal yang justru dicari saat menguji import.
                "nik": (
                    f"{'820301' if crew_code else '317101'}"
                    f"{join_date:%d%m%y}"
                    f"0{number[-3:]}"
                ),
                "work_email": f"{slug}@example.test",
                "mobile": f"08{number[-3:]}{join_date:%d%m}00",
                "is_deleted": False,
            },
        )

        crew = crews.get(crew_code) if crew_code else None
        location = site if crew_code else jakarta

        # Jabatan yang menentukan department dan section-nya, bukan
        # sebaliknya. Tiga kolom yang diisi dari satu sumber tidak bisa
        # lagi saling bertentangan — dan pertentangan itu punya akibat
        # yang tidak berbunyi: approver bertipe Kepala Departemen dicari
        # di department pegawainya, sementara meja pertama alur site
        # dicari di section-nya.
        position = positions[EMPLOYEE_POSITION[number]]
        department = position.department

        OrganizationAssignment.objects.update_or_create(
            employee=employee,
            defaults={
                "company": company,
                "location": location,
                "department": department,
                # Section hanya untuk pegawai site: meja #1 alur site
                # dicari per section, sedangkan alur kantor pusat tidak
                # memakainya sama sekali.
                "section": position.section if crew_code else None,
                "position": position,
                "organization_effective_date": join_date,
                "is_active": True,
                "is_deleted": False,
            },
        )

        probation_offset, contract_offset = EMPLOYMENT_DATES.get(
            number,
            (None, None),
        )

        EmploymentAssignment.objects.update_or_create(
            employee=employee,
            defaults={
                "employment_status": statuses.get(status_code),
                "employment_type": types.get(type_code),
                # `clean()` mewajibkan contract start + contract type
                # begitu tanggal akhirnya diisi, jadi dua kolom itu ikut.
                #
                # Begitu juga probation: tanggal akhir tanpa tanggal
                # mulai ditolak `clean()`. Seed menulis lewat `save()`
                # yang tidak memanggil `full_clean()`, jadi barisnya
                # tersimpan dan kegagalannya baru muncul di layar —
                # menyimpan pegawai itu ditolak dengan alasan kolom yang
                # tidak pernah disentuh siapa pun.
                "probation_start": (
                    join_date if probation_offset is not None else None
                ),
                "probation_end": (
                    TODAY + timedelta(days=probation_offset)
                    if probation_offset is not None
                    else None
                ),
                "contract_start": (
                    join_date if contract_offset is not None else None
                ),
                "contract_type": (
                    contract_types.get("PKWT")
                    or next(iter(contract_types.values()), None)
                    if contract_offset is not None
                    else None
                ),
                "contract_end": (
                    TODAY + timedelta(days=contract_offset)
                    if contract_offset is not None
                    else None
                ),
                "join_date": join_date,
                # Pola kerja wajib sama dengan milik crew — `clean()`
                # menolak dua pola yang bertentangan.
                "work_schedule": (
                    crew.work_schedule if crew is not None else None
                ),
                "roster_crew": crew,
                # Shift = **jam**-nya, dan tanpa ini seluruh perhitungan
                # keterlambatan mati tanpa suara: `scheduled_window()`
                # tidak menemukan jam kerja, `scheduled_check_in`
                # dibiarkan kosong, dan `AttendancePolicyResolver`
                # melewati barisnya. Toleransi yang sudah diatur di
                # layar Attendance Policy tidak pernah dievaluasi.
                #
                # Untuk pegawai roster ini **satu-satunya** sumber jam:
                # `WorkSchedule` bertipe ROSTER tidak menyimpannya, dan
                # `WorkScheduleDay` berbasis hari-dalam-minggu yang
                # tidak cocok dengan siklus 42/14.
                "shift": site_shift if crew is not None else office_shift,
                "working_calendar": (
                    None if crew is not None else office_calendar
                ),
                "job_location": location.name,
                "is_deleted": False,
            },
        )

        employees[number] = employee

    # ------------------------------------------------------------------
    # Garis pelaporan + akun pengguna
    # ------------------------------------------------------------------
    #
    # Dipasang setelah semua pegawai ada: atasan harus sudah tersimpan
    # sebelum bisa ditunjuk bawahannya.

    for number, supervisor_number in REPORTS_TO.items():
        OrganizationAssignment.objects.filter(
            employee=employees[number],
        ).update(reports_to=employees[supervisor_number])

    for number, (username, role_codes) in USERS.items():
        ensure_user(
            employee=employees[number],
            username=username,
            role_codes=role_codes,
        )

    # ------------------------------------------------------------------
    # Dokumen roster pegawai site
    # ------------------------------------------------------------------

    rotations = 0

    for number, _name, _title, _join, crew_code, _note in WORKFORCE:
        if not crew_code:
            continue

        config = crew_config[crew_code]
        employee = employees[number]

        fields = {
            "company": company,
            "location": site,
            "roster_crew": crews[crew_code],
            "cycle_work_days": config["work_days"],
            "cycle_off_days": config["off_days"],
            "cycle_travel_days": config["travel_days"],
            "cycle_count": config["cycle_count"],
            "status": "planned",
        }

        existing = (
            SiteRotation.objects
            .filter(employee=employee, start_date=TODAY, is_deleted=False)
            .first()
        )

        # Lewat service, bukan ORM langsung: nomor dokumen diambil dari
        # pola penomoran dan `full_clean()` benar-benar jalan, jadi
        # bentuk dokumennya sama dengan buatan pengguna.
        if existing is None:
            rotation = SiteRotationService.create(
                data={
                    "employee": employee,
                    "start_date": TODAY,
                    **fields,
                },
            )
        else:
            rotation = SiteRotationService.update(
                instance=existing,
                data=fields,
            )

        SiteRotationService.generate_periods(rotation=rotation, force=True)

        rotations += 1

    # Tidak ada backfill di sini: kewenangan sudah disebut saat tiap
    # penugasan dibuat (`authority_entries`). Perkakas backfill-nya
    # sendiri sudah dihapus di gelombang C — ia menurunkan WHERE dari
    # konfigurasi cakupan lama, dan konfigurasi itu tidak ada lagi.

    return {
        "company": company.name,
        "employees": len(employees),
        "ho": sum(1 for row in WORKFORCE if row[4] is None),
        "site": sum(1 for row in WORKFORCE if row[4]),
        "crews": len(crews),
        "rotations": rotations,
        "office_calendar": (
            office_calendar.code if office_calendar else None
        ),
    }
