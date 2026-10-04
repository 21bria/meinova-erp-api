"""
Cakupan organisasi dan alur persetujuan dokumen Roster Setup.

Dua pertanyaan yang dijawab berkas ini, dan keduanya soal **batas**:

1. **Siapa yang boleh masuk dokumen ini.** Menyaring dropdown bukan
   penjagaan — `add-employees` dan `POST /roster-setup-lines/`
   sama-sama menerima id yang diketik tangan. Yang dikunci di sini:
   pegawai kantor pusat, pegawai site sebelah, dan pegawai di luar
   cakupan data pembuatnya **ditolak di service**, bukan cuma hilang
   dari layar.
2. **Siapa yang menandatanganinya.** Meja "atasan langsung" berangkat
   dari satu pegawai, sementara dokumen ini memuat banyak. Boleh
   dipakai **kalau seluruh baris jatuh ke atasan yang sama**; kalau
   tidak, dokumennya ditolak dengan menyebut siapa membawahi siapa —
   bukan dijatuhkan diam-diam ke salah satunya.

`TenantTestCase` tidak memanggil `super().setUpClass()`, jadi tidak ada
rollback per test: tiap test membuat pegawainya sendiri dan hanya
membaca miliknya.
"""

from __future__ import annotations

from datetime import date
from unittest import mock

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
    Division,
    Location,
    RosterPolicy,
    RosterShiftRotation,
    Section,
    Shift,
)
from apps.administration.seeds.numbering import seed_numbering
from apps.hr.api.roster.setup_service import (
    RosterSetupLineService,
    RosterSetupService,
)
from apps.hr import reporting_line
from apps.hr.api.shift_calendar.pattern import RosterShiftPatternService
from apps.hr.api.site_rotation.services import SiteRotationService
from apps.hr.tests.access_helpers import grant_employee_read
from apps.hr.models import (
    Employee,
    EmployeeShiftAssignment,
    EmploymentAssignment,
    OrganizationAssignment,
    RosterSetupStatus,
    ShiftAssignmentLayer,
    SiteRotation,
)
from apps.workflow.models import (
    ApproverScope,
    ApproverType,
    InstanceStatus,
    WorkflowApproval,
    WorkflowDefinition,
    WorkflowStatus,
    WorkflowStep,
)


User = get_user_model()

AS_OF = date(2026, 8, 1)


