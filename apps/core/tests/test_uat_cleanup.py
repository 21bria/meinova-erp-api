"""
Pembuangan dataset UAT.

Satu kelas, satu schema tenant — membangun schema per kelas mahal, dan
`TenantTestCase` tidak merollback antar test. Konsekuensinya tiap test
membangun dataset-nya sendiri dengan **prefix nomor pegawai yang
berbeda**, lalu hanya menyentuh miliknya. Itu bukan kerapian belaka:
pemeriksaan "ada pegawai UAT di luar daftar sasaran" akan saling
menjatuhkan kalau dua test memakai prefix yang sama.
"""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal

from django_tenants.test.cases import TenantTestCase

from django.contrib.auth import get_user_model

from apps.administration.models import (
    Company,
    Currency,
    Department,
    LeaveType,
    Location,
    Notification,
    Section,
)
from apps.core.services.uat_cleanup import (
    UatCleanupAborted,
    UatCleanupService,
    UatCleanupSpec,
)
from apps.hr.models import (
    Employee,
    EmployeeAttendance,
    EmployeeLeave,
    EmployeeOvertime,
    EmploymentAssignment,
    OrganizationAssignment,
    PayrollAssignment,
)
from apps.notifications.models import NotificationLog
from apps.payroll.models import (
    AllowanceTemplate,
    DeductionTemplate,
    OvertimeGroup,
    PayrollGroup,
    PayrollInput,
    PayrollLeaveRule,
    PayrollPeriod,
    PayrollPolicy,
    PayrollRun,
    PayrollRunComponent,
    PayrollRunEmployee,
    Payslip,
)
from apps.workflow.models import (
    WorkflowApproval,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowStep,
)


