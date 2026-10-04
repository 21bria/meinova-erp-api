"""
BT-APPROVER-2 — cadangan berjenjang meja #2 (HRGA) alur Business Trip.

Rantai kanoniknya, yang pertama ketemu yang menang:

    HRGA@company → HR-ADMIN@company → HR-MANAGER@company → HR-MANAGER@tenant

Dua hal yang dikunci:

* **urutan di seed** — seed yang menukar atau memendekkan tingkatnya harus
  memerahkan test, bukan diam-diam mengubah siapa yang menyetujui;
* **perilaku resolver sungguhan** — tiap tingkat menang tepat ketika
  tingkat di atasnya kosong, dan tingkat sesudahnya tidak ikut masuk.

Bentuk organisasi demo (MMN dengan HR Admin, MIN dengan HR Manager saja,
holding tanpa personel HR, CEO tanpa atasan) dimodelkan dengan company
test sendiri, bukan dengan kode company demo.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError

from apps.administration.models import Company, Location
from apps.hr.api.business_trip.services import BusinessTripService
from apps.workflow.models import ApproverScope, WorkflowDefinition
from apps.workflow.resolver import resolve_approvers
from apps.workflow.seeds import workflows as workflow_seed

from .base import BusinessTripTestCase


CHAIN = [
    ("HR-ADMIN", ApproverScope.COMPANY),
    ("HR-MANAGER", ApproverScope.COMPANY),
    ("HR-MANAGER", ApproverScope.TENANT),
]


class BusinessTripFallbackSeedContractTests(BusinessTripTestCase):
    def step(self, sequence):
        return (
            WorkflowDefinition.objects
            .get(code="HR-BUSINESS-TRIP", is_deleted=False)
            .steps.get(sequence=sequence, is_deleted=False)
        )

    def test_canonical_source_lists_the_chain_in_order(self):
        step = workflow_seed.BUSINESS_TRIP_STEPS[1]

        self.assertEqual(
            (step["approver_role"], step["approver_scope"]),
            ("HRGA", ApproverScope.COMPANY),
        )
        self.assertEqual(step["fallbacks"], CHAIN)

    def test_seeded_step_carries_the_chain_in_order(self):
        step = self.step(2)

        self.assertEqual(
            (step.approver_role.code, step.approver_scope),
            ("HRGA", ApproverScope.COMPANY),
        )
        self.assertEqual(
            list(
                step.fallbacks
                .filter(is_deleted=False, is_active=True)
                .order_by("sequence")
                .values_list("sequence", "role__code", "approver_scope"),
            ),
            [(1, *CHAIN[0]), (2, *CHAIN[1]), (3, *CHAIN[2])],
        )
        self.assertEqual(
            [(role.code, scope) for role, scope in step.fallback_chain()],
            CHAIN,
        )

    def test_step_one_is_untouched(self):
        step = self.step(1)

        self.assertEqual(step.approver_type, "manager")
        self.assertEqual(step.fallback_role.code, "HRGA")
        self.assertFalse(step.fallbacks.exists())
        self.assertTrue(step.is_required)

    def test_reseeding_keeps_the_chain(self):
        workflow_seed.seed()

        self.assertEqual(
            list(
                self.step(2).fallbacks
                .order_by("sequence")
                .values_list("role__code", "approver_scope"),
            ),
            CHAIN,
        )


class BusinessTripFallbackPrecedenceTests(BusinessTripTestCase):
    """
    `company` = perusahaan subjek. `third` = perusahaan lain yang HR
    Manager-nya baru boleh terpanggil lewat tingkat tenant.
    """

    @classmethod
    def build_baseline(cls):
        super().build_baseline()

        cls.third, _ = Company.objects.get_or_create(
            code="BTH",
            is_deleted=False,
            defaults={"name": "Holding"},
        )

        cls.third_office, _ = Location.objects.get_or_create(
            code="BTH-HO",
            is_deleted=False,
            defaults={"company": cls.third, "name": "Holding HO"},
        )

    def setUp(self):
        super().setUp()

        self.manager = self.make_employee()
        self.subject = self.make_employee(reports_to=self.manager)

    def elsewhere(self, roles):
        """Pemegang role di company lain — hanya terjangkau se-tenant."""
        return self.make_employee(
            company=self.other_company,
            roles=roles,
        )

    def step_two(self):
        return (
            WorkflowDefinition.objects
            .get(code="HR-BUSINESS-TRIP", is_deleted=False)
            .steps.get(sequence=2, is_deleted=False)
        )

    def resolved(self, employee=None):
        result = resolve_approvers(
            employee=employee or self.subject,
            step=self.step_two(),
        )

        return (
            {candidate.employee.pk for candidate in result.candidates},
            {
                (candidate.resolved_role, candidate.resolved_scope)
                for candidate in result.candidates
            },
        )

    # ---- 1–4: tiap tingkat menang ketika yang di atasnya kosong ----

    def test_hrga_wins_when_present(self):
        hrga = self.make_employee(roles=["HRGA"])
        self.make_employee(roles=["HR-ADMIN"])
        self.make_employee(roles=["HR-MANAGER"])
        self.elsewhere(["HR-MANAGER"])

        people, tiers = self.resolved()

        self.assertEqual(people, {hrga.pk})
        self.assertEqual(tiers, {("HRGA", ApproverScope.COMPANY)})

    def test_hr_admin_wins_without_hrga(self):
        admin = self.make_employee(roles=["HR-ADMIN"])
        self.make_employee(roles=["HR-MANAGER"])
        self.elsewhere(["HR-MANAGER"])

        people, tiers = self.resolved()

        self.assertEqual(people, {admin.pk})
        self.assertEqual(tiers, {("HR-ADMIN", ApproverScope.COMPANY)})

    def test_company_hr_manager_wins_without_hrga_or_hr_admin(self):
        manager = self.make_employee(roles=["HR-MANAGER"])
        self.elsewhere(["HR-MANAGER"])
        # HR Admin perusahaan lain tidak boleh terpanggil: tingkat HR Admin
        # hanya se-company.
        self.elsewhere(["HR-ADMIN"])

        people, tiers = self.resolved()

        self.assertEqual(people, {manager.pk})
        self.assertEqual(tiers, {("HR-MANAGER", ApproverScope.COMPANY)})

    def test_tenant_hr_manager_resolves_without_company_hr(self):
        group_hr = self.elsewhere(["HR-MANAGER"])
        # HRGA / HR Admin company lain tetap tidak terjangkau.
        self.elsewhere(["HRGA"])
        self.elsewhere(["HR-ADMIN"])

        people, tiers = self.resolved()

        self.assertEqual(people, {group_hr.pk})
        self.assertEqual(tiers, {("HR-MANAGER", ApproverScope.TENANT)})

    # ---- 5: subjek tidak menyetujui dirinya sendiri ----

    def test_self_is_excluded_and_next_tier_is_used(self):
        hr_manager = self.make_employee(
            reports_to=self.manager,
            roles=["HR-MANAGER"],
        )
        group_hr = self.elsewhere(["HR-MANAGER"])

        people, tiers = self.resolved(hr_manager)

        self.assertNotIn(hr_manager.pk, people)
        self.assertEqual(people, {group_hr.pk})
        self.assertEqual(tiers, {("HR-MANAGER", ApproverScope.TENANT)})

    def test_self_alone_in_the_tenant_fails_loudly(self):
        hr_manager = self.make_employee(
            reports_to=self.manager,
            roles=["HR-MANAGER"],
        )

        people, _ = self.resolved(hr_manager)

        self.assertEqual(people, set())

    # ---- 6–7: tingkat yang berhasil menghentikan pencarian ----

    def test_successful_tier_stops_later_tiers(self):
        manager = self.make_employee(roles=["HR-MANAGER"])
        group_hr = self.elsewhere(["HR-MANAGER"])

        people, _ = self.resolved()

        self.assertEqual(people, {manager.pk})
        self.assertNotIn(group_hr.pk, people)

    def test_hr_admin_routing_is_not_widened_by_tenant_tier(self):
        admins = {
            self.make_employee(roles=["HR-ADMIN"]).pk,
            self.make_employee(roles=["HR-ADMIN"]).pk,
        }
        company_manager = self.make_employee(roles=["HR-MANAGER"])
        group_hr = self.elsewhere(["HR-MANAGER"])

        people, tiers = self.resolved()

        self.assertEqual(people, admins)
        self.assertEqual(tiers, {("HR-ADMIN", ApproverScope.COMPANY)})
        self.assertFalse({company_manager.pk, group_hr.pk} & people)

    # ---- 8–10: bentuk organisasi demo, lewat pengajuan sungguhan ----

    def submit(self, employee):
        trip = self.make_trip(employee)

        workflow = BusinessTripService.submit(trip=trip, user=employee.user)

        return [
            (row.sequence, row.approver_employee_id)
            for row in workflow.approvals.order_by("sequence", "id")
        ]

    def test_company_with_only_an_hr_manager_routes_there(self):
        # MIN: tanpa HRGA / HR Admin, HR Manager-nya sendiri yang menyetujui.
        boss = self.make_employee(company=self.other_company)
        employee = self.make_employee(
            company=self.other_company,
            reports_to=boss,
        )
        local_hr = self.elsewhere(["HR-MANAGER"])
        self.make_employee(roles=["HR-MANAGER"])  # company lain, tingkat 3

        self.assertEqual(
            self.submit(employee),
            [(1, boss.pk), (2, local_hr.pk)],
        )

    def test_company_without_hr_routes_to_tenant_hr_manager(self):
        # Holding: tidak ada personel HR sama sekali.
        boss = self.make_employee(company=self.third, location=self.third_office)
        employee = self.make_employee(
            company=self.third,
            location=self.third_office,
            reports_to=boss,
        )
        group_hr = self.make_employee(roles=["HR-MANAGER"])

        self.assertEqual(
            self.submit(employee),
            [(1, boss.pk), (2, group_hr.pk)],
        )

    def test_top_level_employee_still_fails_step_one(self):
        # CEO: tanpa atasan, tanpa HRGA. Meja #2 bisa terisi, meja #1 tidak
        # — dan itu disengaja sampai tata kelola tingkat puncak diputuskan.
        ceo = self.make_employee(company=self.third, location=self.third_office)
        self.make_employee(roles=["HR-MANAGER"])

        people, _ = self.resolved(ceo)
        self.assertTrue(people)

        with self.assertRaises(ValidationError):
            self.submit(ceo)
