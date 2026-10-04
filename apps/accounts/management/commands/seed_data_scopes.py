"""
Role bercakupan, dengan cakupan yang tidak beranak tiap buka site.

Versi sebelumnya membuat satu role per wilayah (`HR-ADMIN-SAGEA`,
`HR-ADMIN-JKT`, `HR-ADMIN-ALL`) karena cakupan lama menyimpan
**nilai** — "location = Sagea". Satu nilai butuh satu role, jadi site
berikutnya berarti role berikutnya, dan tiap role baru harus
dicentangkan ulang izin modelnya satu per satu.

Sekarang yang disimpan **aturannya**: penugasan bermode "ikut penempatan
pemegang" pada tingkat `location`, dan nilainya diambil dari penempatan
orangnya. Admin Sagea melihat Sagea, admin site B melihat site B,
admin yang duduk di Jakarta HO melihat Jakarta HO — satu role, tanpa
satu pun baris cakupan, selamanya.

Yang tidak bisa dijelaskan pola itu — admin yang mengurus dua site
sekaligus — ditangani **kewenangan pada penugasannya** (User Role ->
Kewenangan, mode `explicit` berisi kedua sitenya), bukan role baru dan
bukan cakupan per-orang. Yang terakhir itu sudah dihapus: barisnya
di-OR di atas cakupan **seluruh** role pemegangnya, jadi satu baris yang
dimaksudkan untuk pengawasan kepegawaian ikut membuka slip gaji.
Kewenangan penugasan berlaku hanya untuk izin yang diberikan role
penugasan itu sendiri.

Perintah ini **tidak menulis satu pun kolom cakupan** pada `Role`, dan
sejak gelombang C kolom itu tidak ada lagi. Yang dikerjakannya cuma WHAT: membuat role bercakupan beserta
izin modelnya, menonaktifkan role per wilayah yang ditarik, dan
menyamakan izin baca resource sensitif. WHERE dinyatakan saat penugasan
dibuat (`apps.accounts.seeds.role_authority`).

Tabel di bawah tetap di sini karena ia **pernyataan maksud** — "meja
site melihat sedalam Location". Yang menuliskannya jadi kewenangan
sungguhan `apps.accounts.seeds.role_authority`, dan keduanya dijaga
tetap sepakat oleh
`apps.accounts.tests.test_assignment_creation_contract`.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import AuthorityMode, DataScopeLevel, Role
from apps.accounts.seeds.security_roles import apply_read_grants


def _intent(mode: str, level: str) -> str:
    """
    Maksud cakupan sebagai teks, dari tabel — bukan dari database.

    Sengaja tidak dibaca dari `Role`: perintah ini tidak menuliskan
    WHERE ke sana, dan membaca balik dari sana akan mencetak keadaan
    yang ditetapkan pihak lain seolah-olah baru saja diputuskan di
    sini. Yang dicetak **maksud tabel di bawah**, dan kosakatanya
    kosakata yang berlaku sekarang (`AuthorityMode`).
    """
    label = dict(AuthorityMode.choices).get(mode, mode)

    if not level:
        return str(label)

    return f"{label} / {dict(DataScopeLevel.choices).get(level, level)}"


# `SCOPED_ROLES` **kosong sejak konsolidasi katalog role.**
#
# Dulu berisi `HR-ADMIN-SITE` dan `HR-MANAGER-SITE`: kembaran
# `HR-ADMIN`/`HR-MANAGER` yang izinnya sama persis dan yang membedakannya
# **cuma cakupan**. Sejak cakupan tidak lagi tinggal di `Role`, keduanya
# tidak bisa dibedakan sama sekali — dua baris di layar Roles yang
# berarti hal yang sama, dan pilihan di antaranya harus ditebak orang.
#
# Pemegangnya dipindahkan `accounts.0014_consolidate_site_roles`, dan
# kodenya masuk `OBSOLETE_CODES` di bawah supaya tenant yang masih
# membawanya ikut dinonaktifkan.
#
# Yang menggantikan perannya: kewenangan **per penugasan**. "HR Admin
# sebatas lokasinya sendiri" sekarang `HR-ADMIN` + penugasan bermode
# PLACEMENT pada tingkat Location — dinyatakan per orang, bukan
# ditanam di katalog role.
SCOPED_ROLES: list[dict] = []


# Meja yang memang melihat seluruh tenant — dan sekarang **menyatakannya**.
#
# Sebelum ini semuanya `explicit` dengan nol baris cakupan, yang berarti
# tanpa batasan. Perilakunya sama, tapi sebabnya berbeda dan itu yang
# berbahaya: "melihat semuanya" jadi akibat daftar yang kebetulan
# kosong, bukan keputusan seseorang. Di layar Roles keduanya terlihat
# identik, jadi tidak ada cara membedakan role yang memang lintas
# lokasi dari role yang cakupannya lupa diisi.
#
# `WORKFLOW-ADMIN` dan `SECURITY-ADMIN` ikut, dan itu bukan formalitas:
# `demo.hrmanager` memegang HR-MANAGER **dan** WORKFLOW-ADMIN, dan
# antar-role selalu di-OR — satu role tak bercakupan di sebelahnya
# sudah cukup mengembalikan seluruh tenant.
COMPANY_WIDE_CODES = [
    "HR-ADMIN",
    "HR-MANAGER",
    "HRGA",
    "SYSTEM-ADMIN",
    "SECURITY-ADMIN",
    "WORKFLOW-ADMIN",
]


# Role per wilayah yang ditarik. Dinonaktifkan, bukan dihapus: kalau
# masih ada yang memegangnya, mencabutnya mendadak membuat orang itu
# kehilangan akses tanpa tahu sebabnya. Cakupannya dibuang supaya tidak
# ada dua sumber kebenaran, dan pemegangnya dilaporkan supaya bisa
# dipindahkan sadar.
#
# `HR-ADMIN-ALL` ikut ditarik: begitu `HR-ADMIN` sendiri menyatakan
# cakupan "seluruh data", keduanya berarti hal yang persis sama. Dua
# role bermakna identik di layar Roles adalah pilihan yang harus
# ditebak orang, dan `HR-ADMIN` yang dipertahankan karena namanya
# sudah dirujuk `WORKFLOW_MONITOR_ROLES` dan `HR_REMINDER_ROLES`.
OBSOLETE_CODES = [
    "HR-ADMIN-SAGEA",
    "HR-ADMIN-JKT",
    "HR-ADMIN-ALL",
    # Kembaran `*-SITE`, ditarik bersama konsolidasi katalog role.
    # Pemegangnya sudah dipindahkan ke induknya oleh
    # `accounts.0014_consolidate_site_roles`; baris di sini yang menutup
    # tenant yang entah bagaimana masih membawanya — dan yang
    # **melaporkan** kalau masih ada pemegangnya, alih-alih mencabutnya
    # diam-diam.
    "HR-ADMIN-SITE",
    "HR-MANAGER-SITE",
    "EXECUTIVE-SITE",
]


# Ke mana pemegangnya harus pindah. Ditulis **eksplisit** per kode:
# versi sebelumnya menyimpulkannya di tengah f-string ("kalau bukan
# HR-ADMIN-ALL berarti HR-ADMIN-SITE"), dan aturan tebakan seperti itu
# jadi salah tanpa berbunyi begitu daftarnya bertambah — persis yang
# terjadi di sini.
REPLACED_BY = {
    "HR-ADMIN-SAGEA": "HR-ADMIN",
    "HR-ADMIN-JKT": "HR-ADMIN",
    "HR-ADMIN-ALL": "HR-ADMIN",
    "HR-ADMIN-SITE": "HR-ADMIN",
    "HR-MANAGER-SITE": "HR-MANAGER",
    "EXECUTIVE-SITE": "EXECUTIVE",
}


# Meja site yang sudah ada dari `seed_workflows`: cakupannya saja yang
# dipasang, izin modelnya **tidak disentuh**.
#
# Keduanya tidak punya satu pun izin tulis, dan tanpa cakupan itu
# terlihat aman — padahal membaca dibiarkan terbuka di seluruh sistem
# (dropdown dipakai lintas modul). Jadi KTT Sagea tetap bisa membuka
# daftar nama seluruh perusahaan lewat lookup mana pun. Yang menyempit
# harus cakupannya, bukan izin tulisnya.
#
# `ADMIN-DEPARTMENT` ikut, dan cakupannya **sama dengan
# `ADMIN-SECTION`**: `own` sedalam Location. Itu bukan kelalaian —
# keduanya memang bermode "ikut penempatan pemegangnya" supaya satu role
# melayani berapa pun site, dan yang membedakan keduanya hari ini adalah
# **meja mana yang mereka pegang di alur**, bukan baris mana yang mereka
# lihat. Tenant yang memang ingin memisahkannya per unit tinggal
# mengubah tingkat cakupan salah satunya dari layar Roles; jangan
# ditanam di seed, karena kedalaman yang pas berbeda tiap klien.
#
# Yang **tidak** boleh: membiarkan `ADMIN-DEPARTMENT` tanpa baris di
# sini sama sekali. Role tanpa cakupan berarti *tanpa batasan*, jadi
# admin satu departemen justru membaca seluruh tenant — kebalikan dari
# yang dimaksud saat rolenya ditambahkan.
SITE_DESK_CODES = ["KTT", "ADMIN-SECTION", "ADMIN-DEPARTMENT"]


# Meja yang cakupannya dinyatakan sekarang, dengan tingkat yang berbeda
# per meja. Bentuknya sama dengan `SITE_DESK_CODES` di atas — mode `own`
# — tapi ditulis terpisah karena tingkatnya bukan Location.
#
# **Kenapa `own`, bukan `explicit` berisi baris company.** Keduanya
# menghasilkan penyempitan yang sama untuk tenant satu company hari ini,
# tapi `explicit` gagal ke arah yang salah: begitu barisnya terhapus —
# company-nya di-soft-delete, seseorang membersihkan layar Data
# Permission — role itu kembali berarti *tanpa batasan*, dan tidak ada
# yang berbunyi. `own` tidak punya keadaan itu: tanpa penempatan ia
# memberi nol akses, bukan seluruh tenant.
#
# **Multi-company tetap bisa.** Yang mengurus lebih dari satu company
# diatur pada **penugasannya**: mode `explicit` berisi kedua company,
# lewat User Role -> Kewenangan. Pengecualiannya tercatat atas nama
# orangnya, bukan tersembunyi di konfigurasi role yang dipakai bersama —
# dan, tidak seperti cakupan per-orang yang dulu dipakai untuk ini, ia
# berlaku hanya untuk izin yang diberikan role penugasan itu.
DECLARED_SCOPES = [
    {
        # Meja kedua alur payroll. Ia menyatakan uangnya tersedia untuk
        # perusahaan tempatnya bekerja — bukan untuk seluruh tenant.
        #
        # Sebelum ini `explicit` dengan nol baris, yang berarti **tanpa
        # batasan**: satu-satunya pemegangnya membaca payroll seluruh
        # tenant termasuk company yang bukan urusannya. Itu bukan
        # keputusan siapa pun, itu akibat daftar yang kebetulan kosong.
        "code": "FINANCE-MANAGER",
        "mode": AuthorityMode.PLACEMENT,
        "level": DataScopeLevel.COMPANY,
        "note": "Sesuai penempatan / Company",
    },
    {
        # Pos jaga. Cakupannya lokasi tempatnya bertugas: satpam Sagea
        # menerima tamu Sagea, dan daftar orang yang bisa ia buka
        # berhenti di pagar yang ia jaga.
        #
        # Location, bukan Company, karena satu company bisa punya
        # banyak site — dan "satpam site A boleh melihat orang site B"
        # adalah persis yang tidak dimaksud.
        "code": "SECURITY-GATE",
        "mode": AuthorityMode.PLACEMENT,
        "level": DataScopeLevel.LOCATION,
        "note": "Sesuai penempatan / Location",
    },
]


class Command(BaseCommand):
    help = (
        "Melaporkan maksud cakupan tiap role, menonaktifkan role yang "
        "ditarik, dan menyamakan izin baca resource sensitif. Tidak "
        "membuat role bercakupan lagi — cakupan dinyatakan per penugasan. "
        "Aman diulang."
    )

    @transaction.atomic
    def handle(self, *args, **options):
        # ------------------------------------------------------------------
        # Meja lintas lokasi: menyatakan cakupannya, bukan mengubahnya
        # ------------------------------------------------------------------

        for code in COMPANY_WIDE_CODES:
            role = Role.objects.filter(code=code, is_deleted=False).first()

            if role is None:
                continue

            self.stdout.write(
                self.style.SUCCESS(
                    f"  {code:16} {role.permissions.count():4} izin  "
                    f"maksud cakupan: Seluruh Data"
                )
            )

        # ------------------------------------------------------------------
        # Meja site: cakupan saja, izin tidak disentuh
        # ------------------------------------------------------------------

        for code in SITE_DESK_CODES:
            role = Role.objects.filter(code=code, is_deleted=False).first()

            if role is None:
                continue

            self.stdout.write(
                self.style.SUCCESS(
                    f"  {code:16} {role.permissions.count():4} izin  "
                    f"maksud cakupan: Sesuai penempatan / Location"
                )
            )

        # ------------------------------------------------------------------
        # Meja yang cakupannya baru dinyatakan
        # ------------------------------------------------------------------

        for config in DECLARED_SCOPES:
            role = Role.objects.filter(
                code=config["code"],
                is_deleted=False,
            ).first()

            if role is None:
                self.stdout.write(
                    self.style.WARNING(
                        f"  {config['code']:16} belum ada — jalankan "
                        "seed_workflows/seed_security_roles dulu."
                    )
                )

                continue

            self.stdout.write(
                self.style.SUCCESS(
                    f"  {config['code']:16} {role.permissions.count():4} izin  "
                    f"cakupan: {config['note']}"
                )
            )

            # Penempatan yang hilang membuat mode `own` memberi **nol**
            # akses — benar secara keamanan, tapi kalau tidak dikatakan
            # di sini, gejalanya muncul sebagai layar kosong tanpa satu
            # pun pesan, dan yang dicurigai pertama kali selalu datanya.
            for user in role.users.all():
                employee = getattr(user, "employee_profile", None)

                organization = (
                    getattr(employee, "organization", None)
                    if employee is not None
                    else None
                )

                value = getattr(
                    organization,
                    f"{config['level']}_id",
                    None,
                )

                if value is None:
                    self.stdout.write(
                        self.style.WARNING(
                            f"    ! {user.username} tidak punya "
                            f"{config['level']} pada penempatannya — "
                            "role ini tidak memberinya akses apa pun."
                        )
                    )

        # ------------------------------------------------------------------
        # Role per wilayah yang ditarik
        # ------------------------------------------------------------------

        for code in OBSOLETE_CODES:
            role = Role.objects.filter(code=code, is_deleted=False).first()

            if role is None:
                continue

            holders = list(role.users.values_list("username", flat=True))

            role.is_active = False

            role.save(update_fields=["is_active", "updated_at"])

            replacement = REPLACED_BY.get(code, "HR-ADMIN")

            self.stdout.write(
                self.style.WARNING(
                    f"  {code:16} dinonaktifkan (diganti {replacement})"
                )
            )

            for username in holders:
                self.stdout.write(
                    self.style.WARNING(
                        f"    ! masih dipegang {username} — pindahkan ke "
                        f"{replacement} lewat Security → User Roles, dan "
                        "nyatakan kewenangannya di sana."
                    )
                )

        # ------------------------------------------------------------------
        # Role dasar dibatasi ke data sendiri
        # ------------------------------------------------------------------
        #
        # Menutup celah yang lahir dari aturan "role tanpa baris = tanpa
        # batasan": tanpa satu baris pun, `EMPLOYEE` justru berarti
        # **tanpa batasan**, dan pegawai biasa tetap bisa membaca daftar
        # seluruh pegawai lewat API — menunya memang disembunyikan, tapi
        # menu tersembunyi tidak menyembunyikan satu baris pun.
        # **Tidak ada lagi yang ditulis untuk `EMPLOYEE` di sini.**
        #
        # Dulu blok ini menulis `explicit` + satu baris `own` supaya
        # pegawai biasa tidak membaca seluruh tenant lewat aturan "role
        # tanpa baris = tanpa batasan". Aturan itu sudah tidak ada:
        # `DataScopeService` membaca kewenangan penugasan, dan penugasan
        # tanpa kewenangan tidak membuka apa pun. Yang membatasi
        # `EMPLOYEE` ke datanya sendiri sekarang `SEED_ROLE_AUTHORITY`
        # (`own`), dinyatakan saat penugasannya dibuat.

        # Laporan "explicit tanpa baris = diam-diam tanpa batasan" yang
        # dulu berdiri di sini **dibuang**: keadaan yang dilaporkannya
        # sudah tidak berarti apa-apa bagi akses siapa pun sejak WHERE
        # pindah ke penugasan. Bentuk penugasan yang setara — `EXPLICIT`
        # tanpa satu pun baris — dilaporkan `audit_authority_hygiene`.

        # ------------------------------------------------------------------
        # Izin baca resource sensitif
        # ------------------------------------------------------------------
        #
        # Diulang di sini, bukan cuma di `seed_security_roles`: role
        # bercakupan di atas baru saja dibuat, dan `FINANCE-MANAGER`
        # serta `KTT` lahir di `seed_workflows`. Yang mana yang
        # sudah ada saat `seed_security_roles` berjalan bergantung pada
        # urutan perintah — dan siapa yang boleh membuka payroll tidak
        # boleh bergantung pada urutan perintah.
        self.stdout.write("\nIzin baca resource sensitif:")

        read = apply_read_grants(log=lambda line: self.stdout.write(line))

        for warning in read["warnings"]:
            self.stdout.write(self.style.WARNING(f"  ! {warning}"))

        if not read["granted"]:
            self.stdout.write("  (sudah lengkap)")

        # **Tidak ada penurunan kewenangan di sini, dan itu
        # perubahan penting.**
        #
        # Sampai Stage 4G perintah ini menurunkan kewenangan penugasan
        # dari kolom cakupan yang baru saja ditulisnya — dan karena
        # penugasan membeku saat dibuat, ia bahkan harus menurunkan
        # **ulang** role yang diaturnya supaya `EMPLOYEE` tidak
        # meninggalkan setiap pegawai tanpa akses ke datanya sendiri.
        #
        # Sejak Stage 4H tidak ada yang membeku dari `Role` sama sekali:
        # seed yang memberi role menyebut WHERE-nya sendiri
        # (`apps.accounts.seeds.role_authority`). Jadi jebakan urutannya
        # hilang bersama sebabnya, bukan ditambal.
        #
        # Kolom cakupan yang ditulis perintah ini tinggal dua gunanya:
        # ditampilkan layar Roles, dan dibaca perkakas cutover untuk
        # tenant yang belum dialihkan. Ia **tidak** menentukan akses
        # siapa pun.
        self.stdout.write(
            "\nTugaskan lewat Security → User Roles.\n"
            "Kewenangan tiap penugasan diatur di layar yang sama. "
            "\"Maksud cakupan\" di atas **maksud tabel di berkas ini**, "
            "bukan keadaan yang tersimpan: `Role` tidak punya kolom "
            "cakupan lagi, dan yang menentukan akses kewenangan tiap "
            "penugasan."
        )
