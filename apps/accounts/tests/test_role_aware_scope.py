"""
Kontrak otoritas per-izin: izin dari satu role tidak memakai cakupan
role lain.

Stage 2 membuktikan peminjaman itu ada dan mengunci perilakunya apa
adanya. Berkas ini menguji **perbaikannya**, dan menguji keduanya:
jalur lama masih harus berperilaku seperti dulu selama
`ROLE_AWARE_DATA_SCOPE` mati, jalur baru harus menyempit begitu ia
menyala. Dua mode diuji berdampingan pada panggung yang sama, karena
"berubah" hanya berarti sesuatu kalau keduanya bisa dibandingkan.

Yang **tidak** berubah di sini, dan sengaja diuji supaya tetap begitu:

* `own` organisasi tetap berarti penempatan (company/location), bukan
  "barisku sendiri" — akses baris-sendiri tetap lewat baris `own` di
  `RoleDataPermission` dan lewat `EmployeeDataPolicy`;
* `UserDataPermission` tetap menambah untuk **semua** izin. Itu batas
  yang belum tertutup, dan dikunci di sini supaya tidak hilang dari
  ingatan.

Tiap skenario punya assertion negatif. Test cakupan yang cuma memeriksa
"yang boleh terlihat memang terlihat" akan tetap hijau pada mesin yang
tidak menyaring apa pun.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings

from django_tenants.test.cases import TenantTestCase

from apps.accounts.services.role_assignment import grant_role
from apps.accounts.models import (
    AuthorityResourceType,
    AuthorityMode,
    DataScopeLevel,
    Role,
)
from apps.accounts.scoping import DataScopeService
from apps.administration.models import Company, Department, Location, Position
from apps.hr.api.employee.scope import EMPLOYEE_SCOPE
from apps.hr.models import Employee, OrganizationAssignment


JOIN = date(2020, 1, 6)

PERM_EMPLOYEE = "hr.view_employee"
PERM_PAYSLIP = "payroll.view_payslip"


class RoleAwareScopeTests(TenantTestCase):
    """
    Dua company, dua lokasi di salah satunya, dan pegawai penanda di
    tiap sudut.

    `hr.employee` dipakai sebagai resource uji karena ia satu-satunya
    yang pasti berisi di tiap panggung — dan karena petanya
    (`EMPLOYEE_SCOPE`) persis yang dipakai viewset sungguhan.
    Pertanyaan yang diuji bukan "tabel apa", melainkan "cakupan siapa".
    """

    _n = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "role-aware"
        tenant.name = "Role Aware"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company_a = Company.objects.create(code="RWA", name="Company A")
        cls.company_b = Company.objects.create(code="RWB", name="Company B")

        cls.site_a1 = Location.objects.create(
            company=cls.company_a, code="RWA-1", name="Site A1")
        cls.site_a2 = Location.objects.create(
            company=cls.company_a, code="RWA-2", name="Site A2")
        cls.site_b1 = Location.objects.create(
            company=cls.company_b, code="RWB-1", name="Site B1")

        cls.dept_a = Department.objects.create(
            company=cls.company_a, code="RWA-OPS", name="Operations A")
        cls.dept_b = Department.objects.create(
            company=cls.company_b, code="RWB-OPS", name="Operations B")

        cls.peer_a1 = cls.make_employee(
            cls.company_a, cls.site_a1, cls.dept_a, with_user=False)
        cls.peer_a2 = cls.make_employee(
            cls.company_a, cls.site_a2, cls.dept_a, with_user=False)
        cls.peer_b1 = cls.make_employee(
            cls.company_b, cls.site_b1, cls.dept_b, with_user=False)

        cls.view_employee = Permission.objects.get(
            content_type__app_label="hr", codename="view_employee")
        cls.view_payslip = Permission.objects.get(
            content_type__app_label="payroll", codename="view_payslip")

    # ------------------------------------------------------------------

    @classmethod
    def make_employee(cls, company, location, department, *, with_user=True):
        User = get_user_model()

        cls._n += 1

        user = None

        if with_user:
            user = User.objects.create_user(
                username=f"rw.user{cls._n}",
                email=f"rw.user{cls._n}@example.test",
                password="Test-Only#Pw1",
            )

        position = Position.objects.create(
            company=company,
            department=department,
            code=f"RW-POS{cls._n}",
            name=f"Position {cls._n}",
        )

        employee = Employee.objects.create(
            employee_number=f"RW-{cls._n:03d}",
            first_name="Aware",
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
    # Bentuk panggilannya tidak berubah, jadi tiap skenario di bawah
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
    def make_role(cls, code, *, mode=EXPLICIT, level="", permissions=()):
        role = Role.objects.create(code=f"{code}-{cls._n}", name=code.title())

        cls._declared[role.pk] = {"mode": mode, "level": level, "rows": []}

        if permissions:
            role.permissions.add(*permissions)

        return role

    @classmethod
    def scope_row(cls, role, resource_type, resource=None):
        """Satu nilai cakupan untuk `role`, dicatat sebagai deklarasi."""
        cls._declared[role.pk]["rows"].append(
            (resource_type, getattr(resource, "pk", None)))

    def setUp(self):
        super().setUp()

        self.clear_caches()

    @staticmethod
    def clear_caches():
        for user in get_user_model().objects.all():
            for attribute in ("_role_perm_cache", "_data_scope_cache"):
                if hasattr(user, attribute):
                    delattr(user, attribute)

    # ------------------------------------------------------------------

    def visible(self, user, permission=None):
        """
        Nomor pegawai yang terlihat. Cache-nya dibuang tiap panggilan —
        kalau tidak, jawaban mode sebelumnya terbaca lagi di mode
        berikutnya dan testnya lulus karena alasan yang salah.
        """
        if hasattr(user, "_data_scope_cache"):
            del user._data_scope_cache

        queryset = DataScopeService.filter(
            Employee.objects.filter(is_deleted=False),
            EMPLOYEE_SCOPE,
            user,
            required_permission=permission,
        )

        return set(queryset.values_list("employee_number", flat=True))

    def legacy(self, user, permission=PERM_EMPLOYEE):
        with override_settings(ROLE_AWARE_DATA_SCOPE=False):
            return self.visible(user, permission)

    def aware(self, user, permission=PERM_EMPLOYEE):
        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            return self.visible(user, permission)


    def test_permission_and_scope_from_the_same_role_still_work(self):
        """
        **A.** Perbaikan yang menyempitkan yang benar juga bukan
        perbaikan. Role yang memberi izin **dan** cakupannya sekaligus
        harus tetap bekerja utuh di kedua mode.
        """
        employee = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        role = self.make_role("RW-HR-A", permissions=[self.view_employee])

        self.scope_row(
            role, AuthorityResourceType.COMPANY, self.company_a)

        self.grant(employee.user, role)

        for mode, visible in (
            ("lama", self.legacy(employee.user)),
            ("role-aware", self.aware(employee.user)),
        ):
            self.assertIn(self.peer_a1.employee_number, visible, msg=mode)
            self.assertIn(self.peer_a2.employee_number, visible, msg=mode)
            self.assertNotIn(self.peer_b1.employee_number, visible, msg=mode)

    def test_scope_of_a_role_without_the_permission_is_not_borrowed(self):
        """
        **B, dan inti seluruh Stage 3A.**

        Role A memberi izin dengan cakupan sempit; Role B memberi
        cakupan luas tanpa izin itu. Jalur lama menggabungkan keduanya;
        jalur role-aware berhenti di cakupan Role A.
        """
        employee = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        narrow = self.make_role("RW-NARROW", permissions=[self.view_employee])

        self.scope_row(
            narrow, AuthorityResourceType.LOCATION, self.site_a1)

        wide = self.make_role("RW-WIDE")

        self.scope_row(
            wide, AuthorityResourceType.COMPANY, self.company_a)

        self.grant(employee.user, narrow, wide)

        legacy = self.legacy(employee.user)

        self.assertIn(
            self.peer_a2.employee_number,
            legacy,
            msg="Jalur lama memang meminjam — kalau tidak, panggungnya salah.",
        )

        aware = self.aware(employee.user)

        self.assertIn(self.peer_a1.employee_number, aware)

        self.assertNotIn(
            self.peer_a2.employee_number,
            aware,
            msg=(
                "Cakupan RW-WIDE ikut terpakai padahal role itu tidak "
                "memberi `hr.view_employee`."
            ),
        )

    def test_two_qualifying_roles_union_their_scopes(self):
        """**C.** Dua role yang sama-sama memberi izinnya: digabung."""
        employee = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        first = self.make_role("RW-Q1", permissions=[self.view_employee])

        self.scope_row(
            first, AuthorityResourceType.LOCATION, self.site_a1)

        second = self.make_role("RW-Q2", permissions=[self.view_employee])

        self.scope_row(
            second, AuthorityResourceType.LOCATION, self.site_a2)

        self.grant(employee.user, first, second)

        aware = self.aware(employee.user)

        self.assertIn(self.peer_a1.employee_number, aware)
        self.assertIn(self.peer_a2.employee_number, aware)

        self.assertNotIn(
            self.peer_b1.employee_number,
            aware,
            msg="Gabungan dua lokasi tidak boleh ikut membuka company lain.",
        )


    def test_an_unrelated_all_role_no_longer_opens_everything(self):
        """
        **D.** Bentuk peminjaman yang paling tajam, dan yang paling
        sering ada di tenant sungguhan: satu role lintas-tenant untuk
        urusan lain.
        """
        employee = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        narrow = self.make_role("RW-ALL-N", permissions=[self.view_employee])

        self.scope_row(
            narrow, AuthorityResourceType.LOCATION, self.site_a1)

        # Tanpa `hr.view_employee`. Izinnya sengaja payroll — resource
        # yang sama sekali lain.
        unrelated = self.make_role(
            "RW-ALL-U",
            mode=RoleAwareScopeTests.ALL,
            permissions=[self.view_payslip],
        )

        self.grant(employee.user, narrow, unrelated)

        self.assertIn(
            self.peer_b1.employee_number,
            self.legacy(employee.user),
            msg="Jalur lama memang membuka semuanya.",
        )

        aware = self.aware(employee.user)

        self.assertIn(self.peer_a1.employee_number, aware)

        self.assertNotIn(
            self.peer_b1.employee_number,
            aware,
            msg="Role `all` yang tidak memberi izin ini tidak boleh membuka.",
        )

    def test_a_qualifying_all_role_is_still_unrestricted(self):
        """
        **E.** `all` tidak dilemahkan — ia cuma dibatasi pada izin yang
        memang diberikan role itu.
        """
        employee = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        role = self.make_role(
            "RW-ALL-Q",
            mode=RoleAwareScopeTests.ALL,
            permissions=[self.view_employee],
        )

        self.grant(employee.user, role)

        aware = self.aware(employee.user)

        self.assertIn(self.peer_a1.employee_number, aware)
        self.assertIn(self.peer_b1.employee_number, aware)

        # …tapi tidak untuk izin yang tidak diberikannya.
        self.assertEqual(
            self.aware(employee.user, PERM_PAYSLIP),
            set(),
            msg="`all` milik role ini tidak boleh menular ke izin lain.",
        )


    def test_finance_manager_stops_at_its_own_company(self):
        """
        **F.** `own`/Company, persis bentuk `FINANCE-MANAGER` yang
        diseed. Company lain tertutup **meski** ia memegang role kedua
        yang mencakupnya.
        """
        employee = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        finance = self.make_role(
            "RW-FIN",
            mode=RoleAwareScopeTests.OWN,
            level=DataScopeLevel.COMPANY,
            permissions=[self.view_employee],
        )

        # Role kedua yang mencakup company B, tanpa izin kepegawaian.
        other = self.make_role("RW-FIN-OTHER")

        self.scope_row(
            other, AuthorityResourceType.COMPANY, self.company_b)

        self.grant(employee.user, finance, other)

        aware = self.aware(employee.user)

        self.assertIn(self.peer_a1.employee_number, aware)
        self.assertIn(self.peer_a2.employee_number, aware)

        self.assertNotIn(
            self.peer_b1.employee_number,
            aware,
            msg="Finance Manager tidak boleh melebar ke company role lain.",
        )

    def test_broad_scope_without_the_permission_yields_nothing(self):
        """
        **I.** BOD/Executive: cakupan seluas apa pun, tanpa izin
        rincinya, tetap nol baris.

        Diuji di lapis cakupan, bukan cuma di gerbang izin. Pembaca yang
        merakit querysetnya sendiri — dashboard, report, export — tidak
        melewati `ModelPermission`, jadi kalau penolakannya hanya ada di
        sana, pintu itu tetap terbuka.
        """
        employee = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        executive = self.make_role(
            "RW-EXEC",
            mode=RoleAwareScopeTests.ALL,
            permissions=[self.view_employee],
        )

        self.grant(employee.user, executive)

        self.assertEqual(
            self.aware(employee.user, PERM_PAYSLIP),
            set(),
            msg=(
                "Cakupan tenant-wide tanpa izin payroll tetap harus nol "
                "baris payroll."
            ),
        )

        # Sekaligus bukti bahwa yang menutup bukan panggung yang kosong:
        # izin yang memang dipegangnya tetap membuka barisnya.
        self.assertIn(
            self.peer_b1.employee_number,
            self.aware(employee.user, PERM_EMPLOYEE),
        )


    def test_own_record_row_still_means_only_my_row(self):
        """
        **G.** Baris `own` di `RoleDataPermission` tetap berarti barisnya
        sendiri, dan role-aware tidak menggesernya.
        """
        employee = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        ess = self.make_role("RW-ESS", permissions=[self.view_employee])

        self.scope_row(ess, AuthorityResourceType.OWN)

        self.grant(employee.user, ess)

        aware = self.aware(employee.user)

        self.assertEqual(aware, {employee.employee_number})

        self.assertNotIn(self.peer_a1.employee_number, aware)

    def test_organizational_own_is_still_placement_not_self(self):
        """
        **G, sisi sebaliknya.** `data_scope_mode=OWN` tetap berarti
        penempatan — kalau ia diam-diam berubah jadi "barisku", admin
        site kehilangan seluruh timnya dan gejalanya cuma layar kosong.
        """
        employee = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        role = self.make_role(
            "RW-PLACE",
            mode=RoleAwareScopeTests.OWN,
            level=DataScopeLevel.LOCATION,
            permissions=[self.view_employee],
        )

        self.grant(employee.user, role)

        aware = self.aware(employee.user)

        self.assertIn(employee.employee_number, aware)

        self.assertIn(
            self.peer_a1.employee_number,
            aware,
            msg="`own`/location harus tetap berarti selokasi, bukan sendiri.",
        )

        self.assertNotIn(self.peer_a2.employee_number, aware)



    def test_superuser_is_unrestricted_in_both_modes(self):
        User = get_user_model()

        root = User.objects.create_superuser(
            username="rw.root",
            email="rw.root@example.test",
            password="Test-Only#Pw1",
        )

        for mode in (False, True):
            with override_settings(ROLE_AWARE_DATA_SCOPE=mode):
                self.assertTrue(
                    DataScopeService.for_user(
                        root, permission=PERM_PAYSLIP).unrestricted,
                    msg=f"ROLE_AWARE_DATA_SCOPE={mode}",
                )

    def test_callers_without_a_permission_keep_legacy_behaviour(self):
        """
        Peluncurannya bertahap, dan ini yang membuatnya mungkin.

        Pemanggil yang belum mengirimkan izinnya — 24 dari 25 hari ini:
        lookup, dashboard, report, importer — harus berperilaku persis
        seperti sebelumnya **meski saklarnya menyala**. Kalau tidak,
        menyalakan saklar berarti mengubah 25 jalur sekaligus.
        """
        employee = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        narrow = self.make_role("RW-COMPAT", permissions=[self.view_employee])

        self.scope_row(
            narrow, AuthorityResourceType.LOCATION, self.site_a1)

        wide = self.make_role("RW-COMPAT-W")

        self.scope_row(
            wide, AuthorityResourceType.COMPANY, self.company_a)

        self.grant(employee.user, narrow, wide)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            without = self.visible(employee.user, permission=None)

        self.assertIn(
            self.peer_a2.employee_number,
            without,
            msg=(
                "Pemanggil tanpa `required_permission` ikut menyempit — "
                "peluncuran bertahapnya jadi tidak mungkin."
            ),
        )

    def test_the_flag_is_what_switches_behaviour(self):
        """
        Saklarnya benar-benar yang menentukan, bukan kebetulan panggung.
        """
        employee = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        narrow = self.make_role("RW-FLAG", permissions=[self.view_employee])

        self.scope_row(
            narrow, AuthorityResourceType.LOCATION, self.site_a1)

        wide = self.make_role("RW-FLAG-W")

        self.scope_row(
            wide, AuthorityResourceType.COMPANY, self.company_a)

        self.grant(employee.user, narrow, wide)

        self.assertNotEqual(
            self.legacy(employee.user),
            self.aware(employee.user),
            msg="Kedua mode memberi jawaban yang sama — saklarnya tidak jalan.",
        )