class RosterSetupScopeTestCase(TenantTestCase):
    """Satu company, satu site + satu kantor pusat, dua section."""

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "roster-scope"
        tenant.name = "Roster Scope"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        seed_numbering()

        cls.company = Company.objects.create(code="SCP", name="Scope Test")

        cls.site = Location.objects.create(
            company=cls.company, code="SCPSITE", name="Site Scope",
        )

        cls.head_office = Location.objects.create(
            company=cls.company, code="SCPHO", name="Head Office Scope",
        )

        cls.department = Department.objects.create(
            company=cls.company,
            location=cls.site,
            code="SCPOPS",
            name="Operations",
        )

        cls.section_a = Section.objects.create(
            company=cls.company,
            location=cls.site,
            department=cls.department,
            code="SCPSECA",
            name="Section A",
        )

        cls.section_b = Section.objects.create(
            company=cls.company,
            location=cls.site,
            department=cls.department,
            code="SCPSECB",
            name="Section B",
        )

        # Dua division dipakai menguji cabang cakupan **pembuat** yang
        # murni: dokumen Roster Setup tidak punya kolom Division sama
        # sekali, jadi yang menyaring pegawai di sini hanya
        # kewenangan penugasan — bukan penyaring dokumen yang kebetulan
        # ikut membuang orang yang sama.
        cls.division_a = Division.objects.create(
            company=cls.company, code="SCPDIVA", name="Division A",
        )

        cls.division_b = Division.objects.create(
            company=cls.company, code="SCPDIVB", name="Division B",
        )

        cls.shift_day = Shift.objects.create(
            code="SCP-D", name="Day", start_time="07:00", end_time="19:00",
        )

        cls.policy = RosterPolicy.objects.create(
            company=cls.company,
            location=cls.site,
            code="SCP-6-2",
            name="Roster 6:2",
            cycle_work_days=42,
            cycle_off_days=14,
            default_travel_out_days=1,
            default_travel_in_days=1,
            rolling_horizon_months=12,
        )

        # Perputaran shift: satu langkah saja. Cukup untuk membuktikan
        # Shift Calendar terisi sendiri sesudah dokumen di-commit —
        # yang diuji seam-nya, bukan rumus polanya (itu punya berkas
        # sendiri).
        RosterShiftRotation.objects.create(
            policy=cls.policy,
            sequence=1,
            shift=cls.shift_day,
            block_days=7,
        )

        cls.definition = cls.make_definition()

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def make_definition(cls):
        """
        Alur roster setup seperti yang diseed `seed_workflows`:
        HR Admin Site → Atasan Langsung → HR Manager Site.
        """
        cls.role_hr_admin = Role.objects.create(
            code="SCP-HR-ADMIN", name="HR Admin Site",
        )

        cls.role_hr_manager = Role.objects.create(
            code="SCP-HR-MANAGER", name="HR Manager Site",
        )

        definition = WorkflowDefinition.objects.create(
            code="SCP-ROSTER-SETUP",
            name="Roster Setup — Scope Test",
            module="hr",
            document_type="roster_setup",
            company=cls.company,
            status=WorkflowStatus.ACTIVE,
        )

        WorkflowStep.objects.create(
            definition=definition,
            sequence=1,
            name="Reviewed By (HR Admin Site)",
            approver_type=ApproverType.ROLE,
            approver_role=cls.role_hr_admin,
            approver_scope=ApproverScope.LOCATION,
        )

        WorkflowStep.objects.create(
            definition=definition,
            sequence=2,
            name="Approved By (Atasan Langsung)",
            approver_type=ApproverType.MANAGER,
            level=1,
        )

        WorkflowStep.objects.create(
            definition=definition,
            sequence=3,
            name="Approved By (HR Manager Site)",
            approver_type=ApproverType.ROLE,
            approver_role=cls.role_hr_manager,
            approver_scope=ApproverScope.LOCATION,
        )

        return definition

    @classmethod
    def make_employee(
        cls,
        *,
        location=None,
        department=None,
        section=None,
        division=None,
        reports_to=None,
        policy=None,
        cycle_start=None,
        user=None,
        is_active=True,
    ):
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"SCP{cls._counter:04d}",
            first_name="Scope",
            last_name=f"Employee {cls._counter}",
            is_active=is_active,
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=location or cls.site,
            department=department,
            section=section,
            division=division,
            reports_to=reports_to,
            organization_effective_date=date(2026, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=date(2025, 1, 1),
            roster_policy=policy,
            roster_cycle_start=cycle_start,
        )

        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def make_user(cls, name, *, roles=(), scopes=(), superuser=False):
        """
        Akun + role, dengan WHERE **dinyatakan pada penugasannya**.

        `scopes` berbentuk `(role, resource_type, resource_id)` dan
        tetap jadi sumber maksudnya; yang berubah sejak Stage 4J cuma
ke mana ia ditulis. Sejak Wave C kewenangan penugasan adalah
        satu-satunya tempat WHERE disimpan; model cakupan lama sudah
        tidak ada.

        **Role yang tidak disebut di `scopes` berarti tanpa batasan**,
        sama seperti sebelumnya. Itu dinyatakan di sini sebagai
        `UNRESTRICTED`, bukan disimpulkan dari nama role: yang tahu
        maksudnya pemanggil, dan pemanggil menyatakannya dengan tidak
        mengisi `scopes`.
        """
        cls._counter += 1

        user = User.objects.create_user(
            username=f"{name}.{cls._counter}",
            email=f"{name}.{cls._counter}@example.test",
            password="scope-pass-1",
            is_superuser=superuser,
            is_staff=superuser,
        )

        declared: dict[int, list] = {}

        for role, resource_type, resource_id in scopes:
            declared.setdefault(role.pk, []).append(
                (resource_type, resource_id))

        for role in roles:
            # `hr.employee` bacanya dijaga izin model
            # (`require_view_permission`), dan dropdown pegawai adalah
            # salah satu pintunya. Di produksi setiap role yang diseed
            # memegang `hr.view_employee` lewat `READ_GRANTS`; tanpa
            # baris ini fixture-nya menabrak 403 sebelum satu pun aturan
            # cakupan sempat diuji.
            grant_employee_read(role)

            rows = declared.get(role.pk, [])

            if rows:
                grant_role(
                    user, role,
                    mode=AuthorityMode.EXPLICIT,
                    authorities=rows,
                )
            else:
                grant_role(user, role, mode=AuthorityMode.UNRESTRICTED)

        return user

    def make_setup(self, *, department=None, section=None, user=None):
        return RosterSetupService.create(
            data={
                "company": self.company,
                "location": self.site,
                "department": department,
                "section": section,
                "as_of_date": AS_OF,
                "horizon_months": 12,
            },
            user=user,
        )

    def add_line(self, setup, employee, *, user=None, cycle_start=AS_OF):
        return RosterSetupLineService.create(
            data={
                "request": setup,
                "employee": employee,
                "roster_policy": self.policy,
                "current_cycle_start": cycle_start,
            },
            user=user,
        )


