"""
Isi tabel `Menu` — daftar menu sidebar yang bisa diatur per role.

Tabel ini **kosong sejak awal**: `Menu` dan `RoleMenuPermission` sudah
lama ada, layar Menu Permissions sudah ada, tapi tidak pernah ada yang
mengisinya. Jadi layarnya menampilkan pohon kosong dan tidak ada satu
baris kode pun yang membaca hasilnya.

**Sumber kebenarannya tetap `app/constants/menus.ts` di repo Nuxt.**
Sidebar dirakit dari sana; yang di sini cuma cerminnya supaya menu bisa
dicentang per role. Konsekuensinya jelas dan tidak bisa dihindari selama
sidebar-nya statis: **menambah item di `menus.ts` berarti menambahnya di
sini juga**, kalau tidak item itu tidak akan pernah bisa dibatasi — dan
karena menu yang tidak dikenal dianggap **boleh** (lihat
`MenuAccessService`), item baru otomatis terlihat semua orang sampai
seseorang mendaftarkannya.

Kunci pencocokannya **route**, bukan judul: judul menu berubah jauh
lebih sering daripada rutenya, dan pengaturan yang sudah dicentang orang
tidak boleh hilang gara-gara "Leave" diganti jadi "Cuti".
"""

from __future__ import annotations

from django.db import transaction

from apps.accounts.models import Menu


