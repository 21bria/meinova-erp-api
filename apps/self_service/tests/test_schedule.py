"""
`GET /api/me/schedule/` — "Jadwal Saya" dari My Workspace.

Yang dibuktikan berkas ini, dan hanya ini:

1. Atasan yang membuka Jadwal Saya **hanya** mendapat dirinya sendiri,
   walau cakupan bacanya di layar HR mencakup timnya.
2. Tidak ada parameter yang bisa menggeser subjeknya — `employee`,
   `employee_id`, `user`, `id`, `employee_number`, maupun kombinasinya.
3. Atasan yang sama tetap membuka kalender timnya lewat
   `GET /api/hr/shift-calendar/` — mode pribadi tidak mengubah jalur HR.
4. Pegawai biasa tidak punya jalan keluar dari mode pribadi: endpoint
   `/me` mengabaikan id orang lain, dan endpoint HR tetap menolaknya.
5. Otorisasi HR tidak berubah — `access/` tetap menjawab hal yang sama.
6. Tenant: permintaan tidak meninggalkan schema tenant yang dituju.

Fixture-nya **dipinjam** dari suite akses Shift Calendar: satu garis
pelaporan tiga tingkat, rekan di luar garis, dan kursi Admin/HR. Menulis
ulang fixture itu di sini berarti dua gambaran organisasi yang harus
tetap sama.
"""

from __future__ import annotations

from django.db import connection
from django.test import SimpleTestCase

from apps.hr.tests.shift_calendar.test_calendar_access import (
    MONTH,
    ShiftCalendarAccessTestCase,
)
from apps.self_service.services.workspace import ACTIONS


# Parameter yang pernah — di endpoint mana pun — dipakai untuk menyebut
# orang. Tidak satu pun boleh berpengaruh di `/api/me/schedule/`.
IDENTITY_PARAMS = ("employee", "employee_id", "user", "user_id", "id")


