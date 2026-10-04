from django.core.management.base import BaseCommand

from apps.accounts.models import (
    Menu,
    MenuVisibilityRule,
    Role,
    RoleMenuPermission,
)
from apps.accounts.seeds import seed_menus


# Role yang menunya dibatasi, beserta rute yang boleh dilihatnya.
#
# **Hanya role di sini yang dibatasi.** Role administratif dibiarkan
# tanpa satu pun baris menu, yang berarti "tanpa batasan": menambah menu
# baru tidak boleh mengharuskan seseorang mencentanginya ulang di tujuh
# role sebelum menu itu terlihat.
#
# Ini titik awal, bukan kebijakan. Sesudah diseed, seluruhnya diatur
# dari layar Security → Menu Permissions — per tenant, tanpa rilis kode.
# Syarat pola kerja bawaan, per (role, rute).
#
# Bawaannya diseed dan **tersimpan di baris `RoleMenuPermission`**, jadi
# sesudah ini bisa diubah dari layar Menu Permissions tanpa rilis kode —
# tenant yang pegawai HO-nya memang mengajukan TR tinggal
# mengembalikannya ke "Always".
#
# Travel Request adalah dokumen kepulangan dari site; pegawai kantor
# pusat tidak punya kepulangan untuk diajukan. Site Visit nanti
# kebalikannya (`non_roster_only`).
#
# **Travel Request dan Business Trip membaca Employee Group, bukan pola
# kerja** (POLICY-1A): `field_break` / `business_trip` adalah penanda
# Employee Group yang sama dengan yang ditegakkan API-nya. Nilai roster
# tetap berarti roster di rute mana pun.
MENU_RULES: dict[str, dict[str, str]] = {
    "EMPLOYEE": {
        "/hr/travel-requests": MenuVisibilityRule.FIELD_BREAK,

        # Jadwal roster hanya ada isinya untuk pegawai roster. Untuk
        # pegawai kantor layarnya kosong permanen, dan layar yang tidak
        # pernah berisi apa-apa terbaca seperti fitur yang rusak.
        "/hr/site-rotations": MenuVisibilityRule.ROSTER_ONLY,

        # Business Trip — group mana yang memakainya adalah konfigurasi
        # Employee Group, bukan lokasi atau roster.
        "/hr/business-trips": MenuVisibilityRule.BUSINESS_TRIP,

        # Hub-nya **tidak lagi** roster-only (BT-5). Dulu kedua kartu
        # yang dilihat pegawai biasa (Travel Request, Roster Schedule)
        # roster-only, jadi hub-nya ikut. Sejak Business Trip tinggal di
        # hub yang sama, pegawai kantor punya satu kartu di dalamnya —
        # dan pegawai roster tetap punya dua. Tiap kartu menyaring
        # dirinya sendiri; hub tanpa aturan = `ALWAYS`.
        #
        # **Keputusan final POLICY-2C — jangan dibuka lagi.**
        # `/hr/roster-travel` adalah Travel Hub umum: pegawai mana pun
        # boleh masuk, beroster atau tidak. Visibilitas hub ≠ kelayakan
        # Site Rotation. Kelayakan tiap dokumen tetap di kartunya sendiri:
        # TR `field_break`, BT `business_trip`, Roster Schedule
        # `roster_only`. Mengembalikan hub ke `roster_only` memutus satu-
        # satunya jalan sidebar pegawai non-roster ke Business Trip.
    },
}