# ----------------------------------------------------------------------
# Siapa yang boleh masuk dokumen
# ----------------------------------------------------------------------


class EmployeeScopeTests(RosterSetupScopeTestCase):
    def test_head_office_employee_is_not_a_candidate(self):
        """Pegawai kantor pusat tidak pernah masuk roster site."""
        setup = self.make_setup()

        stray = self.make_employee(location=self.head_office)

        eligible = RosterSetupService.eligible_employees(request=setup)

        self.assertFalse(eligible.filter(pk=stray.pk).exists())

    def test_head_office_employee_cannot_be_forced_through_the_service(self):
        """
        Kasus negatif yang paling penting: id-nya diketik tangan, bukan
        dipilih dari dropdown. Ditolak di service — kalau hanya
        `document_validations` yang menjaganya, barisnya tetap masuk
        dan baru ketahuan saat preview.
        """
        setup = self.make_setup()

        stray = self.make_employee(location=self.head_office)

        with self.assertRaises(ValidationError) as caught:
            self.add_line(setup, stray)

        message = str(caught.exception)

        self.assertIn(stray.employee_number, message)
        self.assertIn("Head Office Scope", message)

    def test_inactive_employee_is_refused(self):
        setup = self.make_setup()

        retired = self.make_employee(is_active=False)

        with self.assertRaises(ValidationError):
            self.add_line(setup, retired)

    def test_section_filter_is_enforced_on_the_line(self):
        setup = self.make_setup(
            department=self.department, section=self.section_a,
        )

        outsider = self.make_employee(
            department=self.department, section=self.section_b,
        )

        with self.assertRaises(ValidationError) as caught:
            self.add_line(setup, outsider)

        self.assertIn("Section A", str(caught.exception))

    def test_employee_outside_the_creator_scope_is_refused(self):
        """
        Cakupan **pembuat**, bukan cakupan dokumen.

        Sengaja lewat Division: dokumen Roster Setup tidak punya kolom
        Division, jadi kedua pegawai lolos seluruh penyaring dokumen
        dan satu-satunya yang membedakan mereka adalah
        kewenangan penugasan milik pembuatnya. Kalau diuji lewat
        Section, yang menolak bisa saja penyaring dokumennya — dan
        test-nya lulus tanpa menyentuh cakupan sama sekali.
        """
        role = Role.objects.create(
            code=f"SCP-ADMIN-{self._counter}", name="Admin Division A",
        )

        admin = self.make_user(
            "scope.admin",
            roles=[role],
            scopes=[(role, "division", self.division_a.pk)],
        )

        setup = self.make_setup(user=admin)

        mine = self.make_employee(division=self.division_a)
        theirs = self.make_employee(division=self.division_b)

        eligible = RosterSetupService.eligible_employees(
            request=setup, user=admin,
        )

        self.assertTrue(eligible.filter(pk=mine.pk).exists())
        self.assertFalse(eligible.filter(pk=theirs.pk).exists())

        with self.assertRaises(ValidationError) as caught:
            self.add_line(setup, theirs, user=admin)

        self.assertIn("cakupan data Anda", str(caught.exception))

    def test_document_outside_the_creator_scope_is_refused(self):
        role = Role.objects.create(
            code=f"SCP-ADMIN-B-{self._counter}", name="Admin Section B",
        )

        admin = self.make_user(
            "scope.admin.b",
            roles=[role],
            scopes=[(role, "section", self.section_b.pk)],
        )

        with self.assertRaises(ValidationError) as caught:
            RosterSetupService.create(
                data={
                    "company": self.company,
                    "location": self.site,
                    "section": self.section_a,
                    "as_of_date": AS_OF,
                },
                user=admin,
            )

        self.assertIn("cakupan data Anda", str(caught.exception))

    def test_add_employees_endpoint_drops_the_ids_it_may_not_accept(self):
        """
        Lewat API, dengan akun yang cakupannya dibatasi — jalur yang
        benar-benar dipakai tombol Add Employees.
        """
        role = Role.objects.create(
            code=f"SCP-ADMIN-API-{self._counter}", name="Admin Section API",
        )

        admin = self.make_user(
            "scope.api",
            roles=[role],
            scopes=[(role, "section", self.section_a.pk)],
        )

        setup = self.make_setup(section=self.section_a, user=admin)

        # Policy dan jangkar diisi di penempatan masing-masing:
        # `add-employees` menyalinnya dari sana (`apply_defaults`), dan
        # baris tanpa keduanya ditolak `full_clean` — kegagalan yang
        # tidak ada hubungannya dengan cakupan, yang justru diuji di
        # sini.
        placement = {"policy": self.policy, "cycle_start": AS_OF}

        mine = self.make_employee(section=self.section_a, **placement)
        theirs = self.make_employee(section=self.section_b, **placement)
        stray = self.make_employee(location=self.head_office, **placement)

        client = TenantClient(self.tenant)

        response = client.post(
            f"/api/hr/roster-setups/{setup.pk}/add-employees/",
            data={"employee_ids": [mine.pk, theirs.pk, stray.pk]},
            content_type="application/json",
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(admin).access_token}"
            ),
        )

        self.assertEqual(response.status_code, 201, response.content)

        added = set(
            setup.lines
            .filter(is_deleted=False)
            .values_list("employee_id", flat=True)
        )

        self.assertEqual(added, {mine.pk})
        self.assertIn("ditolak", response.json()["message"])