class SelfScheduleTests(ShiftCalendarAccessTestCase):
    def me_schedule(self, caller, /, **params):
        return self.api(caller).get(
            "/api/me/schedule/",
            {"month": MONTH, **params},
        )

    def subject(self, response):
        self.assertEqual(response.status_code, 200, response.content)

        return response.json()["data"]["employee"]["employee_number"]

    # ------------------------------------------------------------------
    # 1. Atasan → Jadwal Saya → dirinya sendiri
    # ------------------------------------------------------------------

    def test_manager_gets_only_himself(self):
        response = self.me_schedule(self.user_manager)

        self.assertEqual(self.subject(response), self.manager.employee_number)

        data = response.json()["data"]

        self.assertEqual(data["range"]["start"], f"{MONTH}-01")
        self.assertEqual(len(data["days"]), 31)

    def test_hr_without_scope_limits_still_gets_only_himself(self):
        """Cakupan tak berbatas tidak melebarkan `/me`."""
        response = self.me_schedule(self.user_hr)

        self.assertEqual(self.subject(response), self.hr.employee_number)

    # ------------------------------------------------------------------
    # 2. Manipulasi query tidak menggeser subjek
    # ------------------------------------------------------------------

    def test_identity_params_cannot_switch_the_subject(self):
        for param in IDENTITY_PARAMS:
            for value in (self.crew.pk, self.peer.pk, self.hr.pk, "me"):
                with self.subTest(param=param, value=value):
                    response = self.me_schedule(
                        self.user_manager, **{param: value},
                    )

                    self.assertEqual(
                        self.subject(response),
                        self.manager.employee_number,
                    )

    def test_employee_number_param_cannot_switch_the_subject(self):
        response = self.me_schedule(
            self.user_manager,
            employee_number=self.crew.employee_number,
        )

        self.assertEqual(self.subject(response), self.manager.employee_number)

    def test_all_identity_params_at_once_cannot_switch_the_subject(self):
        response = self.me_schedule(
            self.user_crew,
            employee=self.hr.pk,
            employee_id=self.hr.pk,
            user=self.user_hr.pk,
            user_id=self.user_hr.pk,
            id=self.hr.pk,
            employee_number=self.hr.employee_number,
            mode="team",
        )

        self.assertEqual(self.subject(response), self.crew.employee_number)

    def test_there_is_no_route_with_an_identity(self):
        client = self.api(self.user_manager)

        for path in (
            f"/api/me/schedule/{self.crew.pk}/",
            f"/api/me/schedule/{self.crew.employee_number}/",
        ):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)

    def test_schedule_is_read_only(self):
        client = self.api(self.user_manager)

        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(client, method)(
                    "/api/me/schedule/",
                    {"employee": self.crew.pk},
                    content_type="application/json",
                )

                self.assertEqual(response.status_code, 405)

    # ------------------------------------------------------------------
    # 3. Jalur HR untuk atasan tidak berubah
    # ------------------------------------------------------------------

    def test_manager_still_opens_his_team_through_hr(self):
        for member in (self.supervisor, self.crew):
            with self.subTest(member=member.employee_number):
                response = self.calendar(self.user_manager, member.pk)

                self.assertEqual(
                    self.subject(response), member.employee_number,
                )

    def test_manager_is_still_refused_outside_his_line_through_hr(self):
        response = self.calendar(self.user_manager, self.peer.pk)

        self.assertEqual(response.status_code, 400)

    # ------------------------------------------------------------------
    # 4. Pegawai biasa tidak bisa keluar dari mode pribadi
    # ------------------------------------------------------------------

    def test_employee_cannot_reach_a_colleague_through_me(self):
        response = self.me_schedule(self.user_crew, employee=self.peer.pk)

        self.assertEqual(self.subject(response), self.crew.employee_number)

    def test_employee_cannot_reach_a_colleague_through_hr_either(self):
        for other in (self.peer, self.supervisor, self.manager):
            with self.subTest(other=other.employee_number):
                response = self.calendar(self.user_crew, other.pk)

                self.assertEqual(response.status_code, 400)

    # ------------------------------------------------------------------
    # 5. Otorisasi HR tidak berubah
    # ------------------------------------------------------------------

    def test_access_endpoint_answers_as_before(self):
        cases = (
            (self.user_crew, False),
            (self.user_manager, True),
            (self.user_hr, True),
        )

        for user, selector in cases:
            with self.subTest(user=user.username):
                data = self.api(user).get(
                    "/api/hr/shift-calendar/access/",
                ).json()["data"]

                self.assertEqual(data["selector_required"], selector)

    def test_hr_endpoint_range_parsing_is_unchanged(self):
        client = self.api(self.user_hr)

        bad_month = client.get(
            "/api/hr/shift-calendar/",
            {"employee": self.crew.pk, "month": "2026/08"},
        )

        self.assertEqual(bad_month.status_code, 400)
        self.assertIn("month", bad_month.json()["errors"])

        by_range = client.get(
            "/api/hr/shift-calendar/",
            {
                "employee": self.crew.pk,
                "start": "2026-08-03",
                "end": "2026-08-09",
            },
        )

        self.assertEqual(by_range.status_code, 200)
        self.assertEqual(len(by_range.json()["data"]["days"]), 7)

        # Employee tetap diperiksa lebih dulu daripada rentang.
        missing = client.get(
            "/api/hr/shift-calendar/", {"month": "salah"},
        )

        self.assertEqual(missing.status_code, 400)
        self.assertIn("employee", missing.json()["errors"])

    def test_me_and_hr_return_the_same_calendar(self):
        """Satu mesin kalender, dua pintu — isinya tidak boleh berbeda."""
        mine = self.me_schedule(self.user_crew).json()["data"]
        hr = self.calendar(self.user_hr, self.crew.pk).json()["data"]

        self.assertEqual(mine, hr)

    def test_me_validates_range_like_hr(self):
        response = self.api(self.user_crew).get(
            "/api/me/schedule/", {"month": "2026-13"},
        )

        self.assertEqual(response.status_code, 400)

        too_long = self.api(self.user_crew).get(
            "/api/me/schedule/",
            {"start": "2026-01-01", "end": "2027-06-01"},
        )

        self.assertEqual(too_long.status_code, 400)

    # ------------------------------------------------------------------
    # Identitas yang tidak bisa diresolusi
    # ------------------------------------------------------------------

    def test_unauthenticated_is_401(self):
        from django_tenants.test.client import TenantClient

        response = TenantClient(self.tenant).get("/api/me/schedule/")

        self.assertEqual(response.status_code, 401)

    def test_account_without_employee_is_404_not_linked(self):
        user = self.make_user("nolink", roles=[self.role_hr])

        response = self.me_schedule(user, employee=self.crew.pk)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "employee_not_linked")

    def test_inactive_employee_is_403(self):
        user = self.make_user("inactive", roles=[self.role_employee])
        self.make_employee(section=self.section_a, user=user, is_active=False)

        response = self.me_schedule(user, employee=self.crew.pk)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "employee_inactive")

    # ------------------------------------------------------------------
    # 6. Tenant
    # ------------------------------------------------------------------

    def test_request_stays_inside_the_tenant_schema(self):
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as queries:
            response = self.me_schedule(self.user_manager)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(connection.schema_name, self.tenant.schema_name)

        # Satu-satunya `search_path` yang boleh disetel adalah milik
        # tenant yang dituju (dipasang middleware). Tidak ada query yang
        # menyebut schema lain secara eksplisit.
        for query in queries.captured_queries:
            sql = query["sql"].lower()

            if "search_path" in sql:
                self.assertIn(self.tenant.schema_name, sql)


class ScheduleActionRouteTests(SimpleTestCase):
    """Tombol "Lihat Jadwal" membawa niat tampilan, bukan identitas."""

    def test_route_carries_presentation_intent_only(self):
        action = ACTIONS["schedule"]

        self.assertEqual(action.route, "/hr/shift-calendar?mode=my")

        for param in IDENTITY_PARAMS + ("employee_number",):
            self.assertNotIn(f"{param}=", action.route)

    def test_menu_gate_is_still_the_hr_screen(self):
        self.assertEqual(ACTIONS["schedule"].menu_route, "/hr/shift-calendar")
