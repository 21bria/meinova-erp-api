"""
Penemuan Self Service: kartu launcher dan baris menu.

**Yang dijaga di sini satu kalimat:** pegawai aktif menemukan ruang
pribadinya tanpa memegang satu pun izin administratif HR — dan perubahan
itu tidak membuka aplikasi lain untuknya.

Keduanya harus benar bersamaan. Yang pertama tanpa yang kedua adalah
pelonggaran; yang kedua tanpa yang pertama adalah fitur yang tidak bisa
ditemukan orang yang membutuhkannya.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django_tenants.test.cases import TenantTestCase

from apps.accounts.models import Menu, Role, RoleMenuPermission
from apps.accounts.seeds.menus import MENU_TREE
from apps.administration.api.dashboard.catalog import APP_CATALOG, by_code
from apps.administration.api.dashboard.services.favorite_app_service import (
    FavoriteAppService,
)


User = get_user_model()


def routes_in_tree() -> set[str]:
    return {
        route
        for _module, groups in MENU_TREE
        for _slug, _title, items in groups
        for _label, route, _icon in items
    }


class SelfServiceCatalogTests(TenantTestCase):
    """Bentuk katalog — tidak butuh panggung tenant yang terisi."""

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "self-service-nav-catalog"
        tenant.name = "Self Service Nav Catalog"

    def test_kartu_my_workspace_terdaftar(self):
        entry = by_code().get("me")

        self.assertIsNotNone(entry, "kartu `me` tidak ada di APP_CATALOG")
        self.assertEqual(entry["link"], "/me")
        self.assertEqual(entry["title"], "My Workspace")

    def test_tidak_ada_identitas_kedua(self):
        """
        Satu hal, satu kode.

        `allowed_codes()` mencocokkan kartu lewat `link`, bukan lewat
        kode — jadi dua kode untuk satu ruang tidak akan pernah berbunyi
        sebagai konflik. Ia cuma diam-diam tidak cocok.
        """
        codes = [entry["app_code"] for entry in APP_CATALOG]

        self.assertEqual(len(codes), len(set(codes)))
        self.assertNotIn("self_service", codes)

        pointing_at_me = [e["app_code"] for e in APP_CATALOG if e["link"] == "/me"]

        self.assertEqual(pointing_at_me, ["me"])

    def test_menu_tree_memuat_rute_self_service(self):
        routes = routes_in_tree()

        self.assertIn("/me", routes)
        self.assertIn("/me/profile", routes)
        self.assertIn("/me/attendance", routes)

    def test_rute_pribadi_terdaftar_satu_per_satu(self):
        """
        `MenuAccessService` mencocokkan rute **persis**, bukan awalan.

        Konsekuensinya langsung terasa: rute `/me/*` yang lupa
        didaftarkan membuat tombolnya hilang dari `/me` justru untuk
        role yang dibatasi — audiens yang seluruh halaman itu dibuat
        untuknya — sementara admin yang menunya tanpa batasan melihatnya
        baik-baik saja. Persis jenis kesalahan yang lolos peninjauan.
        """
        from apps.accounts.management.commands.seed_menus import (
            RESTRICTED_ROLES,
        )

        for role, allowed in RESTRICTED_ROLES.items():
            for route in ("/me", "/me/profile", "/me/attendance"):
                self.assertIn(
                    route,
                    allowed,
                    f"{route} tidak diberikan ke role {role}",
                )

    def test_cta_kehadiran_menuju_self_service_bukan_meja_admin(self):
        """
        Kartu Kehadiran di `/me` **tidak** boleh mengarah ke
        `/hr/attendance`.

        Yang di HR menerima `?employee=`, membawa kolom keputusan HR,
        dan barisnya baru tersaring ke pemiliknya lewat cakupan data.
        Mengirim pegawai ke sana untuk melihat presensinya sendiri
        berarti menjadikan layar administratif sebagai jawaban atas
        pertanyaan pribadi.
        """
        from apps.self_service.services.workspace import ACTIONS

        action = ACTIONS["attendance"]

        self.assertEqual(action.route, "/me/attendance")
        self.assertEqual(action.menu_route, "/me/attendance")
        self.assertFalse(action.permission, "halaman sendiri tidak butuh izin HR")

    def test_my_profile_tidak_lagi_di_hr(self):
        """
        Jejak layar lama harus benar-benar hilang dari pendaftaran menu
        — kalau tidak, ia tetap muncul di sidebar HR dan pegawai punya
        dua pintu ke hal yang sama, satu di antaranya mengalihkan.
        """
        self.assertNotIn("/hr/my-profile", routes_in_tree())

    def test_employee_master_tetap_ada(self):
        """HR tetap punya permukaan administratifnya."""
        self.assertIn("/hr/employees", routes_in_tree())

    def test_domain_hr_tidak_ikut_pindah(self):
        routes = routes_in_tree()

        for route in (
            "/hr/attendance",
            "/hr/leave",
            "/hr/attendance-permissions",
            "/hr/overtime",
            "/hr/site-rotations",
        ):
            self.assertIn(route, routes, f"{route} hilang dari HR")

            self.assertFalse(
                route.startswith("/me"),
                "domain HR tidak boleh pindah ke Self Service",
            )


class SelfServiceDiscoveryTests(TenantTestCase):
    """Penemuan kartu untuk role yang benar-benar dibatasi."""

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "self-service-nav"
        tenant.name = "Self Service Nav"

    def _next(self) -> int:
        type(self)._counter += 1

        return type(self)._counter

    def make_user(self):
        n = self._next()

        return User.objects.create_user(
            username=f"nav-{n}",
            email=f"nav-{n}@example.test",
            password="pw",
        )

    def menu(self, route: str) -> Menu:
        n = self._next()

        return Menu.objects.create(
            code=f"nav-{n}-{route.strip('/').replace('/', '-')}",
            title=route,
            route=route,
            module=route.strip("/").split("/")[0],
        )

    def restricted_role(self, routes: list[str]) -> Role:
        """
        Role yang **dibatasi** ke daftar rute ini.

        `RoleMenuPermission` membalik aturannya: role tanpa satu pun
        baris berarti tanpa batasan. Jadi panggung ini harus benar-benar
        memberi baris, kalau tidak yang diuji adalah "semua terlihat"
        dan test-nya hijau tanpa menyentuh apa pun.
        """
        n = self._next()

        role = Role.objects.create(code=f"NAV-{n}", name=f"Nav {n}")

        for route in routes:
            RoleMenuPermission.objects.create(
                role=role,
                menu=self.menu(route),
                can_view=True,
            )

        return role

    def cards(self, user) -> list[str]:
        return [entry["app_code"] for entry in FavoriteAppService.get_favorites(user)]

    # ------------------------------------------------------------------

    def test_pegawai_menemukan_my_workspace_tanpa_izin_hr(self):
        """
        **Inti cutover Stage 6.**

        Akun ini dibatasi ke rute Self Service saja dan tidak memegang
        satu pun izin model. Kartunya harus tetap muncul — kalau tidak,
        fitur yang dibuat untuk pegawai biasa justru tak terlihat oleh
        pegawai biasa.
        """
        user = self.make_user()

        role = self.restricted_role(["/me", "/me/profile"])
        user.roles.add(role)

        self.assertFalse(user.has_perm("hr.view_employee"))
        self.assertIn("me", self.cards(user))

    def test_tidak_membuka_aplikasi_lain(self):
        """
        Sisi sebaliknya, dan sama pentingnya: kartu yang ikut terbuka
        tanpa diminta adalah pelonggaran yang tidak berbunyi.
        """
        user = self.make_user()

        user.roles.add(self.restricted_role(["/me", "/me/profile"]))

        visible = set(self.cards(user))

        self.assertEqual(visible, {"me"})

        for other in ("hr", "payroll", "administration", "workflow", "reports"):
            self.assertNotIn(other, visible)

    def test_role_hr_tetap_melihat_hr(self):
        """Cutover tidak mencabut apa pun dari meja administratif."""
        user = self.make_user()

        user.roles.add(self.restricted_role(["/me", "/hr", "/hr/employees"]))

        visible = set(self.cards(user))

        self.assertIn("hr", visible)
        self.assertIn("me", visible)

    def test_role_tanpa_rute_me_tidak_melihat_kartunya(self):
        """
        Penyaringnya memang bekerja, bukan sekadar meloloskan semua.

        Tanpa test ini, `allowed_codes()` yang rusak dan mengembalikan
        seluruh katalog akan membuat test di atas hijau juga.
        """
        user = self.make_user()

        user.roles.add(self.restricted_role(["/hr", "/hr/employees"]))

        self.assertNotIn("me", self.cards(user))