RESTRICTED_ROLES: dict[str, list[str]] = {
    # Pegawai biasa: mengajukan dan memantau miliknya sendiri.
    #
    # `/hr` ikut, dan sebelumnya tidak — padahal halamannya memang bisa
    # dibuka: pegawai mendarat di HR Dashboard lewat breadcrumb atau URL
    # tapi tidak punya jalan masuk dari sidebar. Angkanya sudah tersaring
    # kewenangan penugasannya ke datanya sendiri, jadi yang terbaca "Total
    # Pegawai 1" memang dirinya sendiri — bukan kebocoran, tapi juga
    # bukan dashboard yang berguna. Dashboard pribadi menyusul.
    # `/hr/attendance` dan `/hr/site-rotations` **read-only dengan
    # sendirinya**, tanpa pengaturan tambahan: role `EMPLOYEE` dicakup
    # `own` (`seed_data_scopes`) sehingga barisnya cuma miliknya, dan ia
    # tidak punya izin model `change_*` untuk keduanya sehingga tombol
    # simpan ditolak `ModelPermission`. Menu bukan izin — ketiga lapisan
    # itu memang harus dibaca bersamaan.
    #
    # Rute hub (`/hr/attendance-leave`, `/hr/roster-travel`,
    # `/hr/visitor`) **wajib ikut** di setiap role yang dibatasi: sejak
    # isinya jadi kartu, hub-lah satu-satunya yang tampil di sidebar, dan
    # role yang tidak diberi rutenya kehilangan seluruh jalan masuknya —
    # layarnya masih boleh dibuka lewat URL, tapi tidak ada tautan ke
    # sana dari mana pun.
    "EMPLOYEE": [
        "/hr",
        # Ruang pribadi pemegang akun. Ikut di **setiap** role yang
        # dibatasi, dan itu disengaja: ini satu-satunya layar yang pasti
        # relevan untuk siapa pun yang punya akun, termasuk meja yang
        # seluruh menu lainnya tersembunyi untuknya.
        #
        # Read-only dengan sendirinya — `/api/me/*` cuma melayani GET.
        # Dan penjagaannya **tidak** menumpang izin HR: batasnya
        # identitas pegawainya sendiri, jadi mencabut `hr.view_employee`
        # dari sebuah role tidak mengambil profilnya sendiri darinya.
        #
        # Keduanya didaftarkan, bukan cuma `/me`: `allowed_codes()`
        # mencocokkan awalan, tapi layar Menu Permissions mengatur per
        # baris — dan tenant yang mencabut `/me/profile` sambil
        # membiarkan `/me` adalah pengaturan yang sah.
        "/me",
        # Presensi sendiri per periode. Didaftarkan tersendiri karena
        # `MenuAccessService` mencocokkan rute **persis**, bukan awalan
        # — tanpa baris ini tombol "Lihat Kehadiran" di `/me` hilang
        # justru untuk role yang halaman itu dibuat untuknya.
        "/me/attendance",
        "/me/profile",
        "/hr/attendance-leave",
        "/hr/roster-travel",
        "/hr/visitor",
        "/hr/attendance",
        # Izin kehadiran. Ikut di setiap role yang dibatasi — pegawai
        # mengajukan izinnya sendiri (cakupan `own`), meja admin
        # mengetikkan izin unitnya. Menu bukan izin: barisnya tetap
        # tersaring kewenangan penugasannya.
        "/hr/attendance-permissions",
        "/hr/leave",
        "/hr/leave-balances",
        "/hr/travel-requests",
        "/hr/business-trips",
        "/hr/site-rotations",
        # Kalender shift. Ikut di role dasar karena dua orang berbeda
        # membutuhkannya lewat pintu yang sama: pegawai roster melihat
        # shift-nya sendiri (cakupan `own`), dan **atasan langsung**
        # melihat jadwal timnya — supervisor di tenant ini memang cuma
        # memegang role `EMPLOYEE`, yang membedakannya `reports_to`,
        # bukan role. Barisnya tetap ditegakkan backend:
        # `ShiftCalendarView` menolak pegawai di luar cakupan **dan** di
        # luar garis pelaporan, termasuk id yang diketik tangan.
        "/hr/shift-calendar",
        # Mengundang tamu adalah hal yang dilakukan pegawai biasa —
        # vendor yang datang menemui teknisi, kandidat yang datang
        # wawancara. Barisnya sudah tersaring `own` ke kunjungan yang
        # ia ajukan sendiri. Visitor Master **tidak** ikut: mengubah
        # daftar tamu se-perusahaan bukan pekerjaan pemohon, dan
        # pencariannya tetap jalan lewat lookup di form.
        "/hr/visitor-requests",
        "/workflow",
        "/workflow/inbox",
        "/workflow/submissions",
        "/workflow/delegations",
    ],

    # Admin Section: menyusun roster dan mengurus administrasi harian
    # site-nya. Tanpa Employee Actions, tanpa Masters, tanpa Payroll —
    # sidebar penuh untuk meja yang cakupannya satu section adalah
    # kebocoran yang paling gampang terlewat, karena tidak ada satu pun
    # pesan error yang menyertainya.
    #
    # `/hr/employees` ikut, dan itu disengaja: daftarnya sudah tersaring
    # kewenangan penugasannya ke pegawai site-nya sendiri, dan menyusun
    # roster tanpa bisa memeriksa datanya lebih dulu berarti menebak.
    # Menulisnya tetap ditolak `ModelPermission` — menu bukan izin.
    "ADMIN-SECTION": [
        "/hr/employees",
        # Ruang pribadi pemegang akun. Ikut di **setiap** role yang
        # dibatasi, dan itu disengaja: ini satu-satunya layar yang pasti
        # relevan untuk siapa pun yang punya akun, termasuk meja yang
        # seluruh menu lainnya tersembunyi untuknya.
        #
        # Read-only dengan sendirinya — `/api/me/*` cuma melayani GET.
        # Dan penjagaannya **tidak** menumpang izin HR: batasnya
        # identitas pegawainya sendiri, jadi mencabut `hr.view_employee`
        # dari sebuah role tidak mengambil profilnya sendiri darinya.
        #
        # Keduanya didaftarkan, bukan cuma `/me`: `allowed_codes()`
        # mencocokkan awalan, tapi layar Menu Permissions mengatur per
        # baris — dan tenant yang mencabut `/me/profile` sambil
        # membiarkan `/me` adalah pengaturan yang sah.
        "/me",
        # Presensi sendiri per periode. Didaftarkan tersendiri karena
        # `MenuAccessService` mencocokkan rute **persis**, bukan awalan
        # — tanpa baris ini tombol "Lihat Kehadiran" di `/me` hilang
        # justru untuk role yang halaman itu dibuat untuknya.
        "/me/attendance",
        "/me/profile",
        "/hr/attendance-leave",
        "/hr/roster-travel",
        "/hr/visitor",
        "/hr/attendance",
        # Izin kehadiran. Ikut di setiap role yang dibatasi — pegawai
        # mengajukan izinnya sendiri (cakupan `own`), meja admin
        # mengetikkan izin unitnya. Menu bukan izin: barisnya tetap
        # tersaring kewenangan penugasannya.
        "/hr/attendance-permissions",
        "/hr/leave",
        "/hr/leave-balances",
        "/hr/travel-requests",
        "/hr/business-trips",
        "/hr/site-rotations",
        "/hr/roster-setups",
        # Memantau hasil roster yang ia susun sendiri. Barisnya sudah
        # tersaring kewenangan penugasannya ke unitnya; menyusun jadwal
        # tanpa bisa memeriksa hasilnya berarti menebak.
        "/hr/shift-calendar",
        "/hr/visitor-requests",
        "/hr/visitor-passes",
        # Reports ikut, dan barisnya sudah tersaring kewenangan penugasannya
        # ke section/department-nya sendiri — meja inilah yang paling
        # sering ditanyai "bulan ini berapa yang mangkir". Tanpa rutenya,
        # `FavoriteAppService.allowed_codes()` juga menyembunyikan kartu
        # Reports dari berandanya: kartu aplikasi dicocokkan lewat awalan
        # rute menu, jadi modul tanpa satu pun menu yang terlihat
        # dianggap tidak boleh dibuka.
        #
        # `EMPLOYEE` sengaja **tidak** ikut: laporan periode adalah alat
        # manajemen, dan pegawai yang cakupannya `own` cuma akan melihat
        # satu baris dirinya sendiri — layar yang tidak menjawab apa pun.
        "/reports",
        "/reports/hr/period-summary",
        "/workflow",
        "/workflow/inbox",
        "/workflow/submissions",
    ],

    # Admin Department: satu tingkat di atas, **menu yang sama persis**.
    # Yang membedakan keduanya bukan layar mana yang boleh dibuka,
    # melainkan baris siapa yang muncul di dalamnya — dan itu urusan
    # kewenangan penugasannya. Memberinya menu tambahan akan membuat "naik
    # satu tingkat" diam-diam berarti "boleh lebih banyak hal".
    "ADMIN-DEPARTMENT": [
        "/hr/employees",
        # Ruang pribadi pemegang akun. Ikut di **setiap** role yang
        # dibatasi, dan itu disengaja: ini satu-satunya layar yang pasti
        # relevan untuk siapa pun yang punya akun, termasuk meja yang
        # seluruh menu lainnya tersembunyi untuknya.
        #
        # Read-only dengan sendirinya — `/api/me/*` cuma melayani GET.
        # Dan penjagaannya **tidak** menumpang izin HR: batasnya
        # identitas pegawainya sendiri, jadi mencabut `hr.view_employee`
        # dari sebuah role tidak mengambil profilnya sendiri darinya.
        #
        # Keduanya didaftarkan, bukan cuma `/me`: `allowed_codes()`
        # mencocokkan awalan, tapi layar Menu Permissions mengatur per
        # baris — dan tenant yang mencabut `/me/profile` sambil
        # membiarkan `/me` adalah pengaturan yang sah.
        "/me",
        # Presensi sendiri per periode. Didaftarkan tersendiri karena
        # `MenuAccessService` mencocokkan rute **persis**, bukan awalan
        # — tanpa baris ini tombol "Lihat Kehadiran" di `/me` hilang
        # justru untuk role yang halaman itu dibuat untuknya.
        "/me/attendance",
        "/me/profile",
        "/hr/attendance-leave",
        "/hr/roster-travel",
        "/hr/visitor",
        "/hr/attendance",
        # Izin kehadiran. Ikut di setiap role yang dibatasi — pegawai
        # mengajukan izinnya sendiri (cakupan `own`), meja admin
        # mengetikkan izin unitnya. Menu bukan izin: barisnya tetap
        # tersaring kewenangan penugasannya.
        "/hr/attendance-permissions",
        "/hr/leave",
        "/hr/leave-balances",
        "/hr/travel-requests",
        "/hr/business-trips",
        "/hr/site-rotations",
        "/hr/roster-setups",
        # Memantau hasil roster yang ia susun sendiri. Barisnya sudah
        # tersaring kewenangan penugasannya ke unitnya; menyusun jadwal
        # tanpa bisa memeriksa hasilnya berarti menebak.
        "/hr/shift-calendar",
        "/hr/visitor-requests",
        "/hr/visitor-passes",
        # Reports ikut, dan barisnya sudah tersaring kewenangan penugasannya
        # ke section/department-nya sendiri — meja inilah yang paling
        # sering ditanyai "bulan ini berapa yang mangkir". Tanpa rutenya,
        # `FavoriteAppService.allowed_codes()` juga menyembunyikan kartu
        # Reports dari berandanya: kartu aplikasi dicocokkan lewat awalan
        # rute menu, jadi modul tanpa satu pun menu yang terlihat
        # dianggap tidak boleh dibuka.
        #
        # `EMPLOYEE` sengaja **tidak** ikut: laporan periode adalah alat
        # manajemen, dan pegawai yang cakupannya `own` cuma akan melihat
        # satu baris dirinya sendiri — layar yang tidak menjawab apa pun.
        "/reports",
        "/reports/hr/period-summary",
        "/workflow",
        "/workflow/inbox",
        "/workflow/submissions",
    ],
}