class UatCleanupTestCase(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "uat-cleanup"
        tenant.name = "UAT Cleanup"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(code="UCL", name="Cleanup Co")

        cls.location = Location.objects.create(
            company=cls.company,
            code="UCL-HO",
            name="Head Office",
        )

        cls.currency = Currency.objects.create(
            code="IDR",
            name="Rupiah",
            symbol="Rp",
            is_base_currency=True,
        )

        cls.payroll_group = PayrollGroup.objects.create(
            code="UCL-MONTHLY",
            name="Monthly",
        )

        # Bel in-app selalu punya pemilik. Sengaja dibuat sebagai
        # pengguna biasa — bukan akun UAT — supaya test membuktikan
        # bahwa yang menentukan boleh-tidaknya dibuang adalah dokumen
        # yang ditunjuk, bukan siapa pemiliknya.
        cls.real_user = get_user_model().objects.create_user(
            username="cleanup-real-user",
            email="real@example.com",
            password="x",
        )

        cls.definition = WorkflowDefinition.objects.create(
            code="UCL-PAY-RUN",
            name="Payroll Run",
            module="payroll",
            document_type="payroll_run",
        )

        cls.step = WorkflowStep.objects.create(
            definition=cls.definition,
            name="Approval",
        )

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    def build_dataset(self, tag, *, finalized=False, employees=2):
        """
        Satu dataset UAT lengkap plus satu pegawai riil sebagai kontrol.

        Mengembalikan `(spec, kontrol)` — `kontrol` memuat ID data riil
        yang wajib tetap ada sesudah pembuangan.
        """

        prefix = f"UT{tag}"

        department = Department.objects.create(
            company=self.company,
            code=f"{prefix}-DEP",
            name="UAT Dept",
        )

        section = Section.objects.create(
            company=self.company,
            department=department,
            code=f"{prefix}-SEC",
            name="UAT Section",
        )

        leave_type = LeaveType.objects.create(
            code=f"{prefix}-LT",
            name="UAT Leave",
        )

        leave_rule = PayrollLeaveRule.objects.create(
            leave_type=leave_type,
            is_unpaid=True,
        )

        overtime_group = OvertimeGroup.objects.create(
            code=f"{prefix}-OT",
            name="UAT Overtime",
            hourly_multiplier=Decimal("1.5"),
            hourly_divisor=Decimal("173"),
        )

        allowance = AllowanceTemplate.objects.create(
            code=f"{prefix}-ALW",
            name="UAT Allowance",
        )

        deduction = DeductionTemplate.objects.create(
            code=f"{prefix}-DED",
            name="UAT Deduction",
        )

        policy = PayrollPolicy.objects.create(
            company=self.company,
            code=f"{prefix}-POL",
            name="UAT Policy",
        )

        period = PayrollPeriod.objects.create(
            company=self.company,
            payroll_group=self.payroll_group,
            code=f"{prefix}-2026-06",
            name="UAT June",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 30),
            payment_date=date(2026, 7, 5),
            working_days=30,
        )

        run = PayrollRun.objects.create(
            period=period,
            company=self.company,
            department=department,
            section=section,
            document_number=f"{prefix}-RUN-1",
            name="UAT Run",
            status="finalized" if finalized else "review",
        )

        uat_employees = []

        for index in range(employees):
            employee = Employee.objects.create(
                employee_number=f"{prefix}{index:03d}",
                first_name="UAT",
                last_name=f"Employee {index}",
            )

            OrganizationAssignment.objects.create(
                employee=employee,
                company=self.company,
                location=self.location,
                department=department,
                section=section,
                organization_effective_date=date(2026, 1, 1),
            )

            EmploymentAssignment.objects.create(
                employee=employee,
                join_date=date(2026, 1, 1),
            )

            PayrollAssignment.objects.create(
                employee=employee,
                payroll_group=self.payroll_group,
                currency=self.currency,
                basic_salary=Decimal("9000000"),
                overtime_group=overtime_group,
                allowance_template=allowance,
                deduction_template=deduction,
                payroll_policy=policy,
                effective_from=date(2026, 1, 1),
            )

            run_employee = PayrollRunEmployee.objects.create(
                run=run,
                employee=employee,
                department=department,
                section=section,
            )

            PayrollRunComponent.objects.create(
                run_employee=run_employee,
                component_type="BASIC_SALARY",
                source="master",
                code="BASIC",
                name="Basic Salary",
                amount=Decimal("9000000"),
            )

            Payslip.objects.create(
                run_employee=run_employee,
                run=run,
                period=period,
                employee=employee,
                department=department,
                section=section,
            )

            PayrollInput.objects.create(
                period=period,
                employee=employee,
            )

            EmployeeAttendance.objects.create(
                employee=employee,
                company=self.company,
                work_date=date(2026, 6, 1),
            )

            EmployeeLeave.objects.create(
                employee=employee,
                leave_type=leave_type,
                start_date=date(2026, 6, 10),
                end_date=date(2026, 6, 11),
            )

            EmployeeOvertime.objects.create(
                employee=employee,
                work_date=date(2026, 6, 12),
                start_time=time(18, 0),
                end_time=time(20, 0),
            )

            uat_employees.append(employee)

        instance = WorkflowInstance.objects.create(
            definition=self.definition,
            module="payroll",
            document_type="payroll_run",
            object_id=str(run.pk),
            document_number=run.document_number,
            status="approved",
        )

        approval = WorkflowApproval.objects.create(
            instance=instance,
            step=self.step,
            status="approved",
        )

        log = NotificationLog.objects.create(
            event="workflow.approved",
            channel="email",
            module="payroll",
            object_type="payroll-payroll_run",
            object_id=str(run.pk),
        )

        # Bel in-app untuk run UAT — milik pengguna riil, menunjuk
        # dokumen UAT. Inilah yang harus ikut terbuang.
        uat_bell = Notification.objects.create(
            user=self.real_user,
            title="Disetujui: Payroll UAT",
            module="payroll",
            object_type="payroll-payroll_run",
            object_id=str(run.pk),
        )

        # Bel dengan object_type lain tapi object_id angka yang sama.
        # Membuktikan penyaringnya membedakan jenis, bukan cuma nomor.
        other_type_bell = Notification.objects.create(
            user=self.real_user,
            title="Employee action",
            module="hr",
            object_type="hr-employee_action",
            object_id=str(run.pk),
        )

        control = self.build_control(tag)

        # Bel untuk run NON-UAT. Tidak boleh tersentuh.
        control_bell = Notification.objects.create(
            user=self.real_user,
            title="Disetujui: Payroll riil",
            module="payroll",
            object_type="payroll-payroll_run",
            object_id=str(control["run_id"]),
        )

        control["uat_bell_id"] = uat_bell.pk
        control["other_type_bell_id"] = other_type_bell.pk
        control["control_bell_id"] = control_bell.pk

        spec = UatCleanupSpec(
            employee_ids=tuple(e.pk for e in uat_employees),
            run_ids=(run.pk,),
            period_ids=(period.pk,),
            workflow_instance_ids=(instance.pk,),
            workflow_approval_ids=(approval.pk,),
            notification_log_ids=(log.pk,),
            leave_rule_ids=(leave_rule.pk,),
            leave_type_ids=(leave_type.pk,),
            overtime_group_ids=(overtime_group.pk,),
            allowance_template_ids=(allowance.pk,),
            deduction_template_ids=(deduction.pk,),
            payroll_policy_ids=(policy.pk,),
            section_ids=(section.pk,),
            department_ids=(department.pk,),
            employee_number_prefix=prefix,
            expected_company_id=self.company.pk,
            expected_department_id=department.pk,
            protected_employee_ids=(control["employee_id"],),
            protected_run_ids=(control["run_id"],),
            protected_period_ids=(control["period_id"],),
            protected_leave_type_ids=(control["leave_type_id"],),
            protected_workflow_definition_ids=(self.definition.pk,),
        )

        return spec, control

    def build_control(self, tag):
        """Data 'riil' yang tidak boleh tersentuh sama sekali."""

        prefix = f"RL{tag}"

        department = Department.objects.create(
            company=self.company,
            code=f"{prefix}-DEP",
            name="Real Dept",
        )

        leave_type = LeaveType.objects.create(
            code=f"{prefix}-LT",
            name="Cuti Tahunan",
        )

        employee = Employee.objects.create(
            employee_number=f"{prefix}001",
            first_name="Real",
            last_name="Employee",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=self.company,
            location=self.location,
            department=department,
            organization_effective_date=date(2026, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=date(2026, 1, 1),
        )

        EmployeeAttendance.objects.create(
            employee=employee,
            company=self.company,
            work_date=date(2026, 6, 1),
        )

        period = PayrollPeriod.objects.create(
            company=self.company,
            payroll_group=self.payroll_group,
            code=f"{prefix}-2026-08",
            name="Real August",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            payment_date=date(2026, 9, 5),
            working_days=30,
        )

        run = PayrollRun.objects.create(
            period=period,
            company=self.company,
            department=department,
            document_number=f"{prefix}-RUN-1",
            name="Real Run",
            status="review",
        )

        run_employee = PayrollRunEmployee.objects.create(
            run=run,
            employee=employee,
            department=department,
        )

        return {
            "employee_id": employee.pk,
            "run_id": run.pk,
            "period_id": period.pk,
            "department_id": department.pk,
            "leave_type_id": leave_type.pk,
            "run_employee_id": run_employee.pk,
        }

    # ------------------------------------------------------------------
    # 1 — mode bawaan tidak menulis
    # ------------------------------------------------------------------

    def test_plan_tidak_menghapus_apa_pun(self):
        spec, control = self.build_dataset("A")

        before = {
            "employee": Employee.objects.count(),
            "run": PayrollRun.objects.count(),
            "attendance": EmployeeAttendance.objects.count(),
            "component": PayrollRunComponent.objects.count(),
            "bell": Notification.objects.count(),
        }

        report = UatCleanupService.plan(spec=spec)

        self.assertFalse(report.is_blocked, report.blockers)
        self.assertFalse(report.executed)
        self.assertEqual(report.deleted, {})
        self.assertEqual(report.planned["hr.Employee"], 2)
        self.assertEqual(report.planned["administration.Notification"], 1)

        # Mode kering tidak boleh menyentuh bel siapa pun.
        self.assertEqual(Notification.objects.count(), before["bell"])

        self.assertEqual(Employee.objects.count(), before["employee"])
        self.assertEqual(PayrollRun.objects.count(), before["run"])
        self.assertEqual(
            EmployeeAttendance.objects.count(),
            before["attendance"],
        )
        self.assertEqual(
            PayrollRunComponent.objects.count(),
            before["component"],
        )

        # Panggil dua kali: perhitungan rencana tidak boleh punya efek
        # samping yang baru terlihat pada panggilan berikutnya.
        again = UatCleanupService.plan(spec=spec)

        self.assertEqual(again.planned, report.planned)

    # ------------------------------------------------------------------
    # 2 & 5 — hanya cakupan UAT yang hilang
    # ------------------------------------------------------------------

    def test_execute_hanya_membuang_cakupan_uat(self):
        spec, control = self.build_dataset("B")

        report = UatCleanupService.execute(spec=spec)

        self.assertTrue(report.executed)
        self.assertEqual(report.deleted["hr.Employee"], 2)
        self.assertEqual(report.deleted["payroll.PayrollRun"], 1)
        self.assertEqual(report.deleted["payroll.PayrollRunComponent"], 2)
        self.assertEqual(report.deleted["hr.EmployeeAttendance"], 2)
        self.assertEqual(report.deleted["hr.EmployeeLeave"], 2)
        self.assertEqual(report.deleted["hr.EmployeeOvertime"], 2)
        self.assertEqual(report.deleted["workflow.WorkflowInstance"], 1)
        self.assertEqual(report.deleted["workflow.WorkflowApproval"], 1)
        self.assertEqual(
            report.deleted["notifications.NotificationLog"],
            1,
        )
        self.assertEqual(report.deleted["administration.Department"], 1)
        self.assertEqual(report.deleted["payroll.PayrollPolicy"], 1)
        self.assertEqual(report.deleted["administration.Notification"], 1)

        # Cakupan UAT benar-benar hilang.
        self.assertFalse(
            Employee.objects.filter(pk__in=spec.employee_ids).exists(),
        )
        self.assertFalse(
            PayrollRun.objects.filter(pk__in=spec.run_ids).exists(),
        )
        self.assertFalse(
            PayrollPeriod.objects.filter(pk__in=spec.period_ids).exists(),
        )
        self.assertFalse(
            LeaveType.objects.filter(pk__in=spec.leave_type_ids).exists(),
        )
        self.assertFalse(
            Payslip.objects.filter(run_id__in=spec.run_ids).exists(),
        )
        self.assertFalse(
            PayrollInput.objects.filter(
                employee_id__in=spec.employee_ids,
            ).exists(),
        )

        # Data riil utuh — termasuk yang ID-nya bertetangga.
        self.assertTrue(
            Employee.objects.filter(pk=control["employee_id"]).exists(),
        )
        self.assertTrue(
            PayrollRun.objects.filter(pk=control["run_id"]).exists(),
        )
        self.assertTrue(
            PayrollPeriod.objects.filter(
                pk=control["period_id"],
            ).exists(),
        )
        self.assertTrue(
            Department.objects.filter(
                pk=control["department_id"],
            ).exists(),
        )
        self.assertTrue(
            LeaveType.objects.filter(
                pk=control["leave_type_id"],
            ).exists(),
        )
        self.assertTrue(
            PayrollRunEmployee.objects.filter(
                pk=control["run_employee_id"],
            ).exists(),
        )
        self.assertTrue(
            EmployeeAttendance.objects.filter(
                employee_id=control["employee_id"],
            ).exists(),
        )

        # Konfigurasi bersama tidak ikut terbawa.
        self.assertTrue(
            WorkflowDefinition.objects.filter(
                pk=self.definition.pk,
            ).exists(),
        )
        self.assertTrue(
            PayrollGroup.objects.filter(
                pk=self.payroll_group.pk,
            ).exists(),
        )
        self.assertTrue(
            Location.objects.filter(pk=self.location.pk).exists(),
        )

    # ------------------------------------------------------------------
    # 3 — jalan kedua aman
    # ------------------------------------------------------------------

    def test_execute_kedua_kali_idempoten(self):
        spec, control = self.build_dataset("C")

        first = UatCleanupService.execute(spec=spec)

        self.assertGreater(first.deleted_total, 0)

        second = UatCleanupService.execute(spec=spec)

        self.assertTrue(second.executed)
        self.assertFalse(second.is_blocked, second.blockers)
        self.assertEqual(second.deleted_total, 0)
        self.assertEqual(second.planned_total, 0)

        self.assertTrue(
            Employee.objects.filter(pk=control["employee_id"]).exists(),
        )

    # ------------------------------------------------------------------
    # 4 — run FINALIZED hanya lewat eksekusi maintenance yang eksplisit
    # ------------------------------------------------------------------

    def test_run_finalized_dibuang_sebagai_pengecualian(self):
        spec, control = self.build_dataset("D", finalized=True)

        run_id = spec.run_ids[0]

        plan = UatCleanupService.plan(spec=spec)

        # Mode kering menyatakan pengecualiannya, dan tidak menyentuh
        # baris FINALIZED itu sama sekali.
        self.assertTrue(plan.finalized_runs)
        self.assertIn(f"run id={run_id}", plan.finalized_runs[0])
        self.assertIn("status=finalized", plan.finalized_runs[0])

        still_there = PayrollRun.objects.get(pk=run_id)

        self.assertEqual(still_there.status, "finalized")

        report = UatCleanupService.execute(spec=spec)

        self.assertTrue(report.finalized_runs)
        self.assertEqual(report.deleted["payroll.PayrollRun"], 1)
        self.assertFalse(PayrollRun.objects.filter(pk=run_id).exists())

    def test_lifecycle_run_finalized_tidak_pernah_disentuh(self):
        spec, control = self.build_dataset("E", finalized=True)

        run_id = spec.run_ids[0]
        period_id = spec.period_ids[0]

        before_run = PayrollRun.objects.filter(pk=run_id).values(
            "status",
            "finalized_at",
            "finalized_by_id",
        )[0]
        before_period = PayrollPeriod.objects.filter(
            pk=period_id,
        ).values("status")[0]

        UatCleanupService.plan(spec=spec)

        after_run = PayrollRun.objects.filter(pk=run_id).values(
            "status",
            "finalized_at",
            "finalized_by_id",
        )[0]
        after_period = PayrollPeriod.objects.filter(
            pk=period_id,
        ).values("status")[0]

        self.assertEqual(before_run, after_run)
        self.assertEqual(before_period, after_period)

        UatCleanupService.execute(spec=spec)

        # Tidak ada run Correction yang lahir diam-diam.
        self.assertFalse(
            PayrollRun.objects.filter(
                document_number__icontains="UTE",
            ).exists(),
        )

    # ------------------------------------------------------------------
    # 6 — dependency tak terduga membatalkan sebelum menghapus
    # ------------------------------------------------------------------

    def test_dependency_tak_terduga_membatalkan_sebelum_hapus(self):
        spec, control = self.build_dataset("F")

        # Seorang pegawai riil kini melapor ke pegawai UAT. Relasi
        # `reports_to` tidak pernah muncul di audit, dan membuang
        # atasannya akan meninggalkan penempatan yatim — persis jenis
        # temuan yang harus menghentikan operasi, bukan diteruskan.
        OrganizationAssignment.objects.filter(
            employee_id=control["employee_id"],
        ).update(reports_to_id=spec.employee_ids[0])

        plan = UatCleanupService.plan(spec=spec)

        self.assertTrue(plan.is_blocked)
        self.assertTrue(
            any(
                "DEPENDENCY BARU" in blocker
                and "reports_to" in blocker
                for blocker in plan.blockers
            ),
            plan.blockers,
        )

        with self.assertRaises(UatCleanupAborted):
            UatCleanupService.execute(spec=spec)

        # Rollback penuh: tidak satu baris pun hilang.
        self.assertEqual(
            Employee.objects.filter(pk__in=spec.employee_ids).count(),
            len(spec.employee_ids),
        )
        self.assertTrue(
            PayrollRun.objects.filter(pk__in=spec.run_ids).exists(),
        )
        self.assertTrue(
            PayrollRunComponent.objects.filter(
                run_employee__run_id__in=spec.run_ids,
            ).exists(),
        )

    def test_pegawai_non_uat_di_dalam_run_membatalkan(self):
        spec, control = self.build_dataset("G")

        PayrollRunEmployee.objects.create(
            run_id=spec.run_ids[0],
            employee_id=control["employee_id"],
        )

        plan = UatCleanupService.plan(spec=spec)

        self.assertTrue(plan.is_blocked)
        self.assertTrue(
            any("CAKUPAN" in blocker for blocker in plan.blockers),
            plan.blockers,
        )

        with self.assertRaises(UatCleanupAborted):
            UatCleanupService.execute(spec=spec)

        self.assertTrue(
            Employee.objects.filter(pk=control["employee_id"]).exists(),
        )
        self.assertEqual(
            Employee.objects.filter(pk__in=spec.employee_ids).count(),
            len(spec.employee_ids),
        )

    def test_provenance_berubah_membatalkan(self):
        spec, control = self.build_dataset("H")

        # ID-nya sama, tapi isinya sudah bukan pegawai UAT lagi.
        Employee.objects.filter(pk=spec.employee_ids[0]).update(
            employee_number="REAL999",
        )

        plan = UatCleanupService.plan(spec=spec)

        self.assertTrue(plan.is_blocked)
        self.assertTrue(
            any("PROVENANCE" in blocker for blocker in plan.blockers),
            plan.blockers,
        )

        with self.assertRaises(UatCleanupAborted):
            UatCleanupService.execute(spec=spec)

        self.assertEqual(
            Employee.objects.filter(pk__in=spec.employee_ids).count(),
            len(spec.employee_ids),
        )

    def test_catatan_kejadian_salah_sasaran_membatalkan(self):
        spec, control = self.build_dataset("I")

        # Log yang sebenarnya menunjuk run riil tidak boleh ikut dibuang
        # hanya karena ID-nya terdaftar.
        NotificationLog.objects.filter(
            pk__in=spec.notification_log_ids,
        ).update(object_id=str(control["run_id"]))

        plan = UatCleanupService.plan(spec=spec)

        self.assertTrue(plan.is_blocked)
        self.assertTrue(
            any(
                "PROVENANCE" in blocker and "notification" in blocker
                for blocker in plan.blockers
            ),
            plan.blockers,
        )

        with self.assertRaises(UatCleanupAborted):
            UatCleanupService.execute(spec=spec)

        self.assertTrue(
            NotificationLog.objects.filter(
                pk__in=spec.notification_log_ids,
            ).exists(),
        )

    # ------------------------------------------------------------------
    # Bel in-app — tabel terpisah dari log pengiriman
    # ------------------------------------------------------------------

    def test_bel_inapp_run_uat_ikut_dibuang(self):
        spec, control = self.build_dataset("J")

        UatCleanupService.execute(spec=spec)

        # (1) bel untuk run UAT hilang
        self.assertFalse(
            Notification.objects.filter(
                pk=control["uat_bell_id"],
            ).exists(),
        )

        # (2) bel untuk run NON-UAT tetap ada
        self.assertTrue(
            Notification.objects.filter(
                pk=control["control_bell_id"],
            ).exists(),
        )

        # (4) object_type lain tidak tersentuh, walau object_id-nya
        # angka yang sama persis dengan run UAT
        self.assertTrue(
            Notification.objects.filter(
                pk=control["other_type_bell_id"],
            ).exists(),
        )

    def test_bel_milik_user_riil_dibuang_hanya_karena_dokumennya(self):
        """
        (3) Pemiliknya tidak menentukan apa-apa.

        Ketiga bel di fixture ini milik pengguna riil yang sama. Yang
        satu terbuang, dua lainnya tidak — pembedanya semata dokumen
        yang ditunjuk.
        """

        spec, control = self.build_dataset("K")

        owner = self.real_user.pk
        bells = Notification.objects.filter(user_id=owner)

        self.assertEqual(
            bells.filter(
                pk__in=[
                    control["uat_bell_id"],
                    control["control_bell_id"],
                    control["other_type_bell_id"],
                ],
            ).count(),
            3,
        )

        UatCleanupService.execute(spec=spec)

        survivors = set(
            Notification.objects.filter(
                pk__in=[
                    control["uat_bell_id"],
                    control["control_bell_id"],
                    control["other_type_bell_id"],
                ],
            ).values_list("pk", flat=True),
        )

        self.assertEqual(
            survivors,
            {control["control_bell_id"], control["other_type_bell_id"]},
        )

        # Penggunanya sendiri tidak ikut terbawa.
        self.assertTrue(
            get_user_model().objects.filter(pk=owner).exists(),
        )

    def test_bel_inapp_idempoten(self):
        """(6) Jalan kedua tetap nol, tanpa galat."""

        spec, control = self.build_dataset("L")

        first = UatCleanupService.execute(spec=spec)

        self.assertEqual(first.deleted["administration.Notification"], 1)

        second = UatCleanupService.execute(spec=spec)

        self.assertFalse(second.is_blocked, second.blockers)
        self.assertEqual(second.deleted["administration.Notification"], 0)
        self.assertEqual(second.planned_total, 0)

        self.assertTrue(
            Notification.objects.filter(
                pk=control["control_bell_id"],
            ).exists(),
        )

    def test_labels_mempersempit_hapus_bukan_pemeriksaan(self):
        """
        Jalan terarah: hanya bel yang dibuang, sisanya utuh.

        Ini jalur yang dipakai untuk susulan sesudah pembuangan utama
        selesai — dan ia tetap menjalankan preflight penuh.
        """

        spec, control = self.build_dataset("M")

        report = UatCleanupService.execute(
            spec=spec,
            labels={"administration.Notification"},
        )

        self.assertEqual(report.deleted["administration.Notification"], 1)
        self.assertNotIn("hr.Employee", report.deleted)

        # Bel UAT hilang...
        self.assertFalse(
            Notification.objects.filter(
                pk=control["uat_bell_id"],
            ).exists(),
        )

        # ...sementara seluruh dataset UAT lainnya masih berdiri.
        self.assertEqual(
            Employee.objects.filter(pk__in=spec.employee_ids).count(),
            len(spec.employee_ids),
        )
        self.assertTrue(
            PayrollRun.objects.filter(pk__in=spec.run_ids).exists(),
        )
