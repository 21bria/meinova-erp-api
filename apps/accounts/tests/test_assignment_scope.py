"""
WHERE sekarang datang dari **kewenangan per penugasan** — buktinya.

Yang dijaga berkas ini bukan cuma "aturan barunya jalan", tapi dua hal
yang lebih mudah lolos:

1. **Izin dan kewenangan tetap berpasangan per penugasan.** Role yang
   tidak memberi izin tidak boleh menyumbang kewenangan apa pun untuk
   izin itu — dan sebaliknya, kewenangan tambahan pada satu penugasan
   tidak boleh melebar ke izin yang diberikan role lain. Itu kebocoran
   yang dibuat cakupan per-orang yang lama: satu baris di-OR di atas
   cakupan seluruh role pemegangnya, jadi baris yang dimaksudkan untuk
   kepegawaian ikut membuka payroll.
2. **`EXPLICIT` tanpa baris berarti tertutup**, bukan terbuka. Arah
   kegagalannya dibalik dibanding aturan cakupan yang lama, dan
   membaliknya kembali tanpa sengaja tidak akan berbunyi — yang
   terlihat cuma orang yang tiba-tiba melihat lebih banyak.

Tiap skenario punya assertion negatifnya. Test yang hanya memeriksa
"yang berhak melihat memang melihat" akan tetap hijau pada mesin yang
tidak menyaring apa pun.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings

from django_tenants.test.cases import TenantTestCase

from apps.accounts.models import (
    AuthorityMode,
    DataScopeLevel,
    Role,
    RoleAssignment,
    RoleAssignmentAuthority,
)
from apps.accounts.scoping import DataScopeService
from apps.accounts.services.role_assignment import assign_roles
from apps.administration.models import Company, Department, Location, Position
from apps.hr.models import Employee, OrganizationAssignment


JOIN = date(2020, 1, 6)

EMPLOYEE_SCOPE = {
    "company": "organization__company",
    "location": "organization__location",
    "department": "organization__department",
    "own": "user_id",
}


@override_settings(ROLE_AWARE_DATA_SCOPE=True)
class AssignmentScopeTestCase(TenantTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company_a = Company.objects.create(code="AS-A", name="AS A")
        cls.company_b = Company.objects.create(code="AS-B", name="AS B")

        cls.site_a = Location.objects.create(
            code="AS-LOC-A", name="AS Site A", company=cls.company_a)

        cls.site_a2 = Location.objects.create(
            code="AS-LOC-A2", name="AS Site A2", company=cls.company_a)

        cls.site_b = Location.objects.create(
            code="AS-LOC-B", name="AS Site B", company=cls.company_b)

        cls.dept_a = Department.objects.create(
            code="AS-DEP-A", name="AS Dept A", company=cls.company_a)

        cls.dept_b = Department.objects.create(
            code="AS-DEP-B", name="AS Dept B", company=cls.company_b)

        cls.position = Position.objects.create(
            code="AS-POS", name="AS Pos", company=cls.company_a)

        cls.view_employee = Permission.objects.get(
            content_type__app_label="hr", codename="view_employee")

        cls.view_payslip = Permission.objects.get(
            content_type__app_label="payroll", codename="view_payslip")

        cls.counter = 0

    @classmethod
    def make_employee(cls, company, location, department=None):
        cls.counter += 1

        number = f"AS{cls.counter:04d}"

        user = get_user_model().objects.create_user(
            username=f"as.user{cls.counter}",
            email=f"as{cls.counter}@example.com",
            password="x",
        )

        employee = Employee.objects.create(
            employee_number=number,
            first_name="AS",
            last_name=number,
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=company,
            location=location,
            department=department or (
                cls.dept_a if company == cls.company_a else cls.dept_b),
            position=cls.position,
            organization_effective_date=JOIN,
        )

        return employee

    @classmethod
    def make_role(cls, code, *, permissions=()):
        # Tidak ada kolom cakupan: tiap test di berkas ini menyebut
        # WHERE-nya sendiri lewat `grant()`/`assign_roles()`.
        role = Role.objects.create(code=code, name=code.title())

        if permissions:
            role.permissions.add(*permissions)

        return role

    @classmethod
    def grant(cls, user, role, mode, *, level="", authorities=()):
        """Memberi role **dan** menetapkan kewenangan penugasannya."""
        assign_roles(user, list(
            user.roles.values_list("pk", flat=True)) + [role.pk])

        assignment = RoleAssignment.objects.get(user=user, role=role)

        assignment.authority_mode = mode
        assignment.authority_level = level

        assignment.save(update_fields=["authority_mode", "authority_level"])

        for resource_type, resource_id in authorities:
            RoleAssignmentAuthority.objects.create(
                assignment=assignment,
                resource_type=resource_type,
                resource_id=resource_id,
            )

        return assignment

    def setUp(self):
        super().setUp()

        self.clear_caches()

    @staticmethod
    def clear_caches():
        for user in get_user_model().objects.all():
            for attribute in ("_role_perm_cache", "_data_scope_cache"):
                if hasattr(user, attribute):
                    delattr(user, attribute)

    def visible(self, user, permission="hr.view_employee"):
        self.clear_caches()

        fresh = get_user_model().objects.get(pk=user.pk)

        return set(
            DataScopeService.filter(
                Employee.objects.filter(is_deleted=False),
                EMPLOYEE_SCOPE,
                fresh,
                required_permission=permission,
            ).values_list("employee_number", flat=True)
        )


# ----------------------------------------------------------------------
# Mode
# ----------------------------------------------------------------------


class AuthorityModeTests(AssignmentScopeTestCase):
    def test_unrestricted_sees_everything(self):
        holder = self.make_employee(self.company_a, self.site_a)
        outsider = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("AS-UNRES", permissions=[self.view_employee])

        self.grant(holder.user, role, AuthorityMode.UNRESTRICTED)

        seen = self.visible(holder.user)

        self.assertIn(holder.employee_number, seen)
        self.assertIn(outsider.employee_number, seen)

    def test_placement_at_location(self):
        holder = self.make_employee(self.company_a, self.site_a)
        neighbour = self.make_employee(self.company_a, self.site_a)
        elsewhere = self.make_employee(self.company_a, self.site_a2)

        role = self.make_role("AS-PLACE-LOC", permissions=[self.view_employee])

        self.grant(holder.user, role, AuthorityMode.PLACEMENT,
                   level=DataScopeLevel.LOCATION)

        seen = self.visible(holder.user)

        self.assertIn(holder.employee_number, seen)
        self.assertIn(neighbour.employee_number, seen)

        self.assertNotIn(elsewhere.employee_number, seen)

    def test_placement_at_company(self):
        holder = self.make_employee(self.company_a, self.site_a)
        same_company = self.make_employee(self.company_a, self.site_a2)
        other_company = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("AS-PLACE-CO", permissions=[self.view_employee])

        self.grant(holder.user, role, AuthorityMode.PLACEMENT,
                   level=DataScopeLevel.COMPANY)

        seen = self.visible(holder.user)

        self.assertIn(same_company.employee_number, seen)
        self.assertNotIn(other_company.employee_number, seen)

    def test_explicit_single_authority(self):
        holder = self.make_employee(self.company_a, self.site_a)
        inside = self.make_employee(self.company_a, self.site_a2)
        outside = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("AS-EXP-1", permissions=[self.view_employee])

        self.grant(holder.user, role, AuthorityMode.EXPLICIT,
                   authorities=[("company", self.company_a.pk)])

        seen = self.visible(holder.user)

        self.assertIn(inside.employee_number, seen)
        self.assertNotIn(outside.employee_number, seen)

    def test_explicit_multi_company(self):
        holder = self.make_employee(self.company_a, self.site_a)
        in_a = self.make_employee(self.company_a, self.site_a2)
        in_b = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("AS-EXP-MULTI", permissions=[self.view_employee])

        self.grant(holder.user, role, AuthorityMode.EXPLICIT, authorities=[
            ("company", self.company_a.pk),
            ("company", self.company_b.pk),
        ])

        seen = self.visible(holder.user)

        self.assertIn(in_a.employee_number, seen)
        self.assertIn(in_b.employee_number, seen)

    def test_explicit_without_rows_is_denied_not_unrestricted(self):
        """
        Arah kegagalan yang dibalik, dan inti perbaikannya.

        Pada `Role`, `explicit` tanpa baris berarti **tanpa batasan**.
        Pada penugasan, berarti **tanpa kewenangan**. Kalau ini pernah
        terbalik lagi, yang terlihat cuma orang yang mendadak melihat
        seluruh tenant.
        """
        holder = self.make_employee(self.company_a, self.site_a)

        self.make_employee(self.company_b, self.site_b)

        role = self.make_role("AS-EXP-ZERO", permissions=[self.view_employee])

        self.grant(holder.user, role, AuthorityMode.EXPLICIT)

        self.assertEqual(self.visible(holder.user), set())

        self.clear_caches()

        scope = DataScopeService.for_user(
            get_user_model().objects.get(pk=holder.user.pk),
            permission="hr.view_employee",
        )

        self.assertTrue(scope.denied)
        self.assertFalse(scope.unrestricted)

    def test_stating_the_where_gives_placement_scope_at_location(self):
        """
        Jalur turunannya dibuang — **kemampuannya** harus tetap ada.

        Sampai 4F, penugasan berkewenangan kosong mengikuti konfigurasi
        `Role` saat itu juga. 4G menurunkannya saat penugasan dibuat. 4H
        membuang turunan itu juga: WHERE dinyatakan pemanggil.

        Yang dikunci di sini: menyatakan "ikut penempatan pemegang, pada
        tingkat lokasi" benar-benar menghasilkan cakupan selokasi. Kalau
        baris ini merah, yang hilang bukan cuma jalur lamanya melainkan
        kemampuannya — dan itu regresi, bukan perubahan kontrak.

        Pasangannya `test_blank_authority_is_closed_not_unrestricted`
        di bawah: penugasan yang **tidak** menyatakannya tetap tertutup.
        """
        holder = self.make_employee(self.company_a, self.site_a)
        neighbour = self.make_employee(self.company_a, self.site_a)
        elsewhere = self.make_employee(self.company_a, self.site_a2)

        role = self.make_role("AS-BLANK", permissions=[self.view_employee])

        # Id telanjang: tidak menyatakan apa pun, jadi tertutup.
        assign_roles(holder.user, [role.pk])

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        self.assertEqual(assignment.authority_mode, "")
        self.assertEqual(self.visible(holder.user), set())

        # **Dan mengirim ulang daftarnya tidak memperbaikinya** — itu
        # bukan kekurangan, itu kontraknya: kewenangan hanya ditulis
        # untuk penugasan yang **baru**, supaya menyimpan layar role
        # tidak pernah menimpa kewenangan yang sudah ada. Yang mengubah
        # penugasan yang sudah berdiri adalah layar Kewenangan.
        assign_roles(holder.user, [{
            "role": role.pk,
            "authority_mode": AuthorityMode.PLACEMENT,
            "authority_level": DataScopeLevel.LOCATION,
        }])

        self.assertEqual(
            RoleAssignment.objects.get(
                user=holder.user, role=role).authority_mode,
            "",
            msg=(
                "Penugasan yang bertahan tertimpa oleh penyimpanan "
                "daftar role — kewenangan yang sudah disunting orang "
                "bisa hilang."
            ),
        )

        # Dinyatakan **saat penugasannya dibuat**: cakupannya terbentuk.
        other = self.make_employee(self.company_a, self.site_a)

        assign_roles(other.user, [{
            "role": role.pk,
            "authority_mode": AuthorityMode.PLACEMENT,
            "authority_level": DataScopeLevel.LOCATION,
        }])

        seen = self.visible(other.user)

        self.assertIn(neighbour.employee_number, seen)
        self.assertNotIn(elsewhere.employee_number, seen)

    def test_blank_authority_is_closed_not_unrestricted(self):
        """
        Arah kegagalan yang **dibalik dengan sadar**.

        Aturan cakupan yang lama membaca "ditentukan sendiri, tanpa satu
        pun baris" sebagai *tanpa batasan* — dua keadaan berlawanan
        dinyatakan sama. Stage 4G membaliknya, dan yang dikunci di sini
        arah barunya: penugasan yang tidak menyatakan kewenangannya
        tidak melihat apa pun.

        Assertion-nya **negatif**, dan itu memang bentuk yang benar di
        sini: yang diuji bukan "ia melihat sesuatu" melainkan "ia tidak
        melihat orang di luar jangkauannya".
        """
        holder = self.make_employee(self.company_a, self.site_a)
        outsider = self.make_employee(self.company_b, self.site_b)

        role = self.make_role(
            "AS-BLANK-ZERO",
            permissions=[self.view_employee],
        )

        # Id telanjang: kewenangannya tidak dinyatakan.
        assign_roles(holder.user, [role.pk])

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        self.assertEqual(assignment.authority_mode, "")

        # Tertutup — bukan terbuka.
        self.assertNotIn(
            outsider.employee_number, self.visible(holder.user))

        self.assertEqual(self.visible(holder.user), set())

        scope = DataScopeService.for_user(
            get_user_model().objects.get(pk=holder.user.pk),
            permission="hr.view_employee",
        )

        self.assertTrue(scope.denied)
        self.assertFalse(scope.unrestricted)


# ----------------------------------------------------------------------
# Kewenangan per orang, dan tidak ada peminjaman
# ----------------------------------------------------------------------


class PerAssignmentAuthorityTests(AssignmentScopeTestCase):
    def test_same_role_different_authority_per_user(self):
        """Yang tidak bisa dinyatakan sebelum stage ini."""
        first = self.make_employee(self.company_a, self.site_a)
        second = self.make_employee(self.company_a, self.site_a2)

        peer_a = self.make_employee(self.company_a, self.site_a)
        peer_a2 = self.make_employee(self.company_a, self.site_a2)

        role = self.make_role("AS-SHARED", permissions=[self.view_employee])

        self.grant(first.user, role, AuthorityMode.EXPLICIT,
                   authorities=[("location", self.site_a.pk)])

        self.grant(second.user, role, AuthorityMode.EXPLICIT,
                   authorities=[("location", self.site_a2.pk)])

        seen_first = self.visible(first.user)
        seen_second = self.visible(second.user)

        self.assertIn(peer_a.employee_number, seen_first)
        self.assertNotIn(peer_a2.employee_number, seen_first)

        self.assertIn(peer_a2.employee_number, seen_second)
        self.assertNotIn(peer_a.employee_number, seen_second)

    def test_role_without_the_permission_contributes_no_authority(self):
        """
        Role yang tidak memberi WHAT menyumbang nol WHERE.

        Kewenangan luas pada role yang tidak memberi izin itu tidak
        boleh membuat izin dari role lain ikut melebar.
        """
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        narrow = self.make_role("AS-NARROW", permissions=[self.view_employee])

        wide = self.make_role("AS-WIDE")  # tanpa izin apa pun

        self.grant(holder.user, narrow, AuthorityMode.EXPLICIT,
                   authorities=[("location", self.site_a.pk)])

        self.grant(holder.user, wide, AuthorityMode.UNRESTRICTED)

        seen = self.visible(holder.user)

        self.assertNotIn(
            far.employee_number, seen,
            msg="Kewenangan role tanpa izin ikut terpakai — peminjaman "
                "lintas role.",
        )

    def test_two_roles_granting_the_same_permission_union_their_authority(self):
        holder = self.make_employee(self.company_a, self.site_a)

        peer_a = self.make_employee(self.company_a, self.site_a)
        peer_a2 = self.make_employee(self.company_a, self.site_a2)
        peer_b = self.make_employee(self.company_b, self.site_b)

        first = self.make_role("AS-UNION-1", permissions=[self.view_employee])
        second = self.make_role("AS-UNION-2", permissions=[self.view_employee])

        self.grant(holder.user, first, AuthorityMode.EXPLICIT,
                   authorities=[("location", self.site_a.pk)])

        self.grant(holder.user, second, AuthorityMode.EXPLICIT,
                   authorities=[("location", self.site_a2.pk)])

        seen = self.visible(holder.user)

        self.assertIn(peer_a.employee_number, seen)
        self.assertIn(peer_a2.employee_number, seen)

        self.assertNotIn(peer_b.employee_number, seen)


# ----------------------------------------------------------------------
# Jangkauan dihitung per izin, tidak dipinjam antar role
# ----------------------------------------------------------------------
#
# Kelas ini dulu bernama `UserDataPermissionRetiredTests`, dan isinya
# satu test lagi yang membuat baris cakupan per-orang untuk membuktikan
# baris itu tidak berpengaruh. Test itu **dihapus bersama tabelnya**:
# sesudah tabelnya tidak ada, tidak ada lagi yang bisa dibuktikan tidak
# berpengaruh, dan assertion pengganti yang tidak menguji apa pun lebih
# buruk daripada tidak ada test.
#
# Yang **tidak** hilang kebocorannya sendiri. Bentuk kebocoran itu —
# kewenangan satu penugasan melebar ke izin yang diberikan role lain —
# masih bisa lahir dari kode sekarang, dan itu yang dijaga di bawah.


class PerPermissionReachTests(AssignmentScopeTestCase):
    def test_executive_pattern_keeps_hr_reach_but_loses_payroll_reach(self):
        """
        Pola `demo.gmho`, direplikasi dari fixture.

        Kewenangan dua company menempel pada penugasan **EXECUTIVE**,
        yang memberi `hr.view_employee` tapi **tidak** memberi
        `payroll.view_payslip`. Jangkauan HR-nya lintas dua company
        tetap; jangkauan payroll-nya menyusut jadi diri sendiri — dan
        itu memang yang diputuskan, karena akses itu dulu datang dari
        role `EMPLOYEE` yang dilebarkan cakupan per-orang.
        """
        holder = self.make_employee(self.company_a, self.site_a)

        in_a = self.make_employee(self.company_a, self.site_a2)
        in_b = self.make_employee(self.company_b, self.site_b)

        executive = self.make_role(
            "AS-EXEC", permissions=[self.view_employee])

        ess = self.make_role("AS-ESS", permissions=[self.view_payslip])

        self.grant(holder.user, executive, AuthorityMode.EXPLICIT, authorities=[
            ("company", self.company_a.pk),
            ("company", self.company_b.pk),
        ])

        self.grant(holder.user, ess, AuthorityMode.EXPLICIT,
                   authorities=[("own", None)])

        seen = self.visible(holder.user)

        self.assertIn(in_a.employee_number, seen)
        self.assertIn(in_b.employee_number, seen)

        self.clear_caches()

        payroll_scope = DataScopeService.for_user(
            get_user_model().objects.get(pk=holder.user.pk),
            permission="payroll.view_payslip",
        )

        self.assertFalse(payroll_scope.unrestricted)

        self.assertEqual(
            payroll_scope.role_scopes, [{"own": True}],
            msg="Jangkauan payroll ikut melebar ke company — kebocoran "
                "lintas role kembali.",
        )


# ----------------------------------------------------------------------
# Workflow tidak ikut berubah
# ----------------------------------------------------------------------


class WorkflowUnaffectedTests(AssignmentScopeTestCase):
    def test_role_holder_resolution_unchanged(self):
        from apps.workflow.models import ApproverScope
        from apps.workflow.resolver import _role_holders

        here = self.make_employee(self.company_a, self.site_a)
        there = self.make_employee(self.company_a, self.site_a2)

        role = self.make_role("AS-WF", permissions=[self.view_employee])

        # Kewenangan yang **berbeda** untuk dua pemegang role yang sama.
        self.grant(here.user, role, AuthorityMode.EXPLICIT,
                   authorities=[("location", self.site_a.pk)])

        self.grant(there.user, role, AuthorityMode.UNRESTRICTED)

        holders = _role_holders(
            role,
            scope=ApproverScope.LOCATION,
            organization=here.organization,
        )

        numbers = {holder.employee_number for holder in holders}

        self.assertIn(here.employee_number, numbers)

        self.assertNotIn(
            there.employee_number, numbers,
            msg="Resolver approval ikut terpengaruh kewenangan data.",
        )
