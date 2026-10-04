"""
Berapa role yang bisa dibolehkan satu kelompok data — dan jawabannya
sebanyak barisnya.

Ditulis di Stage 3A untuk menjawab satu pertanyaan yang tidak boleh
dijawab dengan membaca kode saja: **bisakah `EmployeeDataPolicy`
menyatakan "HR Admin *dan* HR Manager sama-sama boleh membaca dokumen
pegawai"?** Waktu itu jawabannya tidak, dan sebabnya struktural:
`visible_employees_q()` berhenti (`prior_covers_all` → `break`) sesudah
aturan global pertama, jadi aturan global kedua tidak pernah dinilai —
tanpa satu pesan pun.

Stage 3A.1 mengubahnya: aturan dikelompokkan menurut sasarannya, dan
aturan di sasaran yang sama digabung dengan OR. `role` tetap FK
tunggal; yang menyusun gabungannya adalah **barisnya**, bukan kolomnya.

Berkas ini menjaga kedua sisi keputusan itu: bahwa baris kedua kini
benar-benar berlaku, dan bahwa penutupan antar-sasaran — satu-satunya
bentuk "tidak boleh" yang dipunyai master ini — tidak ikut berubah jadi
izin.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model

from django_tenants.test.cases import TenantTestCase

from apps.accounts.models import Role
from apps.administration.models import (
    Company,
    Department,
    EmployeeDataPolicy,
    EmployeeDataSubject,
    Location,
    Position,
)
from apps.hr.api.employee.visibility import EmployeeDataVisibility
from apps.hr.models import Employee, OrganizationAssignment


JOIN = date(2020, 1, 6)


class EmployeeDataPolicyRoleTests(TenantTestCase):
    _n = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "edp-roles"
        tenant.name = "EDP Roles"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(code="EDPA", name="Company A")

        cls.site = Location.objects.create(
            company=cls.company, code="EDPA-1", name="Site A1")

        cls.department = Department.objects.create(
            company=cls.company, code="EDPA-OPS", name="Operations")

        cls.subject = str(EmployeeDataSubject.FIELD_DOCUMENT)

        cls.target = cls.make_employee(with_user=False)

    @classmethod
    def make_employee(cls, *, with_user=True):
        User = get_user_model()

        cls._n += 1

        user = None

        if with_user:
            user = User.objects.create_user(
                username=f"edp.user{cls._n}",
                email=f"edp.user{cls._n}@example.test",
                password="Test-Only#Pw1",
            )

        position = Position.objects.create(
            company=cls.company,
            department=cls.department,
            code=f"EDP-POS{cls._n}",
            name=f"Position {cls._n}",
        )

        employee = Employee.objects.create(
            employee_number=f"EDP-{cls._n:03d}",
            first_name="Policy",
            last_name=f"User {cls._n}",
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=cls.site,
            department=cls.department,
            position=position,
            organization_effective_date=JOIN,
        )

        return Employee.objects.get(pk=employee.pk)

    def policy(self, code, role, *, order, allow_self=False):
        return EmployeeDataPolicy.objects.create(
            code=code,
            name=code,
            subject=self.subject,
            role=role,
            allow_self=allow_self,
            allow_manager=False,
            allow_department_head=False,
            sort_order=order,
            is_active=True,
        )

    def visible_to(self, user) -> set[str]:
        allowed = EmployeeDataVisibility.visible_employees_q(
            subject=self.subject,
            user=user,
        )

        queryset = Employee.objects.filter(is_deleted=False)

        if allowed is not None:
            queryset = queryset.filter(allowed)

        return set(queryset.values_list("employee_number", flat=True))

    def setUp(self):
        super().setUp()

        EmployeeDataPolicy.objects.all().delete()

        for user in get_user_model().objects.all():
            if hasattr(user, "_role_perm_cache"):
                del user._role_perm_cache

    # ------------------------------------------------------------------

    def test_without_any_rule_the_subject_is_open_to_everyone(self):
        """
        Titik berangkatnya, dan sebab `hr.employeedocument` terbuka hari
        ini: **tanpa aturan = terlihat**. Itu bawaan yang disengaja
        (tenant baru tidak boleh kehilangan tabnya), tapi artinya
        kelompok yang belum pernah diatur tidak dijaga sama sekali.
        """
        viewer = self.make_employee()

        self.assertIn(self.target.employee_number, self.visible_to(viewer.user))

    def test_one_global_rule_limits_the_subject_to_that_role(self):
        """Satu baris: bekerja persis seperti yang diharapkan."""
        allowed_role = Role.objects.create(code="EDP-HR-1", name="HR Satu")

        outsider = self.make_employee()

        insider = self.make_employee()

        insider.user.roles.add(allowed_role)

        self.policy("EDP-DOC-1", allowed_role, order=10)

        self.assertIn(
            self.target.employee_number,
            self.visible_to(insider.user),
        )

        self.assertNotIn(
            self.target.employee_number,
            self.visible_to(outsider.user),
            msg="Aturan tidak menyaring siapa pun — panggungnya salah.",
        )

    def test_a_second_global_rule_takes_effect(self):
        """
        **Yang dibuka Stage 3A.1** — dulu justru kebalikannya.

        Dua baris global untuk kelompok yang sama. Keduanya berlaku:
        pemegang role di baris pertama boleh, pemegang role di baris
        kedua juga. Sebelum 3A.1 baris kedua tidak pernah dinilai, dan
        menuliskannya cuma menghasilkan baris yang terlihat benar di
        layar setting tanpa pernah bekerja.
        """
        first_role = Role.objects.create(code="EDP-HR-A", name="HR A")
        second_role = Role.objects.create(code="EDP-HR-B", name="HR B")

        first_user = self.make_employee()
        second_user = self.make_employee()
        outsider = self.make_employee()

        first_user.user.roles.add(first_role)
        second_user.user.roles.add(second_role)

        self.policy("EDP-DOC-A", first_role, order=10)
        self.policy("EDP-DOC-B", second_role, order=20)

        self.assertIn(
            self.target.employee_number,
            self.visible_to(first_user.user),
            msg="Baris pertama seharusnya berlaku.",
        )

        self.assertIn(
            self.target.employee_number,
            self.visible_to(second_user.user),
            msg=(
                "Baris global kedua tidak berlaku — `prior_covers_all` "
                "kembali menghentikan penilaian sesudah baris pertama."
            ),
        )

        # Yang tidak boleh ikut terbuka: penggabungan dua baris bukan
        # alasan orang tanpa role mana pun jadi bisa membacanya.
        self.assertNotIn(
            self.target.employee_number,
            self.visible_to(outsider.user),
            msg="Aturan berhenti menyaring siapa pun.",
        )

    def test_self_access_survives_a_rule_that_names_another_role(self):
        """
        Yang **tetap** bisa dinyatakan: swalayan.

        `allow_self` hidup di baris yang sama, jadi "pegawai melihat
        dokumennya sendiri, HR melihat semua" bisa ditulis satu baris —
        yang tidak bisa cuma menambah role kedua.
        """
        hr_role = Role.objects.create(code="EDP-HR-SELF", name="HR Self")

        viewer = self.make_employee()

        self.policy("EDP-DOC-SELF", hr_role, order=10, allow_self=True)

        visible = self.visible_to(viewer.user)

        self.assertIn(
            viewer.employee_number,
            visible,
            msg="Swalayan harus tetap bisa dinyatakan.",
        )

        self.assertNotIn(
            self.target.employee_number,
            visible,
            msg="…tapi berhenti di dirinya sendiri.",
        )
