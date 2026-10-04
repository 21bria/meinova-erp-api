"""
POLICY-1A — arti `MenuVisibilityRule` tidak bergantung pada rute.

Yang dikunci:

* Travel Request → `field_break`, Business Trip → `business_trip`
  (penanda Employee Group yang sama dengan API-nya), Roster Schedule →
  `roster_only` (keanggotaan roster);
* `roster_only` tetap roster-only, `non_roster_only` tetap non-roster-only,
  `always` tetap tanpa syarat — **termasuk di rute Travel Request /
  Business Trip**;
* BOTH / NONE / TR-only / BT-only;
* akun tanpa `employee_profile`: syarat bersyarat apa pun tidak terpenuhi;
* migrasi `accounts.0015` hanya memindahkan dua pasangan bawaan.
"""

from __future__ import annotations

from datetime import timedelta
from importlib import import_module

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.accounts.api.menu_permissions.access import (
    FEATURE_RULES,
    MenuAccessService,
)
from apps.accounts.management.commands.seed_menus import MENU_RULES
from apps.accounts.models import (
    Menu,
    MenuVisibilityRule,
    Role,
    RoleMenuPermission,
)
from apps.administration.models.references.roster_policy import RosterPolicy
from apps.hr.applicability import HRFeature
from apps.hr.models import EmploymentAssignment

from .base import FAR
from .test_policy_applicability import PolicyTestCase


TR = "/hr/travel-requests"
BT = "/hr/business-trips"
ROTATION = "/hr/site-rotations"
HUB = "/hr/roster-travel"

MIGRATION = import_module(
    "apps.accounts.migrations.0015_menu_feature_visibility_rules",
)


class MenuRuleContract(SimpleTestCase):
    def test_feature_rules_are_the_hr_features(self):
        self.assertEqual(
            FEATURE_RULES,
            {
                MenuVisibilityRule.FIELD_BREAK: HRFeature.FIELD_BREAK,
                MenuVisibilityRule.BUSINESS_TRIP: HRFeature.BUSINESS_TRIP,
            },
        )

    def test_roster_values_are_unchanged(self):
        self.assertEqual(MenuVisibilityRule.ALWAYS, "always")
        self.assertEqual(MenuVisibilityRule.ROSTER_ONLY, "roster_only")
        self.assertEqual(MenuVisibilityRule.NON_ROSTER_ONLY, "non_roster_only")
        self.assertNotIn(MenuVisibilityRule.ROSTER_ONLY, FEATURE_RULES)
        self.assertNotIn(MenuVisibilityRule.NON_ROSTER_ONLY, FEATURE_RULES)

    def test_seed_defaults_name_their_own_meaning(self):
        rules = MENU_RULES["EMPLOYEE"]

        self.assertEqual(rules[TR], MenuVisibilityRule.FIELD_BREAK)
        self.assertEqual(rules[BT], MenuVisibilityRule.BUSINESS_TRIP)
        self.assertEqual(rules[ROTATION], MenuVisibilityRule.ROSTER_ONLY)
        self.assertNotIn(HUB, rules)

    def test_values_fit_the_column(self):
        for value in MenuVisibilityRule.values:
            self.assertLessEqual(len(value), 20, value)


