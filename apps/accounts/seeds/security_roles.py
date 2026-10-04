"""
Mengisi izin per model ke role, lalu menugaskannya.

Ini yang harus dijalankan **sebelum** `ENFORCE_MODEL_PERMISSIONS`
dinyalakan. Urutannya bukan selera: menyalakan penjagaan di tenant yang
seluruh role-nya kosong membuat sistem read-only untuk semua orang
kecuali superuser — termasuk untuk orang yang sedang mengisi role-nya.

Yang diberikan di sini adalah **titik awal yang masuk akal, bukan
kebijakan final**. Sesudah ini seluruh pengaturannya pindah ke layar
Roles: centang per model, per tenant, tanpa rilis kode. Itu maksud
"fleksibel" — matriks di bawah cuma supaya sistem tidak lumpuh di menit
pertama penjagaannya menyala.

Aman diulang: izin ditambahkan (`add`), tidak pernah dicabut. Role yang
sudah disunting orang tidak akan dikembalikan ke bawaan.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import transaction

from apps.accounts.models import AuthorityMode, Role
from apps.accounts.services.role_assignment import grant_role


User = get_user_model()


# Role dasar untuk pegawai biasa. Tanpa ini, orang yang tidak memegang
# role apa pun kehilangan kemampuan mengajukan cuti dan perjalanannya
# sendiri begitu penjagaan menyala — dan itu justru orang terbanyak di
# sistem.
EMPLOYEE_ROLE = "EMPLOYEE"


# Matriks bawaan. `apps` = seluruh model di app tersebut, `models` =
# daftar `app_label.model_name` tertentu.
GRANTS: list[dict] = [
    {
        "code": "SYSTEM-ADMIN",
        "name": "System Administrator",
        "description": (
            "Seluruh izin. Dipegang orang yang menyiapkan sistem, bukan "
            "peran operasional sehari-hari."
        ),
        "apps": "*",
    },
    {
        "code": "HR-ADMIN",
        "name": "HR Admin",
        "description": "Mengelola data kepegawaian dan master pendukungnya.",
        "apps": ["hr", "administration"],
        # PF-0G: menerbitkan run koreksi payroll. Sengaja lewat
        # `codenames` — `apps` di atas tidak memuat payroll, dan izin ini
        # memang bukan CRUD payroll melainkan satu kemampuan tersendiri.
        "codenames": ["payroll.correct_payrollrun"],
    },
    {
        "code": "HR-MANAGER",
        "name": "HR Manager",
        "description": "Mengelola data kepegawaian dan master pendukungnya.",
        "apps": ["hr", "administration"],
        "codenames": ["payroll.correct_payrollrun"],
    },
    {
        "code": "HRGA",
        "name": "HR & General Affairs",
        "description": "Mengelola perjalanan dinas dan data kepegawaian.",
        "apps": ["hr"],
    },
    {
        "code": "SECURITY-ADMIN",
        "name": "Security Administrator",
        "description": "Mengelola pengguna, role, dan hak akses.",
        "apps": ["accounts"],
    },
    {
        "code": "WORKFLOW-ADMIN",
        "name": "Workflow Administrator",
        "description": "Mengonfigurasi alur persetujuan.",
        "apps": ["workflow"],
    },
    {
        # Yang menyiapkan akuntansinya: bagan akun, tahun buku,
        # periode, dimensi, kebijakan, dan pemetaan akun. **Bukan**
        # peran harian — menyusun bagan akun dikerjakan sekali saat
        # sistem disiapkan lalu sesekali sesudahnya.
        #
        # `apps: ["finance"]` ikut memberikan kedua izin kustom
        # (`post_soft_closed_period`, `reopen_locked_period`): yang
        # memegang kunci periodenya memang harus bisa membukanya
        # kembali.
        "code": "FINANCE-ADMIN",
        "name": "Finance Administrator",
        "description": (
            "Menyiapkan akuntansi: bagan akun, tahun buku, periode, "
            "dimensi, kebijakan, dan pemetaan akun."
        ),
        "apps": ["finance"],
    },
    {
        # Role ini **sudah ada** sebelum Finance dibangun — ia meja
        # kedua alur payroll, dan `READ_GRANTS` di bawah memberinya
        # akses baca payroll. Yang ditambahkan di sini pekerjaan
        # akuntansinya: membuat, menyunting, dan memposting jurnal.
        #
        # Sengaja **tanpa** izin ke master akuntansi. Bagan akun dan
        # kebijakan adalah keputusan yang dibuat sekali dan dipakai
        # ribuan kali; yang membukukan transaksi harian tidak perlu —
        # dan tidak boleh diam-diam bisa — mengubah akun tujuan sebuah
        # kebijakan untuk membetulkan satu jurnal.
        "code": "FINANCE-MANAGER",
        "name": "Finance Manager",
        "description": (
            "Membukukan dan menyetujui jurnal. Master akuntansi "
            "dipegang Finance Administrator."
        ),
        "models": [
            "finance.journal",
            "finance.journalline",
            "finance.journallinedimension",
        ],
        # Periode: boleh **melihat** dan **menutup/membuka**, tidak
        # boleh membuat atau menghapus. Menutup buku bulanan pekerjaan
        # meja ini; menyusun kalender akuntansinya bukan.
        "model_permissions": {
            "finance.accountingperiod": ["view", "change"],
            "finance.accountingevent": ["view", "change"],
            "finance.account": ["view"],
            "finance.fiscalyear": ["view"],
        },
        # Jurnal penyesuaian mendarat justru saat buku harian sudah
        # ditutup — itu keadaan yang `SOFT_CLOSED` memang dibuat untuk
        # melayani. Membuka periode yang sudah **dikunci** tidak ikut:
        # itu wewenang Finance Administrator.
        #
        # FIN-B1/B2: memposting dan membalik jurnal adalah izin
        # tersendiri (`models` di atas cuma memberi CRUD), dan meja
        # inilah yang membukukan. Tidak satu pun role HR/payroll
        # memegangnya — yang memfinalisasi payroll tidak ikut boleh
        # memposting jurnal gajinya.
        "codenames": [
            "finance.post_soft_closed_period",
            "finance.post_journal",
            "finance.reverse_journal",
        ],
    },
    {
        "code": "ADMIN-SECTION",
        "name": "Admin Section",
        "description": (
            "Menyusun roster dan mengurus administrasi harian site-nya. "
            "Cakupan barisnya ikut penempatannya sendiri "
            "(kewenangan penugasan bermode 'ikut penempatan'), jadi "
            "satu role melayani berapa pun site."
        ),
        # Sengaja **tanpa** `hr.employee`: daftar pegawai boleh dibaca
        # (membaca memang dibiarkan terbuka `ModelPermission`) tapi
        # tidak boleh diubah dari meja ini. Mengubah data pokok pegawai
        # adalah pekerjaan HR, dan yang membedakan keduanya di layar
        # cuma satu tombol.
        #
        # `hr.siterotation` juga tidak: jadwal terbit dari dokumen Setup
        # dan berubah lewat Adjustment. Membukanya untuk disunting
        # langsung membatalkan seluruh gunanya versi dan baseline.
        #
        # `hr.employeeshiftassignment` **ikut**, dan itu keputusan yang
        # berbeda dari `hr.siterotation` di atas — bukan kelalaian.
        # Menyesuaikan shift satu orang pada satu tanggal (Adjust Shift
        # di kalender) adalah pekerjaan harian meja ini; menyusun ulang
        # roster bukan. Barisnya tetap disaring cakupan organisasinya
        # lewat `assert_adjustable()` di service, jadi izin ini tidak
        # melewati batas unitnya sendiri.
        "models": [
            "hr.rostersetuprequest",
            "hr.rostersetupline",
            "hr.employeeattendance",
            # Izin kehadiran. Meja inilah yang mengetikkan izin untuk
            # pegawai yang tidak memakai Employee Self Service —
            # migrasi data, koreksi, dan kejadian mendadak di site yang
            # orangnya tidak punya akun.
            "hr.attendancepermission",
            "hr.employeeleave",
            "hr.employeeshiftassignment",
            "hr.travelrequest",
            "hr.travelrequestpurpose",
            "hr.travelarrangement",
        ],
        # Business Trip: per kata kerja, **bukan** lewat `models` — `models`
        # ikut memberikan `cancel_businesstrip` (membatalkan perjalanan
        # orang lain / yang sudah berangkat), dan itu kewenangan HR.
        "model_permissions": {
            "hr.businesstrip": ["add", "change", "view", "delete"],
            "hr.businesstripleg": ["add", "change", "view", "delete"],
        },
    },
    {
        "code": "ADMIN-DEPARTMENT",
        "name": "Admin Department",
        "description": (
            "Satu tingkat di atas Admin Section: mengurus administrasi "
            "seluruh section di departemennya. Ada supaya turunannya "
            "pasti — meja Admin Section pada alur site jatuh ke sini "
            "lebih dulu sebelum melebar ke HR."
        ),
        # Izinnya **sama persis** dengan ADMIN-SECTION, dan itu
        # disengaja: yang membedakan keduanya bukan boleh mengubah apa,
        # melainkan **baris siapa** — dan itu urusan kewenangan
        # penugasan,
        # bukan izin model. Memberi Admin Department izin lebih banyak
        # akan membuat "naik satu tingkat" diam-diam berarti "boleh
        # lebih banyak hal", yang tidak pernah diminta siapa pun.
        "models": [
            "hr.rostersetuprequest",
            "hr.rostersetupline",
            "hr.employeeattendance",
            # Izin kehadiran. Meja inilah yang mengetikkan izin untuk
            # pegawai yang tidak memakai Employee Self Service —
            # migrasi data, koreksi, dan kejadian mendadak di site yang
            # orangnya tidak punya akun.
            "hr.attendancepermission",
            "hr.employeeleave",
            "hr.employeeshiftassignment",
            "hr.travelrequest",
            "hr.travelrequestpurpose",
            "hr.travelarrangement",
        ],
        # Business Trip: per kata kerja, **bukan** lewat `models` — `models`
        # ikut memberikan `cancel_businesstrip` (membatalkan perjalanan
        # orang lain / yang sudah berangkat), dan itu kewenangan HR.
        "model_permissions": {
            "hr.businesstrip": ["add", "change", "view", "delete"],
            "hr.businesstripleg": ["add", "change", "view", "delete"],
        },
    },
    {
        # Pos jaga. Role baru, dan itu bukan pelanggaran "jangan bikin
        # role baru" — role di sistem ini adalah **data**, dan yang
        # dilarang adalah membangun mesin izin kedua. Yang tidak ada
        # sebelumnya justru pekerjaannya: tidak satu pun role yang sudah
        # diseed menggambarkan orang yang menjaga gerbang.
        #
        # Izinnya sengaja sempit. `hr.visitorpass` penuh (ia yang
        # menerbitkan dan menerima kartu) tapi `hr.visitorrequest`
        # hanya **change** — tanpa `add`: satpam menandai kedatangan
        # tamu yang sudah disetujui, ia tidak mengundang siapa pun.
        # Membacanya tetap terbuka (`ModelPermission` memang tidak
        # menjaga baca), dan cakupan barisnya diatur kewenangan
        # penugasan per lokasi seperti role site lain.
        "code": "SECURITY-GATE",
        "name": "Security / Gate",
        "description": (
            "Menerima tamu di pos jaga: check-in, check-out, dan "
            "menerbitkan kartu tamu. Tidak bisa mengundang tamu atau "
            "menyetujui kunjungan."
        ),
        "models": [
            "hr.visitorpass",
        ],
        # Izin per-kata-kerja untuk model yang tidak boleh dapat
        # keempatnya. Bentuk yang lebih sempit daripada `models`, dan
        # dipakai justru di tempat yang paling perlu dibatasi.
        "model_permissions": {
            "hr.visitorrequest": ["change"],
            "hr.externalvisitor": ["add", "change"],
        },
    },
    {
        "code": EMPLOYEE_ROLE,
        "name": "Employee",
        "description": (
            "Role dasar: mengajukan cuti dan perjalanan dinasnya sendiri. "
            "Penyaringan 'miliknya sendiri' dilakukan modulnya, bukan izin ini."
        ),
        "models": [
            "hr.employeeleave",
            "hr.travelrequest",
            "hr.travelrequestpurpose",
            "hr.travelarrangement",
            # Mengundang tamu adalah hal yang dilakukan pegawai biasa.
            # `externalvisitor` **tidak** ikut: mendaftarkan tamu baru
            # boleh, tapi itu mengubah master yang dipakai seluruh
            # perusahaan — dan yang perlu dilakukan pemohon cuma
            # memilih dari yang sudah ada. Kalau tamunya belum
            # terdaftar, HRGA yang mendaftarkannya.
            "hr.visitorrequest",
            # Mengajukan izin kehadirannya sendiri — inti Employee Self
            # Service pada modul ini. Barisnya sudah tersaring `own`;
            # yang menolak izin milik orang lain kewenangan
            # penugasannya, bukan izin model ini.
            "hr.attendancepermission",
        ],
        # **`view` saja, dan itu seluruh isi baris "Employee = VIEW
        # only" pada matriks Shift Calendar.**
        #
        # Ia tidak menegakkan apa pun sendiri — `ModelPermission`
        # membiarkan baca terbuka, dan yang benar-benar menyempitkan
        # baris kalendernya cakupan `own` di `seed_data_scopes`. Yang
        # dilakukan baris ini membuat keputusannya **terlihat**: di
        # layar Roles, "pegawai boleh melihat penugasan shift tapi
        # tidak mengubahnya" jadi tiga kotak kosong di sebelah satu
        # kotak tercentang, bukan empat kotak kosong yang tidak bisa
        # dibedakan dari model yang lupa didaftarkan.
        #
        # **Atasan langsung memakai baris yang sama.** Ia tidak punya
        # role sendiri — yang membedakannya `reports_to`, bukan role —
        # jadi "Supervisor = VIEW only" dan "Employee = VIEW only"
        # memang satu baris yang sama, dan harus tetap begitu.
        "model_permissions": {
            "hr.employeeshiftassignment": ["view"],
            # Mengajukan perjalanan dinasnya sendiri (cakupan `own`).
            # Tanpa `cancel_businesstrip`: pegawai membatalkan
            # perjalanannya sendiri sebelum berangkat tanpa izin itu
            # (aturannya di service); selebihnya wewenang HR.
            "hr.businesstrip": ["add", "change", "view", "delete"],
            "hr.businesstripleg": ["add", "change", "view", "delete"],
        },
    },
]


def _role(config: dict) -> tuple[Role, bool]:
    role = Role.objects.filter(code=config["code"], is_deleted=False).first()

    if role is not None:
        return role, False

    role = Role.objects.create(
        code=config["code"],
        name=config["name"],
        description=config.get("description", ""),
    )

    return role, True


def _permissions(config: dict) -> tuple[list[Permission], list[str]]:
    if config.get("apps") == "*":
        return list(Permission.objects.all()), []

    queryset = Permission.objects.none()

    missing: list[str] = []

    app_labels = config.get("apps") or []

    if app_labels:
        queryset = Permission.objects.filter(
            content_type__app_label__in=app_labels,
        )

    names = config.get("models") or []

    for name in names:
        app_label, _, model = name.partition(".")

        rows = Permission.objects.filter(
            content_type__app_label=app_label,
            content_type__model=model,
            # **CRUD saja.** Sebelum ini kunci `models` memberi seluruh
            # izin yang menempel pada model itu, termasuk izin kustom
            # dari `Meta.permissions` — dan itu diam-diam memberi
            # kemampuan yang bukan CRUD kepada role yang cuma diminta
            # bisa mengurus barisnya. `hr.record_employeeleave`
            # (mencatat cuti tanpa alur persetujuan) akan mendarat di
            # role EMPLOYEE lewat `hr.employeeleave` di daftar ini,
            # yang persis kebalikan dari gunanya.
            #
            # Kemampuan non-CRUD dinyatakan sadar lewat `codenames`.
            codename__in=[
                f"{verb}_{model}"
                for verb in ("add", "change", "delete", "view")
            ],
        )

        if not rows.exists():
            # Model yang namanya berubah akan diam-diam menghasilkan role
            # kosong kalau tidak dilaporkan.
            missing.append(name)

            continue

        queryset = queryset | rows

    # Izin per-kata-kerja, untuk model yang tidak boleh dapat keempatnya.
    # `models` di atas memberi add/change/delete/view sekaligus — benar
    # untuk sebagian besar meja, salah untuk pos jaga: satpam menandai
    # kedatangan tamu (`change_visitorrequest`) tapi tidak mengundang
    # siapa pun (`add_visitorrequest`).
    for name, verbs in (config.get("model_permissions") or {}).items():
        app_label, _, model = name.partition(".")

        rows = Permission.objects.filter(
            content_type__app_label=app_label,
            content_type__model=model,
            codename__in=[f"{verb}_{model}" for verb in verbs],
        )

        if not rows.exists():
            missing.append(name)

            continue

        queryset = queryset | rows

    # Izin yang **bukan** `<kata kerja>_<model>`.
    #
    # Dua kunci CRUD di atas menurunkan nama izinnya dari nama model,
    # dan itu benar untuk hampir semuanya. Yang tidak: izin kustom yang
    # dideklarasikan di `Meta.permissions` — `finance.
    # post_soft_closed_period` dan `finance.reopen_locked_period`
    # keduanya menempel pada `accountingperiod` tapi tidak menyebut
    # nama model itu sama sekali. Tanpa kunci ini, satu-satunya cara
    # memberikannya adalah `apps: ["finance"]`, yang berarti memberi
    # seluruh modul Finance kepada orang yang cuma perlu satu wewenang.
    for label in config.get("codenames") or []:
        app_label, _, codename = label.partition(".")

        rows = Permission.objects.filter(
            content_type__app_label=app_label,
            codename=codename,
        )

        if not rows.exists():
            missing.append(label)

            continue

        queryset = queryset | rows

    return list(queryset.distinct()), missing


@transaction.atomic
def seed(*, assign: list[str] | None = None, log=print) -> dict:
    created_roles = 0
    granted = 0

    warnings: list[str] = []

    roles: dict[str, Role] = {}

    for config in GRANTS:
        role, created = _role(config)

        roles[config["code"]] = role

        created_roles += int(created)

        permissions, missing = _permissions(config)

        warnings.extend(
            f"{config['code']}: model '{name}' tidak ditemukan."
            for name in missing
        )

        before = role.permissions.count()

        # `add`, bukan `set` — role yang sudah disunting orang tidak
        # boleh dikembalikan ke bawaan tiap kali seed dijalankan ulang.
        role.permissions.add(*permissions)

        after = role.permissions.count()

        granted += after - before

        log(
            f"  {config['code']:16} {after:4} izin"
            f"{'  (baru)' if created else ''}"
            f"{f'  +{after - before}' if after > before else ''}"
        )

    system_admin = roles["SYSTEM-ADMIN"]
    employee = roles[EMPLOYEE_ROLE]

    assigned_admin = 0
    assigned_employee = 0

    # Superuser tidak butuh role apa pun untuk lewat penjagaan, tapi
    # tetap diberi supaya layar Roles memperlihatkan siapa administrator
    # sistemnya — "kok tidak ada yang memegang role ini" adalah
    # pertanyaan berikutnya kalau dikosongkan.
    for user in User.objects.filter(is_superuser=True, is_active=True):
        if not user.roles.filter(pk=system_admin.pk).exists():
            user.roles.add(system_admin)

            assigned_admin += 1

    for username in assign or []:
        user = User.objects.filter(username=username).first()

        if user is None:
            user = User.objects.filter(email=username).first()

        if user is None:
            warnings.append(f"Akun '{username}' tidak ditemukan.")

            continue

        if not user.roles.filter(pk=system_admin.pk).exists():
            user.roles.add(system_admin)

            assigned_admin += 1

            log(f"  SYSTEM-ADMIN -> {user.username}")

    # Yang belum memegang role apa pun akan kehilangan kemampuan
    # mengajukan cutinya sendiri begitu penjagaan menyala. Diberi role
    # dasar, bukan dibiarkan — dan sengaja hanya yang benar-benar kosong,
    # supaya role yang sudah ditugaskan orang tidak ikut diubah.
    #
    # **WHERE-nya disebut di sini, bukan diturunkan dari `Role`.**
    # Maksudnya sudah dinyatakan kalimat di atas: yang dijaga kemampuan
    # mengurus **datanya sendiri**. Itu `EXPLICIT` berisi satu baris
    # `own` — bukan simpulan dari nama rolenya, melainkan alasan
    # penugasannya diberikan. Kalau dibiarkan kosong, pegawai biasa
    # tidak bisa melihat cutinya sendiri dan tidak ada pesan yang
    # menjelaskan kenapa.
    for user in User.objects.filter(is_active=True, is_superuser=False):
        if user.roles.exists():
            continue

        grant_role(
            user,
            employee,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("own", None)],
        )

        assigned_employee += 1

    # Izin baca untuk resource sensitif. Dijalankan di sini **dan** di
    # `seed_data_scopes`, karena sebagian penerimanya baru ada setelah
    # seed lain berjalan.
    read = apply_read_grants(log=log)

    granted += read["granted"]

    warnings.extend(read["warnings"])

    # **SYSTEM-ADMIN sengaja diberikan tanpa kewenangan data.**
    #
    # Penerimanya superuser — WHERE-nya tidak pernah dibaca — kecuali
    # yang disebut lewat `--assign`, dan untuk yang itu cakupan se-tenant
    # adalah keputusan yang harus diambil orang, di layar User Role ->
    # Kewenangan. Menuliskannya di sini berarti menyimpulkannya dari
    # nama role.
    if assigned_admin:
        warnings.append(
            f"{assigned_admin} penugasan SYSTEM-ADMIN dibuat tanpa "
            "kewenangan data. Superuser tidak membutuhkannya; akun "
            "biasa yang diberi lewat --assign harus diatur di layar "
            "User Role -> Kewenangan."
        )

    return {
        "roles": len(GRANTS),
        "created": created_roles,
        "granted": granted,
        "assigned_admin": assigned_admin,
        "assigned_employee": assigned_employee,
        "warnings": warnings,
    }


# ----------------------------------------------------------------------
# Izin BACA untuk resource sensitif
# ----------------------------------------------------------------------
#
# Sampai sebelum ini `ModelPermission` meloloskan seluruh SAFE_METHOD,
# jadi tidak satu pun role perlu `view_*` untuk membaca apa pun — dan
# akibatnya tidak satu pun role **punya**: pada 20 model payroll di
# balik endpoint, hanya SYSTEM-ADMIN yang memegang `view_*`. Bukan
# HR-ADMIN, bukan Finance Manager.
#
# Karena itu urutannya tidak boleh dibalik. Menyalakan
# `ENFORCE_VIEW_PERMISSIONS` sebelum daftar di bawah ini diseed akan
# mengunci **setiap** operator payroll dari payroll — persis kegagalan
# yang dicegah `ENFORCE_MODEL_PERMISSIONS` di sisi tulis dulu.
#
# Yang ada di sini hanya resource ber-`require_view_permission = True`.
# Resource lain bacanya tetap terbuka, dan itu disengaja: dropdown dan
# lookup dipakai lintas modul oleh orang yang tidak berkepentingan
# mengubahnya.
#
# **Ditulis sebagai daftar per role, bukan "semua model di app ini".**
# Bentuk `apps: [...]` yang dipakai izin tulis di atas akan memberi
# Finance Manager seluruh app payroll termasuk yang tidak pernah ia
# buka; di sisi baca yang dijaga justru resource paling rahasia, jadi
# daftarnya harus disebut satu per satu supaya penambahan model baru
# **tidak** otomatis ikut terbaca.
# Stage 3B menambahkan satu nama ke daftar ini: `payroll.payrollperiod`.
# Sebabnya bukan kerahasiaan — periode payroll tidak memuat data
# seorang pun — melainkan **koherensi WHAT**. Begitu pemilih periode di
# dashboard dihitung per izin, izin yang dipakainya
# `payroll.view_payrollperiod`, dan sebelum ini hanya SYSTEM-ADMIN yang
# memegangnya. Tanpa penambahan ini, setiap operator payroll membuka
# dashboard dengan pemilih periode kosong — kehilangan yang tidak
# disengaja siapa pun, dan tidak ada hubungannya dengan keamanan.
#
# Diberikan **persis** kepada role yang sudah memegang
# `payroll.payrollrun`: run tidak bisa dibaca tanpa tahu periodenya.
READ_GRANTS: dict[str, list[str]] = {
    # Operator payroll. Merekalah yang menjalankan run, mengoreksi
    # input, dan menjawab pertanyaan "kenapa potongan saya segini".
    "HR-ADMIN": [
        "payroll.payslip",
        "payroll.payrollrun",
        "payroll.payrollperiod",
        "payroll.payrollrunemployee",
        "payroll.payrollinput",
        "payroll.bpjsenrollment",
    ],
    "HR-MANAGER": [
        "payroll.payslip",
        "payroll.payrollrun",
        "payroll.payrollperiod",
        "payroll.payrollrunemployee",
        "payroll.payrollinput",
        "payroll.bpjsenrollment",
    ],
    # Kembaran `*-SITE` keduanya **dibuang**, bukan dipindahkan: daftar
    # izinnya sama persis dengan induknya di atas, dan sejak cakupan
    # tidak lagi tinggal di `Role` tidak ada satu pun hal yang
    # membedakan keduanya. Pemegangnya dipindahkan
    # `accounts.0014_consolidate_site_roles`.
    # Meja kedua alur payroll. Ia menyatakan uangnya tersedia, jadi ia
    # harus bisa membuka angkanya — run, rinciannya per pegawai, dan
    # slipnya.
    #
    # **Baca saja.** Tidak satu pun izin tulis payroll: yang boleh
    # dilakukan Finance Manager adalah menyetujui, dan menyetujui lewat
    # `approve/` yang penjagaannya `WorkflowApprovalService.check_right()`
    # — bukan `change_payrollrun`. Memberinya izin tulis akan membuat
    # meja pemeriksa bisa mengubah yang diperiksanya.
    #
    # `payroll.payrollinput` **tidak** ikut: memperbaiki input adalah
    # pekerjaan HR sebelum run dikunci, dan Finance memeriksa hasilnya,
    # bukan bahan bakunya.
    "FINANCE-MANAGER": [
        "hr.employee",
        "payroll.payslip",
        "payroll.payrollrun",
        "payroll.payrollperiod",
        "payroll.payrollrunemployee",
    ],
    # Pegawai biasa: **datanya sendiri**, dan hanya karena cakupan
    # `own` yang menyempitkan barisnya. Izin ini menjawab "jenis data
    # apa", bukan "baris siapa" — tanpa cakupan `own` di sebelahnya,
    # baris yang sama akan berarti seluruh tenant.
    #
    # `payrollassignment` sengaja **tidak** ikut meski hari ini terbaca:
    # penempatan payroll adalah keputusan HR tentang seseorang, bukan
    # dokumen yang diterbitkan untuknya. Yang perlu dilihat pegawai
    # atas gajinya adalah slipnya, dan slipnya ikut.
    "EMPLOYEE": [
        "hr.employee",
        "hr.employeebankaccount",
        "hr.employeedocument",
        "hr.employeemedicalevent",
        "payroll.payslip",
    ],
    # Meja yang mengurus orang tanpa mengurus gajinya. Semuanya cuma
    # `hr.employee`, dan barisnya tetap disempitkan cakupan masing-masing.
    "ADMIN-SECTION": ["hr.employee"],
    "ADMIN-DEPARTMENT": ["hr.employee"],
    "KTT": ["hr.employee"],
    "HRGA": ["hr.employee"],
    "EXECUTIVE": ["hr.employee"],
    "BOD": ["hr.employee"],
    # Menyusun konfigurasi alur berarti memilih siapa yang jadi
    # approver — dan itu tidak bisa dilakukan tanpa membaca daftar
    # orangnya. Sama untuk yang menugaskan role.
    "WORKFLOW-ADMIN": ["hr.employee"],
    "SECURITY-ADMIN": ["hr.employee"],
    # Pos jaga. **Hanya `hr.employee`, dan itu batas yang disengaja.**
    # Satpam perlu tahu siapa karyawan yang menerima tamunya; ia tidak
    # perlu — dan tidak boleh — membuka slip gaji, rekening, atau
    # catatan medis siapa pun. Cakupannya `own` sedalam Location, jadi
    # yang terbaca pun hanya orang di pos tempat ia bertugas.
    "SECURITY-GATE": ["hr.employee"],
}


def apply_read_grants(log=print) -> dict:
    """
    Menambahkan `view_*` sesuai `READ_GRANTS`.

    Dipisah dari `seed()` dan dipanggil juga oleh `seed_data_scopes`
    karena sebagian role penerimanya tidak lahir di sini: `FINANCE-MANAGER`
    dan `KTT` dibuat `seed_workflows`. Kalau hanya dipanggil dari
    `seed()`, urutan seed menentukan siapa yang kebagian — dan urutan
    seed bukan hal yang boleh menentukan siapa bisa membuka payroll.

    `add`, tidak pernah `set`: role yang sudah disunting orang tidak
    dikembalikan ke bawaan.
    """
    granted = 0

    warnings: list[str] = []

    for code, names in READ_GRANTS.items():
        role = Role.objects.filter(code=code, is_deleted=False).first()

        if role is None:
            # Bukan kesalahan: tenant boleh saja belum memakai role itu.
            continue

        permissions = []

        for name in names:
            app_label, _, model = name.partition(".")

            permission = Permission.objects.filter(
                content_type__app_label=app_label,
                content_type__model=model,
                codename=f"view_{model}",
            ).first()

            if permission is None:
                warnings.append(
                    f"{code}: izin baca '{name}' tidak ditemukan."
                )

                continue

            permissions.append(permission)

        before = role.permissions.count()

        role.permissions.add(*permissions)

        after = role.permissions.count()

        granted += after - before

        if after > before:
            log(f"  {code:16} +{after - before} izin baca")

    return {"granted": granted, "warnings": warnings}