class Command(BaseCommand):
    help = (
        "Isi tabel Menu dari struktur sidebar frontend, lalu batasi menu "
        "role EMPLOYEE dan ADMIN-SECTION. Aman diulang."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--skip-roles",
            action="store_true",
            help="Hanya isi tabel Menu, jangan sentuh batasan role.",
        )

        parser.add_argument(
            "--role",
            dest="only_role",
            help="Batasi satu role saja (kodenya).",
        )

    def handle(self, *args, **options):
        self.stdout.write("Mengisi tabel Menu:")

        result = seed_menus(log=self.stdout.write)

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{result['created']} menu baru, "
                f"{result['updated']} diperbarui, "
                f"{result['retired']} ditandai tidak dipakai."
            )
        )

        if options["skip_roles"]:
            return

        only = options.get("only_role")

        for code, routes in RESTRICTED_ROLES.items():
            if only and only != code:
                continue

            self.restrict(
                code=code,
                routes=routes,
                rules=MENU_RULES.get(code, {}),
            )

    def restrict(
        self,
        *,
        code: str,
        routes: list[str],
        rules: dict[str, str] | None = None,
    ) -> None:
        role = Role.objects.filter(code=code, is_deleted=False).first()

        if role is None:
            self.stdout.write(
                self.style.WARNING(
                    f"! Role {code} belum ada — jalankan "
                    "`tenant_command seed_security_roles` dulu."
                )
            )

            return

        menus = list(
            Menu.objects.filter(
                route__in=routes,
                is_deleted=False,
            )
        )

        missing = set(routes) - {menu.route for menu in menus}

        # Grup induknya ikut supaya judul grup tetap punya isi kalau nanti
        # ada yang membaca pohonnya per grup.
        parents = {menu.parent_id for menu in menus if menu.parent_id}

        RoleMenuPermission.objects.filter(role=role).delete()

        by_route = rules or {}

        rule_of = {
            menu.pk: by_route.get(menu.route, MenuVisibilityRule.ALWAYS)
            for menu in menus
        }

        RoleMenuPermission.objects.bulk_create([
            RoleMenuPermission(
                role=role,
                menu_id=menu_id,
                can_view=True,
                # Grup induk tidak punya rute, jadi selalu tanpa syarat.
                visibility_rule=rule_of.get(
                    menu_id,
                    MenuVisibilityRule.ALWAYS,
                ),
            )
            for menu_id in {menu.pk for menu in menus} | parents
        ])

        self.stdout.write(
            self.style.SUCCESS(
                f"\nRole {code} dibatasi ke {len(menus)} menu:"
            )
        )

        for menu in sorted(menus, key=lambda item: item.route):
            rule = by_route.get(menu.route)

            suffix = f"  [{rule}]" if rule else ""

            self.stdout.write(f"  {menu.route:26} {menu.title}{suffix}")

        for route in sorted(missing):
            self.stdout.write(
                self.style.WARNING(f"  ! {route} tidak ada di tabel Menu.")
            )
