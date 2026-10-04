# python manage.py tenant_command payroll_dashboard_uat --schema=demo
# python manage.py tenant_command payroll_dashboard_uat --schema=demo --remove
"""
Akun UAT untuk browser test Payroll Dashboard.

Dipakai `scripts/uat/payroll-dashboard.mjs` di repo Nuxt, yang membaca
dashboard yang sama dengan **tiga** akun berbeda dan membandingkan
hasilnya. Dua di antaranya dibuat di sini; yang ketiga `admin`.

| Akun | Cakupan organisasi | Boleh baca gaji? | Yang dibuktikannya |
| --- | --- | --- | --- |
| `uat-partial` | company MMR | pegawai Jakarta HO saja | KPI, tabel, chart, dan rincian semuanya menyusut bersama |
| `uat-blind` | company MMR | tidak sama sekali | nol, bukan total run — bentuk kebocoran yang ditambal hotfix rekap |

**Kenapa cakupan organisasinya company, bukan departemen.** Dokumen
`PayrollRun` hanya membawa `company` (run se-perusahaan punya
`department` kosong, dan `DataScopeService` tidak melewatkan kolom
kosong). Akun yang dibatasi ke satu departemen karena itu tidak bisa
membuka satu run pun, dan yang diuji jadi bukan lapis payroll-nya.

Karena itu "sebagian"-nya datang dari lapis **payroll**:
`EmployeeDataPolicy` khusus lokasi Jakarta HO yang menyebut role
`uat-partial`. Specificity-nya di atas `EDP-PAYROLL` bawaan yang
global, jadi pegawai Jakarta HO dinilai aturan itu saja dan sisanya
jatuh ke aturan global — yang menyebut HR-MANAGER, dan tidak dipegang
kedua akun ini.

**Hapus lagi sesudah UAT** (`--remove`). Akun berkata sandi yang
tertulis di kode tidak boleh menetap di tenant mana pun, termasuk
peragaan.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import (
    AuthorityMode,
    Role,
    RoleAssignmentAuthority,
)
from apps.accounts.services.role_assignment import assign_roles
from apps.administration.models import (
    Company,
    EmployeeDataPolicy,
    EmployeeDataSubject,
    Location,
)
from apps.core.services.demo_password import demo_password


ROLE_PARTIAL = "UAT-PAYROLL-PARTIAL"
ROLE_OPEN = "UAT-PAYROLL-OPEN"
POLICY = "EDP-UAT-PAYROLL-HO"

USERNAMES = ["uat-partial", "uat-blind"]

COMPANY_CODE = "MMR"
LOCATION_NAME = "Jakarta Head Office"


class Command(BaseCommand):
    help = "Membuat (atau menghapus) akun UAT Payroll Dashboard."

    def add_arguments(self, parser):
        parser.add_argument(
            "--remove",
            action="store_true",
            help="Hapus akun, role, dan aturan yang dibuat perintah ini.",
        )
        parser.add_argument(
            "--password",
            help=(
                "Password akun UAT. Tanpa ini dibaca dari DEMO_PASSWORD; "
                "tidak ada password bawaan."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        if options["remove"]:
            return self.remove()

        return self.create(demo_password(options["password"]))

    # ------------------------------------------------------------------

    def create(self, password: str):
        User = get_user_model()

        company = Company.objects.get(code=COMPANY_CODE, is_deleted=False)
        location = Location.objects.get(
            name=LOCATION_NAME,
            company=company,
            is_deleted=False,
        )

        partial = self._role(ROLE_PARTIAL, "UAT Payroll Partial")
        blind = self._role(ROLE_OPEN, "UAT Payroll Open")

        EmployeeDataPolicy.objects.update_or_create(
            code=POLICY,
            defaults={
                "name": "UAT Payroll Jakarta HO",
                "subject": EmployeeDataSubject.FIELD_PAYROLL,
                "role": partial,
                "location": location,
                "is_active": True,
            },
        )

        for username, role in (("uat-partial", partial), ("uat-blind", blind)):
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"email": f"{username}@uat.local"},
            )

            user.is_active = True
            user.set_password(password)
            user.save()
            # Keanggotaan **dan** WHERE-nya dalam satu transaksi.
            # Kewenangan ditulis pada penugasannya, bukan pada Role-nya:
            # itu yang dibaca runtime. Tanpa menyebutnya, akun UAT ini
            # tidak melihat apa pun — tidak ada lagi yang menurunkannya
            # dari konfigurasi role.
            assign_roles(user, [{
                "role": role.pk,
                "authority_mode": AuthorityMode.EXPLICIT,
                "authorities": [
                    {"resource_type": "company", "resource_id": company.pk},
                ],
            }])

            self.stdout.write(
                f"  {username:14} {role.code:22} "
                f"{'dibuat' if created else 'diperbarui'}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                "\nAkun UAT siap (password dari --password/DEMO_PASSWORD). "
                "Hapus lagi dengan --remove."
            )
        )

    def _role(self, code, name):
        # `Role` menjawab WHAT saja — tidak ada kolom cakupan untuk
        # disentuh. WHERE-nya ditulis per penugasan, di `_accounts()`.
        role, _ = Role.objects.get_or_create(
            code=code,
            defaults={"name": name},
        )

        return role

    # ------------------------------------------------------------------

    def remove(self):
        User = get_user_model()

        roles = Role.objects.filter(code__in=[ROLE_PARTIAL, ROLE_OPEN])

        # Aturan visibilitas lebih dulu: ia menunjuk role-nya, dan
        # menghapus role duluan membuat aturannya ikut hilang tanpa
        # pernah tercatat di keluaran.
        removed = {
            "policy": EmployeeDataPolicy.objects.filter(code=POLICY).delete(),
            # Kewenangan penugasan ikut terhapus bersama role-nya
            # (CASCADE), tapi dihitung lebih dulu supaya kelihatan di
            # keluaran — "0 baris" pada keluaran adalah satu-satunya
            # tanda kalau seed-nya tidak pernah benar-benar menulis.
            "authority": (
                RoleAssignmentAuthority.objects.filter(
                    assignment__role__in=roles,
                ).count(),
                None,
            ),
            "user": User.objects.filter(username__in=USERNAMES).delete(),
            "role": roles.delete(),
        }

        for label, (count, _) in removed.items():
            self.stdout.write(f"  {label:12} {count} baris dihapus")

        self.stdout.write(self.style.SUCCESS("\nAkun UAT dibersihkan."))
