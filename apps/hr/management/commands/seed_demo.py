"""
Membangun **seluruh isi tenant peragaan** dalam satu perintah.

Urutannya bukan selera, dan tiap langkah yang tertukar punya akibat
yang sudah pernah terjadi:

* `seed_demo_roster` **sebelum** `seed_demo_site_travel` — ia membuang
  lalu membangun ulang seluruh periode roster, dan Travel Request yang
  sudah menunjuk salah satu blok off akan menunjuk baris yang tidak ada
  lagi.
* `generate_leave_balances` **sesudah** pegawainya ada — jatah dihitung
  dari Join Date, dan tanpa pegawai ia menulis nol baris tanpa
  mengeluh.
* `seed_demo_leave_balance` **sebelum** `seed_demo_workflow` — dokumen
  cuti data uji disetujui di langkah itu, dan `recalculate_used` diam
  saja kalau kartu saldonya belum berdiri: potongannya tidak pernah
  tercatat, dan kartunya berbunyi sisa penuh untuk orang yang cutinya
  sudah disetujui.
* `seed_demo_attendance` **paling akhir** — hari kerja pegawai site
  diturunkan dari baris `RotationPeriod` yang berlaku, jadi
  menjalankannya sebelum rosternya terbit menghasilkan nol baris untuk
  seluruh site.
* `seed_shift_calendar_demo` **di antara keduanya**: sesudah
  `seed_demo_roster` karena ia menempelkan shift ke blok kerja yang
  sudah ada, dan sebelum `seed_demo_attendance` karena baris presensi
  mengambil jendela terjadwal dari shift yang berlaku pada tanggal itu.
  Terbalik, sebulan penuh baris presensi memakai shift permanen dan
  tidak satu pun shift malam muncul.

Dua bentuk keluaran, dan pilihannya bergantung apa yang mau dilihat:

* tanpa flag — tenant peragaan **penuh**: pegawai, roster, dokumen
  berjalan, dan presensi. Ini yang dipakai untuk mendemokan layar yang
  sudah ada isinya.
* `--employees-only` — **hanya master pegawai**. Cuti, saldo, roster,
  presensi, dan seluruh dokumen dibiarkan kosong, supaya alur entry-nya
  bisa ditelusuri sendiri dari awal.

Password seluruh akun peragaan (superadmin dan pegawai) dibaca dari
variabel lingkungan `DEMO_PASSWORD`; tanpa itu perintah ini berhenti
sebelum menulis apa pun. Tidak ada password bawaan di kode.

Aman diulang. Untuk membangun dari nol (bukan menimpa), jalankan
`reset_demo_data` lebih dulu — baris bertanda terhapus tetap menempati
kunci uniknya dan justru menggagalkan pembangunan ulang.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand

from apps.core.services.demo_password import demo_password


DEMO_STEPS = [
    ("seed_demo_workforce", {}),
    # Sesudah pegawainya ada (aturannya menyaring per lokasi) dan
    # sebelum presensinya diterbitkan — baris presensi menghitung
    # keterlambatannya saat ditulis, jadi policy yang datang belakangan
    # tidak akan terpakai sampai ada yang menjalankan
    # `recalculate_attendance`.
    ("seed_demo_attendance_policy", {}),
    ("seed_data_scopes", {}),
    # Sesudah `seed_data_scopes` supaya role bawaan sudah menyatakan
    # cakupannya lebih dulu, dan sebelum dokumen apa pun terbit: BOD
    # dan GM ikut terhitung di laporan yang dibentuk langkah-langkah
    # berikutnya.
    ("seed_demo_org_scope", {}),
    ("seed_demo_roster", {}),
    ("seed_demo_site_travel", {}),
    ("seed_demo_workflow", {}),
    ("seed_demo_employee_action", {}),
    # Sesudah roster terbit: hari cuti pegawai site dihitung dari blok
    # roster yang berlaku, jadi cuti yang ditulis sebelum rencananya ada
    # menyimpan jumlah hari yang tidak cocok dengan jadwalnya sendiri.
    ("seed_demo_hr_records", {}),
    # Kunjungan tamu. Sesudah pegawai dan alur persetujuannya ada —
    # dokumennya dijalankan lewat kotak masuk approver sungguhan, jadi
    # menjalankannya sebelum `seed_demo_workflow` membuat seluruh
    # dokumennya berhenti di meja pertama.
    ("seed_demo_visitors", {}),
    # Rencana shift **sebelum** presensinya diterbitkan: baris
    # presensi mengambil jendela terjadwal dari shift yang berlaku pada
    # tanggal itu, jadi menjalankannya sesudah presensi terbit
    # meninggalkan sebulan baris yang jamnya dari shift permanen.
    ("seed_shift_calendar_demo", {}),
    ("seed_demo_attendance", {}),
    # Paling akhir, dan sengaja terpisah dari seed pembentuk akun:
    # yang ini menutup akun peragaan yang **tidak** dibentuk
    # `seed_demo_workforce` — sisa tenant yang pernah diseed
    # `seed_demo_employees` tetap ada dengan alamat lamanya, dan tidak
    # ada langkah lain di atas yang menyentuhnya.
    ("sync_demo_emails", {}),
]


class Command(BaseCommand):
    help = (
        "Bangun seluruh isi tenant peragaan: struktur, superadmin, "
        "pegawai, roster, dokumen, dan presensinya. "
        "Contoh: tenant_command seed_demo --schema=demo"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help=(
                "Buang data uji lama lebih dulu. Master organisasi dan "
                "referensi tidak disentuh."
            ),
        )
        parser.add_argument(
            "--skip-tenant",
            action="store_true",
            dest="skip_tenant",
            help=(
                "Lewati penyiapan tenant (referensi + organisasi + "
                "policy); langsung ke data uji."
            ),
        )
        parser.add_argument(
            "--year",
            type=int,
            default=2026,
            help="Tahun jatah cuti yang diterbitkan.",
        )
        parser.add_argument(
            "--employees-only",
            action="store_true",
            dest="employees_only",
            help=(
                "Hanya master pegawai (lengkap seluruh tab) plus cakupan "
                "data. Cuti, saldo, roster, presensi, dan seluruh dokumen "
                "dibiarkan KOSONG — untuk tenant yang transaksinya mau "
                "diisi tangan."
            ),
        )

    def handle(self, *args, **options):
        # Sebelum langkah pertama: seed pembentuk akun membaca variabel
        # yang sama, dan yang lupa menyetelnya lebih baik berhenti di sini
        # daripada mendapati tenant setengah jadi.
        password = demo_password()

        failures: list[tuple[str, str]] = []

        def run(name: str, kwargs: dict | None = None) -> None:
            kwargs = kwargs or {}

            self.stdout.write(f"  → {name}")

            try:
                call_command(name, **kwargs, verbosity=0)
            except Exception as error:
                failures.append((name, str(error)))
                self.stdout.write(self.style.ERROR(f"     gagal: {error}"))

        if options["reset"]:
            self.stdout.write(self.style.MIGRATE_HEADING("0. Reset data uji"))
            run("reset_demo_data")

        if not options["skip_tenant"]:
            self.stdout.write(
                self.style.MIGRATE_HEADING("1. Penyiapan tenant")
            )
            run("seed_tenant", {"org": "demo"})

        # Superadmin sesudah `seed_security_roles` (yang dipanggil
        # `seed_tenant`), supaya role SYSTEM-ADMIN sudah ada untuk
        # ditempelkan. Sebelum data uji, supaya kalau ada langkah di
        # bawah yang gagal, tenantnya tetap bisa dibuka dan diperiksa.
        self.stdout.write(self.style.MIGRATE_HEADING("2. Superadmin"))
        run("create_superadmin", {"password": password})

        # ------------------------------------------------------------------
        # Jalur "pegawai saja"
        # ------------------------------------------------------------------
        #
        # Berhenti tepat setelah masternya berdiri. Jatah cuti pun tidak
        # diterbitkan: `generate_leave_balances` adalah **langkah yang
        # mau diperagakan** di alur entry, dan menjalankannya di sini
        # membuat layar Leave Balance sudah terisi sebelum ada yang
        # menekan apa pun — pertanyaan "angkanya dari mana" jadi tidak
        # punya jawaban yang bisa ditunjuk.
        if options["employees_only"]:
            self.stdout.write(
                self.style.MIGRATE_HEADING("3. Pegawai (tanpa transaksi)")
            )

            run("seed_demo_employees")
            run("seed_data_scopes")
            run("seed_demo_org_scope")
            run("sync_demo_emails")

            if failures:
                self.stdout.write(
                    self.style.ERROR(f"\n{len(failures)} langkah gagal:")
                )

                for label, error in failures:
                    self.stdout.write(self.style.ERROR(f"  ! {label}: {error}"))

                return

            self.stdout.write(
                self.style.SUCCESS(
                    "\nTenant peragaan siap diisi tangan. "
                    "Login: admin / password dari DEMO_PASSWORD\n"
                    "Urutan pengisiannya: "
                    "docs/09-business-flows/Employee-Onboarding-Flow.md"
                )
            )

            return

        self.stdout.write(self.style.MIGRATE_HEADING("3. Data uji"))

        for name, kwargs in DEMO_STEPS:
            run(name, kwargs)

            # Jatah cuti disisipkan tepat sesudah pegawainya ada: dokumen
            # cuti di langkah berikutnya memotong saldo, dan saldo yang
            # belum terbit membuat potongannya mendarat di angka minus
            # yang terbaca seperti kesalahan hitung.
            if name == "seed_demo_workforce":
                run("generate_leave_balances", {"year": options["year"]})
                run("generate_leave_balances", {"year": options["year"] + 1})

                # Dan sesudahnya saldo awalnya, karena tenant peragaan
                # ini **bermigrasi**: baris `LeaveGoLive` membuat jatah
                # tahun berjalan tidak lagi diterbitkan dari policy, jadi
                # seluruh angka tahun itu datang dari dokumen saldo awal.
                # Tanpa langkah ini seluruh kartu berbunyi nol, lalu cuti
                # data uji yang disetujui memotongnya jadi minus.
                #
                # Ia juga menjalankan ulang `generate_leave_balances`
                # sendiri — dua panggilan di atas dibiarkan karena
                # cakupannya lebih luas (seluruh pegawai aktif, bukan
                # cuma yang bernomor data uji).
                run(
                    "seed_demo_leave_balance",
                    {"year": options["year"], "quiet_rows": True},
                )

        if failures:
            self.stdout.write(
                self.style.ERROR(f"\n{len(failures)} langkah gagal:")
            )

            for label, error in failures:
                self.stdout.write(self.style.ERROR(f"  ! {label}: {error}"))

            return

        self.stdout.write(
            self.style.SUCCESS(
                "\nTenant peragaan siap. "
                "Login: admin / password dari DEMO_PASSWORD"
            )
        )
