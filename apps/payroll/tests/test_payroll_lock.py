"""
Tiga hal yang harus dibuktikan, bukan dijanjikan.

1. **Effective date** — payroll Juni memakai konfigurasi Juni walaupun
   konfigurasi Juli sudah ada di database.
2. **Immutability** — setiap jalur yang bisa mengubah hasil payroll yang
   sudah FINALIZED ditolak, satu per satu.
3. **Rekonsiliasi slip** — `Payslip` adalah salinan hasil run, bukan
   perhitungan kedua.

Fixture-nya dipakai ulang dari `test_payroll_flow` supaya keadaan
awalnya persis sama; kelas dasarnya sendiri tidak memuat test.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.hr.models import PayrollAssignment
from apps.payroll.models import (
    AllowanceTemplate,
    AllowanceTemplateLine,
    PayrollBasis,
    PayrollInput,
    PayrollInputStatus,
    PayrollInputType,
    PayrollRunComponent,
    PayrollRunEmployee,
    PayrollRunStatus,
    Payslip,
)
from apps.payroll.services import (
    PayrollInputService,
    PayrollPeriodService,
    PayrollRunEmployeeService,
    PayrollRunService,
    PayslipService,
)

from .test_payroll_flow import PayrollFlowTestCase


class PayrollLockTestCase(PayrollFlowTestCase):
    """
    Pembantu bersama: menjalankan satu run sampai FINALIZED.

    Persetujuannya **dilewati dengan menyetel status**, bukan lewat
    engine. Yang diuji di berkas ini penguncian dan snapshot; resolusi
    approver butuh pemegang role sungguhan dan diperagakan lewat
    `tenant_command payroll_uat --approve` di atas data demo.
    """

    def finalize_run(self, *, period, employees=None):
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        # Baris yang belum lengkap konfigurasinya dikeluarkan lebih
        # dulu — itu jalan keluar bisnisnya, dan tanpa itu Finalize
        # memang harus menolak.
        PayrollRunEmployee.objects.filter(
            run=run, payroll_assignment__isnull=True,
        ).update(
            is_excluded=True,
            status="excluded",
            exclusion_reason="Konfigurasi belum lengkap (fixture).",
        )

        PayrollRunService._refresh_totals(run=run)
        PayrollRunService.validate(run=run)
        PayrollRunService.acknowledge(run=run)

        run.refresh_from_db()
        run.status = PayrollRunStatus.APPROVED
        run.save(update_fields=["status"])

        PayrollRunService.finalize(run=run)

        run.refresh_from_db()

        return run


class EffectiveDateTest(PayrollLockTestCase):
    """
    Satu pegawai, dua konfigurasi, dua periode.

    Ini pertanyaan yang paling mudah dijawab salah oleh implementasi
    mana pun: begitu gaji naik, seluruh payroll lama ikut naik kalau
    yang dibaca `is_current`.
    """

    def make_july_period(self):
        self._counter += 1

        from apps.payroll.models import PayrollPeriod

        self.ensure_finance_calendar(date(2026, 7, 31))

        return PayrollPeriod.objects.create(
            company=self.company,
            payroll_group=self.payroll_group,
            code=f"2026-07-{self._counter}",
            name="Juli 2026",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 31),
            payment_date=date(2026, 8, 5),
            working_days=31,
        )

    def promote(self, employee, *, basic, template):
        """
        Kenaikan gaji lewat jalur resminya.

        `PayrollAssignmentService.create` menutup baris sebelumnya
        (`effective_to`, `is_current=False`) dan membuka yang baru —
        itu yang membuat riwayatnya berbentuk rentang, bukan satu baris
        yang ditimpa.
        """
        from apps.hr.api.payroll_assignment.services import (
            PayrollAssignmentService,
        )

        return PayrollAssignmentService.create(
            data={
                "employee": employee,
                "payroll_group": self.payroll_group,
                "currency": self.currency,
                "tax_status": self.tax_status,
                "overtime_eligible": False,
                "basic_salary": basic,
                "allowance_template": template,
                "deduction_template": self.deduction_template,
                "effective_from": date(2026, 7, 1),
            },
        )

    def test_periode_juni_memakai_konfigurasi_juni(self):
        employee = self.make_employee(basic_salary="10000000")
        self.make_attendance(employee, days=20)

        june = self.make_period()
        run = self.finalize_run(period=june)

        line = self.line_for(run, employee)

        self.assertEqual(line.basic_salary, Decimal("10000000.00"))

        # Kenaikan berlaku 1 Juli — sesudah periode Juni ditutup.
        self.promote(
            employee,
            basic=Decimal("20000000"),
            template=self.allowance_template,
        )

        line.refresh_from_db()

        self.assertEqual(line.basic_salary, Decimal("10000000.00"))

    def test_periode_juli_memakai_konfigurasi_juli(self):
        employee = self.make_employee(basic_salary="10000000")

        self.promote(
            employee,
            basic=Decimal("20000000"),
            template=self.allowance_template,
        )

        july = self.make_july_period()
        run = self.make_run(july)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        line = self.line_for(run, employee)

        self.assertEqual(line.basic_salary, Decimal("20000000.00"))

    def test_dua_periode_berdampingan_memakai_angkanya_masing_masing(self):
        """
        Bukti yang paling langsung: satu pegawai, dua run hidup
        berdampingan, dua angka berbeda — dan yang lama sudah terkunci.
        """
        employee = self.make_employee(basic_salary="10000000")
        self.make_attendance(employee, days=20)

        june = self.make_period()
        june_run = self.finalize_run(period=june)

        june_slip = Payslip.objects.get(run=june_run, employee=employee)
        june_net = june_slip.net_pay

        self.promote(
            employee,
            basic=Decimal("20000000"),
            template=self.allowance_template,
        )

        july = self.make_july_period()
        july_run = self.make_run(july)

        PayrollRunService.generate_employees(run=july_run)
        PayrollRunService.calculate(run=july_run)

        june_line = self.line_for(june_run, employee)
        july_line = self.line_for(july_run, employee)

        self.assertEqual(june_line.basic_salary, Decimal("10000000.00"))
        self.assertEqual(july_line.basic_salary, Decimal("20000000.00"))

        june_slip.refresh_from_db()

        self.assertEqual(june_slip.net_pay, june_net)

    def test_riwayat_assignment_berbentuk_rentang(self):
        employee = self.make_employee(basic_salary="10000000")

        self.promote(
            employee,
            basic=Decimal("20000000"),
            template=self.allowance_template,
        )

        rows = list(
            PayrollAssignment.objects
            .filter(employee=employee, is_deleted=False)
            .order_by("effective_from")
        )

        self.assertEqual(len(rows), 2)

        # Baris lama ditutup tepat sehari sebelum yang baru berlaku,
        # dan tidak lagi `is_current`.
        self.assertEqual(rows[0].effective_to, date(2026, 6, 30))
        self.assertFalse(rows[0].is_current)
        self.assertIsNone(rows[1].effective_to)
        self.assertTrue(rows[1].is_current)


class FinalizeImmutabilityTest(PayrollLockTestCase):
    """
    Setiap jalur yang bisa mengubah hasil payroll terkunci, dicoba satu
    per satu.

    Ditulis sebagai test terpisah per jalur, bukan satu test panjang:
    yang gagal harus menyebut jalur mana yang bocor, bukan cuma
    "immutability gagal".
    """

    def setUp(self):
        super().setUp()

        self.employee = self.make_employee(basic_salary="10000000")
        self.make_attendance(self.employee, days=20)

        self.period = self.make_period()

        self.input_row = PayrollInputService.create(
            data={
                "period": self.period,
                "employee": self.employee,
                "input_type": PayrollInputType.INCENTIVE,
                "code": "BONUS",
                "name": "Bonus",
                "amount": Decimal("1000000"),
                "status": PayrollInputStatus.CONFIRMED,
            },
        )

        self.run = self.finalize_run(period=self.period)
        self.line = self.line_for(self.run, self.employee)

    def test_run_terkunci_menolak_recalculate(self):
        with self.assertRaises(ValidationError):
            PayrollRunService.calculate(run=self.run)

    def test_run_terkunci_menolak_generate_ulang(self):
        with self.assertRaises(ValidationError):
            PayrollRunService.generate_employees(run=self.run)

    def test_run_terkunci_menolak_penyuntingan_dokumen(self):
        with self.assertRaises(ValidationError):
            PayrollRunService.update(
                instance=self.run,
                data={"name": "Diubah setelah final"},
            )

    def test_run_terkunci_menolak_penghapusan(self):
        with self.assertRaises(ValidationError):
            PayrollRunService.soft_delete(instance=self.run)

    def test_periode_terkunci_menolak_input_baru(self):
        self.period.refresh_from_db()

        with self.assertRaises(ValidationError):
            PayrollInputService.create(
                data={
                    "period": self.period,
                    "employee": self.employee,
                    "input_type": PayrollInputType.ADJUSTMENT,
                    "code": "LATE",
                    "name": "Koreksi terlambat",
                    "amount": Decimal("250000"),
                },
            )

    def test_periode_terkunci_menolak_perubahan_input(self):
        with self.assertRaises(ValidationError):
            PayrollInputService.update(
                instance=self.input_row,
                data={"amount": Decimal("9999999")},
            )

    def test_periode_terkunci_menolak_penghapusan_input(self):
        with self.assertRaises(ValidationError):
            PayrollInputService.soft_delete(instance=self.input_row)

    def test_periode_terkunci_menolak_penyuntingan_periode(self):
        self.period.refresh_from_db()

        with self.assertRaises(ValidationError):
            PayrollPeriodService.update(
                instance=self.period,
                data={"name": "Diubah setelah final"},
            )

    def test_baris_pegawai_terkunci_menolak_perubahan(self):
        with self.assertRaises(ValidationError):
            PayrollRunEmployeeService.update(
                instance=self.line,
                data={"notes": "Diubah setelah final"},
            )

    def test_baris_pegawai_tidak_bisa_dihapus(self):
        with self.assertRaises(ValidationError):
            PayrollRunEmployeeService.soft_delete(instance=self.line)

    def test_baris_pegawai_tidak_bisa_ditambah_manual(self):
        with self.assertRaises(ValidationError):
            PayrollRunEmployeeService.create(
                data={"run": self.run, "employee": self.employee},
            )

    def test_payslip_tidak_bisa_disunting(self):
        slip = Payslip.objects.get(run=self.run, employee=self.employee)

        with self.assertRaises(ValidationError):
            PayslipService.update(
                instance=slip,
                data={"net_pay": Decimal("1")},
            )

    def test_payslip_tidak_bisa_dihapus(self):
        slip = Payslip.objects.get(run=self.run, employee=self.employee)

        with self.assertRaises(ValidationError):
            PayslipService.soft_delete(instance=slip)

    def test_komponen_hasil_tidak_punya_jalur_tulis_api(self):
        """
        `PayrollRunComponent` tidak punya viewset sama sekali.

        Ia hanya diserialisasi **read-only** di dalam
        `PayrollRunEmployeeSerializer`. Jadi yang menjaganya bukan
        pemeriksaan status, melainkan ketiadaan endpoint — dan itu yang
        dijaga test ini: begitu ada yang mendaftarkan route-nya, test
        ini gagal dan penjagaannya harus dipikirkan lebih dulu.
        """
        from django.urls import NoReverseMatch, reverse

        with self.assertRaises(NoReverseMatch):
            reverse("payrollruncomponent-list")

        self.assertTrue(
            PayrollRunComponent.objects
            .filter(run_employee=self.line)
            .exists(),
        )

    def test_perubahan_master_tidak_mengubah_payroll_terkunci(self):
        slip = Payslip.objects.get(run=self.run, employee=self.employee)

        before_net = slip.net_pay
        before_basic = self.line.basic_salary
        before_components = {
            row.code: row.amount
            for row in self.line.components.all()
        }

        # Tunjangan dinaikkan sepuluh kali lipat...
        line = AllowanceTemplateLine.objects.get(
            template=self.allowance_template, code="TRANSPORT",
        )
        line.amount = Decimal("250000")
        line.save(update_fields=["amount"])

        # ...gaji pokoknya juga.
        assignment = PayrollAssignment.objects.get(
            employee=self.employee, is_current=True,
        )
        assignment.basic_salary = Decimal("100000000")
        assignment.save(update_fields=["basic_salary"])

        slip.refresh_from_db()
        self.line.refresh_from_db()

        self.assertEqual(slip.net_pay, before_net)
        self.assertEqual(self.line.basic_salary, before_basic)
        self.assertEqual(
            {row.code: row.amount for row in self.line.components.all()},
            before_components,
        )


class PayslipReconciliationTest(PayrollLockTestCase):
    """
    Slip = salinan hasil run, bukan perhitungan kedua.
    """

    def test_tiga_pegawai_cocok_sampai_rupiah_terakhir(self):
        employees = []

        for salary in ("8000000", "12500000", "17250000"):
            employee = self.make_employee(basic_salary=salary)
            self.make_attendance(employee, days=20)
            employees.append(employee)

        period = self.make_period()
        run = self.finalize_run(period=period)

        self.assertEqual(
            Payslip.objects.filter(run=run, is_deleted=False).count(),
            len(employees),
        )

        for employee in employees:
            line = self.line_for(run, employee)
            slip = Payslip.objects.get(run=run, employee=employee)

            self.assertEqual(slip.net_pay, line.net_pay)
            self.assertEqual(slip.gross_earning, line.gross_earning)
            self.assertEqual(slip.total_deduction, line.total_deduction)
            self.assertEqual(slip.tax_amount, line.tax_amount)
            self.assertEqual(slip.basic_salary, line.basic_salary)

    def test_komponen_slip_seluruhnya_dari_snapshot_run(self):
        employee = self.make_employee(basic_salary="12000000")
        self.make_attendance(employee, days=20)

        period = self.make_period()
        run = self.finalize_run(period=period)

        line = self.line_for(run, employee)
        slip = Payslip.objects.get(run=run, employee=employee)

        rows = list(line.components.all())

        earnings = {
            row["code"]: Decimal(row["amount"])
            for row in slip.snapshot["earnings"]
        }
        deductions = {
            row["code"]: Decimal(row["amount"])
            for row in slip.snapshot["deductions"]
        }

        self.assertEqual(
            earnings,
            {
                row.code: row.amount
                for row in rows
                if row.component_type == "earning"
            },
        )
        self.assertEqual(
            deductions,
            {
                row.code: row.amount
                for row in rows
                if row.component_type == "deduction"
            },
        )

        # Totalnya pun disalin, bukan dijumlahkan ulang di sisi slip.
        self.assertEqual(
            Decimal(slip.snapshot["totals"]["net_pay"]),
            line.net_pay,
        )

    def test_slip_tidak_menjalankan_mesin_hitung(self):
        """
        Snapshot slip tetap sama walau seluruh bahan perhitungannya
        dihapus.

        Kalau slip diam-diam menghitung ulang, membuang komponen dan
        input akan mengubah isinya. Ini cara paling langsung
        membuktikan ia tidak melakukannya.
        """
        employee = self.make_employee(basic_salary="9000000")
        self.make_attendance(employee, days=20)

        period = self.make_period()
        run = self.finalize_run(period=period)

        slip = Payslip.objects.get(run=run, employee=employee)

        before = slip.snapshot
        before_net = slip.net_pay

        PayrollInput.objects.filter(period=period).delete()
        AllowanceTemplate.objects.filter(
            pk=self.allowance_template.pk,
        ).update(is_active=False)

        slip.refresh_from_db()

        self.assertEqual(slip.snapshot, before)
        self.assertEqual(slip.net_pay, before_net)
        self.assertEqual(
            Decimal(slip.snapshot["totals"]["net_pay"]), before_net,
        )
