"""
Pemeran Organization Scope di tenant peragaan: dua BOD dan dua GM.

Kenapa berkas tersendiri, bukan tambahan baris di `demo_employees.py`
-------------------------------------------------------------------
Seed pegawai peragaan yang sudah ada **terkunci ke satu company**
(`COMPANY_CODE = "MMR"`): jabatan, cost center, dan kalendernya semua
dicari di perusahaan itu. Itu keputusan yang disengaja dan masih benar
— approver lintas company terhitung kebocoran, jadi seluruh panggung
dokumen memang harus berdiri di satu badan usaha.

Yang dibutuhkan Organization Scope justru kebalikannya: orang yang
**tidak** semuanya duduk di company yang sama, supaya "boleh melihat
data organisasi yang mana" punya sesuatu untuk dibedakan. Karena itu
empat orang ini berdiri di berkas sendiri, memakai struktur organisasi
peragaan yang sudah ada apa adanya, dan tidak menyentuh satu baris pun
milik 26 pegawai yang sudah berdiri.

Tiga tingkat cakupan yang dibentuk
----------------------------------
Ketiganya memakai mekanisme kewenangan penugasan (`RoleAssignment`)
yang sudah ada — tidak ada tabel, kolom, atau lapisan penjagaan baru.

* **BOD** — `explicit`, satu baris per company peragaan (MNI + MMR +
  MLS). Inilah bentuk "Company multi-select": satu role memegang tiga
  baris `company`, dan ketiganya di-OR-kan. Dipakai menguji laporan
  gabungan seluruh grup.
* **GM/Executive kantor pusat** — role `EXECUTIVE`, kewenangan
  `explicit` berisi **MMR** (company penempatannya sendiri) **dan MLS**
  (company kedua yang tidak bisa dijelaskan penempatannya). Company
  tambahan itu ditulis sebagai kewenangan pada penugasannya, bukan
  dengan membuat role baru per kombinasi.
* **GM/Executive site** — role `EXECUTIVE` yang **sama**, tapi
  kewenangannya bermode "ikut penempatan pemegang" sedalam
  **location**.

  Inilah yang dulu butuh role tersendiri (`EXECUTIVE-SITE`) dan sekarang
  tidak lagi: waktu WHERE masih tinggal di `Role`, satu role cuma bisa
  punya satu cakupan, jadi "GM pusat lintas company" dan "GM site sebatas
  lokasinya" memaksa dua baris di katalog. Sejak WHERE pindah ke
  penugasan, keduanya **satu role dengan dua kewenangan** — dan dua
  pemeran di bawah memperagakan tepat itu.

Employee Group **tidak** menentukan hak akses
---------------------------------------------
Keempatnya memakai group yang sudah ada di master (`BOARD`,
`EXECUTIVE`) dan group itu tetap **lepas dari lokasi**: GM kantor pusat
dan GM site sama-sama `EXECUTIVE`. Yang membedakan keduanya Organization
Scope-nya, bukan group-nya — dan tidak ada satu baris kode pun di sini
yang membaca `employee_group` untuk memutuskan akses.

Aman diulang.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import transaction

from apps.accounts.models import (
    AuthorityMode,
    AuthorityResourceType,
    DataScopeLevel,
    Role,
)
from apps.accounts.seeds.role_authority import authority_entry
from apps.accounts.services.role_assignment import assign_roles
from apps.administration.models import Company, Location, Position
from apps.administration.models.references.hr_attendance import (
    Shift,
    WorkSchedule,
)
from apps.administration.models.references.hr import (
    EmployeeGroup,
    EmploymentStatus,
    EmploymentType,
    Gender,
)
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    OrganizationAssignment,
)
from apps.core.services.demo_password import demo_password
from apps.hr.seeds.demo_accounts import demo_email


User = get_user_model()


# Tanggal acuan, dipatok — sama dengan seed pegawai peragaan lainnya.
TODAY = date(2026, 8, 9)


# Seluruh company peragaan. Urutannya kode, bukan selera: dipakai apa
# adanya sebagai cakupan role BOD.
DEMO_COMPANY_CODES = ["MNI", "MMR", "MLS"]


# ======================================================================
# Role
# ======================================================================
#
# Izinnya sengaja **hanya `view`**. Ketiganya meja pembaca: yang
# dibuktikan di sini seberapa luas datanya, bukan apa yang boleh
# diubahnya. Kemampuan mengajukan cuti/perjalanan sendiri tetap datang
# dari role `EMPLOYEE` yang ikut dipegang — role di-OR, jadi menambah
# `EMPLOYEE` tidak melebarkan cakupan (barisnya bermode `own`).
#
# Yang **tidak boleh** diberikan ke keempat orang ini: role bermode
# `all` (HR-MANAGER, HR-ADMIN, SYSTEM-ADMIN, …). Satu saja di antaranya
# mengembalikan seluruh tenant dan seluruh pengujian ini jadi tidak
# membuktikan apa pun.

VIEW_APPS = ["hr", "administration"]


SCOPE_ROLES = [
    {
        "code": "BOD",
        "name": "Board of Directors",
        "description": (
            "Direksi grup. Membaca data seluruh company yang dicentang "
            "di daftar company peragaan. Cakupannya ditulis eksplisit "
            "per company supaya bisa dipersempit tanpa mengubah role."
        ),
        "mode": AuthorityMode.EXPLICIT,
        "level": "",
    },
    {
        "code": "EXECUTIVE",
        "name": "Executive",
        # Namanya **tidak** menyebut cakupan, dan itu disengaja: role ini
        # dipegang GM kantor pusat (lintas company) **dan** GM site
        # (sebatas lokasinya). Nama yang menjanjikan salah satunya akan
        # salah untuk separuh pemegangnya.
        "description": (
            "GM/Executive. Seberapa luas datanya ditentukan kewenangan "
            "pada penugasannya masing-masing — lintas company untuk GM "
            "kantor pusat, sebatas lokasi untuk GM site — bukan oleh "
            "role ini."
        ),
        "mode": AuthorityMode.PLACEMENT,
        "level": DataScopeLevel.COMPANY,
    },
]


# WHERE role BOD, yang tidak bisa ditulis di tabel bersama.
#
# Kewenangan lain datang dari `apps.accounts.seeds.role_authority` —
# satu tempat untuk seluruh katalog role hasil seed. BOD pengecualian
# karena nilainya **id company peragaan**, yang baru ada saat seed
# berjalan; tabel bersama hanya boleh memuat yang tidak bergantung pada
# data tenant.
#
# `Role.data_scope_*` di `SCOPE_ROLES` di atas tetap diisi: layar Roles
# masih menampilkannya dan perkakas cutover masih membacanya untuk
# tenant yang belum dialihkan. Ia tidak lagi menentukan apa pun saat
# penugasan dibuat, dan itu memang yang dikehendaki.
BOD_ROLE_CODE = "BOD"


# ======================================================================
# Pemeran
# ======================================================================


@dataclass(frozen=True)
class ScopePerson:
    number: str
    name: str
    company: str                    # kode Company
    location: str                   # kode Location
    position: str                   # kode Position
    group: str                      # kode EmployeeGroup
    username: str
    roles: tuple[str, ...]
    join: date
    birth: date
    gender: str
    reports_to: str | None = None   # nomor pegawai
    # Company tambahan di luar yang tersirat dari penempatannya.
    # Ditulis sebagai kewenangan penugasan, bukan role baru.
    extra_companies: tuple[str, ...] = ()
    # Tingkat "ikut penempatan pemegang" **untuk orang ini**, per kode
    # role: `{"EXECUTIVE": DataScopeLevel.LOCATION}`.
    #
    # Ada karena satu role sekarang boleh dipegang dengan kewenangan yang
    # berbeda-beda. `SEED_ROLE_AUTHORITY` menyatakan bawaan **per role**,
    # dan bawaan itu benar untuk mayoritas; yang tidak, dinyatakan di
    # sini alih-alih dengan menambah role baru ke katalog. Itu persis
    # pertukaran yang dibuat gelombang C: kombinasi pindah dari katalog
    # role ke penugasan.
    placement_level_by_role: tuple[tuple[str, str], ...] = ()
    note: str = ""


HO_LOCATION_CODE = "JKT-HO"

OFFICE_SHIFT_CODE = "OFFICE-10"
SITE_SHIFT_CODE = "SITE-DAY"
OFFICE_SCHEDULE_CODE = "REG5"


PEOPLE = [
    ScopePerson(
        number="BOD001", name="Wirawan Adisurya",
        company="MNI", location="JKT-HO", position="MNI-DIR",
        group="BOARD", username="demo.bod1", roles=("BOD", "EMPLOYEE"),
        join=date(2015, 1, 5), birth=date(1968, 2, 17), gender="M",
        reports_to=None,
        note="Presiden Direktur — cakupan seluruh company peragaan",
    ),
    ScopePerson(
        number="BOD002", name="Lestari Handayani",
        company="MNI", location="JKT-HO", position="MNI-DIR",
        group="BOARD", username="demo.bod2", roles=("BOD", "EMPLOYEE"),
        join=date(2016, 3, 1), birth=date(1972, 9, 4), gender="F",
        reports_to="BOD001",
        note="Direktur Operasi — cakupan seluruh company peragaan",
    ),
    ScopePerson(
        number="HO009", name="Gunawan Prasetyo",
        company="MMR", location="JKT-HO", position="MMR-GMHO",
        group="EXECUTIVE", username="demo.gmho", roles=("EXECUTIVE", "EMPLOYEE"),
        join=date(2018, 7, 2), birth=date(1976, 11, 22), gender="M",
        reports_to="BOD002",
        # MMR datang dari penempatannya (`own` sedalam company); MLS
        # ditambahkan per orang. Dua company, dan **MNI sengaja tidak
        # ikut** — itu yang membuat angkanya berbeda dari BOD dan
        # membuat pengujian membuktikan sesuatu.
        extra_companies=("MLS",),
        note="GM kantor pusat — menguji laporan gabungan MMR + MLS",
    ),
    ScopePerson(
        number="SGA011", name="Bayu Nugraha",
        company="MMR", location="SAGEA-MINE", position="MMR-GMSITE",
        group="EXECUTIVE", username="demo.gmsite",
        # Role yang **sama** dengan GM kantor pusat; yang membedakan
        # keduanya kewenangan penugasannya, bukan kode role-nya.
        roles=("EXECUTIVE", "EMPLOYEE"),
        placement_level_by_role=(("EXECUTIVE", DataScopeLevel.LOCATION),),
        join=date(2019, 5, 13), birth=date(1980, 6, 30), gender="M",
        reports_to="HO009",
        note="GM site Sagea — cakupan sebatas lokasinya sendiri",
    ),
]


# ======================================================================
# Penyusunan
# ======================================================================


def _view_permissions() -> list[Permission]:
    """
    Izin `view` untuk seluruh model di app yang disebut.

    Sengaja tidak lewat `_permissions()` di `security_roles.py`: yang di
    sana memberi keempat kata kerja sekaligus per app, dan meja pembaca
    tidak boleh ikut mendapat `add`/`change`/`delete` seluruh HR.
    """
    return list(
        Permission.objects.filter(
            content_type__app_label__in=VIEW_APPS,
            codename__startswith="view_",
        )
    )


def _ensure_roles(log) -> dict[str, Role]:
    permissions = _view_permissions()

    roles: dict[str, Role] = {}

    for config in SCOPE_ROLES:
        role = Role.objects.filter(
            code=config["code"], is_deleted=False,
        ).first()

        if role is None:
            role = Role(code=config["code"])

        role.name = config["name"]
        role.description = config["description"]
        role.is_active = True
        role.is_deleted = False

        # `update_fields` untuk role yang sudah ada: `save()` penuh
        # menulis kolom cakupan lama juga — nilainya tidak berubah,
        # tapi seed produksi tidak boleh muncul sebagai penulis skema
        # itu sama sekali. Baris baru membawanya dengan bawaan model.
        if role.pk:
            role.save(update_fields=[
                "name",
                "description",
                "is_active",
                "is_deleted",
                "updated_at",
            ])
        else:
            role.save()

        # `add`, bukan `set` — role yang sudah disunting orang di layar
        # Roles tidak boleh dikembalikan ke bawaan tiap seed jalan.
        role.permissions.add(*permissions)

        roles[config["code"]] = role

        # Maksudnya dicetak dari tabel, bukan dari kolom di database:
        # kolom itu tidak ditulis seed ini lagi (Stage 4I), jadi
        # membacanya akan memperlihatkan nilai lama seolah-olah baru
        # saja ditetapkan di sini.
        log(
            f"  {config['code']:16} {role.permissions.count():4} izin  "
            f"maksud cakupan: {config['mode']}"
            + (f" / {config['level']}" if config["level"] else "")
        )

    return roles


# `_ensure_bod_scope()` **dibuang di Stage 4I**, dan perkakas yang dulu
# menggantikannya ikut hilang di gelombang C bersama skema lamanya.
#
# Ia menulis satu baris cakupan lama per company peragaan sebagai garis
# dasar pembanding peralihan. Baris itu tidak menentukan akses siapa pun
# — yang berlaku `_authority_entry()` di bawah.


def _authority_entry(role, companies, person: ScopePerson) -> dict:
    """Entri `{"role": id, ...}` untuk `assign_roles()`."""
    override = dict(person.placement_level_by_role).get(role.code)

    if override:
        # Dinyatakan untuk orang ini, bukan diturunkan dari kode role.
        return {
            "role": role.pk,
            "authority_mode": AuthorityMode.PLACEMENT,
            "authority_level": override,
        }

    if role.code != BOD_ROLE_CODE:
        return authority_entry(role)

    # Direksi grup: company peragaan yang disebut, satu per satu.
    return {
        "role": role.pk,
        "authority_mode": AuthorityMode.EXPLICIT,
        "authorities": [
            {
                "resource_type": AuthorityResourceType.COMPANY,
                "resource_id": company.id,
            }
            for code in DEMO_COMPANY_CODES
            if (company := companies.get(code)) is not None
        ],
    }


def _ensure_user(*, employee, person: ScopePerson, roles_by_code,
                 companies) -> None:
    username = person.username

    email = demo_email(username)

    first_name, _, last_name = person.name.partition(" ")

    user, _created = User.objects.get_or_create(
        username=username,
        defaults={
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
        },
    )

    user.set_password(demo_password())
    user.first_name = first_name
    user.last_name = last_name
    user.email = email

    user.save(
        update_fields=["password", "first_name", "last_name", "email"],
    )

    if employee.user_id != user.pk:
        employee.user = user
        employee.save(update_fields=["user"])

    roles = [
        role
        for role in (
            roles_by_code.get(code)
            or Role.objects.filter(code=code, is_deleted=False).first()
            for code in person.roles
        )
        if role is not None
    ]

    # Keanggotaan **dan** WHERE-nya dalam satu transaksi. Tidak ada
    # jendela waktu ketika role sudah dipegang tapi kewenangannya belum
    # ditentukan — dan kalaupun ada, arahnya tertutup.
    assign_roles(
        user,
        [_authority_entry(role, companies, person) for role in roles],
    )


def _ensure_extra_companies(
    *,
    user,
    person: ScopePerson,
    companies: dict[str, Company],
) -> int:
    """
    Company tambahan seorang pengguna, di luar penempatannya.

    **Ditulis sebagai kewenangan penugasan, bukan cakupan per-orang.**
    Yang lama menempel pada orangnya tanpa menyebut role, jadi satu
    baris melebarkan **setiap** izin yang dipegangnya sekaligus — GM
    yang diberi company kedua untuk pengawasan kepegawaian ikut membuka
    slip gaji company itu lewat role `EMPLOYEE`-nya. Sekarang
    kewenangannya menempel pada penugasan yang memang memberi izinnya.

    Penugasan sasarannya **role pertama pemegangnya yang bukan
    `EMPLOYEE`** — role fungsional orang itu. `EMPLOYEE` sengaja
    dilewati: ia ada untuk layanan mandiri (`own`), dan menempelkan
    company ke sana justru menghasilkan irisan "data saya **dan** di
    company itu", bukan pelebaran.

    Modenya dijadikan `EXPLICIT`, dan nilai yang selama ini diturunkan
    dari penempatan **dimaterialkan lebih dulu** — tanpa itu, berpindah
    dari `PLACEMENT` akan mencabut company asalnya.
    """
    from apps.accounts.models import (
        AuthorityMode,
        RoleAssignment,
        RoleAssignmentAuthority,
    )
    from apps.accounts.scoping import DataScopeService

    wanted = {
        company.id
        for code in person.extra_companies
        if (company := companies.get(code)) is not None
    }

    if not wanted:
        return 0

    assignment = (
        RoleAssignment.objects
        .filter(user=user, role__is_deleted=False)
        .exclude(role__code="EMPLOYEE")
        .select_related("role")
        .order_by("role__code")
        .first()
    )

    if assignment is None:
        return 0

    # **Company penempatannya selalu ikut, apa pun mode saat ini.**
    #
    # Kontrak daftar `extra_companies` adalah "company **tambahan**, di
    # luar penempatannya" — jadi hasilnya penempatan + tambahan.
    # Sempat hanya dimaterialkan saat modenya masih `PLACEMENT`, dan
    # itu salah ke arah yang berbahaya: pada tenant yang sudah
    # dialihkan modenya sudah `EXPLICIT`, cabangnya terlewat, lalu
    # penulisan ulang di bawah menghapus company asalnya. Menjalankan
    # ulang seed menyempitkan orangnya dari {MMR, MLS} jadi {MLS} —
    # tanpa satu pun pesan.
    placement = DataScopeService._placement(user)

    home = placement.get("company")

    if home is not None:
        wanted.add(home)

    assignment.authority_mode = AuthorityMode.EXPLICIT
    assignment.authority_level = ""

    assignment.save(update_fields=["authority_mode", "authority_level"])

    # Ditulis ulang seluruhnya supaya daftar di berkas ini tetap jadi
    # satu-satunya sumber — baris sisa dari konfigurasi lama akan terus
    # memberi akses yang tidak pernah lagi disebutkan siapa pun.
    RoleAssignmentAuthority.objects.filter(
        assignment=assignment,
        resource_type=AuthorityResourceType.COMPANY,
    ).delete()

    RoleAssignmentAuthority.objects.bulk_create([
        RoleAssignmentAuthority(
            assignment=assignment,
            resource_type=AuthorityResourceType.COMPANY,
            resource_id=company_id,
        )
        for company_id in sorted(wanted)
    ])

    return len(wanted)


@transaction.atomic
def seed(*, log=None) -> dict:
    log = log or (lambda *args: None)

    # Gagal di sini, sebelum satu baris pun ditulis, kalau DEMO_PASSWORD kosong.
    demo_password()

    companies = {
        row.code: row
        for row in Company.objects.filter(
            code__in=DEMO_COMPANY_CODES, is_deleted=False,
        )
    }

    missing_companies = [
        code for code in DEMO_COMPANY_CODES if code not in companies
    ]

    if missing_companies:
        raise RuntimeError(
            f"Company {', '.join(missing_companies)} belum ada. Jalankan "
            "`tenant_command seed_demo_organization` lebih dulu.",
        )

    # Lokasi dan jabatan **dicari, tidak dibuat**. Seed ini menempatkan
    # orang di struktur yang sudah ada; kalau ia ikut membuat masternya
    # saat tidak ketemu, dua seed sama-sama merasa memiliki struktur
    # organisasi dan yang menempel ke pegawai ditentukan seed mana yang
    # kebetulan jalan terakhir.
    locations: dict[tuple[str, str], Location] = {}
    positions: dict[str, Position] = {}

    for person in PEOPLE:
        key = (person.company, person.location)

        if key not in locations:
            location = Location.objects.filter(
                company=companies[person.company],
                code=person.location,
                is_deleted=False,
            ).first()

            if location is None:
                raise RuntimeError(
                    f"Location {person.location} belum ada di company "
                    f"{person.company}. Jalankan "
                    "`tenant_command seed_demo_organization` lebih dulu.",
                )

            locations[key] = location

        if person.position not in positions:
            position = (
                Position.objects
                .select_related("department", "section", "division")
                .filter(
                    company=companies[person.company],
                    code=person.position,
                    is_deleted=False,
                )
                .first()
            )

            if position is None:
                raise RuntimeError(
                    f"Jabatan {person.position} belum ada di company "
                    f"{person.company}. Jalankan "
                    "`tenant_command seed_demo_organization` lebih dulu "
                    "(jabatan GM peragaan ditambahkan di sana).",
                )

            positions[person.position] = position

    genders = {row.code: row for row in Gender.objects.filter(is_deleted=False)}
    groups = {
        row.code: row for row in EmployeeGroup.objects.filter(is_deleted=False)
    }
    statuses = {
        row.code: row for row in EmploymentStatus.objects.filter(is_deleted=False)
    }
    types = {
        row.code: row for row in EmploymentType.objects.filter(is_deleted=False)
    }

    # Master jam kerja. Dibaca, bukan dibuat — data uji tidak boleh
    # diam-diam menambah baris ke master yang dipakai semua orang.
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

    for code in ("BOARD", "EXECUTIVE"):
        if code not in groups:
            warnings.append(
                f"Employee Group '{code}' belum ada di master — kolomnya "
                "dikosongkan. Jalankan "
                "`tenant_command seed_administration --only=hr-reference`.",
            )

    # ------------------------------------------------------------------
    # Role + cakupan role
    # ------------------------------------------------------------------
    log("\nRole cakupan:")

    roles_by_code = _ensure_roles(log)

    # ------------------------------------------------------------------
    # Pegawai + akun
    # ------------------------------------------------------------------
    employees: dict[str, Employee] = {}

    for person in PEOPLE:
        first_name, _, last_name = person.name.partition(" ")

        employee, _ = Employee.objects.update_or_create(
            employee_number=person.number,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "gender": genders.get(person.gender),
                "birth_date": person.birth,
                # NIK diturunkan dari nomor pegawai, bukan angka acak:
                # hasil seed harus sama tiap kali dijalankan.
                "nik": (
                    f"317101{person.join:%d%m%y}"
                    f"9{person.number[-3:]}"
                ),
                "work_email": demo_email(person.username),
                "mobile": f"08{person.number[-3:]}{person.join:%d%m}99",
                "is_active": True,
                "is_deleted": False,
            },
        )

        employees[person.number] = employee

        _ensure_user(
            employee=employee,
            person=person,
            roles_by_code=roles_by_code,
            companies=companies,
        )

    # ------------------------------------------------------------------
    # Penempatan. Dua lintasan: garis pelaporan menunjuk sesama pemeran
    # di daftar ini, jadi orangnya harus berdiri semua lebih dulu.
    # ------------------------------------------------------------------
    for person in PEOPLE:
        position = positions[person.position]

        OrganizationAssignment.objects.update_or_create(
            employee=employees[person.number],
            defaults={
                "company": companies[person.company],
                "branch": (
                    companies[person.company].branches
                    .filter(is_deleted=False).order_by("code").first()
                ),
                "location": locations[(person.company, person.location)],
                "division": position.division,
                "department": position.department,
                "section": position.section,
                "position": position,
                "reports_to": (
                    employees.get(person.reports_to)
                    if person.reports_to
                    else None
                ),
                "organization_effective_date": person.join,
                "is_active": True,
                "is_deleted": False,
            },
        )

        # Shift dan pola kerja ikut diisi, dan itu bukan kelengkapan
        # kosmetik: `scheduled_window()` yang tidak menemukan jam kerja
        # mengembalikan `(None, None)`, jadi seluruh tap orang ini
        # berstatus NO SCHEDULE dan tidak satu pun toleransi
        # `AttendancePolicy` dievaluasi. Gagalnya diam — yang terlihat
        # cuma kolom jadwal yang kosong di layar Attendance.
        #
        # Untuk pegawai roster ini shift **cadangan**: tanggal yang
        # sudah punya `EmployeeShiftAssignment` memakai shift itu.
        at_site = person.location != HO_LOCATION_CODE

        EmploymentAssignment.objects.update_or_create(
            employee=employees[person.number],
            defaults={
                "employment_status": statuses.get("ACTIVE"),
                "employment_type": types.get("PERM"),
                "employee_group": groups.get(person.group),
                "join_date": person.join,
                "shift": site_shift if at_site else office_shift,
                "work_schedule": None if at_site else office_schedule,
                "is_active": True,
                "is_deleted": False,
            },
        )

    # ------------------------------------------------------------------
    # Cakupan tambahan per orang
    # ------------------------------------------------------------------
    extra_rows = 0

    log("\nCompany tambahan (kewenangan penugasan):")

    for person in PEOPLE:
        if not person.extra_companies:
            continue

        user = employees[person.number].user

        if user is None:
            continue

        count = _ensure_extra_companies(
            user=user,
            person=person,
            companies=companies,
        )

        extra_rows += count

        log(
            f"  {person.username:16} +{count} company: "
            + ", ".join(person.extra_companies)
        )

    if not extra_rows:
        log("  (tidak ada)")

    # **Tidak ada backfill di sini, dan itu disengaja.**
    #
    # Sampai Stage 4G seed ini memanggil backfill untuk menutup
    # penugasan yang lahir kosong. Sejak 4H penugasan tidak lahir
    # kosong lagi — kewenangannya disebut saat dibuat — dan sejak
    # gelombang C perkakas backfill-nya tidak ada lagi: ia membaca
    # kolom dan tabel cakupan lama yang sudah dihapus. Penugasan yang
    # kewenangannya belum dinyatakan dilaporkan
    # `audit_authority_hygiene`.

    return {
        "people": len(PEOPLE),
        "roles": len(SCOPE_ROLES),
        "companies": len(companies),
        "extra_rows": extra_rows,
        "warnings": warnings,
    }