# ----------------------------------------------------------------------
# Meja atasan langsung pada dokumen batch
# ----------------------------------------------------------------------


class BatchApproverTests(RosterSetupScopeTestCase):
    def findings(self, setup):
        return {
            item["code"]: item["message"]
            for item in RosterSetupService.preview(
                request=setup,
            )["workflow_validations"]
        }

    def test_one_supervisor_for_the_whole_batch_is_accepted(self):
        supervisor = self.make_employee(
            user=self.make_user("scope.spv"),
        )

        setup = self.make_setup()

        for _ in range(2):
            self.add_line(
                setup, self.make_employee(reports_to=supervisor),
            )

        preview = RosterSetupService.preview(request=setup)

        self.assertNotIn(
            "mixed_approver",
            {item["code"] for item in preview["workflow_validations"]},
        )
        self.assertTrue(preview["can_submit"])

    def test_two_supervisors_in_one_document_are_blocked(self):
        """
        Keputusan batch `report_to`: **satu dokumen, satu atasan.**
        Memilih salah satunya berarti satu orang menandatangani jadwal
        bawahan orang lain, dan yang tidak menandatangani tidak pernah
        tahu jadwal timnya berubah.
        """
        first = self.make_employee(user=self.make_user("scope.spv.a"))
        second = self.make_employee(user=self.make_user("scope.spv.b"))

        setup = self.make_setup()

        mine = self.make_employee(reports_to=first)
        theirs = self.make_employee(reports_to=second)

        self.add_line(setup, mine)
        self.add_line(setup, theirs)

        findings = self.findings(setup)

        self.assertIn("mixed_approver", findings)

        message = findings["mixed_approver"]

        # Pesannya harus menyebut **siapa membawahi siapa** — tanpa itu
        # "atasannya berbeda" tidak memberi tahu dokumen ini harus
        # dipecah jadi berapa.
        for number in (
            first.employee_number,
            second.employee_number,
            mine.employee_number,
            theirs.employee_number,
        ):
            self.assertIn(number, message)

        preview = RosterSetupService.preview(request=setup)

        self.assertFalse(preview["can_submit"])

        # Isinya sendiri **benar** — yang menghalangi mejanya, bukan
        # barisnya. Dua jawaban yang berbeda, dan seed peragaan yang
        # commit langsung bergantung pada perbedaan itu.
        self.assertTrue(preview["can_commit"])

    def test_submit_refuses_a_document_with_two_supervisors(self):
        first = self.make_employee(user=self.make_user("scope.spv.c"))
        second = self.make_employee(user=self.make_user("scope.spv.d"))

        setup = self.make_setup()

        self.add_line(setup, self.make_employee(reports_to=first))
        self.add_line(setup, self.make_employee(reports_to=second))

        with self.assertRaises(ValidationError):
            RosterSetupService.submit(request=setup)

        setup.refresh_from_db()

        self.assertEqual(setup.status, RosterSetupStatus.DRAFT)

    def test_empty_reports_to_names_the_employees_it_is_missing_for(self):
        setup = self.make_setup()

        orphan = self.make_employee()

        self.add_line(setup, orphan)

        findings = self.findings(setup)

        self.assertIn("approver_not_found", findings)
        self.assertIn(
            orphan.employee_number, findings["approver_not_found"],
        )


