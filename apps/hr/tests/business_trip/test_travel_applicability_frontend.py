"""
TR/BT POLICY — frontend & keamanan semantik (follow-up POLICY-1/1A).

Yang dikunci di sini (sisanya sudah di `test_policy_applicability.py` dan
`test_menu_visibility_semantics.py`):

* konsistensi satu konfigurasi Employee Group di **enam** jalur sekaligus:
  create TR, submit TR, create BT, submit BT, menu TR, menu BT;
* kontrak schema Employee Group yang dibaca generator frontend: dua
  penanda bisa disunting, `travel_document` select read-only berisi kode
  resolver apa adanya, `travel_document_warnings` widget peringatan;
* lewat API: simpan BOTH/NONE tidak pernah ditolak, peringatannya
  `{kind, message}`, dan `travel_document` tidak bisa ditulis.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.accounts.api.menu_permissions.access import MenuAccessService
from apps.accounts.management.commands.seed_menus import MENU_RULES
from apps.accounts.models import Menu, MenuVisibilityRule, Role, RoleMenuPermission
from apps.administration.api.reference.hr.views.hr import employee_group_schema
from apps.hr import applicability
from apps.hr.api.business_trip.services import BusinessTripService
from apps.hr.api.travel_request.services import TravelRequestService

from .base import FAR
from .test_policy_applicability import PolicyTestCase


TR = "/hr/travel-requests"
BT = "/hr/business-trips"
GROUPS = "/api/administration/references/hr/employment-groups/"


# ---------------------------------------------------------------------------
# Schema yang dibaca generator
# ---------------------------------------------------------------------------


class EmployeeGroupSchemaContract(SimpleTestCase):
    def setUp(self):
        self.fields = employee_group_schema()["fields"]

    def test_both_flags_are_editable_switches_with_help_text(self):
        for name, label in (
            ("field_break_applicable", "Field Break / Travel Request"),
            ("business_trip_applicable", "Business Trip"),
        ):
            with self.subTest(field=name):
                meta = self.fields[name]

                self.assertEqual(meta["label"], label)
                self.assertTrue(meta["form"])
                self.assertNotEqual(meta.get("read_only"), True)
                self.assertIn("may use", meta["help_text"])

    def test_travel_document_is_a_read_only_display_of_resolver_codes(self):
        meta = self.fields["travel_document"]

        self.assertEqual(meta["type"], "select")
        self.assertTrue(meta["read_only"])
        self.assertTrue(meta["display"])
        self.assertFalse(meta["filter"])
        self.assertEqual(meta["modes"], ["edit", "detail"])

        # Kosakata = konstanta resolver, bukan kosakata kedua.
        self.assertEqual(
            [option["value"] for option in meta["options"]],
            [
                applicability.TRAVEL_REQUEST,
                applicability.BUSINESS_TRIP,
                applicability.BOTH,
                applicability.NONE,
            ],
        )

    def test_warnings_are_a_display_widget_not_a_field(self):
        meta = self.fields["travel_document_warnings"]

        self.assertEqual(meta["widget"], "warnings")
        self.assertTrue(meta["read_only"])
        self.assertTrue(meta["display"])
        self.assertFalse(meta.get("required"))


# ---------------------------------------------------------------------------
# API Employee Group
# ---------------------------------------------------------------------------


class EmployeeGroupApiTests(PolicyTestCase):
    def setUp(self):
        super().setUp()

        self.http = TenantClient(self.tenant)

        admin = get_user_model().objects.create_superuser(
            username="p1f.admin",
            email="p1f.admin@example.test",
            password="Test-Only#Pw1",
        )

        self.headers = {
            "HTTP_AUTHORIZATION": (
                f"Bearer {RefreshToken.for_user(admin).access_token}"
            ),
        }

    def patch(self, group, payload):
        response = self.http.patch(
            f"{GROUPS}{group.pk}/",
            data=json.dumps(payload),
            content_type="application/json",
            **self.headers,
        )

        return response, json.loads(response.content)

    @staticmethod
    def record(body):
        return body.get("data", body) if isinstance(body.get("data"), dict) else body

    def test_none_and_both_save_with_warnings_only(self):
        group = self.tr_group

        for flags, expected in (
            ((False, False), applicability.NONE),
            ((True, True), applicability.BOTH),
        ):
            with self.subTest(expected=expected):
                response, body = self.patch(group, {
                    "field_break_applicable": flags[0],
                    "business_trip_applicable": flags[1],
                })

                self.assertEqual(response.status_code, 200, body)

                data = self.record(body)

                self.assertEqual(data["travel_document"], expected)
                self.assertEqual(
                    [w["kind"] for w in data["travel_document_warnings"]],
                    [expected],
                )
                self.assertTrue(data["travel_document_warnings"][0]["message"])

                group.refresh_from_db()
                self.assertEqual(
                    (group.field_break_applicable, group.business_trip_applicable),
                    flags,
                )

    def test_single_document_groups_have_no_warning(self):
        response, body = self.patch(self.both_group, {
            "field_break_applicable": False,
            "business_trip_applicable": True,
        })

        self.assertEqual(response.status_code, 200, body)

        data = self.record(body)

        self.assertEqual(data["travel_document"], applicability.BUSINESS_TRIP)
        self.assertEqual(data["travel_document_warnings"], [])

    def test_travel_document_cannot_be_written(self):
        """Turunan: nilai kiriman diabaikan, penanda tetap penentunya."""
        response, body = self.patch(self.none_group, {
            "travel_document": applicability.BOTH,
            "travel_document_warnings": [],
        })

        self.assertEqual(response.status_code, 200, body)

        data = self.record(body)

        self.assertEqual(data["travel_document"], applicability.NONE)

        self.none_group.refresh_from_db()
        self.assertFalse(self.none_group.field_break_applicable)
        self.assertFalse(self.none_group.business_trip_applicable)


# ---------------------------------------------------------------------------
# Satu konfigurasi, enam jalur
# ---------------------------------------------------------------------------


class ApiMenuConsistencyTests(PolicyTestCase):
    """
    Create, submit, dan menu TR/BT harus sepakat untuk konfigurasi group
    yang sama. Menu hanya UX; yang diuji adalah bahwa ia tidak menyodorkan
    dokumen yang pasti ditolak, dan tidak menyembunyikan yang sah.
    """

    def setUp(self):
        super().setUp()

        self.role = Role.objects.create(code="P1F-EMPLOYEE", name="P1F Employee")

        for n, route in enumerate((TR, BT)):
            menu = Menu.objects.create(code=f"p1f{n}", title=route, route=route)

            # Nilai bawaan seed — yang dipakai tenant sesudah `0015`.
            RoleMenuPermission.objects.create(
                role=self.role,
                menu=menu,
                can_view=True,
                visibility_rule=MENU_RULES["EMPLOYEE"][route],
            )

    def test_seed_rules_are_the_feature_rules(self):
        self.assertEqual(MENU_RULES["EMPLOYEE"][TR], MenuVisibilityRule.FIELD_BREAK)
        self.assertEqual(MENU_RULES["EMPLOYEE"][BT], MenuVisibilityRule.BUSINESS_TRIP)

    @staticmethod
    def eligible(call) -> bool:
        """Lolos kelayakan pegawai — galat lain (baris kosong dsb.) bukan urusan ini."""
        try:
            call()
        except ValidationError as error:
            return "employee" not in error.message_dict

        return True

    def test_create_submit_and_menu_agree_for_every_mode(self):
        offset = 0

        for group, tr_expected, bt_expected in (
            (self.tr_group, True, False),
            (self.bt_group, False, True),
            (self.both_group, True, True),
            (self.none_group, False, False),
        ):
            with self.subTest(mode=applicability.group_travel_document(group)):
                offset += 60

                # Draf dibuat saat group masih BOTH, lalu group diganti —
                # jalur submit harus menilai ulang dengan group yang baru.
                employee = self.make_employee(location=self.site, group=self.both_group)
                draft_tr = self.make_travel_request(
                    employee,
                    start=FAR + timedelta(days=offset),
                    end=FAR + timedelta(days=offset + 4),
                    purpose=False,
                )
                draft_bt = self.make_trip(
                    employee,
                    start=FAR + timedelta(days=offset + 20),
                )

                self.switch_group(employee, group)
                employee = type(employee).objects.get(pk=employee.pk)

                employee.user.roles.set([self.role])
                routes = set(MenuAccessService.visible_for(employee.user)["routes"])

                tr_create = self.eligible(lambda: self.make_travel_request(
                    employee,
                    start=FAR + timedelta(days=offset + 10),
                    end=FAR + timedelta(days=offset + 12),
                ))
                bt_create = self.eligible(lambda: self.make_trip(
                    employee,
                    start=FAR + timedelta(days=offset + 30),
                ))
                tr_submit = self.eligible(
                    lambda: TravelRequestService.submit(request=draft_tr),
                )
                bt_submit = self.eligible(
                    lambda: BusinessTripService.submit(trip=draft_bt),
                )

                self.assertEqual(
                    applicability.travel_document(employee),
                    applicability.group_travel_document(group),
                )
                self.assertEqual(
                    (TR in routes, tr_create, tr_submit),
                    (tr_expected,) * 3,
                )
                self.assertEqual(
                    (BT in routes, bt_create, bt_submit),
                    (bt_expected,) * 3,
                )
