"""
Kontrak `DataScopeService` yang **berlaku hari ini**, dikunci apa adanya.

Berkas ini **karakterisasi, bukan perbaikan.** Tidak satu baris pun di
`apps/accounts/scoping.py` diubah untuk membuatnya hijau. Gunanya
menjawab satu pertanyaan yang selama ini hanya bisa dijawab dengan
membaca kode: *kalau seseorang memegang kombinasi role dan baris
cakupan seperti ini, baris mana yang ia lihat?*

Kenapa itu perlu ditulis sebelum apa pun diubah: kontrak cakupan
sekarang punya dua aturan yang **gagal ke arah terbuka**, dan keduanya
tidak berbunyi —

1. role bermode `explicit` **tanpa satu pun baris** berarti *tanpa
   batasan*, bukan *tanpa akses*;
2. satu role bermode `all` di antara role lain **membatalkan seluruh
   pembatasan** milik role tetangganya.

Keduanya mungkin memang disengaja, dan mungkin harus berubah. Yang
pasti: mengubahnya tanpa test yang menyatakan perilaku lama lebih dulu
berarti tidak ada yang bisa membedakan "perilakunya berubah karena
diputuskan" dari "perilakunya berubah karena tidak sengaja".

Tiap skenario punya **assertion negatif**. Test cakupan yang hanya
memeriksa "yang boleh terlihat memang terlihat" akan tetap hijau pada
implementasi yang tidak menyaring apa pun.

Wave C
------
Kelas `UserDataPermissionTests` **dihapus bersama modelnya.** Seluruh
gunanya membuktikan baris `UserDataPermission` tidak lagi melebarkan
maupun menyempitkan cakupan; sesudah tabelnya hilang tidak ada lagi yang
bisa dibuktikan tidak berpengaruh, dan mengarang assertion pengganti
yang tidak menguji apa pun lebih buruk daripada tidak ada test.

Aturan nomor 1 di atas juga sudah **tidak berlaku** pada penugasan:
`EXPLICIT` tanpa baris berarti tanpa kewenangan, dan itulah yang dikunci
`test_explicit_with_zero_rows_now_fails_CLOSED`.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django_tenants.test.cases import TenantTestCase

from apps.accounts.services.role_assignment import grant_role
from apps.accounts.models import (
    AuthorityMode,
    DataScopeLevel,
    Role,
)
from apps.accounts.scoping import DataScopeService
from apps.administration.models import Company, Department, Location, Position
from apps.hr.models import Employee, OrganizationAssignment


from datetime import date

JOIN = date(2020, 1, 6)


# Peta yang dipakai seluruh test di bawah. Sengaja sama bentuknya dengan
# `EMPLOYEE_SCOPE` yang dipakai viewset Employee sungguhan — kalau
# bentuknya berbeda, yang diuji bukan penyaring yang benar-benar jalan.
EMPLOYEE_SCOPE = {
    "company": "organization__company",
    "branch": "organization__branch",
    "location": "organization__location",
    "division": "organization__division",
    "department": "organization__department",
    "section": "organization__section",
    "own": "user_id",
}


class DataScopeSemanticsTestCase(TenantTestCase):
    """
    Panggung tiga company dan tiga lokasi.

    Tiga, bukan dua: pertanyaan "apakah C ikut tersaring" tidak bisa
    dijawab panggung yang cuma punya A dan B — union yang salah dan
    union yang benar menghasilkan jawaban yang sama.
    """

    _n = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "data-scope"
        tenant.name = "Data Scope"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company_a = Company.objects.create(code="DSA", name="Company A")
        cls.company_b = Company.objects.create(code="DSB", name="Company B")
        cls.company_c = Company.objects.create(code="DSC", name="Company C")

        cls.site_a1 = Location.objects.create(
            company=cls.company_a, code="DSA-1", name="Site A1")
        cls.site_a2 = Location.objects.create(
            company=cls.company_a, code="DSA-2", name="Site A2")
        cls.site_b1 = Location.objects.create(
            company=cls.company_b, code="DSB-1", name="Site B1")

        cls.dept_a = Department.objects.create(
            company=cls.company_a, code="DSA-OPS", name="Operations")
        cls.dept_b = Department.objects.create(
            company=cls.company_b, code="DSB-OPS", name="Operations B")

        # Pegawai penanda, satu per kombinasi yang diuji.
        cls.emp_a1 = cls.make_employee(cls.company_a, cls.site_a1, cls.dept_a)
        cls.emp_a2 = cls.make_employee(cls.company_a, cls.site_a2, cls.dept_a)
        cls.emp_b1 = cls.make_employee(cls.company_b, cls.site_b1, cls.dept_b)
        cls.emp_c = cls.make_employee(cls.company_c, None, None)

    # ------------------------------------------------------------------

    @classmethod
    def make_employee(cls, company, location, department, *, with_user=True):
        User = get_user_model()

        cls._n += 1

        user = None

        if with_user:
            user = User.objects.create_user(
                username=f"ds.user{cls._n}",
                email=f"ds.user{cls._n}@example.test",
                password="Test-Only#Pw1",
            )

        position = Position.objects.create(
            company=company,
            department=department,
            code=f"DS-POS{cls._n}",
            name=f"Position {cls._n}",
        )

        employee = Employee.objects.create(
            employee_number=f"DS-{cls._n:03d}",
            first_name="Scope",
            last_name=f"User {cls._n}",
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=company,
            location=location,
            department=department,
            position=position,
            organization_effective_date=JOIN,
        )

        return Employee.objects.get(pk=employee.pk)

    # ------------------------------------------------------------------
    # Deklarasi maksud — milik test ini, bukan skema
    # ------------------------------------------------------------------
    #
    # Bentuk panggilannya tidak berubah (`make_role(code, mode=ALL)`,
    # `grant_role(role, "company", obj)`), jadi tiap skenario di bawah
    # tetap terbaca seperti sebelumnya. Yang berubah **ke mana**
    # deklarasinya disimpan: dulu ke kolom `Role` dan baris
    # `RoleDataPermission`, sekarang ke dict Python milik kelas ini.
    #
    # Sampai Wave C penerjemahnya `backfill_authority()` — perkakas
    # migrasi yang membaca model lama. Model itu sudah dihapus, jadi
    # pemetaannya ada di `grant()`, dengan aturan yang sama persis:
    #
    #   ALL      -> UNRESTRICTED
    #   OWN      -> PLACEMENT pada level yang disebut
    #   EXPLICIT -> EXPLICIT berisi baris yang dideklarasikan
    #
    # Termasuk kasus yang paling mudah salah: `EXPLICIT` **tanpa** baris
    # tetap berarti tanpa kewenangan, bukan tanpa batasan.

    ALL = "all"
    OWN = "own"
    EXPLICIT = "explicit"

    _declared: dict = {}

    @classmethod
    def grant(cls, user, *roles):
        """Memberi role berikut kewenangan yang dideklarasikan test ini."""
        for role in roles:
            declared = cls._declared.get(
                role.pk, {"mode": cls.EXPLICIT, "level": "", "rows": []})

            if declared["mode"] == cls.ALL:
                grant_role(user, role, mode=AuthorityMode.UNRESTRICTED)
            elif declared["mode"] == cls.OWN:
                grant_role(
                    user, role,
                    mode=AuthorityMode.PLACEMENT,
                    level=declared["level"],
                )
            else:
                grant_role(
                    user, role,
                    mode=AuthorityMode.EXPLICIT,
                    authorities=declared["rows"],
                )

    @classmethod
    def make_role(cls, code, *, mode=EXPLICIT, level=""):
        role = Role.objects.create(code=code, name=code.title())

        cls._declared[role.pk] = {"mode": mode, "level": level, "rows": []}

        return role

    @classmethod
    def grant_role(cls, role, resource_type, resource):
        """Satu nilai cakupan untuk `role`, dicatat sebagai deklarasi."""
        cls._declared[role.pk]["rows"].append((resource_type, resource.pk))

    def visible(self, user):
        """Nomor pegawai yang terlihat oleh `user` lewat peta Employee."""
        queryset = DataScopeService.filter(
            Employee.objects.filter(is_deleted=False),
            EMPLOYEE_SCOPE,
            user,
        )

        return set(queryset.values_list("employee_number", flat=True))

    def setUp(self):
        super().setUp()

        # `for_user()` menyimpan hasilnya di instance user; test yang
        # mengubah role sesudah cache terisi akan membaca cakupan lama.
        for user in get_user_model().objects.all():
            if hasattr(user, "_data_scope_cache"):
                del user._data_scope_cache


class ExplicitScopeTests(DataScopeSemanticsTestCase):
    """Skenario 1, 2, 5, 9 — cakupan yang ditulis sebagai baris."""

    def test_single_company_hides_every_other_company(self):
        role = self.make_role("DS-A-ONLY")

        self.grant_role(role, "company", self.company_a)

        actor = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        self.grant(actor.user, role)

        seen = self.visible(actor.user)

        self.assertIn(self.emp_a1.employee_number, seen)

        self.assertIn(self.emp_a2.employee_number, seen)

        # Assertion negatif — inti test-nya.
        self.assertNotIn(self.emp_b1.employee_number, seen)

        self.assertNotIn(self.emp_c.employee_number, seen)

    def test_two_companies_are_a_union_and_the_third_stays_hidden(self):
        role = self.make_role("DS-AB")

        self.grant_role(role, "company", self.company_a)
        self.grant_role(role, "company", self.company_b)

        actor = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        self.grant(actor.user, role)

        seen = self.visible(actor.user)

        self.assertIn(self.emp_a1.employee_number, seen)

        self.assertIn(self.emp_b1.employee_number, seen)

        self.assertNotIn(self.emp_c.employee_number, seen)

    def test_two_locations_are_a_union_and_the_third_stays_hidden(self):
        role = self.make_role("DS-SITES")

        self.grant_role(role, "location", self.site_a1)
        self.grant_role(role, "location", self.site_b1)

        actor = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        self.grant(actor.user, role)

        seen = self.visible(actor.user)

        self.assertIn(self.emp_a1.employee_number, seen)

        self.assertIn(self.emp_b1.employee_number, seen)

        self.assertNotIn(self.emp_a2.employee_number, seen)

    def test_dimensions_inside_one_role_are_ANDed(self):
        """
        "Company A **dan** Site B1" tidak memuat siapa pun: tidak ada
        pegawai yang memenuhi keduanya. Ini yang membuat cakupan campur
        dimensi berbahaya kalau ditulis tanpa disadari.
        """
        role = self.make_role("DS-MIXED")

        self.grant_role(role, "company", self.company_a)
        self.grant_role(role, "location", self.site_b1)

        actor = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        self.grant(actor.user, role)

        self.assertEqual(self.visible(actor.user), set())

    def test_explicit_with_zero_rows_now_fails_CLOSED(self):
        """
        Kegagalan ke arah terbuka yang dikunci di sini, **dibalik**.

        Dulu: role bermode `explicit` tanpa satu pun baris berarti
        *tanpa batasan*, bukan *tanpa akses*. Role yang cakupannya lupa
        diisi membuka seluruh tenant, dan di layar Roles ia terlihat
        persis sama dengan role yang cakupannya sudah diatur. Baris ini
        mengunci perilaku itu supaya perubahannya tidak bisa terjadi
        diam-diam — dan sekarang perubahannya sudah terjadi, terbuka.

        Arti lama itu **masih ada pada `Role`**: `data_scope_mode`
        bawaannya tetap `explicit`, dan `LegacyScope` masih membacanya
        begitu untuk membandingkan tenant sebelum dialihkan. Yang
        berubah jalannya ke runtime. Kewenangan diturunkan ke
        penugasan saat penugasannya dibuat, dan di sana `EXPLICIT`
        tanpa baris berarti **tanpa kewenangan**.

        Penyempitan ini disengaja dan harus diukur per tenant sebelum
        peralihan — `audit_assignment_cutover` yang melaporkannya.
        """
        role = self.make_role("DS-EMPTY")

        actor = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        self.grant(actor.user, role)

        scope = DataScopeService.for_user(actor.user)

        self.assertFalse(scope.unrestricted)
        self.assertTrue(scope.denied)

        seen = self.visible(actor.user)

        self.assertNotIn(self.emp_b1.employee_number, seen)

        self.assertNotIn(self.emp_c.employee_number, seen)


class OwnModeTests(DataScopeSemanticsTestCase):
    """Skenario 3, 4, 10 — cakupan yang dihitung dari penempatan."""

    def test_own_company_follows_the_holder_placement(self):
        role = self.make_role(
            "DS-OWN-CO",
            mode=DataScopeSemanticsTestCase.OWN,
            level=DataScopeLevel.COMPANY,
        )

        actor = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        self.grant(actor.user, role)

        seen = self.visible(actor.user)

        self.assertIn(self.emp_a1.employee_number, seen)

        self.assertIn(self.emp_a2.employee_number, seen)

        self.assertNotIn(self.emp_b1.employee_number, seen)

    def test_own_location_is_narrower_than_own_company(self):
        role = self.make_role(
            "DS-OWN-LOC",
            mode=DataScopeSemanticsTestCase.OWN,
            level=DataScopeLevel.LOCATION,
        )

        actor = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        self.grant(actor.user, role)

        seen = self.visible(actor.user)

        self.assertIn(self.emp_a1.employee_number, seen)

        # Company yang sama, lokasi berbeda — harus hilang.
        self.assertNotIn(self.emp_a2.employee_number, seen)

        self.assertNotIn(self.emp_b1.employee_number, seen)

    def test_own_without_an_employee_profile_is_DENIED_not_open(self):
        """
        Akun tanpa pegawai tidak punya penempatan, jadi mode `own` tidak
        bisa menghitung apa pun. Ditutup, **bukan** dilonggarkan — dan
        itu satu-satunya tempat kontrak ini gagal ke arah aman.
        """
        User = get_user_model()

        role = self.make_role(
            "DS-OWN-ORPHAN",
            mode=DataScopeSemanticsTestCase.OWN,
            level=DataScopeLevel.LOCATION,
        )

        user = User.objects.create_user(
            username="ds.orphan",
            email="ds.orphan@example.test",
            password="Test-Only#Pw1",
        )

        self.grant(user, role)

        scope = DataScopeService.for_user(user)

        self.assertFalse(scope.unrestricted)

        self.assertTrue(scope.denied)

        self.assertEqual(self.visible(user), set())


class MultiRoleTests(DataScopeSemanticsTestCase):
    """Skenario 8 — dan aturan yang paling mudah mengejutkan."""

    def test_roles_are_ORed_so_adding_a_role_only_widens(self):
        role_a = self.make_role("DS-OR-A")
        role_b = self.make_role("DS-OR-B")

        self.grant_role(role_a, "company", self.company_a)
        self.grant_role(role_b, "company", self.company_b)

        actor = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        self.grant(actor.user, role_a, role_b)

        seen = self.visible(actor.user)

        self.assertIn(self.emp_a1.employee_number, seen)

        self.assertIn(self.emp_b1.employee_number, seen)

        self.assertNotIn(self.emp_c.employee_number, seen)

    def test_one_all_role_erases_every_restriction_beside_it(self):
        """
        **Perilaku sekarang, dan konsekuensinya besar.**

        Satu role bermode `all` membuat cakupan orang itu tanpa batasan
        untuk **seluruh modul** — termasuk modul yang role itu tidak
        ada urusannya. `demo.hrmanager` memegang HR-MANAGER (`all`)
        bersama WORKFLOW-ADMIN, dan karena itu membaca payroll,
        finance, dan SCM seluruh tenant juga.

        Dikunci apa adanya. Apakah cakupan seharusnya sadar-role adalah
        keputusan arsitektur, bukan sesuatu yang boleh bergeser diam.
        """
        restricted = self.make_role("DS-MIX-RESTRICTED")

        self.grant_role(restricted, "company", self.company_a)

        wide = self.make_role("DS-MIX-ALL", mode=DataScopeSemanticsTestCase.ALL)

        actor = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        self.grant(actor.user, restricted, wide)

        scope = DataScopeService.for_user(actor.user)

        self.assertTrue(scope.unrestricted)

        # Company C tetap terlihat walau tidak satu pun role menyebutnya.
        self.assertIn(self.emp_c.employee_number, self.visible(actor.user))


class ReadPermissionGapTests(DataScopeSemanticsTestCase):
    """
    Cakupan menjawab **di mana**; ia tidak pernah menjawab **apa**.

    Dikunci karena inilah setengah kontrak enterprise yang belum ada:
    `ModelPermission` melewatkan seluruh `SAFE_METHODS`, jadi izin
    `view_*` tidak pernah diperiksa satu kali pun. Orang yang cakupannya
    Company A membaca **semua jenis data** Company A — termasuk payroll —
    tanpa perlu satu izin model pun.
    """

    def test_model_permission_does_not_gate_reads(self):
        from rest_framework.permissions import SAFE_METHODS

        from apps.accounts.permissions import ModelPermission

        class _Request:
            method = "GET"
            user = None

        class _View:
            action = "list"

        request = _Request()

        request.user = self.make_employee(
            self.company_a, self.site_a1, self.dept_a,
        ).user

        # Nol role, nol izin — dan tetap lolos.
        self.assertEqual(request.user.roles.count(), 0)

        self.assertIn(request.method, SAFE_METHODS)

        self.assertTrue(
            ModelPermission().has_permission(request, _View()),
            msg=(
                "Kalau ini gagal, izin baca sudah ditegakkan dan catatan "
                "di docstring berkas ini sudah usang — perbarui, jangan "
                "hapus test-nya."
            ),
        )
