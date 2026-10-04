"""
Business Decision #5 — beban perusahaan dipisahkan dari potongan pegawai.

Yang diputuskan: iuran yang **dibayar perusahaan** (porsi pemberi kerja
BPJS dan sejenisnya) adalah sumbu ketiga, bukan potongan bertanda. Ia
tidak mengurangi yang diterima pegawai, tidak menambah gross, dan tidak
menyentuh dasar pajak pegawai — sementara biaya tenaga kerja tidak
lengkap tanpanya:

    Total Payroll Cost = gross_earning + employer_contribution

Sebagian besar berkas ini ada untuk membuktikan hal yang **tidak**
terjadi. Kegagalan yang ditakutkan di sini semuanya diam: iuran
perusahaan yang ikut terjumlah jadi potongan tetap menghasilkan slip
yang terlihat masuk akal — pegawainya saja yang dibayar kurang. Karena
itu tiap invariannya diuji sebagai angka, bukan sebagai ada/tidaknya
kolom.

Fixture-nya menumpang `PayrollFlowTestCase`, sama seperti seluruh test
payroll lain, supaya keadaan awalnya persis sama.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.payroll.models import (
    DeductionTemplateLine,
    PayrollBasis,
    PayrollComponentType,
    PayrollRunComponent,
)
from apps.payroll.services import PayrollRunService

from .test_payroll_flow import PayrollFlowTestCase


class EmployerContributionTestCase(PayrollFlowTestCase):
    """Satu pegawai, satu periode, satu iuran perusahaan."""

    EMPLOYER_RATE = Decimal("4")

    def setUp(self):
        super().setUp()

        # Pegawainya dibuat per test, bukan sekali di kelas: run
        # menarik **seluruh** pegawai aktif, dan `TenantTestCase` tidak
        # me-rollback antar test — pegawai test sebelumnya masih ada.
        self.employee = self.make_employee()

    def add_employer_line(self, *, rate=None, **overrides):
        """
        Porsi pemberi kerja JHT — persentase gaji pokok, seperti aslinya.

        Angkanya **bukan** kebijakan: besaran BPJS sungguhan masih
        Business Decision #3 dan sengaja belum ditulis di mana pun.
        Yang diuji di sini perilaku sumbunya, bukan tarifnya.
        """
        payload = {
            "template": self.deduction_template,
            "code": "BPJS-JHT-ER",
            "name": "BPJS JHT (Perusahaan)",
            "sequence": 90,
            "basis": PayrollBasis.PERCENT_OF_BASIC,
            "rate": rate if rate is not None else self.EMPLOYER_RATE,
            "is_employer_cost": True,
        }
        payload.update(overrides)

        return DeductionTemplateLine.objects.create(**payload)

    def calculated_line(self, period):
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        return run, self.line_for(run, self.employee)


class EmployerContributionCalculationTest(EmployerContributionTestCase):
    """
    A. Angkanya lahir, dan lahir di sisinya sendiri.
    """

    def test_iuran_perusahaan_jadi_komponen_bertipe_sendiri(self):
        self.add_employer_line()

        _, line = self.calculated_line(self.make_period())

        component = self.component(line, "BPJS-JHT-ER")

        self.assertEqual(
            component.component_type,
            PayrollComponentType.EMPLOYER_CONTRIBUTION,
        )

        # 4% dari gaji pokok yang terhitung periode itu.
        self.assertEqual(
            component.amount,
            (line.basic_salary * self.EMPLOYER_RATE / Decimal("100"))
            .quantize(Decimal("0.01")),
        )

    def test_employer_contribution_menjumlah_komponennya(self):
        self.add_employer_line()
        self.add_employer_line(
            code="BPJS-JKK-ER",
            name="BPJS JKK (Perusahaan)",
            sequence=91,
            basis=PayrollBasis.FIXED,
            rate=Decimal("0"),
            amount=Decimal("24000"),
        )

        _, line = self.calculated_line(self.make_period())

        total = sum(
            item.amount
            for item in line.components.filter(
                component_type=PayrollComponentType.EMPLOYER_CONTRIBUTION,
            )
        )

        self.assertEqual(line.employer_contribution, total)
        self.assertEqual(
            line.employer_contribution,
            self.component(line, "BPJS-JHT-ER").amount + Decimal("24000"),
        )


class EmployerContributionDoesNotTouchEmployeePayTest(
    EmployerContributionTestCase,
):
    """
    B. Inti keputusan ini: yang diterima pegawai tidak bergerak.

    Diuji sebagai **perbandingan sebelum/sesudah pada run yang sama** —
    bukan dengan mengecek bahwa satu angka "kelihatan benar". Satu-
    satunya bukti yang tidak bisa ditawar bahwa iuran perusahaan tidak
    menyentuh gaji pegawai adalah net yang identik dengan hitungan
    ketika barisnya belum ada.
    """

    def before_and_after(self):
        """
        Run yang **sama** dihitung dua kali, bukan dua periode berbeda.

        Perbandingan antar periode menanggung selisih yang tidak ada
        hubungannya dengan keputusan ini; satu run yang dihitung ulang
        hanya berbeda pada satu hal, yaitu barisnya.
        """
        run = self.make_run(self.make_period())

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        line = self.line_for(run, self.employee)

        before = {
            "net_pay": line.net_pay,
            "gross_earning": line.gross_earning,
            "total_deduction": line.total_deduction,
            "taxable_earning": line.taxable_earning,
            "tax_amount": line.tax_amount,
        }

        self.add_employer_line()

        PayrollRunService.calculate(run=run)

        return before, self.line_for(run, self.employee)

    def test_net_gross_dan_potongan_tidak_bergerak(self):
        before, after = self.before_and_after()

        self.assertEqual(after.net_pay, before["net_pay"])
        self.assertEqual(after.gross_earning, before["gross_earning"])
        self.assertEqual(after.total_deduction, before["total_deduction"])

        # Dan iurannya memang ada — kalau tidak, test di atas lulus
        # karena barisnya tidak pernah terhitung sama sekali.
        self.assertGreater(after.employer_contribution, Decimal("0"))

    def test_dasar_pajak_dan_pph21_tidak_bergerak(self):
        """
        Iuran perusahaan bukan potongan pegawai, jadi ia tidak boleh
        mengurangi dasar PPh21 — juga tidak boleh menambahnya.

        Kalau perusahaan memutuskan premi JKK/JKM yang dibayarnya
        adalah penghasilan pegawai yang kena pajak, itu keputusan
        tersendiri yang belum diambil; lihat `payroll.md`.
        """
        before, after = self.before_and_after()

        self.assertEqual(after.taxable_earning, before["taxable_earning"])
        self.assertEqual(after.tax_amount, before["tax_amount"])

    def test_net_tetap_gross_dikurangi_potongan(self):
        self.add_employer_line()

        _, line = self.calculated_line(self.make_period())

        self.assertEqual(
            line.net_pay,
            line.gross_earning - line.total_deduction,
        )


class EmployerContributionTotalsTest(EmployerContributionTestCase):
    """
    C. Total run dan biaya payroll.
    """

    def test_total_run_menjumlah_beban_perusahaan(self):
        self.add_employer_line()

        run, line = self.calculated_line(self.make_period())

        PayrollRunService._refresh_totals(run=run)
        run.refresh_from_db()

        # Dijumlah dari barisnya, bukan dibandingkan dengan satu
        # pegawai: run menarik seluruh pegawai aktif, dan test
        # sebelumnya meninggalkan pegawainya di tenant yang sama.
        lines = run.employees.filter(is_deleted=False, is_excluded=False)

        def total_of(field):
            return sum(
                (getattr(item, field) for item in lines),
                Decimal("0"),
            )

        self.assertEqual(
            run.total_employer_contribution,
            total_of("employer_contribution"),
        )

        self.assertGreater(line.employer_contribution, Decimal("0"))

        # Dan tidak menyelinap ke total lain.
        self.assertEqual(run.total_earning, total_of("gross_earning"))
        self.assertEqual(run.total_deduction, total_of("total_deduction"))
        self.assertEqual(run.total_net, total_of("net_pay"))

    def test_total_payroll_cost_di_atas_gross_bukan_net(self):
        """
        `Gross + Employer`, bukan `Net + Employer`.

        Kekeliruan yang paling mudah dibuat sekaligus paling mahal:
        pajak dan iuran pegawai tetap dibayarkan perusahaan ke pihak
        ketiga, jadi biaya sesungguhnya justru **di atas** gross.
        """
        self.add_employer_line()

        run, line = self.calculated_line(self.make_period())

        PayrollRunService._refresh_totals(run=run)
        run.refresh_from_db()

        cost = run.total_earning + run.total_employer_contribution

        self.assertGreater(cost, run.total_earning)
        self.assertGreater(cost, run.total_net)


class EmployerContributionValidationTest(EmployerContributionTestCase):
    """
    D. Yang ditolak, bukan diperbaiki diam-diam.
    """

    def test_reduces_taxable_ditolak_pada_beban_perusahaan(self):
        line = DeductionTemplateLine(
            template=self.deduction_template,
            code="BPJS-JHT-ER-BAD",
            name="Salah konfigurasi",
            sequence=95,
            basis=PayrollBasis.PERCENT_OF_BASIC,
            rate=Decimal("4"),
            is_employer_cost=True,
            reduces_taxable=True,
        )

        with self.assertRaises(ValidationError) as raised:
            line.full_clean()

        self.assertIn("reduces_taxable", raised.exception.message_dict)

    def test_pph21_ditolak_sebagai_beban_perusahaan(self):
        line = DeductionTemplateLine(
            template=self.deduction_template,
            code="PPH21-ER-BAD",
            name="Salah konfigurasi",
            sequence=96,
            basis=PayrollBasis.PPH21_PROGRESSIVE,
            is_employer_cost=True,
        )

        with self.assertRaises(ValidationError) as raised:
            line.full_clean()

        self.assertIn("basis", raised.exception.message_dict)

    def test_baris_lama_yang_terlanjur_tersimpan_tetap_tidak_mengurangi_pajak(
        self,
    ):
        """
        Validasi menjaga pintu masuk; mesin hitung menjaga hasilnya.

        Baris yang sudah tersimpan sebelum aturan ini ada tidak pernah
        lewat `full_clean()` lagi — dan yang lolos di sini mengurangi
        pajak pegawai dengan iuran yang tidak pernah dipotong darinya.
        """
        run = self.make_run(self.make_period())

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        before_tax = self.line_for(run, self.employee).tax_amount

        line = self.add_employer_line()

        # Menembus validasi, persis seperti baris warisan.
        DeductionTemplateLine.objects.filter(pk=line.pk).update(
            reduces_taxable=True,
        )

        PayrollRunService.calculate(run=run)

        after = self.line_for(run, self.employee)
        component = self.component(after, "BPJS-JHT-ER")

        self.assertFalse(component.reduces_taxable)
        self.assertEqual(after.tax_amount, before_tax)


class EmployerContributionPayslipTest(EmployerContributionTestCase):
    """
    E. Slip: terlihat, tapi tidak di antara potongan.
    """

    def test_snapshot_memisahkan_iuran_perusahaan_dari_potongan(self):
        from apps.payroll.services import PayslipService

        self.add_employer_line()

        run, line = self.calculated_line(self.make_period())

        snapshot = PayslipService.build_snapshot(run=run, line=line)

        codes = {row["code"] for row in snapshot["deductions"]}

        self.assertNotIn("BPJS-JHT-ER", codes)

        self.assertEqual(
            {row["code"] for row in snapshot["employer_contributions"]},
            {"BPJS-JHT-ER"},
        )

    def test_jumlah_baris_potongan_masih_sama_dengan_total_deduction(self):
        """
        Bukti bahwa daftar potongan pada slip tetap bisa dijumlah
        tangan dan cocok dengan totalnya.
        """
        from apps.payroll.services import PayslipService

        self.add_employer_line()

        run, line = self.calculated_line(self.make_period())

        snapshot = PayslipService.build_snapshot(run=run, line=line)

        total = sum(
            Decimal(row["amount"]) for row in snapshot["deductions"]
        )

        self.assertEqual(total, line.total_deduction)
        self.assertEqual(
            Decimal(snapshot["totals"]["employer_contribution"]),
            line.employer_contribution,
        )
        self.assertEqual(
            Decimal(snapshot["totals"]["total_payroll_cost"]),
            line.gross_earning + line.employer_contribution,
        )


class EmployerContributionSummaryTest(EmployerContributionTestCase):
    """
    F. Rekap run memisahkannya juga.
    """

    def test_komponen_tidak_bocor_ke_daftar_potongan_rekap(self):
        self.add_employer_line()

        run, _ = self.calculated_line(self.make_period())

        rows = (
            PayrollRunComponent.objects
            .filter(
                is_deleted=False,
                run_employee__run=run,
                component_type=PayrollComponentType.DEDUCTION,
            )
            .values_list("code", flat=True)
        )

        self.assertNotIn("BPJS-JHT-ER", set(rows))