class MenuVisibilitySemanticsTests(PolicyTestCase):
    def setUp(self):
        super().setUp()

        self.role = Role.objects.create(code="P1A-EMPLOYEE", name="P1A Employee")

        self.menus = {
            route: Menu.objects.create(code=f"p1a{n}", title=route, route=route)
            for n, route in enumerate((TR, BT, ROTATION, HUB))
        }

        self.roster_policy = RosterPolicy.objects.create(
            company=self.company,
            code="P1A-ROS",
            name="P1A Roster",
        )

    # ------------------------------------------------------------------

    def grant(self, route, rule, *, role=None):
        RoleMenuPermission.objects.update_or_create(
            role=role or self.role,
            menu=self.menus[route],
            defaults={"can_view": True, "visibility_rule": rule},
        )

    def grant_seed_defaults(self):
        """Persis `seed_menus.MENU_RULES` untuk EMPLOYEE (+ hub tanpa syarat)."""
        for route in (TR, BT, ROTATION, HUB):
            self.grant(
                route,
                MENU_RULES["EMPLOYEE"].get(route, MenuVisibilityRule.ALWAYS),
            )

    def employee(self, group, *, roster=False):
        employee = self.make_employee(location=self.site, group=group)

        if roster:
            # `update()`: yang diuji menunya, bukan validasi penempatan.
            EmploymentAssignment.objects.filter(employee=employee).update(
                roster_policy=self.roster_policy,
            )

        return type(employee).objects.get(pk=employee.pk)

    def routes(self, user):
        user.roles.set([self.role])

        access = MenuAccessService.visible_for(user)

        self.assertFalse(access["unrestricted"])

        return set(access["routes"])

    # ------------------------------------------------------------------
    # Seed bawaan: TR/BT dari Employee Group, Roster Schedule dari roster
    # ------------------------------------------------------------------

    def test_four_modes_with_seed_defaults_match_the_api(self):
        self.grant_seed_defaults()

        start = FAR

        for group, tr_visible, bt_visible in (
            (self.tr_group, True, False),
            (self.bt_group, False, True),
            (self.both_group, True, True),
            (self.none_group, False, False),
        ):
            for roster in (False, True):
                with self.subTest(group=group.code, roster=roster):
                    employee = self.employee(group, roster=roster)
                    routes = self.routes(employee.user)

                    self.assertEqual(TR in routes, tr_visible)
                    self.assertEqual(BT in routes, bt_visible)
                    # Roster Schedule hanya membaca roster, apa pun group-nya.
                    self.assertEqual(ROTATION in routes, roster)
                    self.assertIn(HUB, routes)

                    start += timedelta(days=30)

                    self.assertEqual(
                        self.api_accepts(lambda: self.make_travel_request(employee)),
                        tr_visible,
                    )
                    self.assertEqual(
                        self.api_accepts(
                            lambda: self.make_trip(employee, start=start),
                        ),
                        bt_visible,
                    )

    def api_accepts(self, create):
        try:
            create()
        except ValidationError as error:
            self.assertIn("employee", error.message_dict)
            return False

        return True

    def test_unconfigured_employee_sees_both(self):
        self.grant_seed_defaults()

        employee = self.employee(self.both_group)
        EmploymentAssignment.objects.filter(employee=employee).update(
            employee_group=None,
        )

        routes = self.routes(employee.user)

        self.assertIn(TR, routes)
        self.assertIn(BT, routes)

    # ------------------------------------------------------------------
    # Arti nilai tidak bergantung pada rute
    # ------------------------------------------------------------------

    def test_roster_only_on_travel_request_route_is_roster(self):
        """Tidak lagi diam-diam berarti `field_break` di rute TR."""
        self.grant(TR, MenuVisibilityRule.ROSTER_ONLY)

        # Field Break berlaku, tapi bukan pegawai roster → tersembunyi.
        self.assertNotIn(TR, self.routes(self.employee(self.tr_group).user))

        # Field Break mati, tapi pegawai roster → tampil.
        self.assertIn(
            TR,
            self.routes(self.employee(self.bt_group, roster=True).user),
        )

    def test_non_roster_only_on_business_trip_route_is_non_roster(self):
        """Tidak lagi diam-diam berarti `business_trip` di rute BT."""
        self.grant(BT, MenuVisibilityRule.NON_ROSTER_ONLY)

        self.assertNotIn(
            BT,
            self.routes(self.employee(self.bt_group, roster=True).user),
        )
        self.assertIn(BT, self.routes(self.employee(self.tr_group).user))

    def test_always_is_unconditional_on_every_route(self):
        for route in (TR, BT, ROTATION):
            self.grant(route, MenuVisibilityRule.ALWAYS)

        routes = self.routes(self.employee(self.none_group).user)

        self.assertTrue({TR, BT, ROTATION} <= routes)

    def test_feature_rule_means_the_same_on_any_route(self):
        """`field_break` di rute non-TR tetap penanda Employee Group."""
        self.grant(ROTATION, MenuVisibilityRule.FIELD_BREAK)
        self.grant(HUB, MenuVisibilityRule.BUSINESS_TRIP)

        tr_only = self.routes(self.employee(self.tr_group).user)

        self.assertIn(ROTATION, tr_only)
        self.assertNotIn(HUB, tr_only)

    def test_other_roster_route_keeps_roster_semantics(self):
        self.grant(HUB, MenuVisibilityRule.ROSTER_ONLY)

        self.assertNotIn(HUB, self.routes(self.employee(self.both_group).user))
        self.assertIn(
            HUB,
            self.routes(self.employee(self.both_group, roster=True).user),
        )

    def test_one_satisfied_rule_from_any_role_opens_the_menu(self):
        other = Role.objects.create(code="P1A-OTHER", name="P1A Other")

        self.grant(TR, MenuVisibilityRule.FIELD_BREAK)
        self.grant(TR, MenuVisibilityRule.ROSTER_ONLY, role=other)

        employee = self.employee(self.bt_group, roster=True)
        employee.user.roles.set([self.role, other])

        access = MenuAccessService.visible_for(employee.user)

        self.assertIn(TR, access["routes"])

    # ------------------------------------------------------------------
    # Akun tanpa employee_profile
    # ------------------------------------------------------------------

    def test_account_without_employee_profile(self):
        """Syarat bersyarat apa pun tidak terpenuhi; `always` tetap tampil.
        Tidak ada jalan pintas khusus TR/BT."""
        self.grant_seed_defaults()
        self.grant(ROTATION, MenuVisibilityRule.NON_ROSTER_ONLY)

        user = get_user_model().objects.create_user(
            username="p1a.system",
            email="p1a.system@example.test",
            password="Test-Only#Pw1",
        )

        routes = self.routes(user)

        self.assertNotIn(TR, routes)
        self.assertNotIn(BT, routes)
        # `non_roster_only` = bukan beroster: akun non-pegawai memenuhinya,
        # perilaku lama yang tidak diubah.
        self.assertIn(ROTATION, routes)
        self.assertIn(HUB, routes)

    # ------------------------------------------------------------------
    # Migrasi accounts.0015
    # ------------------------------------------------------------------

    def test_migration_moves_only_the_two_seed_pairs(self):
        other = Role.objects.create(code="P1A-MIG", name="P1A Migration")

        self.grant(TR, MenuVisibilityRule.ROSTER_ONLY)
        self.grant(BT, MenuVisibilityRule.NON_ROSTER_ONLY)
        self.grant(ROTATION, MenuVisibilityRule.ROSTER_ONLY)
        self.grant(HUB, MenuVisibilityRule.ROSTER_ONLY)

        # Kombinasi yang disetel tangan di rute TR/BT — tidak disentuh.
        self.grant(TR, MenuVisibilityRule.NON_ROSTER_ONLY, role=other)
        self.grant(BT, MenuVisibilityRule.ALWAYS, role=other)

        MIGRATION.to_feature_rules(django_apps, None)

        def rule(route, role):
            return RoleMenuPermission.objects.get(
                role=role,
                menu=self.menus[route],
            ).visibility_rule

        self.assertEqual(rule(TR, self.role), MenuVisibilityRule.FIELD_BREAK)
        self.assertEqual(rule(BT, self.role), MenuVisibilityRule.BUSINESS_TRIP)
        self.assertEqual(rule(ROTATION, self.role), MenuVisibilityRule.ROSTER_ONLY)
        self.assertEqual(rule(HUB, self.role), MenuVisibilityRule.ROSTER_ONLY)
        self.assertEqual(rule(TR, other), MenuVisibilityRule.NON_ROSTER_ONLY)
        self.assertEqual(rule(BT, other), MenuVisibilityRule.ALWAYS)

        # Idempoten: menjalankannya lagi tidak mengubah apa pun.
        MIGRATION.to_feature_rules(django_apps, None)
        self.assertEqual(rule(TR, self.role), MenuVisibilityRule.FIELD_BREAK)

        MIGRATION.to_roster_rules(django_apps, None)

        self.assertEqual(rule(TR, self.role), MenuVisibilityRule.ROSTER_ONLY)
        self.assertEqual(rule(BT, self.role), MenuVisibilityRule.NON_ROSTER_ONLY)
        self.assertEqual(rule(ROTATION, self.role), MenuVisibilityRule.ROSTER_ONLY)