# ----------------------------------------------------------------------
# Ujung ke ujung: submit → tiga meja → commit → shift calendar
# ----------------------------------------------------------------------


class ApprovalFlowTests(RosterSetupScopeTestCase):
    def approve(self, user, *, expect=200):
        """Menyetujui baris terdepan lewat API kotak masuk."""
        approval = (
            WorkflowApproval.objects
            .filter(approver=user, status="pending")
            .order_by("sequence")
            .first()
        )

        self.assertIsNotNone(
            approval, f"{user.username} tidak punya baris menunggu.",
        )

        client = TenantClient(self.tenant)

        response = client.post(
            f"/api/workflow/approvals/{approval.pk}/approve/",
            data={"comment": ""},
            content_type="application/json",
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
        )

        self.assertEqual(response.status_code, expect, response.content)

        return response

    def build_batch(self):
        """Satu site, tiga meja terisi, dua pegawai satu atasan."""
        hr_admin_user = self.make_user(
            "scope.hradmin", roles=[self.role_hr_admin],
        )
        hr_manager_user = self.make_user(
            "scope.hrmanager", roles=[self.role_hr_manager],
        )
        supervisor_user = self.make_user("scope.supervisor")

        self.make_employee(user=hr_admin_user)
        self.make_employee(user=hr_manager_user)

        supervisor = self.make_employee(user=supervisor_user)

        setup = self.make_setup()

        crew = [
            self.make_employee(reports_to=supervisor),
            self.make_employee(reports_to=supervisor),
        ]

        for employee in crew:
            self.add_line(setup, employee)

        return setup, crew, {
            "hr_admin": hr_admin_user,
            "supervisor": supervisor_user,
            "hr_manager": hr_manager_user,
        }

    def test_three_desks_then_auto_commit_then_shift_calendar(self):
        setup, crew, desks = self.build_batch()

        instance = RosterSetupService.submit(request=setup)

        setup.refresh_from_db()

        self.assertEqual(setup.status, RosterSetupStatus.SUBMITTED)

        rows = list(instance.approvals.order_by("sequence"))

        self.assertEqual(
            [row.approver_id for row in rows],
            [
                desks["hr_admin"].pk,
                desks["supervisor"].pk,
                desks["hr_manager"].pk,
            ],
        )

        self.approve(desks["hr_admin"])
        self.approve(desks["supervisor"])
        self.approve(desks["hr_manager"])

        instance.refresh_from_db()
        setup.refresh_from_db()

        self.assertEqual(instance.status, InstanceStatus.APPROVED)

        # Commit otomatis: tidak ada tombol yang ditekan sesudah meja
        # terakhir.
        self.assertEqual(setup.status, RosterSetupStatus.COMMITTED)

        for employee in crew:
            self.assertTrue(
                SiteRotation.objects
                .filter(employee=employee, is_deleted=False)
                .exists(),
            )

            # Shift Calendar terisi sendiri dari Roster Policy → Shift
            # Rotation, tanpa satu tombol pun.
            self.assertTrue(
                EmployeeShiftAssignment.objects
                .filter(
                    employee=employee,
                    is_deleted=False,
                    layer=ShiftAssignmentLayer.BASELINE,
                )
                .exists(),
            )

    def test_final_approval_survives_a_broken_email_queue(self):
        """
        Regresi persetujuan terakhir.

        `notify()` membungkus badannya dengan savepoint, tapi callback
        `on_commit` jalan **di luar** savepoint itu — sesudah
        transaksinya commit, masih di dalam request. Broker yang mati
        membuat `.delay()` melempar dari titik itu: datanya sudah
        tersimpan (dokumen `committed`, roster terbit, baseline shift
        terbentuk) tapi response-nya 500, dan approver membaca
        "Keputusan gagal disimpan" untuk sesuatu yang berhasil
        seluruhnya. Ia lalu mengulanginya.

        Yang dikunci di sini: broker mati **tidak** mengubah satu pun
        hasil yang dilihat pengguna.
        """
        setup, crew, desks = self.build_batch()

        RosterSetupService.submit(request=setup)

        broker_down = mock.Mock(
            side_effect=RuntimeError("Connection refused"),
        )

        with mock.patch(
            "apps.notifications.tasks.send_email_notification.delay",
            broker_down,
        ):
            for desk in ("hr_admin", "supervisor", "hr_manager"):
                self.approve(desks[desk])

        setup.refresh_from_db()

        self.assertEqual(setup.status, RosterSetupStatus.COMMITTED)
        self.assertEqual(setup.commit_error, "")

        for employee in crew:
            self.assertTrue(
                SiteRotation.objects
                .filter(employee=employee, is_deleted=False)
                .exists(),
            )
            self.assertTrue(
                EmployeeShiftAssignment.objects
                .filter(
                    employee=employee,
                    is_deleted=False,
                    layer=ShiftAssignmentLayer.BASELINE,
                )
                .exists(),
            )

    def test_an_approver_outside_the_scope_cannot_decide(self):
        """
        HR Admin site lain memegang role yang sama. Ia tidak pernah
        kebagian baris — dan kalau id barisnya ditembak langsung,
        `check_right` menolaknya.
        """
        setup, _crew, desks = self.build_batch()

        outsider = self.make_user(
            "scope.hradmin.other", roles=[self.role_hr_admin],
        )

        self.make_employee(user=outsider, location=self.head_office)

        instance = RosterSetupService.submit(request=setup)

        self.assertFalse(
            instance.approvals.filter(approver=outsider).exists(),
        )

        target = instance.approvals.order_by("sequence").first()

        client = TenantClient(self.tenant)

        response = client.post(
            f"/api/workflow/approvals/{target.pk}/approve/",
            data={"comment": ""},
            content_type="application/json",
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(outsider).access_token}"
            ),
        )

        self.assertEqual(response.status_code, 400, response.content)

        instance.refresh_from_db()

        self.assertEqual(instance.status, InstanceStatus.PENDING)


