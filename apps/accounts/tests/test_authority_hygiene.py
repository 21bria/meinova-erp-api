"""
Pemeriksaan kebersihan kewenangan — penggantinya perkakas peralihan.

Berkas ini ada karena penghapusan skema lama ikut menghapus
pemeriksaannya. `audit_legacy_retirement` menemukan penugasan tanpa
kewenangan **sebagai efek samping** dari pertanyaan lain ("sudah
dipindahkan dari skema lama?"), dan pertanyaan itu berhenti berarti
begitu skemanya tidak ada.

Yang dijaga di sini bagian yang tidak kedaluwarsa: keadaan kewenangan
yang tidak menyatakan apa pun tetap bisa lahir besok, dari kode yang
ditulis orang yang belum pernah mendengar soal skema lama.

Tiap test punya **pasangan negatifnya** — satu tenant bersih yang harus
tetap dilaporkan bersih. Pemeriksa yang menandai semuanya tidak lebih
berguna daripada yang tidak menandai apa pun, dan cuma yang pertama
terlihat seperti bekerja.
"""

from __future__ import annotations

import io
from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command

from django_tenants.test.cases import TenantTestCase

from apps.accounts.models import (
    AuthorityMode,
    DataScopeLevel,
    Role,
    RoleAssignment,
    RoleAssignmentAuthority,
)
from apps.accounts.services.authority_hygiene import (
    authority_hygiene,
    is_clean,
)
from apps.accounts.services.role_assignment import grant_role
from apps.administration.models import Company, Department, Location, Position
from apps.hr.models import Employee, OrganizationAssignment


JOIN = date(2020, 1, 6)


class AuthorityHygieneTestCase(TenantTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(code="AH-C", name="AH C")

        cls.site = Location.objects.create(
            code="AH-LOC", name="AH Site", company=cls.company)

        cls.department = Department.objects.create(
            code="AH-DEP", name="AH Dept", company=cls.company)

        cls.position = Position.objects.create(
            code="AH-POS", name="AH Pos", company=cls.company)

        cls.view_employee = Permission.objects.get(
            content_type__app_label="hr", codename="view_employee")

        cls.counter = 0

    @classmethod
    def make_employee(cls):
        cls.counter += 1

        number = f"AH{cls.counter:04d}"

        user = get_user_model().objects.create_user(
            username=f"ah.user{cls.counter}",
            email=f"ah{cls.counter}@example.com",
            password="x",
        )

        employee = Employee.objects.create(
            employee_number=number, first_name="AH", last_name=number,
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee, company=cls.company, location=cls.site,
            department=cls.department, position=cls.position,
            organization_effective_date=JOIN,
        )

        return employee

    @classmethod
    def make_role(cls, code):
        role = Role.objects.create(code=code, name=code.title())

        role.permissions.add(cls.view_employee)

        return role

    def clean_holder(self, code):
        """Satu penugasan yang benar-benar menyatakan kewenangannya."""
        holder = self.make_employee()

        role = self.make_role(code)

        grant_role(
            holder.user, role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("company", self.company.pk)],
        )

        return holder, role


class CleanTenantTests(AuthorityHygieneTestCase):
    def test_a_tenant_whose_authority_is_stated_is_clean(self):
        self.clean_holder("AH-OK")

        report = authority_hygiene()

        self.assertTrue(is_clean(report), report)

        self.assertEqual(report["blank_authority"], [])
        self.assertEqual(report["explicit_without_rows"], [])
        self.assertEqual(report["malformed_rows"], [])

        # Dan hitungannya memang melihat sesuatu — laporan "bersih" atas
        # tenant kosong tidak membuktikan pemeriksanya jalan.
        self.assertEqual(report["assignments"], 1)
        self.assertEqual(report["authority_rows"], 1)

    def test_placement_with_a_level_is_clean(self):
        holder = self.make_employee()

        role = self.make_role("AH-PLACEMENT")

        grant_role(
            holder.user, role,
            mode=AuthorityMode.PLACEMENT,
            level=DataScopeLevel.LOCATION,
        )

        self.assertTrue(is_clean(authority_hygiene()))

    def test_unrestricted_without_rows_is_clean(self):
        """`UNRESTRICTED` memang tidak memakai baris — bukan temuan."""
        holder = self.make_employee()

        role = self.make_role("AH-UNRESTRICTED")

        grant_role(holder.user, role, mode=AuthorityMode.UNRESTRICTED)

        self.assertTrue(is_clean(authority_hygiene()))


