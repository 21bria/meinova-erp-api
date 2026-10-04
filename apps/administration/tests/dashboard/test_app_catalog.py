"""
Katalog aplikasi beranda: **semua modul tampil, aksesnya yang ditandai**.

Sebelum ini modul yang tidak boleh dibuka pengguna dibuang dari respons,
dan pegawai yang hanya berhak atas HR + Workflow membuka beranda lalu
menemukan dua ikon di kanvas kosong — ERP-nya terbaca seperti produk
yang isinya memang cuma dua modul.

Yang dikunci berkas ini ada tiga, dan yang ketiga yang paling penting:

1. katalog mengirim **seluruh** modul untuk siapa pun;
2. `is_accessible` mengikuti `MenuAccessService` — satu-satunya tempat
   hak akses menu dihitung, tidak diduplikasi di sini maupun di
   frontend;
3. **menampilkan bukan membolehkan.** `get_favorites` — yang menentukan
   modul apa yang benar-benar jadi pintasan milik pengguna — tetap
   menyaring hak akses seperti sebelumnya, dan penjagaan sebenarnya
   (permission endpoint, DataScope) tidak disentuh sama sekali.
"""

from __future__ import annotations

from django_tenants.test.cases import TenantTestCase

from apps.accounts.models import Menu, Role, RoleMenuPermission, User
from apps.administration.api.dashboard.catalog import APP_CATALOG
from apps.administration.api.dashboard.services import FavoriteAppService


class AppCatalogAccessTests(TenantTestCase):
    """Dua pengguna dengan hak berbeda, satu katalog yang sama."""

    def setUp(self):
        super().setUp()

        self.superadmin = User.objects.create_user(
            username="katalog.super",
            email="katalog.super@example.test",
            password="Test-Only#Pw1",
            is_superuser=True,
            is_staff=True,
        )

        # Pengguna terbatas: satu role yang hanya mencentang menu HR.
        #
        # Role **tanpa** satu pun baris menu berarti tanpa batasan
        # (lihat `MenuAccessService`), jadi barisnya harus benar-benar
        # ada — tanpa itu yang diuji bukan pengguna terbatas, melainkan
        # pengguna biasa yang kebetulan lolos semuanya.
        self.employee = User.objects.create_user(
            username="katalog.pegawai",
            email="katalog.pegawai@example.test",
            password="Test-Only#Pw1",
        )

        role = Role.objects.create(name="Katalog Terbatas", code="katalog-terbatas")

        self.employee.roles.add(role)

        menu = Menu.objects.create(
            code="hr-employees",
            title="Employees",
            route="/hr/employees",
            is_group=False,
        )

        RoleMenuPermission.objects.create(role=role, menu=menu, can_view=True)

    # ------------------------------------------------------------------

    def test_katalog_memuat_seluruh_modul_untuk_pengguna_terbatas(self):
        """Yang tidak boleh dibuka tetap dikirim, bukan dibuang."""
        entries = FavoriteAppService.get_catalog(self.employee)

        self.assertEqual(
            {item["app_code"] for item in entries},
            {item["app_code"] for item in APP_CATALOG},
        )

    def test_penanda_akses_mengikuti_menu_permission(self):
        """`is_accessible` = hasil `MenuAccessService`, bukan hitungan baru."""
        by_code = {
            item["app_code"]: item
            for item in FavoriteAppService.get_catalog(self.employee)
        }

        # Menu yang dicentang berutekan `/hr/employees`, dan kartu HR
        # menunjuk `/hr` — kecocokannya lewat awalan rute.
        self.assertTrue(by_code["hr"]["is_accessible"])

        for code in ("payroll", "administration", "reports"):
            self.assertFalse(
                by_code[code]["is_accessible"],
                msg=f"{code} seharusnya tidak bisa dibuka pengguna ini",
            )

    def test_superuser_bisa_membuka_seluruh_modul_yang_sudah_jalan(self):
        by_code = {
            item["app_code"]: item
            for item in FavoriteAppService.get_catalog(self.superadmin)
        }

        for item in by_code.values():
            self.assertTrue(item["is_accessible"])

    def test_belum_tersedia_dipisah_dari_tidak_punya_akses(self):
        """
        `is_available` soal modulnya, `is_accessible` soal penggunanya.

        Disatukan, "Segera hadir" terbaca sebagai "Anda tidak punya
        izin" — dan penggunanya mengejar admin untuk hak akses ke modul
        yang memang belum ada isinya.
        """
        by_code = {
            item["app_code"]: item
            for item in FavoriteAppService.get_catalog(self.superadmin)
        }

        # Superuser: tidak ada satu pun yang tertutup karena izin, tapi
        # modul yang belum jadi tetap ditandai belum tersedia. `scm`
        # masih COMING_SOON; `finance` sudah BETA sejak modulnya dibangun.
        self.assertFalse(by_code["scm"]["is_available"])
        self.assertTrue(by_code["scm"]["is_accessible"])

        self.assertTrue(by_code["hr"]["is_available"])

    def test_pintasan_pengguna_tetap_tersaring_hak_akses(self):
        """
        Penjagaan yang **tidak** ikut berubah.

        Katalog memang menampilkan semuanya; `get_favorites` — yang
        menentukan modul apa yang jadi pintasan pengguna — tetap hanya
        berisi yang boleh ia buka.
        """
        codes = {
            item["app_code"]
            for item in FavoriteAppService.get_favorites(self.employee)
        }

        self.assertIn("hr", codes)
        self.assertNotIn("payroll", codes)
        self.assertNotIn("administration", codes)