# ----------------------------------------------------------------------
# Baseline shift tidak boleh tertinggal
# ----------------------------------------------------------------------


class BaselineOrphanTests(RosterSetupScopeTestCase):
    def test_deleting_a_plan_clears_its_baseline_shifts(self):
        """
        `EmployeeShiftAssignment` tidak punya FK ke roster sama sekali,
        jadi tanpa penanganan khusus menghapus rencananya meninggalkan
        shift di tanggal yang rosternya sudah tidak ada — dan layarnya
        terlihat terisi, jadi kesalahannya gagal diam.
        """
        setup = self.make_setup()

        employee = self.make_employee()

        self.add_line(setup, employee)

        RosterSetupService.commit(request=setup)

        plan = SiteRotation.objects.get(employee=employee, is_deleted=False)

        baseline = EmployeeShiftAssignment.objects.filter(
            employee=employee,
            is_deleted=False,
            layer=ShiftAssignmentLayer.BASELINE,
        )

        self.assertTrue(baseline.exists())

        SiteRotationService.soft_delete(instance=plan)

        self.assertFalse(baseline.exists())

    def test_sync_without_a_roster_clears_instead_of_doing_nothing(self):
        employee = self.make_employee(
            policy=self.policy, cycle_start=AS_OF,
        )

        EmployeeShiftAssignment.objects.create(
            employee=employee,
            shift=self.shift_day,
            layer=ShiftAssignmentLayer.BASELINE,
            start_date=AS_OF,
            end_date=date(2026, 8, 31),
        )

        result = RosterShiftPatternService.sync(employee=employee)

        self.assertEqual(result["skipped"], "no_roster")
        self.assertEqual(result["cleared"], 1)

        self.assertFalse(
            EmployeeShiftAssignment.objects
            .filter(
                employee=employee,
                is_deleted=False,
                layer=ShiftAssignmentLayer.BASELINE,
            )
            .exists(),
        )