# (module, [(slug_grup, judul_grup, [(judul, route, ikon), ...]), ...])
MENU_TREE: list[tuple[str, list]] = [
    # ------------------------------------------------------------------
    # Self Service — ruang pribadi pemegang akun, lintas modul.
    #
    # Barisnya **wajib ada di sini**, dan itu bukan kerapian. Dua hal
    # membacanya: layar Menu Permissions (supaya tenant bisa mengatur
    # siapa yang melihatnya) dan `FavoriteAppService.allowed_codes()`,
    # yang menyaring kartu launcher lewat pencocokan awalan rute. Tanpa
    # baris `/me`, kartu My Workspace tersembunyi justru untuk pegawai
    # biasa — audiens yang seluruh fiturnya dibuat.
    #
    # Modulnya sendiri, bukan diselipkan ke `hr`: kode modul menentukan
    # sidebar mana yang aktif, dan `/me` memang bukan bagian HR.
    # ------------------------------------------------------------------
    ("me", [
        ("self-service", "My Workspace", [
            ("My Workspace", "/me", "i-lucide-house"),
            ("My Attendance", "/me/attendance", "i-lucide-fingerprint"),
            ("My Profile", "/me/profile", "i-lucide-id-card"),
        ]),
    ]),

    ("hr", [
        ("human-resources", "Human Resources", [
            ("Dashboard", "/hr", "i-lucide-layout-dashboard"),
            # **My Profile tidak lagi di sini.** Kartu pegawai milik
            # sendiri bukan fitur HR: ia dibuka orang dari perusahaan
            # mana pun yang punya akun, dan tidak ada hubungannya dengan
            # mengelola pegawai. Ia pindah ke modul `me` di bawah, dan
            # `/hr/my-profile` sekarang mengalihkan ke sana.
            ("Employees", "/hr/employees", "i-lucide-users"),
            (
                "Employee Actions",
                "/hr/employee-actions",
                "i-lucide-file-signature",
            ),
        ]),
        ("masters", "Masters", [
            ("Masters", "/hr/masters", "i-lucide-database"),
        ]),
        # Tiga grup di bawah punya **baris hub** di posisi pertama, dan
        # itulah satu-satunya yang tampil di sidebar sejak isinya jadi
        # kartu berkategori. Baris layarnya tetap didaftarkan di sini,
        # dan itu bukan sisa: kartu hub adalah pintu kedua ke layar yang
        # sama, dan `MasterHub` menyaringnya lewat rute masing-masing.
        # Membuang baris layarnya berarti seluruh kartunya jadi "rute
        # tak dikenal" — dan yang tak dikenal dianggap **boleh**, jadi
        # pembatasan menu per role hilang tanpa satu pun pesan.
        ("attendance-leave", "Attendance & Leave", [
            (
                "Attendance & Leave",
                "/hr/attendance-leave",
                "i-lucide-calendar-check",
            ),
            ("Attendance", "/hr/attendance", "i-lucide-calendar-check"),
            # Dua layar shift, dan tempatnya **Attendance**, bukan
            # Roster & Travel. Yang di sana menjawab "kapan bekerja";
            # yang di sini "kalau bekerja, shift apa dan jam berapa" —
            # dan yang membukanya orang yang sedang mengurus presensi,
            # bukan yang sedang mengurus tiket pulang. Grup di sini
            # harus sama dengan kartu hub di frontend
            # (`registry/section-hub/hr-attendance-leave.ts`): kalau
            # berbeda, layarnya tetap terbuka tapi dua sisi menyebutkan
            # tempat yang berlainan ke pengguna yang sama.
            ("Shift Calendar", "/hr/shift-calendar", "i-lucide-calendar-clock"),
            # **Records**, dan kata itu bukan hiasan. Layar ini
            # memperlihatkan baris mentahnya beserta lapis
            # baseline/adjustment — istilah tabel yang tidak perlu
            # dipahami siapa pun yang cuma menyusun jadwal. Jalur
            # normalnya dua: shift normal ditetapkan dari Roster
            # Schedule, penyesuaian dari Shift Calendar. Yang di sini
            # untuk admin, audit, dan penelusuran.
            #
            # Barisnya **tidak** dibuang walau kartunya dipindah ke
            # kelompok advanced di frontend: rute yang tidak punya baris
            # menu dianggap boleh, jadi membuangnya justru melepas
            # pembatasan per role.
            (
                "Shift Assignment Records",
                "/hr/shift-assignments",
                "i-lucide-clock-arrow-up",
            ),
            (
                "Attendance Permission",
                "/hr/attendance-permissions",
                "i-lucide-file-clock",
            ),
            ("Leave", "/hr/leave", "i-lucide-clock-3"),
            ("Leave Balance", "/hr/leave-balances", "i-lucide-wallet-minimal"),
            # Dua layar go-live, dan urutannya di sini = urutan
            # pemakaiannya. Tanggalnya ditetapkan lebih dulu; saldo awal
            # yang diimport sebelum itu tidak punya tanggal untuk
            # diikuti. Keduanya sengaja **tidak** masuk daftar menu role
            # `EMPLOYEE`: ini alat HR saat migrasi, bukan layar yang
            # perlu dibuka pegawai — dan saldonya sudah terbaca di kartu
            # cutinya sendiri.
            (
                "Leave Go-Live",
                "/hr/leave-go-live",
                "i-lucide-calendar-check-2",
            ),
            (
                "Leave Opening Balance",
                "/hr/leave-opening-balances",
                "i-lucide-file-input",
            ),
            ("Overtime", "/hr/overtime", "i-lucide-briefcase-business"),
        ]),
        ("roster-travel", "Roster & Travel", [
            ("Roster & Travel", "/hr/roster-travel", "i-lucide-plane"),
            ("Travel Request", "/hr/travel-requests", "i-lucide-plane"),
            ("Business Trip", "/hr/business-trips", "i-lucide-briefcase"),
            ("Roster Schedule", "/hr/site-rotations", "i-lucide-calendar-range"),
            ("Roster Setup", "/hr/roster-setups", "i-lucide-calendar-plus"),
            ("Roster Adjustment", "/hr/roster-adjustments", "i-lucide-calendar-cog"),
            ("Rotation Credit", "/hr/rotation-credits", "i-lucide-coins"),
        ]),
        # Grup tersendiri, bukan disisipkan ke Roster & Travel: yang di
        # atas adalah perjalanan **pegawai**, yang di sini kedatangan
        # **tamu**. Keduanya kebetulan sama-sama menyangkut tiket dan
        # penginapan, dan itu satu-satunya kemiripannya — orang yang
        # membuka salah satunya tidak pernah sedang mencari yang lain.
        ("visitor", "Visitor Management", [
            ("Visitor", "/hr/visitor", "i-lucide-door-open"),
            ("Visitor Request", "/hr/visitor-requests", "i-lucide-door-open"),
            ("Visitor Master", "/hr/external-visitors", "i-lucide-contact-round"),
            ("Visitor Pass", "/hr/visitor-passes", "i-lucide-id-card"),
        ]),
        ("development", "Development", [
            ("Training", "/hr/training", "i-lucide-graduation-cap"),
            ("Recruitment", "/hr/recruitment", "i-lucide-user-plus"),
            ("Candidates", "/hr/candidates", "i-lucide-contact"),
        ]),
    ]),
    ("payroll", [
        ("payroll", "Payroll", [
            # `/payroll/dashboard`, bukan `/payroll`: path modul
            # telanjang cuma mengoper ke sana, dan yang didaftarkan di
            # sini harus alamat yang benar-benar ditulis `menus.ts` —
            # pencocokannya sama persis, huruf per huruf.
            ("Dashboard", "/payroll/dashboard", "i-lucide-layout-dashboard"),
        ]),
        ("masters", "Masters", [
            ("Masters", "/payroll/masters", "i-lucide-database"),
        ]),
        # Rutenya **harus sama persis** dengan `menus.ts` di repo Nuxt.
        # Sidebar dirakit dari sana sementara pembatasan per role dicocokkan
        # lewat route di sini, jadi satu huruf yang beda berarti menunya
        # hilang untuk setiap role yang dibatasi — tanpa error, tanpa log.
        # Lima baris di bawah sempat menunjuk halaman yang tidak pernah ada
        # (`/payroll/adjustments`, `/payroll/tax`, `/payroll/bpjs`) atau
        # halaman yang sudah pindah.
        ("processing", "Processing", [
            ("Payroll Periods", "/payroll/payroll-periods", "i-lucide-calendar-range"),
            ("Payroll Run", "/payroll/payroll-runs", "i-lucide-calculator"),
            ("Payroll Input", "/payroll/inputs", "i-lucide-sliders-horizontal"),
            ("Payroll Review", "/payroll/payroll-run-employees", "i-lucide-search-check"),
            ("Payslips", "/payroll/payslips", "i-lucide-receipt-text"),
        ]),
        ("compliance", "Compliance", [
            ("Tax", "/payroll/tax-brackets", "i-lucide-file-text"),
            # Sejak Business Decision #3A, BPJS punya layarnya sendiri
            # dan bukan lagi komponen ber-kode "BPJS-*" di Deduction
            # Components.
            ("BPJS Rules", "/payroll/bpjs-rules", "i-lucide-landmark"),
            ("BPJS Programs", "/payroll/bpjs-programs", "i-lucide-shield-check"),
            (
                "BPJS Risk Classes",
                "/payroll/bpjs-risk-classes",
                "i-lucide-triangle-alert",
            ),
            (
                "BPJS Base Definitions",
                "/payroll/bpjs-base-definitions",
                "i-lucide-layers",
            ),
            (
                "BPJS Base Components",
                "/payroll/bpjs-base-components",
                "i-lucide-list-tree",
            ),
            (
                "BPJS Enrollments",
                "/payroll/bpjs-enrollments",
                "i-lucide-user-check",
            ),
        ]),
        # Bank Transfer dan Tax Report dilepas bersama itemnya di
        # `menus.ts`: halamannya belum ada, jadi menunya mendarat di
        # "Page not found".
        ("reports", "Reports", [
            ("Payroll Summary", "/payroll/reports/summary", "i-lucide-chart-column"),
        ]),
    ]),
    ("workflow", [
        ("workflow", "Workflow", [
            ("Dashboard", "/workflow", "i-lucide-layout-dashboard"),
            ("My Approvals", "/workflow/inbox", "i-lucide-inbox"),
            ("My Submissions", "/workflow/submissions", "i-lucide-send"),
        ]),
        ("monitoring", "Monitoring", [
            ("Running Documents", "/workflow/instances", "i-lucide-git-branch"),
        ]),
        ("configuration", "Configuration", [
            ("Workflow Definitions", "/workflow/definitions", "i-lucide-workflow"),
            ("Approval Steps", "/workflow/steps", "i-lucide-list-ordered"),
            ("Delegations", "/workflow/delegations", "i-lucide-user-round-cog"),
        ]),
    ]),
    # Reports — cerminan `moduleMenus.reports` di `app/constants/menus.ts`.
    # Tumbuh per laporan yang sudah punya layarnya; rute yang belum ada
    # tidak didaftarkan supaya pintasan beranda tidak menawarkan halaman
    # kosong.
    ("reports", [
        ("reports", "Reports", [
            ("All Reports", "/reports", "i-lucide-layout-dashboard"),
        ]),
        ("reports-hr", "HR", [
            (
                "HR Period Summary",
                "/reports/hr/period-summary",
                "i-lucide-table-2",
            ),
            (
                "Employee Reporting Audit",
                "/reports/hr/employee-reporting-audit",
                "i-lucide-network",
            ),
            (
                "Manpower Summary",
                "/reports/hr/manpower-summary",
                "i-lucide-users-round",
            ),
            (
                "Contract Expiry",
                "/reports/hr/contract-expiry",
                "i-lucide-file-clock",
            ),
            (
                "Manpower Movement",
                "/reports/hr/manpower-movement",
                "i-lucide-arrow-left-right",
            ),
        ]),
    ]),
    ("scm", [
        ("supply-chain", "Supply Chain", [
            ("Dashboard", "/scm", "i-lucide-layout-dashboard"),
            ("Purchase Request", "/scm/purchase-requests", "i-lucide-clipboard-list"),
            ("Purchase Order", "/scm/purchase-orders", "i-lucide-package-check"),
            ("Vendors", "/scm/vendors", "i-lucide-users-round"),
            ("Inventory", "/scm/inventory", "i-lucide-boxes"),
            ("Warehouses", "/scm/warehouses", "i-lucide-warehouse"),
            ("Stock Movement", "/scm/stock-movement", "i-lucide-package"),
            ("Goods Receipt", "/scm/goods-receipt", "i-lucide-truck"),
        ]),
    ]),
    # ------------------------------------------------------------------
    # Finance
    #
    # Delapan baris lama di sini **menunjuk halaman yang tidak pernah
    # ada** — Cash & Bank, AP, AR, Budget, Fixed Assets semuanya rute
    # kosong sejak menu ini ditulis. Baris menu yang menunjuk rute tak
    # dikenal tidak berbunyi sebagai error: `MenuAccessService`
    # mengembalikan daftar rute dan sidebar menyaringnya dengan
    # `routes.includes(link)`, jadi yang salah cuma tidak pernah cocok
    # dengan apa pun. Yang tersisa sekarang cuma layar yang benar-benar
    # ada; sisanya menyusul bersama modulnya masing-masing.
    # ------------------------------------------------------------------
    ("finance", [
        ("finance", "Finance", [
            ("Dashboard", "/finance", "i-lucide-layout-dashboard"),
        ]),
        ("general-ledger", "General Ledger", [
            ("Journals", "/finance/journals", "i-lucide-file-text"),
            ("Account Ledger", "/finance/account-ledger", "i-lucide-book-open-text"),
            ("Trial Balance", "/finance/trial-balance", "i-lucide-scale"),
            (
                "Accounting Events",
                "/finance/accounting-events",
                "i-lucide-radio",
            ),
        ]),
        ("finance-setup", "Setup", [
            (
                "Chart of Accounts",
                "/finance/chart-of-accounts",
                "i-lucide-book-open",
            ),
            ("Fiscal Years", "/finance/fiscal-years", "i-lucide-calendar-range"),
            (
                "Accounting Periods",
                "/finance/accounting-periods",
                "i-lucide-calendar-check",
            ),
            (
                "Accounting Dimensions",
                "/finance/accounting-dimensions",
                "i-lucide-tags",
            ),
            (
                "Accounting Policies",
                "/finance/accounting-policies",
                "i-lucide-file-cog",
            ),
            (
                "Account Mapping",
                "/finance/account-mappings",
                "i-lucide-arrow-left-right",
            ),
            # **Tidak ada di sidebar**, dan barisnya tetap didaftarkan.
            # Aturan kebijakan dibuka dari dalam kebijakannya (tab
            # Rules), bukan sebagai daftar rata — tapi rutenya nyata dan
            # bisa diketik. Rute yang **tidak punya baris menu dianggap
            # boleh**, jadi membuangnya dari sini justru melepas
            # pembatasan per role. Alasan yang sama dengan
            # `/hr/shift-assignments`.
            (
                "Policy Rules",
                "/finance/accounting-policy-rules",
                "i-lucide-list-tree",
            ),
        ]),
    ]),
    # ------------------------------------------------------------------
    # Asset Management (ASSET-6). Cermin `moduleMenus.assets` di
    # `app/constants/menus.ts`. Hanya layar yang ada — Entitlement, Fixed
    # Asset, dan Depreciation belum. Custody/riwayat adalah tab di layar
    # detail aset, bukan menu. Tidak masuk `RESTRICTED_ROLES`: role
    # terbatas (mis. EMPLOYEE) memang tidak diberi modul ini.
    # ------------------------------------------------------------------
    ("assets", [
        ("asset-management", "Asset Management", [
            ("Asset Register", "/assets/register", "i-lucide-package"),
            ("Assignments", "/assets/assignments", "i-lucide-user-check"),
            ("Transfers", "/assets/transfers", "i-lucide-arrow-left-right"),
            ("Returns", "/assets/returns", "i-lucide-undo-2"),
        ]),
        ("asset-setup", "Setup", [
            ("Asset Categories", "/assets/categories", "i-lucide-tags"),
        ]),
    ]),
    ("administration", [
        ("administration", "Administration", [
            ("Dashboard", "/administration", "i-lucide-layout-dashboard"),
            ("Organization", "/administration/organization", "i-lucide-building-2"),
            ("Currency", "/administration/currency", "i-lucide-badge-dollar-sign"),
            ("Calendar", "/administration/calendar", "i-lucide-calendar-days"),
            ("Security", "/administration/security", "i-lucide-shield-check"),
            ("Settings", "/administration/settings", "i-lucide-settings-2"),
            ("Audit Trail", "/administration/audit", "i-lucide-history"),
        ]),
        ("references", "References", [
            ("Geography", "/administration/master/geography", "i-lucide-map"),
            ("Organization", "/administration/master/organization", "i-lucide-building"),
            ("Bank", "/administration/master/bank", "i-lucide-landmark"),
            ("HR Reference", "/administration/master/hr", "i-lucide-user-cog"),
        ]),
        # Notifikasi. Grup tersendiri, bukan disisipkan ke Settings:
        # yang diatur bukan satu form melainkan tiga hal yang dibuka
        # bergantian saat menelusuri satu keluhan — "kenapa saya tidak
        # dapat emailnya" dijawab dengan membaca Log, memeriksa Rules,
        # lalu membetulkan Template.
        ("notifications", "Notifications", [
            (
                "Email Templates",
                "/administration/email-templates",
                "i-lucide-mail",
            ),
            (
                "Notification Rules",
                "/administration/notification-rules",
                "i-lucide-bell-ring",
            ),
            (
                "Notification Log",
                "/administration/notification-logs",
                "i-lucide-mail-check",
            ),
            (
                "Notification Setting",
                "/administration/notification-settings",
                # BUKAN "mail-cog": ikon itu tidak ada, baik di
                # lucide-vue-next maupun di koleksi iconify. Nama ikon
                # yang salah gagal dengan cara yang sangat berbeda di
                # dua tempat — di sidebar ia cuma kotak kosong, tapi di
                # registry beranda ia menggagalkan impor modul dan
                # **menjatuhkan seluruh aplikasi** dengan 500.
                "i-lucide-sliders-horizontal",
            ),
        ]),
        # Layar penulis panduan — bukan Help Center-nya sendiri.
        # `/help` sengaja **tidak** didaftarkan di sini: halaman
        # bantuan harus terbuka untuk semua orang, dan menu yang bisa
        # dicabut per role berarti ada tenant yang pegawainya tidak
        # punya jalan masuk ke panduan sama sekali.
        ("help-center", "Help Center", [
            (
                "Help Categories",
                "/administration/help-categories",
                "i-lucide-folder-tree",
            ),
            (
                "Help Articles",
                "/administration/help-articles",
                "i-lucide-book-open",
            ),
        ]),
    ]),
]


