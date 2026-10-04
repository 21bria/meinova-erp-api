"""
Siapa yang boleh melihat kalender siapa — dan siapa yang boleh
mengubahnya.

Dua sumbu, dan seluruh berkas ini menjaga supaya keduanya tidak pernah
tertukar:

* **Melihat** = cakupan baris. `DataScope` (Organization Scope /
  kewenangan penugasan) ∪ garis pelaporan ∪ dirinya sendiri. Tidak ada
  izin model yang dibutuhkan untuk membuka kalender — pegawai biasa
  memang harus bisa melihat jadwalnya sendiri.
* **Mengubah** = `ModelPermission` (`hr.add_employeeshiftassignment`)
  **plus** cakupan organisasi. Garis pelaporan sengaja tidak ikut:
  memantau jadwal tim adalah pekerjaan atasan, mengubahnya bukan.

Empat kursi diuji lewat pintu yang sama, karena memang cuma ada satu:
pegawai, atasan langsung, Admin Section/Department, dan HR. Yang
membedakan mereka **bukan** cabang `if role == …` di kode mana pun —
melainkan baris cakupan dan `reports_to` yang ada di data.

Tiap kelompok negatifnya diuji terpisah dan dengan cara yang paling
kasar yang bisa dilakukan orang: **id pegawai luar cakupan diketik
langsung ke URL**. Dropdown yang tersaring bukan penjagaan.

`TenantTestCase` tidak memanggil `super().setUpClass()`, jadi tidak ada
rollback per test — tiap test hanya membaca fixture kelasnya dan
membuat barisnya sendiri kalau perlu menulis.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.accounts.models import AuthorityMode, Role
from apps.accounts.services.role_assignment import grant_role
from apps.administration.models import (
    Company,
    Department,
    Location,
    RosterPolicy,
    Section,
    Shift,
)
from apps.administration.seeds.numbering import seed_numbering
from apps.hr.api.shift_calendar.scope import (
    adjustable_employees,
    can_adjust_shift,
    viewable_employees,
)
from apps.hr.api.shift_calendar.services import EmployeeShiftAssignmentService
from apps.hr.tests.access_helpers import grant_employee_read
from apps.hr.models import (
    Employee,
    EmployeeShiftAssignment,
    EmploymentAssignment,
    OrganizationAssignment,
    ShiftAssignmentLayer,
)


User = get_user_model()


MONTH = "2026-08"


class ShiftCalendarAccessTestCase(TenantTestCase):
    """
    Satu company, satu site + satu kantor pusat, satu department, dua
    section, dan satu garis pelaporan tiga tingkat.

    Bentuknya sengaja dipilih supaya tiap kursi punya **satu orang yang
    hanya bisa dijangkau lewat jalurnya sendiri**: pegawai Section B
    tidak pernah masuk cakupan Admin Section A, pegawai HO tidak pernah
    masuk cakupan Admin Department site, dan bawahan tingkat dua hanya
    terjangkau lewat penelusuran `reports_to` yang berjenjang.
    """

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "shiftcal-access"
        tenant.name = "Shift Calendar Access"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        seed_numbering()

        cls.company = Company.objects.create(code="SCA", name="Access Test")

        cls.site = Location.objects.create(
            company=cls.company, code="SCASITE", name="Site Access",
        )

        cls.head_office = Location.objects.create(
            company=cls.company, code="SCAHO", name="Head Office Access",
        )

        cls.department = Department.objects.create(
            company=cls.company,
            location=cls.site,
            code="SCAOPS",
            name="Operations",
        )

        cls.other_department = Department.objects.create(
            company=cls.company,
            location=cls.site,
            code="SCAENG",
            name="Engineering",
        )

        cls.section_a = Section.objects.create(
            company=cls.company,
            location=cls.site,
            department=cls.department,
            code="SCASECA",
            name="Section A",
        )

        cls.section_b = Section.objects.create(
            company=cls.company,
            location=cls.site,
            department=cls.department,
            code="SCASECB",
            name="Section B",
        )

        cls.shift_day = Shift.objects.create(
            code="SCA-D", name="Day", start_time="07:00", end_time="19:00",
        )

        cls.policy = RosterPolicy.objects.create(
            company=cls.company,
            location=cls.site,
            code="SCA-6-2",
            name="Roster 6:2",
            cycle_work_days=42,
            cycle_off_days=14,
            default_travel_out_days=1,
            default_travel_in_days=1,
            rolling_horizon_months=12,
        )

        # --------------------------------------------------------------
        # Role. Tidak satu pun kode role dibaca kode produksi — yang
        # menentukan cakupannya `role_authority` di bawah.
        # --------------------------------------------------------------

        cls.role_employee = Role.objects.create(
            code="SCA-EMPLOYEE", name="Employee",
        )

        cls.role_admin_section = Role.objects.create(
            code="SCA-ADMIN-SECTION", name="Admin Section",
        )

        cls.role_admin_department = Role.objects.create(
            code="SCA-ADMIN-DEPT", name="Admin Department",
        )

        # HR: **tanpa satu baris cakupan pun**, dan di sistem ini itu
        # berarti tanpa batasan. Ditulis begitu dengan sengaja karena
        # itulah bentuk HR-ADMIN yang sebenarnya diseed.
        cls.role_hr = Role.objects.create(code="SCA-HR", name="HR Admin")

        # WHERE tiap role, **dinyatakan**. Sejak Wave C kewenangan
        # penugasan adalah satu-satunya tempat WHERE disimpan.
        #
        # Role yang tidak disebut di sini berarti **tanpa batasan**,
        # persis seperti yang dikatakan komentar `role_hr` di atas.
        cls.role_authority = {
            cls.role_employee.pk: (
                AuthorityMode.EXPLICIT, [("own", None)],
            ),
            cls.role_admin_section.pk: (
                AuthorityMode.EXPLICIT, [("section", cls.section_a.pk)],
            ),
            cls.role_admin_department.pk: (
                AuthorityMode.EXPLICIT, [("department", cls.department.pk)],
            ),
        }

        # --------------------------------------------------------------
        # Orang
        # --------------------------------------------------------------

        # Manajer → supervisor → crew. Tiga tingkat, supaya penelusuran
        # berjenjang benar-benar diuji: kalau `subordinate_ids` cuma
        # satu tingkat, `crew` hilang dari daftar manajer.
        cls.user_manager = cls.make_user("manager", roles=[cls.role_employee])
        cls.manager = cls.make_employee(
            section=cls.section_a, user=cls.user_manager,
        )

        cls.user_supervisor = cls.make_user(
            "supervisor", roles=[cls.role_employee],
        )
        cls.supervisor = cls.make_employee(
            section=cls.section_a,
            reports_to=cls.manager,
            user=cls.user_supervisor,
        )

        cls.user_crew = cls.make_user("crew", roles=[cls.role_employee])
        cls.crew = cls.make_employee(
            section=cls.section_a,
            reports_to=cls.supervisor,
            user=cls.user_crew,
        )

        # Rekan sesama Section A yang **tidak** melapor ke siapa pun di
        # garis itu: yang membedakan pegawai dari atasan di test ini
        # murni `reports_to`, bukan section-nya.
        cls.peer = cls.make_employee(section=cls.section_a)

        # Section B: di department yang sama, jadi ia terlihat oleh
        # Admin Department tapi tidak oleh Admin Section A.
        cls.other_section_employee = cls.make_employee(section=cls.section_b)

        # Department lain di site yang sama: di luar cakupan Admin
        # Department sekalipun lokasinya sama.
        cls.other_department_employee = cls.make_employee(
            department=cls.other_department,
        )

        # Kantor pusat: di luar site sama sekali.
        cls.ho_employee = cls.make_employee(
            location=cls.head_office, department=None, section=None,
        )

        cls.user_admin_section = cls.make_user(
            "adminsection", roles=[cls.role_admin_section],
        )
        cls.admin_section = cls.make_employee(
            section=cls.section_a, user=cls.user_admin_section,
        )

        cls.user_admin_department = cls.make_user(
            "admindept", roles=[cls.role_admin_department],
        )
        cls.admin_department = cls.make_employee(
            section=cls.section_a, user=cls.user_admin_department,
        )

        cls.user_hr = cls.make_user("hr", roles=[cls.role_hr])
        cls.hr = cls.make_employee(
            location=cls.head_office,
            department=None,
            section=None,
            user=cls.user_hr,
        )

        # Izin operasional Adjust Shift dipasang ke role HR saja —
        # dicentang lewat `Role.permissions` persis seperti di layar
        # Roles, bukan lewat `user_permissions` bawaan Django yang
        # memang tidak dibaca sistem ini.
        cls.grant_adjust(cls.role_hr)

        # Admin Section **dengan** izin adjust: dipakai membuktikan
        # bahwa izin operasional saja tidak cukup — cakupan barisnya
        # tetap berlaku. Tanpa kursi ini, "cakupan pada jalur tulis"
        # tidak pernah benar-benar diuji, karena satu-satunya pemegang
        # izinnya kebetulan tak bercakupan.
        cls.role_admin_section_adjust = Role.objects.create(
            code="SCA-ADMIN-SECTION-ADJ", name="Admin Section (Adjust)",
        )

        cls.role_authority[cls.role_admin_section_adjust.pk] = (
            AuthorityMode.EXPLICIT, [("section", cls.section_a.pk)],
        )

        cls.grant_adjust(cls.role_admin_section_adjust)

        cls.user_section_adjuster = cls.make_user(
            "sectionadjuster", roles=[cls.role_admin_section_adjust],
        )
        cls.section_adjuster = cls.make_employee(
            section=cls.section_a, user=cls.user_section_adjuster,
        )

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def grant_adjust(cls, role):
        from django.contrib.auth.models import Permission

        role.permissions.add(
            *Permission.objects.filter(
                content_type__app_label="hr",
                content_type__model="employeeshiftassignment",
                codename__in=[
                    "add_employeeshiftassignment",
                    "change_employeeshiftassignment",
                    "delete_employeeshiftassignment",
                    "view_employeeshiftassignment",
                ],
            )
        )

    # `None` adalah nilai yang sah untuk Department — pegawai kantor
    # pusat memang tidak punya. Tanpa penanda tersendiri, `None` berarti
    # "pakai bawaannya", dan pegawai HO diam-diam masuk department site:
    # test cakupan Admin Department lolos karena mengujinya terbalik.
    _UNSET = object()

    @classmethod
    def make_employee(
        cls,
        *,
        location=None,
        department=_UNSET,
        section=None,
        reports_to=None,
        user=None,
        is_active=True,
    ):
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"SCA{cls._counter:04d}",
            first_name="Access",
            last_name=f"Employee {cls._counter}",
            is_active=is_active,
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=location or cls.site,
            department=(
                department
                if department is not cls._UNSET
                else (section.department if section else cls.department)
            ),
            section=section,
            reports_to=reports_to,
            organization_effective_date=date(2026, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=date(2025, 1, 1),
            roster_policy=cls.policy,
            roster_cycle_start=date(2026, 8, 1),
        )

        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def make_user(cls, name, *, roles=(), superuser=False):
        cls._counter += 1

        user = User.objects.create_user(
            username=f"{name}.{cls._counter}",
            email=f"{name}.{cls._counter}@example.test",
            password="access-pass-1",
            is_superuser=superuser,
            is_staff=superuser,
        )

        for role in roles:
            mode, authorities = cls.role_authority.get(
                role.pk, (AuthorityMode.UNRESTRICTED, []),
            )

            grant_role(user, role, mode=mode, authorities=authorities)

            # `hr.employee` termasuk resource yang bacanya dijaga izin
            # model (`require_view_permission`), dan dropdown pegawai
            # adalah salah satu pintunya. Tanpa baris ini setiap role
            # bikinan test menabrak 403 sebelum satu pun aturan cakupan
            # sempat diuji — bukan temuan, cuma fixture yang belum
            # menyebutkan izin yang di produksi dipegang **semua** role
            # lewat `READ_GRANTS`.
            #
            # Yang diuji berkas ini tetap cakupannya: izin menjawab
            # jenis datanya, dan menambahkannya tidak melebarkan satu
            # baris pun.
            grant_employee_read(role)

        return user

    # ------------------------------------------------------------------
    # Perkakas
    # ------------------------------------------------------------------

    def api(self, user):
        client = TenantClient(self.tenant)

        token = RefreshToken.for_user(user).access_token

        client.defaults["HTTP_AUTHORIZATION"] = f"Bearer {token}"

        return client

    def calendar(self, user, employee):
        """`GET /api/hr/shift-calendar/` dengan id yang diketik apa adanya."""
        return self.api(user).get(
            "/api/hr/shift-calendar/",
            {"employee": employee, "month": MONTH},
        )

    @staticmethod
    def fresh(user):
        """
        Akun yang cakupannya belum di-cache.

        `DataScopeService.for_user` menyimpan hasilnya di instance user
        (`_data_scope_cache`), jadi memakai ulang objek yang sama antar
        assert bisa membaca cakupan versi lama — dan test yang begitu
        lolos karena tidak menguji apa pun.
        """
        return User.objects.get(pk=user.pk)

    def ids(self, queryset):
        return set(queryset.values_list("pk", flat=True))


# ----------------------------------------------------------------------
# Cakupan baca, di tingkat service
# ----------------------------------------------------------------------


class ViewableScopeTests(ShiftCalendarAccessTestCase):
    def test_employee_sees_only_himself(self):
        visible = viewable_employees(self.fresh(self.user_crew))

        self.assertEqual(self.ids(visible), {self.crew.pk})

    def test_supervisor_sees_himself_and_his_team(self):
        visible = viewable_employees(self.fresh(self.user_supervisor))

        self.assertEqual(
            self.ids(visible),
            {self.supervisor.pk, self.crew.pk},
        )

    def test_reporting_line_is_traversed_through_levels(self):
        """Manajer melihat supervisor **dan** crew di bawahnya."""
        visible = viewable_employees(self.fresh(self.user_manager))

        self.assertEqual(
            self.ids(visible),
            {self.manager.pk, self.supervisor.pk, self.crew.pk},
        )

    def test_supervisor_does_not_see_a_peer_outside_his_line(self):
        visible = self.ids(viewable_employees(self.fresh(self.user_supervisor)))

        self.assertNotIn(self.peer.pk, visible)
        self.assertNotIn(self.other_section_employee.pk, visible)
        self.assertNotIn(self.ho_employee.pk, visible)

    def test_admin_section_sees_its_section_only(self):
        visible = self.ids(
            viewable_employees(self.fresh(self.user_admin_section)),
        )

        self.assertIn(self.crew.pk, visible)
        self.assertIn(self.peer.pk, visible)
        self.assertIn(self.admin_section.pk, visible)

        self.assertNotIn(self.other_section_employee.pk, visible)
        self.assertNotIn(self.other_department_employee.pk, visible)
        self.assertNotIn(self.ho_employee.pk, visible)

    def test_admin_department_sees_both_sections_but_not_other_units(self):
        visible = self.ids(
            viewable_employees(self.fresh(self.user_admin_department)),
        )

        self.assertIn(self.crew.pk, visible)
        self.assertIn(self.other_section_employee.pk, visible)

        self.assertNotIn(self.other_department_employee.pk, visible)
        self.assertNotIn(self.ho_employee.pk, visible)

    def test_hr_follows_data_permission_and_sees_everyone(self):
        visible = self.ids(viewable_employees(self.fresh(self.user_hr)))

        for employee in (
            self.crew,
            self.other_section_employee,
            self.other_department_employee,
            self.ho_employee,
        ):
            self.assertIn(employee.pk, visible)

    def test_own_calendar_survives_a_scope_that_excludes_it(self):
        """
        Cakupan yang tidak memuat penempatannya sendiri tetap tidak
        menutup kalendernya sendiri.

        Admin Section A yang dipindah ke Section B akan kehilangan
        halamannya sendiri kalau cakupan jadi satu-satunya penentu —
        dan tidak ada satu pesan pun yang menyebut sebabnya.
        """
        user = self.make_user("displaced", roles=[self.role_admin_section])

        employee = self.make_employee(section=self.section_b, user=user)

        visible = self.ids(viewable_employees(self.fresh(user)))

        self.assertIn(employee.pk, visible)


# ----------------------------------------------------------------------
# Cakupan baca, lewat API — id diketik tangan
# ----------------------------------------------------------------------


class CalendarEndpointTests(ShiftCalendarAccessTestCase):
    def test_employee_opens_his_own_calendar(self):
        response = self.calendar(self.user_crew, self.crew.pk)

        self.assertEqual(response.status_code, 200)

        payload = response.json()["data"]

        self.assertEqual(
            payload["employee"]["employee_number"],
            self.crew.employee_number,
        )

    def test_employee_me_resolves_to_the_caller(self):
        response = self.calendar(self.user_crew, "me")

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            response.json()["data"]["employee"]["employee_number"],
            self.crew.employee_number,
        )

    def test_employee_is_refused_another_employees_calendar(self):
        response = self.calendar(self.user_crew, self.peer.pk)

        self.assertEqual(response.status_code, 400)

        self.assertIn("employee", response.json()["errors"])

    def test_employee_is_refused_his_own_supervisors_calendar(self):
        """Garis pelaporan hanya berlaku ke bawah, tidak ke atas."""
        response = self.calendar(self.user_crew, self.supervisor.pk)

        self.assertEqual(response.status_code, 400)

    def test_supervisor_opens_his_subordinates_calendar(self):
        response = self.calendar(self.user_supervisor, self.crew.pk)

        self.assertEqual(response.status_code, 200)

    def test_supervisor_is_refused_a_peer_outside_his_line(self):
        response = self.calendar(self.user_supervisor, self.peer.pk)

        self.assertEqual(response.status_code, 400)

    def test_admin_section_is_refused_another_section(self):
        response = self.calendar(
            self.user_admin_section,
            self.other_section_employee.pk,
        )

        self.assertEqual(response.status_code, 400)

    def test_admin_department_is_refused_another_department(self):
        response = self.calendar(
            self.user_admin_department,
            self.other_department_employee.pk,
        )

        self.assertEqual(response.status_code, 400)

    def test_hr_opens_anyone(self):
        response = self.calendar(self.user_hr, self.ho_employee.pk)

        self.assertEqual(response.status_code, 200)

    def test_a_non_numeric_employee_id_is_a_400_not_a_500(self):
        response = self.calendar(self.user_hr, "bukan-angka")

        self.assertEqual(response.status_code, 400)


# ----------------------------------------------------------------------
# Dropdown pegawai — jalur yang paling gampang bocor
# ----------------------------------------------------------------------


class EmployeeSelectorTests(ShiftCalendarAccessTestCase):
    def lookup(self, user):
        response = self.api(user).get(
            "/api/hr/employees/lookup/",
            {"reporting_line": 1, "page_size": 200},
        )

        self.assertEqual(response.status_code, 200)

        payload = response.json()

        rows = payload.get("data", payload)

        if isinstance(rows, dict):
            rows = rows.get("results", [])

        return {row["value"] for row in rows}

    def test_employee_selector_holds_only_himself(self):
        self.assertEqual(self.lookup(self.user_crew), {self.crew.pk})

    def test_supervisor_selector_holds_himself_and_his_team(self):
        self.assertEqual(
            self.lookup(self.user_supervisor),
            {self.supervisor.pk, self.crew.pk},
        )

    def test_admin_section_selector_stops_at_its_section(self):
        values = self.lookup(self.user_admin_section)

        self.assertIn(self.peer.pk, values)

        self.assertNotIn(self.other_section_employee.pk, values)
        self.assertNotIn(self.ho_employee.pk, values)

    def test_hr_selector_holds_everyone(self):
        values = self.lookup(self.user_hr)

        self.assertIn(self.ho_employee.pk, values)
        self.assertIn(self.other_department_employee.pk, values)


# ----------------------------------------------------------------------
# Endpoint access — yang dipakai layar memutuskan bentuknya
# ----------------------------------------------------------------------


class AccessEndpointTests(ShiftCalendarAccessTestCase):
    def access(self, user):
        response = self.api(user).get("/api/hr/shift-calendar/access/")

        self.assertEqual(response.status_code, 200)

        return response.json()["data"]

    def test_employee_gets_himself_and_no_selector(self):
        payload = self.access(self.user_crew)

        self.assertFalse(payload["selector_required"])

        self.assertEqual(payload["default_employee"]["id"], self.crew.pk)
        self.assertEqual(payload["self_employee"]["id"], self.crew.pk)

        self.assertFalse(payload["can_adjust"])

    def test_supervisor_gets_a_selector_defaulted_to_himself(self):
        payload = self.access(self.user_supervisor)

        self.assertTrue(payload["selector_required"])

        self.assertEqual(
            payload["default_employee"]["id"],
            self.supervisor.pk,
        )

        self.assertFalse(payload["can_adjust"])

    def test_admin_section_gets_a_selector(self):
        payload = self.access(self.user_admin_section)

        self.assertTrue(payload["selector_required"])

        self.assertFalse(payload["can_adjust"])

    def test_an_inactive_employee_still_gets_his_own_calendar(self):
        """
        Akun masih hidup, orangnya sudah tidak aktif.

        Daftar pegawai menyaring `is_active=True` (basisnya dropdown),
        sementara endpoint kalender hanya menyaring `is_deleted` — jadi
        ia tidak muncul di daftar mana pun tapi kalendernya tetap boleh
        dibuka. Tanpa cabang khusus, layarnya berbunyi "akun belum
        ditautkan ke data pegawai", dan itu **salah**: akunnya tertaut,
        orangnya yang sudah berhenti. Ditemukan di UAT tenant `demo`,
        bukan di test.
        """
        user = self.make_user("retired", roles=[self.role_employee])

        employee = self.make_employee(
            section=self.section_a,
            user=user,
            is_active=False,
        )

        payload = self.access(user)

        self.assertFalse(payload["selector_required"])

        self.assertEqual(payload["default_employee"]["id"], employee.pk)

        self.assertEqual(
            self.calendar(user, "me").status_code,
            200,
        )

    def test_hr_gets_a_selector_and_may_adjust(self):
        payload = self.access(self.user_hr)

        self.assertTrue(payload["selector_required"])
        self.assertTrue(payload["can_adjust"])


# ----------------------------------------------------------------------
# Adjust Shift — izin operasional **dan** cakupan, bukan salah satu
# ----------------------------------------------------------------------


class AdjustPermissionTests(ShiftCalendarAccessTestCase):
    payload_base = {
        "layer": ShiftAssignmentLayer.OVERRIDE,
        "start_date": "2026-08-10",
        "end_date": "2026-08-12",
        "reason": "Uji cakupan",
    }

    def post_adjust(self, user, employee):
        return self.api(user).post(
            "/api/hr/shift-assignments/",
            {
                **self.payload_base,
                "employee": employee.pk,
                "shift": self.shift_day.pk,
            },
            content_type="application/json",
        )

    def test_view_only_employee_cannot_adjust(self):
        """Melihat kalendernya sendiri boleh; mengubahnya tidak."""
        self.assertEqual(
            self.calendar(self.user_crew, self.crew.pk).status_code,
            200,
        )

        response = self.post_adjust(self.user_crew, self.crew)

        self.assertEqual(response.status_code, 403)

    def test_view_only_supervisor_cannot_adjust_his_team(self):
        self.assertEqual(
            self.calendar(self.user_supervisor, self.crew.pk).status_code,
            200,
        )

        self.assertEqual(
            self.post_adjust(self.user_supervisor, self.crew).status_code,
            403,
        )

    def test_hr_with_the_permission_may_adjust(self):
        response = self.post_adjust(self.user_hr, self.peer)

        self.assertEqual(response.status_code, 201, response.content)

        self.assertTrue(
            EmployeeShiftAssignment.objects
            .filter(employee=self.peer, layer=ShiftAssignmentLayer.OVERRIDE)
            .exists()
        )

    def test_the_permission_alone_does_not_cross_the_scope(self):
        """
        Izin operasional **dan** cakupan barisnya, bukan salah satu.

        `filter_queryset()` menjaga baca/ubah/hapus, tapi `create` tidak
        pernah melewatinya — jadi tanpa penjagaan di service, satu
        request dengan id yang diketik tangan sudah cukup.
        """
        response = self.post_adjust(
            self.user_section_adjuster,
            self.other_section_employee,
        )

        self.assertEqual(response.status_code, 400)

        self.assertIn("employee", response.json()["errors"])

        self.assertFalse(
            EmployeeShiftAssignment.objects
            .filter(employee=self.other_section_employee)
            .exists()
        )

    def test_the_permission_holder_may_adjust_inside_his_scope(self):
        response = self.post_adjust(self.user_section_adjuster, self.crew)

        self.assertEqual(response.status_code, 201, response.content)

    def test_moving_a_row_to_an_employee_outside_scope_is_refused(self):
        """Mengganti pegawai satu baris adalah penerbitan yang menyamar."""
        row = EmployeeShiftAssignmentService.create(
            data={
                "employee": self.crew,
                "shift": self.shift_day,
                "layer": ShiftAssignmentLayer.OVERRIDE,
                "start_date": date(2026, 9, 1),
                "end_date": date(2026, 9, 3),
                "reason": "Uji pindah",
            },
        )

        response = self.api(self.user_section_adjuster).patch(
            f"/api/hr/shift-assignments/{row.pk}/",
            {"employee": self.other_section_employee.pk},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

        row.refresh_from_db()

        self.assertEqual(row.employee_id, self.crew.pk)

    def test_an_out_of_scope_row_is_not_even_reachable(self):
        """
        Baris pegawai luar cakupan: 404 dari `filter_queryset()`, bukan
        400 dari service. Dua lapis, dan yang pertama sudah cukup.
        """
        row = EmployeeShiftAssignmentService.create(
            data={
                "employee": self.other_section_employee,
                "shift": self.shift_day,
                "layer": ShiftAssignmentLayer.OVERRIDE,
                "start_date": date(2026, 9, 10),
                "end_date": date(2026, 9, 12),
                "reason": "Uji jangkauan",
            },
        )

        response = self.api(self.user_section_adjuster).delete(
            f"/api/hr/shift-assignments/{row.pk}/",
        )

        self.assertEqual(response.status_code, 404)


# ----------------------------------------------------------------------
# Matriks izin, dikunci pada seed-nya
# ----------------------------------------------------------------------


class PermissionMatrixSeedTests(TenantTestCase):
    """
    Matriks final Shift Calendar, dikunci di tempat ia benar-benar
    ditentukan: `seed_security_roles`.

    **Kenapa ini test tersendiri dan bukan bagian dari kelas di atas.**
    Yang di atas menguji penegakannya — `ModelPermission` menolak yang
    tidak punya izin, `assert_adjustable()` menolak baris di luar
    cakupan. Keduanya benar untuk **apa pun** isi matriksnya, jadi
    tidak satu pun dari mereka akan berbunyi kalau seseorang menghapus
    `hr.employeeshiftassignment` dari daftar `ADMIN-SECTION`. Yang
    hilang bukan penjagaannya, melainkan **kemampuan orang mengerjakan
    pekerjaannya** — dan kegagalan seperti itu tidak pernah muncul
    sebagai error, cuma sebagai tombol yang tidak ada.

    Sudah terjadi sekali, dan itu sebabnya berkas ini ada: seed-nya
    memang sudah benar untuk HR (`apps: ["hr"]` mencakup model ini
    sejak awal) tapi **belum pernah diulang** sejak modelnya lahir,
    sehingga di tenant `demo` tidak satu pun role bisa Adjust Shift —
    termasuk `SYSTEM-ADMIN`. Test ini tidak bisa menangkap seed yang
    belum dijalankan; yang dijaganya isi matriksnya.
    """

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "shiftcal-matrix"
        tenant.name = "Shift Calendar Matrix"

    # Matriks yang diminta, ditulis apa adanya. Kolom kirinya kode role,
    # kanannya kata kerja izin `EmployeeShiftAssignment`.
    #
    # **Atasan langsung tidak punya barisnya sendiri** — ia memegang
    # `EMPLOYEE`, dan yang membedakannya `reports_to`. "Supervisor =
    # VIEW only" karena itu baris `EMPLOYEE` yang sama, bukan baris
    # kedua yang bisa menyimpang darinya.
    MATRIX = {
        "EMPLOYEE": {"view"},
        "ADMIN-SECTION": {"view", "add", "change", "delete"},
        "ADMIN-DEPARTMENT": {"view", "add", "change", "delete"},
        "HR-ADMIN": {"view", "add", "change", "delete"},
        "HR-MANAGER": {"view", "add", "change", "delete"},
        "SYSTEM-ADMIN": {"view", "add", "change", "delete"},
    }

    @staticmethod
    def _verbs(role):
        return {
            permission.codename.split("_", 1)[0]
            for permission in role.permissions.filter(
                content_type__app_label="hr",
                content_type__model="employeeshiftassignment",
            )
        }

    def test_seed_produces_the_agreed_matrix(self):
        from apps.accounts.seeds import seed

        seed(log=lambda *args, **kwargs: None)

        for code, expected in self.MATRIX.items():
            role = Role.objects.filter(code=code, is_deleted=False).first()

            self.assertIsNotNone(role, f"role {code} tidak diseed")

            self.assertEqual(
                self._verbs(role),
                expected,
                f"{code} tidak sesuai matriks Shift Calendar",
            )

    def test_the_seed_is_repeatable(self):
        """
        Dijalankan dua kali menghasilkan matriks yang sama.

        Seed ini **hanya menambah**, tidak pernah mencabut — itu yang
        membuatnya aman diulang di tenant yang role-nya sudah disunting
        orang. Sifat itu cuma berguna kalau benar-benar dipegang.
        """
        from apps.accounts.seeds import seed

        seed(log=lambda *args, **kwargs: None)

        first = {
            code: self._verbs(Role.objects.get(code=code, is_deleted=False))
            for code in self.MATRIX
        }

        seed(log=lambda *args, **kwargs: None)

        second = {
            code: self._verbs(Role.objects.get(code=code, is_deleted=False))
            for code in self.MATRIX
        }

        self.assertEqual(first, second)

    def test_view_and_adjust_are_separable_at_all(self):
        """
        Matriksnya harus benar-benar **memisahkan** dua kata kerja.

        Kalau setiap role yang boleh melihat juga boleh mengubah, tidak
        ada yang tersisa dari "VIEW ≠ ADJUST" selain kalimatnya — dan
        test di atas akan tetap hijau untuk matriks yang memberi semua
        orang keempat kata kerja.
        """
        from apps.accounts.seeds import seed

        seed(log=lambda *args, **kwargs: None)

        employee = Role.objects.get(code="EMPLOYEE", is_deleted=False)
        admin = Role.objects.get(code="ADMIN-SECTION", is_deleted=False)

        self.assertIn("view", self._verbs(employee))

        for verb in ("add", "change", "delete"):
            self.assertNotIn(
                verb,
                self._verbs(employee),
                f"EMPLOYEE seharusnya tidak punya {verb}_employeeshiftassignment",
            )

            self.assertIn(verb, self._verbs(admin))


# ----------------------------------------------------------------------
# Regresi: jalur yang **tidak** boleh berubah karena penjagaan ini
# ----------------------------------------------------------------------


class NoRegressionTests(ShiftCalendarAccessTestCase):
    def test_seeds_and_commands_still_write_without_a_user(self):
        """
        Seed dan perintah manajemen memanggil service tanpa `user` —
        keduanya berjalan sebagai sistem, bukan sebagai seseorang.
        Menjaganya di sini akan menghentikan `seed_demo_roster` dan
        `sync_shift_baseline` untuk pegawai yang tidak dimiliki siapa
        pun.
        """
        row = EmployeeShiftAssignmentService.create(
            data={
                "employee": self.ho_employee,
                "shift": self.shift_day,
                "layer": ShiftAssignmentLayer.BASELINE,
                "start_date": date(2026, 10, 1),
                "end_date": date(2026, 10, 5),
            },
        )

        self.assertEqual(row.employee_id, self.ho_employee.pk)

    def test_a_superuser_is_never_narrowed(self):
        root = self.make_user("root", superuser=True)

        visible = self.ids(viewable_employees(self.fresh(root)))

        self.assertIn(self.ho_employee.pk, visible)

        self.assertTrue(can_adjust_shift(self.fresh(root)))

    def test_adjust_scope_excludes_the_reporting_line(self):
        """
        Cakupan tulis **bukan** cakupan baca. Atasan langsung melihat
        timnya; ia tidak mengubah shift-nya kecuali cakupan
        organisasinya memang memuat orang itu.
        """
        user = self.fresh(self.user_supervisor)

        self.assertIn(self.crew.pk, self.ids(viewable_employees(user)))

        self.assertNotIn(
            self.crew.pk,
            self.ids(adjustable_employees(self.fresh(self.user_supervisor))),
        )

    def test_service_guard_reports_the_employee_number(self):
        with self.assertRaises(ValidationError) as caught:
            EmployeeShiftAssignmentService.create(
                data={
                    "employee": self.ho_employee,
                    "shift": self.shift_day,
                    "layer": ShiftAssignmentLayer.OVERRIDE,
                    "start_date": date(2026, 11, 1),
                    "end_date": date(2026, 11, 2),
                    "reason": "Uji pesan",
                },
                user=self.fresh(self.user_section_adjuster),
            )

        self.assertIn(
            self.ho_employee.employee_number,
            str(caught.exception.message_dict["employee"]),
        )