# ----------------------------------------------------------------------
# Siapa boleh membuka Shift Calendar siapa
# ----------------------------------------------------------------------


class ShiftCalendarAccessTests(RosterSetupScopeTestCase):
    """
    `GET /api/hr/shift-calendar/?employee=<id>` adalah satu-satunya
    pintu, dan `employee` datang dari URL — jadi penjagaannya harus ada
    di endpoint itu, bukan di dropdown yang menyusunnya.

    Tiga kursi yang harus bisa membukanya, dan masing-masing lewat
    mekanisme yang berbeda: HR (tanpa batasan), Admin Department /
    Section (cakupan unit organisasi), dan **atasan langsung** (garis
    pelaporan). Yang ketiga tidak punya cakupan unit sama sekali —
    cakupannya `own`, satu baris: dirinya.
    """

    def calendar(self, user, employee, *, month="2026-09"):
        client = TenantClient(self.tenant)

        return client.get(
            "/api/hr/shift-calendar/",
            data={"employee": employee.pk, "month": month},
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
        )

    def lookup(self, user, **params):
        client = TenantClient(self.tenant)

        response = client.get(
            "/api/hr/employees/lookup/",
            data=params,
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
        )

        self.assertEqual(response.status_code, 200, response.content)

        # Bentuk respons lookup berbeda-beda tergantung paginasi dan
        # pembungkus `success_response`: kadang `{"results": [...]}`,
        # kadang `{"data": [...]}`, kadang `{"data": {"results": [...]}}`.
        # Yang diuji isinya, jadi pembungkusnya dikupas apa adanya.
        payload = response.json()

        while isinstance(payload, dict):
            for key in ("results", "data"):
                if key in payload:
                    payload = payload[key]

                    break
            else:
                break

        rows = payload if isinstance(payload, list) else []

        return {row.get("value") or row.get("id") for row in rows}

    def make_own_scoped_user(self, name):
        """Akun bercakupan `own` — persis kursi supervisor di lapangan."""
        role = Role.objects.create(
            code=f"SCP-OWN-{self._counter}-{name}", name=f"Own {name}",
        )

        return self.make_user(
            name, roles=[role], scopes=[(role, "own", None)],
        )

    # ------------------------------------------------------------------

    def test_supervisor_may_open_a_subordinate_calendar(self):
        boss_user = self.make_own_scoped_user("spv")
        boss = self.make_employee(user=boss_user)

        crew = self.make_employee(reports_to=boss)

        response = self.calendar(boss_user, crew)

        self.assertEqual(response.status_code, 200, response.content)

    def test_supervisor_may_not_open_someone_outside_the_line(self):
        """
        Kasus negatif yang menentukan: id-nya diketik langsung ke URL,
        bukan dipilih dari dropdown. Kalau ini lolos, menyaring dropdown
        tidak menjaga apa pun.
        """
        boss_user = self.make_own_scoped_user("spv.outside")
        self.make_employee(user=boss_user)

        stranger = self.make_employee()

        response = self.calendar(boss_user, stranger)

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("cakupan", response.content.decode())

    def test_reporting_line_cascades_past_one_level(self):
        """
        Manajer membawahi supervisor yang membawahi crew, dan "tim saya"
        bagi manajer memang mencakup keduanya.
        """
        manager_user = self.make_own_scoped_user("mgr")
        manager = self.make_employee(user=manager_user)

        supervisor = self.make_employee(reports_to=manager)
        crew = self.make_employee(reports_to=supervisor)

        for target in (supervisor, crew):
            self.assertEqual(
                self.calendar(manager_user, target).status_code,
                200,
                f"{target.employee_number} seharusnya terbaca manajernya.",
            )

    def test_a_reporting_loop_does_not_hang_the_walk(self):
        """
        A→B→A pernah benar-benar ada di data organisasi. Penelusuran
        tanpa pagar akan berputar sampai kehabisan memori alih-alih
        melaporkan datanya yang salah.
        """
        first_user = self.make_own_scoped_user("loop")
        first = self.make_employee(user=first_user)

        second = self.make_employee(reports_to=first)

        organization = first.organization
        organization.reports_to = second
        organization.save(update_fields=["reports_to"])

        self.assertEqual(
            reporting_line.subordinate_ids(first_user),
            {second.pk},
        )

    def test_widening_never_resurrects_a_deleted_employee(self):
        """
        `|` menggabungkan kondisinya dengan OR, bukan menumpuknya. Meng-
        OR dengan queryset telanjang akan menghidupkan kembali baris
        yang sudah dibuang penyaring dasar — bocor lewat jalur yang
        justru ditambahkan untuk memperluas akses.
        """
        boss_user = self.make_own_scoped_user("spv.deleted")
        boss = self.make_employee(user=boss_user)

        gone = self.make_employee(reports_to=boss)

        gone.is_deleted = True
        gone.save(update_fields=["is_deleted"])

        base = Employee.objects.filter(is_deleted=False)

        widened = reporting_line.widen(
            base.filter(user_id=boss_user.pk),
            base=base,
            user=boss_user,
        )

        self.assertFalse(widened.filter(pk=gone.pk).exists())
        self.assertEqual(self.calendar(boss_user, gone).status_code, 400)

    def test_admin_section_is_bounded_by_its_organization_scope(self):
        role = Role.objects.create(
            code=f"SCP-CAL-ADMIN-{self._counter}", name="Admin Section Cal",
        )

        admin = self.make_user(
            "scope.cal.admin",
            roles=[role],
            scopes=[(role, "section", self.section_a.pk)],
        )

        mine = self.make_employee(section=self.section_a)
        theirs = self.make_employee(section=self.section_b)

        self.assertEqual(self.calendar(admin, mine).status_code, 200)
        self.assertEqual(self.calendar(admin, theirs).status_code, 400)

    def test_hr_without_restrictions_still_sees_everyone(self):
        """
        Yang ditambahkan hanya menambah. Kursi yang sudah boleh melihat
        semuanya tidak boleh ikut menyempit.
        """
        hr = self.make_user("scope.cal.hr", roles=[self.role_hr_admin])

        anyone = self.make_employee(section=self.section_b)

        self.assertEqual(self.calendar(hr, anyone).status_code, 200)

    def test_lookup_widens_only_when_it_is_asked_to(self):
        """
        Tanpa param, dropdown ini menghasilkan baris yang sama persis
        seperti sebelumnya — Employee Master, Org Chart, dan Reporting
        Line tidak ikut berubah.
        """
        boss_user = self.make_own_scoped_user("spv.lookup")
        boss = self.make_employee(user=boss_user)

        crew = self.make_employee(reports_to=boss)

        plain = self.lookup(boss_user)
        widened = self.lookup(boss_user, reporting_line="1")

        self.assertNotIn(crew.pk, plain)
        self.assertIn(crew.pk, widened)
        self.assertIn(boss.pk, widened)

    def test_a_misspelled_flag_does_not_widen(self):
        boss_user = self.make_own_scoped_user("spv.typo")
        self.make_employee(user=boss_user)

        crew = self.make_employee(
            reports_to=Employee.objects.get(user_id=boss_user.pk),
        )

        self.assertNotIn(
            crew.pk, self.lookup(boss_user, reporting_line="ya"),
        )