def _code(module: str, route: str, fallback: str) -> str:
    """Kode unik dan stabil, diturunkan dari route."""
    if not route:
        return f"{module}.{fallback}"

    parts = [part for part in route.strip("/").split("/") if part]

    return ".".join(parts) if parts else f"{module}.{fallback}"


@transaction.atomic
def seed(*, log=print) -> dict:
    created = 0
    updated = 0
    order = 0

    seen: set[str] = set()

    for module, groups in MENU_TREE:
        for group_index, (group_slug, group_title, items) in enumerate(groups):
            order += 1

            # Berprefiks `group:` karena grup dan item bisa bernama
            # sama — "Masters" adalah judul grup **dan** judul menunya
            # di HR maupun Payroll, dan tanpa prefiks baris grupnya
            # ditimpa baris item lewat `update_or_create`, diam-diam.
            group_code = f"group:{module}.{group_slug}"

            group, is_new = Menu.objects.update_or_create(
                code=group_code,
                defaults={
                    "title": group_title,
                    "module": module,
                    "route": "",
                    "icon": "",
                    "is_group": True,
                    "sort_order": order,
                    "parent": None,
                    "is_deleted": False,
                },
            )

            seen.add(group_code)

            created += int(is_new)
            updated += int(not is_new)

            for title, route, icon in items:
                order += 1

                code = _code(module, route, group_slug)

                _, is_new = Menu.objects.update_or_create(
                    code=code,
                    defaults={
                        "title": title,
                        "module": module,
                        "route": route,
                        "icon": icon,
                        "is_group": False,
                        "sort_order": order,
                        "parent": group,
                        "is_deleted": False,
                    },
                )

                seen.add(code)

                created += int(is_new)
                updated += int(not is_new)

            log(f"  {module:15} {group_title:22} {len(items):2} item")

    # Menu yang sudah tidak ada di sidebar ditandai terhapus, bukan
    # dihapus: `RoleMenuPermission` menunjuknya, dan pengaturan yang
    # sudah dicentang orang tidak boleh hilang kalau menunya cuma
    # dipindah sementara.
    stale = Menu.objects.filter(is_deleted=False).exclude(code__in=seen)

    retired = stale.count()

    stale.update(is_deleted=True)

    return {
        "created": created,
        "updated": updated,
        "retired": retired,
    }
