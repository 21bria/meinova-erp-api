"""
Mesin hitung payroll, tanpa menyentuh database sama sekali.

`SimpleTestCase` disengaja dan itu properti yang harus dijaga:
`PayrollCalculationService` menerima seluruh bahannya lewat
`CalculationInput` dan tidak boleh menerbitkan satu query pun. Begitu
ada yang menambahkan pembacaan ORM di dalamnya, berkas ini yang pertama
gagal.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.test import SimpleTestCase

from apps.payroll.models import (
    PayrollBasis,
    PayrollComponentType,
    PayrollFindingLevel,
)
from apps.payroll.services.calculation import (
    CalculationInput,
    PayrollCalculationService,
)


ZERO = Decimal("0.00")


@dataclass
class FakeLine:
    """
    Pengganti `AllowanceTemplateLine` / `DeductionTemplateLine`.

    Mesin hitung cuma membaca atribut, tidak pernah menyimpan atau
    menelusuri relasinya — jadi objek sederhana ini cukup, dan test-nya
    jadi tidak butuh tenant.
    """

    pk: int = 1
    code: str = "X"
    name: str = "X"
    sequence: int = 1
    basis: str = PayrollBasis.FIXED
    amount: Decimal = ZERO
    rate: Decimal = ZERO
    minimum_amount = None
    maximum_amount = None
    minimum_base = None
    maximum_base = None
    is_taxable: bool = True
    reduces_taxable: bool = False
    is_prorated: bool = False


@dataclass
class FakeBracket:
    income_from: Decimal
    income_to: Decimal | None
    rate: Decimal


def make_input(**overrides) -> CalculationInput:
    defaults = dict(
        basic_salary=Decimal("10000000"),
        period_days=30,
        divisor_days=Decimal("30"),
        proration_factor=Decimal("1"),
        working_days=Decimal("30"),
        paid_days=Decimal("30"),
        attendance_days=Decimal("20"),
        absent_days=ZERO,
        leave_days=ZERO,
        unpaid_leave_days=ZERO,
        overtime_hours=ZERO,
    )
    defaults.update(overrides)

    return CalculationInput(**defaults)


def amount_of(result, code) -> Decimal:
    for component in result.components:
        if component.code == code:
            return component.amount

    raise AssertionError(f"Komponen {code} tidak ada di hasil.")


class BasicSalaryTest(SimpleTestCase):
    def test_basic_salary_penuh(self):
        result = PayrollCalculationService.calculate(make_input())

        self.assertEqual(amount_of(result, "BASIC"), Decimal("10000000.00"))
        self.assertEqual(result.gross_earning, Decimal("10000000.00"))
        self.assertEqual(result.net_pay, Decimal("10000000.00"))

    def test_prorata_setengah_bulan(self):
        """
        Pegawai yang masuk pertengahan bulan dibayar sesuai masa
        kerjanya, bukan sesuai kehadirannya.
        """
        result = PayrollCalculationService.calculate(
            make_input(proration_factor=Decimal("0.5")),
        )

        self.assertEqual(amount_of(result, "BASIC"), Decimal("5000000.00"))


class AllowanceTest(SimpleTestCase):
    def test_tunjangan_per_hari_hadir(self):
        line = FakeLine(
            code="TRANSPORT",
            name="Transport",
            basis=PayrollBasis.PER_ATTENDANCE_DAY,
            amount=Decimal("25000"),
            is_prorated=False,
        )

        result = PayrollCalculationService.calculate(
            make_input(allowance_lines=[line], attendance_days=Decimal("20")),
        )

        self.assertEqual(amount_of(result, "TRANSPORT"), Decimal("500000.00"))
        self.assertEqual(result.gross_earning, Decimal("10500000.00"))

    def test_tunjangan_persen_gaji_pokok(self):
        line = FakeLine(
            code="POSITION",
            name="Jabatan",
            basis=PayrollBasis.PERCENT_OF_BASIC,
            rate=Decimal("10"),
        )

        result = PayrollCalculationService.calculate(
            make_input(allowance_lines=[line]),
        )

        self.assertEqual(amount_of(result, "POSITION"), Decimal("1000000.00"))

    def test_tunjangan_ikut_prorata_kalau_ditandai(self):
        line = FakeLine(
            code="COMM",
            name="Komunikasi",
            basis=PayrollBasis.FIXED,
            amount=Decimal("500000"),
            is_prorated=True,
        )

        result = PayrollCalculationService.calculate(
            make_input(
                allowance_lines=[line],
                proration_factor=Decimal("0.5"),
            ),
        )

        self.assertEqual(amount_of(result, "COMM"), Decimal("250000.00"))

    def test_tunjangan_tidak_kena_pajak_tidak_menambah_dasar(self):
        line = FakeLine(
            code="NONTAX",
            name="Non Taxable",
            basis=PayrollBasis.FIXED,
            amount=Decimal("1000000"),
            is_taxable=False,
            is_prorated=False,
        )

        result = PayrollCalculationService.calculate(
            make_input(allowance_lines=[line]),
        )

        self.assertEqual(result.gross_earning, Decimal("11000000.00"))
        self.assertEqual(result.taxable_earning, Decimal("10000000.00"))


class OvertimeTest(SimpleTestCase):
    def test_lembur_dihitung_dari_pembagi_master(self):
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("10"),
                overtime_eligible=True,
                overtime_multiplier=Decimal("1.5"),
                overtime_divisor=Decimal("173"),
            ),
        )

        # 10.000.000 / 173 = 57.803,468208; x1,5 = 86.705,202312;
        # x10 jam = 867.052,02
        self.assertEqual(amount_of(result, "OT"), Decimal("867052.02"))

    def test_lembur_tanpa_eligibility_jadi_peringatan_bukan_uang(self):
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("10"),
                overtime_eligible=False,
                overtime_divisor=Decimal("173"),
            ),
        )

        self.assertEqual(result.gross_earning, Decimal("10000000.00"))
        self.assertTrue(
            any(
                item["code"] == "overtime_not_eligible"
                and item["level"] == PayrollFindingLevel.WARNING
                for item in result.findings
            ),
        )

    def test_pembagi_kosong_jadi_error_bukan_pembagian_nol(self):
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("10"),
                overtime_eligible=True,
                overtime_divisor=ZERO,
            ),
        )

        self.assertTrue(
            any(
                item["code"] == "overtime_divisor_missing"
                and item["level"] == PayrollFindingLevel.ERROR
                for item in result.findings
            ),
        )


class DeductionTest(SimpleTestCase):
    def test_bpjs_persen_dengan_plafon_dasar(self):
        line = FakeLine(
            code="BPJS-KES",
            name="BPJS Kesehatan",
            basis=PayrollBasis.PERCENT_OF_BASIC,
            rate=Decimal("1"),
            reduces_taxable=True,
        )
        line.maximum_base = Decimal("12000000")

        result = PayrollCalculationService.calculate(
            make_input(
                basic_salary=Decimal("20000000"),
                deduction_lines=[line],
            ),
        )

        # Dasarnya diplafon 12 juta, bukan 20 juta.
        self.assertEqual(amount_of(result, "BPJS-KES"), Decimal("120000.00"))

    def test_potongan_cuti_tidak_dibayar_otomatis(self):
        result = PayrollCalculationService.calculate(
            make_input(unpaid_leave_days=Decimal("3")),
        )

        # 10.000.000 x 3 / 30 = 1.000.000 tepat.
        #
        # Bukan 333.333,33 x 3 = 999.999,99. Nilai sehari yang sudah
        # dibulatkan ke rupiah lalu dikalikan jumlah hari menyisakan
        # selisih yang besarnya berubah mengikuti jumlah harinya, dan
        # tidak ada cara menjelaskan satu rupiah itu kepada pegawai
        # yang menanyakannya. Pembulatan dilakukan sekali, di akhir.
        self.assertEqual(
            amount_of(result, "UNPAID-LEAVE"),
            Decimal("1000000.00"),
        )
        self.assertEqual(result.unpaid_leave_deduction, Decimal("1000000.00"))

        # Business Decision #2: gross turun sebesar gaji yang tidak
        # pernah terbentuk, dan pengurangnya keluar dari
        # `total_deduction` supaya tidak dikurangkan dua kali.
        self.assertEqual(result.gross_earning, Decimal("9000000.00"))
        self.assertEqual(result.total_deduction, Decimal("0.00"))
        self.assertEqual(result.net_pay, Decimal("9000000.00"))

    def test_potongan_master_mencegah_potongan_otomatis_ganda(self):
        """
        Tenant yang sudah mengonfigurasi potongan cuti tidak dibayar
        sendiri tidak boleh kena potong dua kali.
        """
        line = FakeLine(
            code="CUTI-TDK-DIBAYAR",
            name="Cuti Tidak Dibayar",
            basis=PayrollBasis.PER_UNPAID_LEAVE_DAY,
            amount=Decimal("200000"),
        )

        result = PayrollCalculationService.calculate(
            make_input(
                deduction_lines=[line],
                unpaid_leave_days=Decimal("3"),
            ),
        )

        codes = [component.code for component in result.components]

        self.assertIn("CUTI-TDK-DIBAYAR", codes)
        self.assertNotIn("UNPAID-LEAVE", codes)
        self.assertEqual(
            amount_of(result, "CUTI-TDK-DIBAYAR"),
            Decimal("600000.00"),
        )
        self.assertEqual(result.unpaid_leave_deduction, Decimal("600000.00"))


class AttendanceSwitchTest(SimpleTestCase):
    """
    Saklar kebijakan mematikan **jalurnya**, bukan cuma komponen
    otomatisnya.
    """

    def test_saklar_mati_juga_mematikan_komponen_master(self):
        """
        Tenant yang mengonfigurasi potongan alpanya sendiri di Deduction
        Template tetap tunduk pada saklar perusahaan. Kalau tidak,
        kalimat "perusahaan ini tidak memotong absen" jadi dusta:
        saklarnya mati, potongannya jalan, dan tidak ada satu layar pun
        yang memperlihatkan pertentangannya.
        """
        line = FakeLine(
            code="POTONG-ALPA",
            name="Potongan Alpa",
            basis=PayrollBasis.PER_ABSENT_DAY,
            amount=Decimal("150000"),
        )

        result = PayrollCalculationService.calculate(
            make_input(
                deduction_lines=[line],
                absent_days=Decimal("2"),
                deduct_absence=False,
            ),
        )

        codes = [component.code for component in result.components]

        self.assertNotIn("POTONG-ALPA", codes)
        self.assertNotIn("ABSENT", codes)
        self.assertEqual(result.absence_deduction, ZERO)

    def test_saklar_menyala_membiarkan_komponen_master_jalan(self):
        line = FakeLine(
            code="POTONG-ALPA",
            name="Potongan Alpa",
            basis=PayrollBasis.PER_ABSENT_DAY,
            amount=Decimal("150000"),
        )

        result = PayrollCalculationService.calculate(
            make_input(
                deduction_lines=[line],
                absent_days=Decimal("2"),
            ),
        )

        self.assertEqual(
            amount_of(result, "POTONG-ALPA"), Decimal("300000.00"),
        )
        self.assertEqual(result.absence_deduction, Decimal("300000.00"))

        # Angka audit dijumlahkan dari **basis**, bukan dari kode
        # komponen bawaan — jadi tenant yang memakai komponennya
        # sendiri tetap dapat angka yang benar.
        self.assertEqual(result.absence_deduction, Decimal("300000.00"))
        self.assertEqual(result.unpaid_leave_deduction, ZERO)


class TaxTest(SimpleTestCase):
    BRACKETS = [
        FakeBracket(Decimal("0"), Decimal("60000000"), Decimal("5")),
        FakeBracket(Decimal("60000000"), Decimal("250000000"), Decimal("15")),
        FakeBracket(Decimal("250000000"), Decimal("500000000"), Decimal("25")),
        FakeBracket(Decimal("500000000"), None, Decimal("30")),
    ]

    def pph21_line(self):
        return FakeLine(
            code="PPH21",
            name="PPh 21",
            basis=PayrollBasis.PPH21_PROGRESSIVE,
            sequence=90,
        )

    def test_pph21_progresif(self):
        result = PayrollCalculationService.calculate(
            make_input(
                basic_salary=Decimal("10000000"),
                deduction_lines=[self.pph21_line()],
                non_taxable_income=Decimal("54000000"),
                tax_brackets=self.BRACKETS,
            ),
        )

        # Setahun 120jt - PTKP 54jt = PKP 66jt.
        # 60jt x 5% = 3.000.000; 6jt x 15% = 900.000 → 3.900.000 setahun.
        # Sebulan = 325.000.
        self.assertEqual(amount_of(result, "PPH21"), Decimal("325000.00"))
        self.assertEqual(result.tax_amount, Decimal("325000.00"))

    def test_iuran_yang_mengurangi_pajak_menurunkan_dasarnya(self):
        bpjs = FakeLine(
            code="BPJS-JHT",
            name="JHT",
            basis=PayrollBasis.PERCENT_OF_BASIC,
            rate=Decimal("2"),
            reduces_taxable=True,
            sequence=10,
        )

        result = PayrollCalculationService.calculate(
            make_input(
                basic_salary=Decimal("10000000"),
                deduction_lines=[bpjs, self.pph21_line()],
                non_taxable_income=Decimal("54000000"),
                tax_brackets=self.BRACKETS,
            ),
        )

        # Dasar bulanan 10jt - 200rb = 9,8jt → setahun 117,6jt
        # - PTKP 54jt = 63,6jt. 60jt x 5% + 3,6jt x 15% = 3.540.000.
        # Sebulan = 295.000.
        self.assertEqual(amount_of(result, "PPH21"), Decimal("295000.00"))

    def test_bracket_kosong_jadi_peringatan_bukan_pajak_diam_diam_nol(self):
        result = PayrollCalculationService.calculate(
            make_input(
                deduction_lines=[self.pph21_line()],
                non_taxable_income=Decimal("54000000"),
                tax_brackets=[],
            ),
        )

        self.assertEqual(result.tax_amount, ZERO)
        self.assertTrue(
            any(
                item["code"] == "tax_bracket_missing"
                for item in result.findings
            ),
        )

    def test_penghasilan_di_bawah_ptkp_tidak_kena_pajak(self):
        result = PayrollCalculationService.calculate(
            make_input(
                basic_salary=Decimal("4000000"),
                deduction_lines=[self.pph21_line()],
                non_taxable_income=Decimal("54000000"),
                tax_brackets=self.BRACKETS,
            ),
        )

        self.assertEqual(result.tax_amount, ZERO)


class ReproducibilityTest(SimpleTestCase):
    def test_dua_kali_jalan_hasilnya_sama_persis(self):
        """
        Payroll harus reproducible: bahan yang sama menghasilkan angka
        yang sama, tanpa `timezone.now()` atau pembacaan yang bisa
        bergeser di dalam mesinnya.
        """
        allowance = FakeLine(
            code="TRANSPORT",
            basis=PayrollBasis.PER_ATTENDANCE_DAY,
            amount=Decimal("25000"),
        )

        data = make_input(
            allowance_lines=[allowance],
            overtime_hours=Decimal("7.5"),
            overtime_eligible=True,
            overtime_divisor=Decimal("173"),
            overtime_multiplier=Decimal("2"),
            unpaid_leave_days=Decimal("1"),
        )

        first = PayrollCalculationService.calculate(data)
        second = PayrollCalculationService.calculate(data)

        self.assertEqual(first.net_pay, second.net_pay)
        self.assertEqual(
            [(c.code, c.amount) for c in first.components],
            [(c.code, c.amount) for c in second.components],
        )

    def test_setiap_komponen_membawa_jejak_perhitungannya(self):
        allowance = FakeLine(
            code="TRANSPORT",
            basis=PayrollBasis.PER_ATTENDANCE_DAY,
            amount=Decimal("25000"),
        )

        result = PayrollCalculationService.calculate(
            make_input(allowance_lines=[allowance]),
        )

        transport = next(
            c for c in result.components if c.code == "TRANSPORT"
        )

        self.assertEqual(transport.quantity, Decimal("20"))
        self.assertIn("25000", transport.calculation_note)
        self.assertEqual(
            transport.component_type,
            PayrollComponentType.EARNING,
        )
