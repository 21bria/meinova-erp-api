"""
Administrasi kewenangan penugasan — lewat API, seperti yang dipakai layar.

Yang dijaga di sini bukan cuma "bisa disimpan", tapi tiga hal yang
kalau salah baru ketahuan dari keluhan pengguna:

1. **Menyimpan kewenangan tidak boleh menyentuh keanggotaan.** PK
   penugasan harus bertahan — kewenangan menempel padanya, dan
   penugasan yang dibuat ulang kehilangan kewenangannya tanpa berbunyi.
2. **Baris `own` tidak boleh terhapus** oleh layar yang tidak
   menampilkannya. 22 penugasan EMPLOYEE di tenant peragaan
   bergantung padanya; penyimpanan yang mengirim daftar tanpa `own`
   akan mencabut hak orang atas datanya sendiri.
3. **`EXPLICIT` tanpa baris diterima**, dan artinya tertutup. Kalau
   suatu saat ia diam-diam jadi "tanpa batasan", yang terlihat cuma
   orang yang mendadak melihat seluruh tenant.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings

from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

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

AUTHORITY_URL = "/api/accounts/user-roles/authority/"
SAVE_URL = "/api/accounts/user-roles/save/"

EMPLOYEE_SCOPE = {
    "company": "organization__company",
    "location": "organization__location",
    "own": "user_id",
}


@override_settings(ROLE_AWARE_DATA_SCOPE=True)
class AuthorityAdminTestCase(TenantTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company_a = Company.objects.create(code="AA-A", name="AA A")
        cls.company_b = Company.objects.create(code="AA-B", name="AA B")

        cls.site_a = Location.objects.create(
            code="AA-LOC-A", name="AA Site A", company=cls.company_a)

        cls.site_b = Location.objects.create(
            code="AA-LOC-B", name="AA Site B", company=cls.company_b)

        cls.department = Department.objects.create(
            code="AA-DEP", name="AA Dept", company=cls.company_a)

        cls.position = Position.objects.create(
            code="AA-POS", name="AA Pos", company=cls.company_a)

        cls.view_employee = Permission.objects.get(
            content_type__app_label="hr", codename="view_employee")

        cls.counter = 0

        cls.admin = cls.make_employee(cls.company_a, cls.site_a).user

        cls.admin.is_superuser = True
        cls.admin.save(update_fields=["is_superuser"])

    @classmethod
    def make_employee(cls, company, location):
        cls.counter += 1

        number = f"AA{cls.counter:04d}"

        user = get_user_model().objects.create_user(
            username=f"aa.user{cls.counter}",
            email=f"aa{cls.counter}@example.com",
            password="x",
        )

        employee = Employee.objects.create(
            employee_number=number, first_name="AA", last_name=number,
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee, company=company, location=location,
            department=cls.department, position=cls.position,
            organization_effective_date=JOIN,
        )

        return employee

    @classmethod
    def make_role(cls, code, *, permissions=()):
        # `Role` menjawab WHAT saja; WHERE dinyatakan lewat layar
        # Kewenangan yang justru diuji berkas ini.
        role = Role.objects.create(code=code, name=code.title())

        if permissions:
            role.permissions.add(*permissions)

        return role

    def setUp(self):
        super().setUp()

        self.clear_caches()

    @staticmethod
    def clear_caches():
        for user in get_user_model().objects.all():
            for attribute in ("_role_perm_cache", "_data_scope_cache"):
                if hasattr(user, attribute):
                    delattr(user, attribute)

    def client_as_admin(self) -> APIClient:
        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

        client.force_authenticate(user=self.admin)

        return client

    def put_authority(self, user, role, mode, level="", authorities=()):
        return self.client_as_admin().post(
            AUTHORITY_URL,
            {
                "user": user.pk,
                "role": role.pk,
                "authority_mode": mode,
                "authority_level": level,
                "authorities": list(authorities),
            },
            format="json",
        )

    def visible(self, user):
        self.clear_caches()

        fresh = get_user_model().objects.get(pk=user.pk)

        return set(
            DataScopeService.filter(
                Employee.objects.filter(is_deleted=False),
                EMPLOYEE_SCOPE,
                fresh,
                required_permission="hr.view_employee",
            ).values_list("employee_number", flat=True)
        )


# ----------------------------------------------------------------------
# Baca
# ----------------------------------------------------------------------


class ReadAuthorityTests(AuthorityAdminTestCase):
    def test_read_returns_authority_per_assignment(self):
        holder = self.make_employee(self.company_a, self.site_a)

        first = self.make_role("AA-READ-1")
        second = self.make_role("AA-READ-2")

        assign_roles(holder.user, [first.pk, second.pk])

        response = self.client_as_admin().get(
            AUTHORITY_URL, {"user": holder.user.pk})

        self.assertEqual(response.status_code, 200, response.content[:300])

        payload = response.json()

        codes = {row["role_code"] for row in payload["assignments"]}

        self.assertEqual(codes, {"AA-READ-1", "AA-READ-2"})

        # Jenis yang boleh disunting datang dari server, dan
        # warehouse/project/iup **tidak** termasuk.
        self.assertIn("company", payload["resource_types"])

        for hidden in ("warehouse", "project", "iup", "own"):
            self.assertNotIn(hidden, payload["resource_types"])

    def test_preserved_own_rows_are_reported_separately(self):
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role("AA-READ-OWN")

        assign_roles(holder.user, [role.pk])

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        RoleAssignmentAuthority.objects.create(
            assignment=assignment, resource_type="own", resource_id=None)

        row = next(
            item for item in self.client_as_admin()
            .get(AUTHORITY_URL, {"user": holder.user.pk})
            .json()["assignments"]
            if item["role_code"] == "AA-READ-OWN"
        )

        self.assertEqual(row["authorities"], [])

        self.assertEqual(
            row["preserved"], [{"resource_type": "own", "resource_id": None}])


# ----------------------------------------------------------------------
# Tulis
# ----------------------------------------------------------------------


class WriteAuthorityTests(AuthorityAdminTestCase):
    def test_update_to_unrestricted(self):
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("AA-W-UNRES", permissions=[self.view_employee])

        assign_roles(holder.user, [role.pk])

        response = self.put_authority(
            holder.user, role, AuthorityMode.UNRESTRICTED)

        self.assertEqual(response.status_code, 200, response.content[:300])

        self.assertIn(far.employee_number, self.visible(holder.user))

    def test_update_to_placement_with_level(self):
        holder = self.make_employee(self.company_a, self.site_a)
        near = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("AA-W-PLACE", permissions=[self.view_employee])

        assign_roles(holder.user, [role.pk])

        response = self.put_authority(
            holder.user, role, AuthorityMode.PLACEMENT,
            level=DataScopeLevel.LOCATION,
        )

        self.assertEqual(response.status_code, 200, response.content[:300])

        seen = self.visible(holder.user)

        self.assertIn(near.employee_number, seen)
        self.assertNotIn(far.employee_number, seen)

    def test_update_to_explicit_rows(self):
        holder = self.make_employee(self.company_a, self.site_a)
        in_b = self.make_employee(self.company_b, self.site_b)
        in_a = self.make_employee(self.company_a, self.site_a)

        role = self.make_role("AA-W-EXP", permissions=[self.view_employee])

        assign_roles(holder.user, [role.pk])

        response = self.put_authority(
            holder.user, role, AuthorityMode.EXPLICIT,
            authorities=[
                {"resource_type": "company", "resource_id": self.company_b.pk},
            ],
        )

        self.assertEqual(response.status_code, 200, response.content[:300])

        seen = self.visible(holder.user)

        self.assertIn(in_b.employee_number, seen)
        self.assertNotIn(in_a.employee_number, seen)

    def test_explicit_without_rows_is_accepted_and_denies(self):
        holder = self.make_employee(self.company_a, self.site_a)

        self.make_employee(self.company_b, self.site_b)

        role = self.make_role("AA-W-ZERO", permissions=[self.view_employee])

        assign_roles(holder.user, [role.pk])

        response = self.put_authority(
            holder.user, role, AuthorityMode.EXPLICIT, authorities=[])

        self.assertEqual(response.status_code, 200, response.content[:300])

        self.assertEqual(self.visible(holder.user), set())

    def test_own_rows_survive_an_explicit_save(self):
        """
        Layar tidak menampilkan `own`, jadi ia juga tidak boleh
        menghapusnya. Tanpa ini, satu kali Simpan mencabut hak orang
        atas datanya sendiri.
        """
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role("AA-W-KEEPOWN", permissions=[self.view_employee])

        assign_roles(holder.user, [role.pk])

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        RoleAssignmentAuthority.objects.create(
            assignment=assignment, resource_type="own", resource_id=None)

        self.put_authority(
            holder.user, role, AuthorityMode.EXPLICIT,
            authorities=[
                {"resource_type": "company", "resource_id": self.company_a.pk},
            ],
        )

        rows = set(
            assignment.authorities.values_list("resource_type", "resource_id")
        )

        self.assertIn(("own", None), rows)
        self.assertIn(("company", self.company_a.pk), rows)


# ----------------------------------------------------------------------
# Validasi
# ----------------------------------------------------------------------


class ValidationTests(AuthorityAdminTestCase):
    def setUp(self):
        super().setUp()

        self.holder = self.make_employee(self.company_a, self.site_a)

        self.role = self.make_role("AA-V", permissions=[self.view_employee])

        assign_roles(self.holder.user, [self.role.pk])

    def test_placement_without_level_is_rejected(self):
        response = self.put_authority(
            self.holder.user, self.role, AuthorityMode.PLACEMENT)

        self.assertEqual(response.status_code, 400, response.content[:300])

    def test_placement_with_rows_is_rejected(self):
        response = self.put_authority(
            self.holder.user, self.role, AuthorityMode.PLACEMENT,
            level=DataScopeLevel.LOCATION,
            authorities=[
                {"resource_type": "company", "resource_id": self.company_a.pk},
            ],
        )

        self.assertEqual(response.status_code, 400, response.content[:300])

    def test_unrestricted_with_level_or_rows_is_rejected(self):
        self.assertEqual(
            self.put_authority(
                self.holder.user, self.role, AuthorityMode.UNRESTRICTED,
                level=DataScopeLevel.COMPANY,
            ).status_code,
            400,
        )

        self.assertEqual(
            self.put_authority(
                self.holder.user, self.role, AuthorityMode.UNRESTRICTED,
                authorities=[
                    {"resource_type": "company",
                     "resource_id": self.company_a.pk},
                ],
            ).status_code,
            400,
        )

    def test_explicit_with_level_is_rejected(self):
        response = self.put_authority(
            self.holder.user, self.role, AuthorityMode.EXPLICIT,
            level=DataScopeLevel.COMPANY,
        )

        self.assertEqual(response.status_code, 400, response.content[:300])

    def test_unknown_mode_is_rejected(self):
        response = self.put_authority(self.holder.user, self.role, "seluruhnya")

        self.assertEqual(response.status_code, 400, response.content[:300])

    def test_hidden_resource_types_are_rejected(self):
        for hidden in ("warehouse", "project", "iup"):
            response = self.put_authority(
                self.holder.user, self.role, AuthorityMode.EXPLICIT,
                authorities=[{"resource_type": hidden, "resource_id": 1}],
            )

            self.assertEqual(
                response.status_code, 400, msg=f"{hidden} diterima",
            )

    def test_authority_cannot_be_set_for_a_role_the_user_does_not_hold(self):
        """
        Layar kewenangan **bukan** pintu kedua untuk memberi role.
        """
        stranger = self.make_role("AA-V-NOTHELD")

        response = self.put_authority(
            self.holder.user, stranger, AuthorityMode.UNRESTRICTED)

        self.assertEqual(response.status_code, 400, response.content[:300])

        self.assertFalse(
            RoleAssignment.objects
            .filter(user=self.holder.user, role=stranger)
            .exists(),
        )


# ----------------------------------------------------------------------
# Keanggotaan tidak ikut terganggu
# ----------------------------------------------------------------------


class MembershipStabilityTests(AuthorityAdminTestCase):
    def test_saving_authority_keeps_the_assignment_pk(self):
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role("AA-PK", permissions=[self.view_employee])

        assign_roles(holder.user, [role.pk])

        before = RoleAssignment.objects.get(user=holder.user, role=role).pk

        for mode, level, rows in (
            (AuthorityMode.UNRESTRICTED, "", []),
            (AuthorityMode.PLACEMENT, DataScopeLevel.LOCATION, []),
            (AuthorityMode.EXPLICIT, "", [
                {"resource_type": "company", "resource_id": self.company_a.pk},
            ]),
            (AuthorityMode.EXPLICIT, "", []),
        ):
            response = self.put_authority(
                holder.user, role, mode, level=level, authorities=rows)

            self.assertEqual(response.status_code, 200, response.content[:300])

            self.assertEqual(
                RoleAssignment.objects.get(user=holder.user, role=role).pk,
                before,
            )

    def test_removing_a_role_removes_its_authority(self):
        holder = self.make_employee(self.company_a, self.site_a)

        keep = self.make_role("AA-RM-KEEP")
        drop = self.make_role("AA-RM-DROP")

        assign_roles(holder.user, [keep.pk, drop.pk])

        self.put_authority(
            holder.user, drop, AuthorityMode.EXPLICIT,
            authorities=[
                {"resource_type": "company", "resource_id": self.company_a.pk},
            ],
        )

        dropped = RoleAssignment.objects.get(user=holder.user, role=drop).pk

        self.assertTrue(
            RoleAssignmentAuthority.objects
            .filter(assignment_id=dropped).exists(),
        )

        response = self.client_as_admin().post(
            SAVE_URL,
            {"user": holder.user.pk, "roles": [str(keep.pk)]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content[:300])

        # CASCADE, bukan baris yatim yang tertinggal.
        self.assertFalse(
            RoleAssignmentAuthority.objects
            .filter(assignment_id=dropped).exists(),
        )

    def test_adding_a_role_creates_exactly_one_assignment(self):
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role("AA-ADD-ONE")

        self.client_as_admin().post(
            SAVE_URL,
            {"user": holder.user.pk, "roles": [str(role.pk)]},
            format="json",
        )

        self.assertEqual(
            RoleAssignment.objects
            .filter(user=holder.user, role=role).count(),
            1,
        )

# ----------------------------------------------------------------------
# Tidak ada jalan kembali ke pelebaran lintas role
# ----------------------------------------------------------------------
#
# `NoUserDataPermissionWideningTests` **dihapus bersama tabelnya**. Satu
# testnya membuat baris cakupan per-orang lalu membuktikan baris itu
# tidak melebarkan apa pun; sesudah tabelnya tidak ada, tidak ada lagi
# yang bisa dibuktikan tidak berpengaruh.
#
# Kebocorannya sendiri tetap dijaga, di tempat yang memang mengujinya:
#
# * `test_authority_cannot_be_set_for_a_role_the_user_does_not_hold`
#   di atas — kewenangan tidak bisa dipasang lewat role yang tidak
#   dipegang;
# * `apps.accounts.tests.test_assignment_scope.PerPermissionReachTests`
#   — kewenangan satu penugasan tidak melebar ke izin yang diberikan
#   role lain.