class FindingsTests(AuthorityHygieneTestCase):
    def test_blank_authority_is_reported(self):
        holder = self.make_employee()

        role = self.make_role("AH-BLANK")

        # Jalur yang tidak menyebut WHERE sama sekali.
        holder.user.roles.add(role)

        report = authority_hygiene()

        self.assertFalse(is_clean(report))

        self.assertEqual(
            [(row.user_id, row.role_id) for row in report["blank_authority"]],
            [(holder.user.pk, role.pk)],
        )

    def test_explicit_without_rows_is_reported(self):
        holder = self.make_employee()

        role = self.make_role("AH-EXP-ZERO")

        grant_role(
            holder.user, role, mode=AuthorityMode.EXPLICIT, authorities=[])

        report = authority_hygiene()

        self.assertFalse(is_clean(report))

        self.assertEqual(
            [row.role_id for row in report["explicit_without_rows"]],
            [role.pk],
        )

        # **Dilaporkan, bukan diperbaiki.** Keadaannya tidak boleh
        # bergeser hanya karena dibaca — perkakas ini read-only, dan
        # menebak WHERE seseorang justru kesalahan yang dihindari
        # seluruh rangkaian ini.
        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        self.assertEqual(assignment.authority_mode, AuthorityMode.EXPLICIT)
        self.assertFalse(assignment.authorities.exists())

    def test_placement_without_a_level_is_reported(self):
        holder = self.make_employee()

        role = self.make_role("AH-PLACEMENT-BARE")

        # Langsung ke tabelnya: `grant_role()` menolaknya, dan justru
        # itu sebabnya bentuk ini cuma bisa lahir dari jalur lain.
        RoleAssignment.objects.create(
            user=holder.user,
            role=role,
            authority_mode=AuthorityMode.PLACEMENT,
            authority_level="",
        )

        report = authority_hygiene()

        self.assertFalse(is_clean(report))

        self.assertEqual(
            [row.role_id for row in report["placement_without_level"]],
            [role.pk],
        )

    def test_a_malformed_row_is_reported(self):
        holder, role = self.clean_holder("AH-MALFORMED")

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        RoleAssignmentAuthority.objects.create(
            assignment=assignment,
            resource_type="tidak-dikenal",
            resource_id=1,
        )

        report = authority_hygiene()

        self.assertFalse(is_clean(report))

        self.assertEqual(
            [row.resource_type for row in report["malformed_rows"]],
            ["tidak-dikenal"],
        )

    def test_a_company_row_without_an_id_is_reported(self):
        """`company` tanpa id tidak menyaring apa pun — dan tidak berarti."""
        holder, role = self.clean_holder("AH-NOID")

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        RoleAssignmentAuthority.objects.create(
            assignment=assignment,
            resource_type="company",
            resource_id=None,
        )

        self.assertFalse(is_clean(authority_hygiene()))

    def test_own_without_an_id_is_not_a_finding(self):
        """`own` memang tidak menyebut id: sasarannya pemegangnya sendiri."""
        holder = self.make_employee()

        role = self.make_role("AH-OWN")

        grant_role(
            holder.user, role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("own", None)],
        )

        self.assertTrue(is_clean(authority_hygiene()))

    def test_rows_on_a_non_explicit_mode_are_reported(self):
        """
        Baris yang **terlihat** membatasi tapi tidak dibaca siapa pun.

        Bukan kebocoran — `DataScopeService` mengabaikannya. Yang
        membuatnya perlu dilaporkan: di layar ia terbaca seperti
        pembatasan yang berlaku, dan pembatasan yang cuma terlihat
        lebih berbahaya daripada yang tidak ada sama sekali.
        """
        holder = self.make_employee()

        role = self.make_role("AH-UNRESTRICTED-ROWS")

        grant_role(holder.user, role, mode=AuthorityMode.UNRESTRICTED)

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        RoleAssignmentAuthority.objects.create(
            assignment=assignment,
            resource_type="company",
            resource_id=self.company.pk,
        )

        report = authority_hygiene()

        self.assertFalse(is_clean(report))

        self.assertEqual(len(report["rows_on_non_explicit_mode"]), 1)


class CommandTests(AuthorityHygieneTestCase):
    def test_the_command_passes_on_a_clean_tenant(self):
        self.clean_holder("AH-CMD-OK")

        out = io.StringIO()

        call_command(
            "audit_authority_hygiene",
            schema=self.tenant.schema_name,
            stdout=out,
            stderr=io.StringIO(),
        )

        self.assertIn("BERSIH", out.getvalue())

    def test_the_command_fails_on_a_finding(self):
        holder = self.make_employee()

        role = self.make_role("AH-CMD-BAD")

        holder.user.roles.add(role)

        out, err = io.StringIO(), io.StringIO()

        with self.assertRaises(SystemExit):
            call_command(
                "audit_authority_hygiene",
                schema=self.tenant.schema_name,
                stdout=out,
                stderr=err,
            )

        self.assertIn("ADA TEMUAN", out.getvalue())

    def test_the_command_changes_nothing(self):
        """Read-only, dibuktikan dari keadaan sesudahnya."""
        holder = self.make_employee()

        role = self.make_role("AH-CMD-READONLY")

        holder.user.roles.add(role)

        before = sorted(
            RoleAssignment.objects.values_list(
                "pk", "user_id", "role_id", "authority_mode", "authority_level")
        )

        rows_before = RoleAssignmentAuthority.objects.count()

        with self.assertRaises(SystemExit):
            call_command(
                "audit_authority_hygiene",
                schema=self.tenant.schema_name,
                stdout=io.StringIO(),
                stderr=io.StringIO(),
            )

        self.assertEqual(
            sorted(
                RoleAssignment.objects.values_list(
                    "pk", "user_id", "role_id",
                    "authority_mode", "authority_level")
            ),
            before,
        )

        self.assertEqual(RoleAssignmentAuthority.objects.count(), rows_before)
