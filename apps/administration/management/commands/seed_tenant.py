"""
Menyiapkan sebuah tenant sampai bisa dipakai — **tanpa satu baris data
uji pun**.

Ini yang dijalankan untuk tenant produksi. Sebelumnya tidak ada
perintah seperti ini: menyiapkan tenant berarti menjalankan belasan
seed satu per satu dari ingatan, dan urutannya menentukan hasilnya —
`seed_administration --only=calendar` yang jalan sebelum ada company
menulis nol baris dan tidak mengeluh, jadi kalender kerja seluruh
tenant kosong tanpa ada yang menyadarinya sampai perhitungan hari cuti
jatuh ke fallback Senin–Jumat.

Tiga tahap, dan urutannya itu yang jadi isi perintah ini:

1. **Referensi** — master yang tidak menyebut perusahaan mana pun
   (geografi, bank, mata uang, referensi HR, menu, role, alur kerja,
   profil import, panduan).
2. **Organisasi** — struktur perusahaannya, dipilih lewat `--org`.
3. **Master ber-company** — kalender, penomoran, dan seluruh policy.
   Semuanya menyaring per company, jadi menjalankannya sebelum tahap 2
   menghasilkan tabel kosong yang terbaca seperti fitur yang belum jadi.

Aman diulang; seluruh seed di bawahnya idempoten.
"""

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection


# Penanda untuk perintah yang menerima `--schema` sendiri alih-alih
# mengandalkan `tenant_command`. Diganti nama schema yang sedang aktif
# saat dijalankan.
CURRENT_SCHEMA = "$current_schema"


# Tahap 1 — tidak menyebut company mana pun.
REFERENCE_STEPS = [
    ("seed_administration", {"only": "geography"}),
    ("seed_administration", {"only": "hr-reference"}),
    ("seed_administration", {"only": "organization-reference"}),
    ("seed_administration", {"only": "bank"}),
    ("seed_administration", {"only": "bank-branch"}),
    ("seed_administration", {"only": "currency"}),
    ("seed_administration", {"only": "numbering"}),
    ("seed_hr_attendance", {}),
    ("seed_payroll", {}),
    ("seed_menus", {}),
    ("seed_security_roles", {}),
    ("seed_import_profiles", {}),
    # Perintah ini berpindah schema sendiri lewat `--schema`, bukan
    # lewat `tenant_command` seperti sisanya. Tanpa dioper, ia menolak
    # jalan dengan "the following arguments are required: --schema" —
    # dan penolakannya muncul di tengah daftar langkah lain yang
    # berhasil, jadi terbaca seperti seed yang setengah jalan.
    ("seed_attendance_import_profiles", {"schema": CURRENT_SCHEMA}),
    ("seed_dashboard", {}),
    ("seed_help_center", {}),
]


# Tahap 3 — menyaring per company, jadi wajib sesudah organisasinya ada.
COMPANY_STEPS = [
    ("seed_administration", {"only": "calendar"}),
    ("seed_leave_policy", {}),
    ("seed_attendance_policy", {}),
    ("seed_employee_action_policy", {}),
    ("seed_employee_data_policy", {}),
    ("seed_roster_policy", {}),
    ("seed_workflows", {}),
]


ORG_CHOICES = ["demo", "kw", "none"]


class Command(BaseCommand):
    help = (
        "Siapkan satu tenant: referensi → organisasi → master "
        "ber-company. Tanpa data uji. "
        "Contoh: tenant_command seed_tenant --org=demo --schema=demo"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--org",
            default="none",
            choices=ORG_CHOICES,
            help=(
                "Struktur organisasi yang ditulis. `demo` = 3 company "
                "peragaan, `kw` = struktur klien Karya Wijaya, `none` = "
                "tidak menulis organisasi sama sekali (untuk tenant yang "
                "strukturnya akan diimpor dari file)."
            ),
        )
        parser.add_argument(
            "--skip-reference",
            action="store_true",
            dest="skip_reference",
            help="Lewati tahap referensi (sudah pernah dijalankan).",
        )

    def handle(self, *args, **options):
        failures: list[tuple[str, str]] = []

        def run(name: str, kwargs: dict) -> None:
            kwargs = {
                key: (
                    connection.schema_name
                    if value == CURRENT_SCHEMA
                    else value
                )
                for key, value in kwargs.items()
            }

            label = name + (
                f" --{list(kwargs)[0]}={list(kwargs.values())[0]}"
                if kwargs
                else ""
            )

            self.stdout.write(f"  → {label}")

            try:
                call_command(name, **kwargs, verbosity=0)
            except Exception as error:
                # Satu seed yang gagal tidak menghentikan sisanya.
                # Seluruhnya idempoten, jadi menjalankan ulang setelah
                # sebabnya dibetulkan tidak menduplikasi apa pun — dan
                # berhenti di tengah meninggalkan tenant setengah jadi
                # yang jauh lebih sulit dibaca daripada satu daftar
                # kegagalan di akhir.
                failures.append((label, str(error)))
                self.stdout.write(self.style.ERROR(f"     gagal: {error}"))

        if not options["skip_reference"]:
            self.stdout.write(self.style.MIGRATE_HEADING("1. Referensi"))

            for name, kwargs in REFERENCE_STEPS:
                run(name, kwargs)

        org = options["org"]

        self.stdout.write(self.style.MIGRATE_HEADING("2. Organisasi"))

        if org == "demo":
            run("seed_demo_organization", {})
        elif org == "none":
            self.stdout.write(
                "  → dilewati (--org=none)"
            )
        else:
            run("seed_client_org", {"client": org})

        self.stdout.write(self.style.MIGRATE_HEADING("3. Master ber-company"))

        for name, kwargs in COMPANY_STEPS:
            run(name, kwargs)

        if failures:
            self.stdout.write(
                self.style.ERROR(
                    f"\n{len(failures)} langkah gagal:"
                )
            )

            for label, error in failures:
                self.stdout.write(self.style.ERROR(f"  ! {label}: {error}"))

            # Dilempar, bukan sekadar dicetak: perintah ini dipanggil
            # `seed_demo`, dan yang kembali diam-diam terbaca sebagai
            # berhasil — ringkasan di ujungnya berbunyi "Tenant peragaan
            # siap" di atas daftar kegagalan yang barusan tercetak.
            raise CommandError(
                f"{len(failures)} langkah gagal saat menyiapkan tenant."
            )

        self.stdout.write(
            self.style.SUCCESS("\nTenant siap dipakai.")
        )
