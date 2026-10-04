"""
Business Decision #3 — klasifikasi dan aturan hitung tunjangan.

Satu pertanyaan: **berapa yang dibayar untuk satu baris
`AllowanceTemplateLine`, dan kenapa.** Tiga basis (nominal, persen, per
hari), dua klasifikasi (kena pajak / tidak), satu saklar prorata, dan
dua plafon.

Yang paling banyak diuji di sini bukan aritmetikanya melainkan
**prorata yang tidak boleh dikenakan dua kali**. Tiga jalur berbeda
bisa memprorata satu angka, dan dua di antaranya tidak kelihatan:

* persen dihitung dari gaji pokok **sebulan**, bukan dari gaji pokok
  yang sudah diprorata — kalau tertukar, tunjangan pegawai yang masuk
  tanggal 16 jadi seperempat, bukan setengah;
* basis per hari nilainya **sudah** mengandung harinya, jadi faktor
  prorata di atasnya adalah potongan kedua yang menyamar jadi
  "tunjangannya memang segitu";
* potongan absen dan cuti tidak dibayar (#2) sama sekali tidak boleh
  menyentuh tunjangan.

Berkas ini campuran dua lapis: yang murni aritmetika memakai
`SimpleTestCase` tanpa database (mesinnya memang tidak boleh menyentuh
ORM), dan yang menguji effective date serta kekebalan Finalize memakai
fixture tenant yang sama dengan test payroll lainnya.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.hr.models import PayrollAssignment
from apps.payroll.models import (
    AllowanceTemplate,
    AllowanceTemplateLine,
    PayrollBasis,
    PayrollComponentSource,
    PayrollComponentType,
    PayrollProrationMethod,
    PayrollRunEmployeeStatus,
    PayrollRunStatus,
    Payslip,
)
from apps.payroll.services import PayrollRunService
from apps.payroll.services.calculation import (
    CalculationInput,
    PayrollCalculationService,
)

from .test_proration import ProrationTestCase


ZERO = Decimal("0.00")


# ----------------------------------------------------------------------
# Lapis 1 — aritmetika, tanpa database
# ----------------------------------------------------------------------


@dataclass
class Line:
    """
    Pengganti `AllowanceTemplateLine`. Mesin hitung cuma membaca
    atributnya, jadi objek sederhana ini cukup — dan test aritmetikanya
    tidak butuh tenant.
    """

    pk: int = 1
    code: str = "ALW"
    name: str = "Tunjangan"
    sequence: int = 10
    basis: str = PayrollBasis.FIXED
    amount: Decimal = ZERO
    rate: Decimal = ZERO
    # Beranotasi supaya benar-benar jadi field dataclass — tanpa
    # anotasi keempatnya cuma atribut kelas dan tidak bisa diisi lewat
    # kwargs, dan test plafonnya gagal dengan pesan yang tidak
    # menyebut sebabnya.
    minimum_amount: Decimal | None = None
    maximum_amount: Decimal | None = None
    minimum_base: Decimal | None = None
    maximum_base: Decimal | None = None
    is_taxable: bool = True
    reduces_taxable: bool = False
    is_prorated: bool = True


def make_input(**overrides) -> CalculationInput:
    """
    Pegawai sebulan penuh, gaji 10 juta. Yang membedakan tiap test
    hanya baris tunjangannya.
    """
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


def half_month(**overrides) -> CalculationInput:
    """
    Pegawai yang masuk tanggal 16: 15 hari dari 30, faktor 0,5.

    Angka harinya ikut disetel — bukan cuma faktornya — karena mesin
    hitung memang memprorata dari hari (`15/30`), bukan dari faktor
    yang sudah dibulatkan. Itu yang membuat 1.500.000 jadi tepat
    750.000 dan bukan 749.999,99.
    """
    defaults = dict(
        proration_factor=Decimal("0.500000"),
        working_days=Decimal("15"),
        proration_base_days=Decimal("30"),
        proration_method=PayrollProrationMethod.FIXED_30,
        proration_method_label="Fixed 30 Days",
    )
    defaults.update(overrides)

    return make_input(**defaults)


def component(result, code):
    for item in result.components:
        if item.code == code:
            return item

    raise AssertionError(f"Komponen {code} tidak ada di hasil.")


def codes(result):
    return [item.code for item in result.components]


class FixedAllowanceTest(SimpleTestCase):
    """A, B, C. Nominal tetap."""

    def test_a_full_month_dibayar_tepat_sesuai_konfigurasi(self):
        result = PayrollCalculationService.calculate(
            make_input(
                allowance_lines=[
                    Line(code="TUNJ", amount=Decimal("1500000")),
                ],
            ),
        )

        item = component(result, "TUNJ")

        self.assertEqual(item.amount, Decimal("1500000.00"))
        self.assertTrue(item.is_taxable)
        self.assertEqual(
            item.source, PayrollComponentSource.ALLOWANCE_TEMPLATE,
        )
        self.assertEqual(item.component_type, PayrollComponentType.EARNING)

        # Sebulan penuh tidak dibagi lalu dikali lagi, jadi tidak ada
        # sisa rupiah — dan barisnya tidak mengaku diprorata.
        self.assertFalse(item.is_prorated)

    def test_b_prorata_setengah_periode(self):
        result = PayrollCalculationService.calculate(
            half_month(
                allowance_lines=[
                    Line(
                        code="TUNJ",
                        amount=Decimal("1500000"),
                        is_prorated=True,
                    ),
                ],
            ),
        )

        item = component(result, "TUNJ")

        self.assertEqual(item.amount, Decimal("750000.00"))
        self.assertTrue(item.is_prorated)

        # Keterangannya harus menghasilkan angkanya sendiri.
        self.assertIn("15/30", item.calculation_note)
        self.assertIn("1500000.00", item.calculation_note)

    def test_c_tanpa_prorata_tetap_penuh(self):
        result = PayrollCalculationService.calculate(
            half_month(
                allowance_lines=[
                    Line(
                        code="TUNJ",
                        amount=Decimal("1500000"),
                        is_prorated=False,
                    ),
                ],
            ),
        )

        item = component(result, "TUNJ")

        self.assertEqual(item.amount, Decimal("1500000.00"))
        self.assertFalse(item.is_prorated)


class PercentageAllowanceTest(SimpleTestCase):
    """D, E. Persen dari gaji pokok."""

    def test_d_sepuluh_persen_dari_gaji_pokok(self):
        result = PayrollCalculationService.calculate(
            make_input(
                allowance_lines=[
                    Line(
                        code="TUNJ",
                        basis=PayrollBasis.PERCENT_OF_BASIC,
                        rate=Decimal("10"),
                    ),
                ],
            ),
        )

        item = component(result, "TUNJ")

        self.assertEqual(item.amount, Decimal("1000000.00"))
        self.assertEqual(item.base_amount, Decimal("10000000.00"))
        self.assertEqual(item.rate, Decimal("10"))

    def test_e_prorata_hanya_sekali(self):
        """
        Ini regression yang paling penting di berkas ini.

        Persennya dihitung dari gaji pokok **sebulan** (10 juta), bukan
        dari gaji pokok yang sudah diprorata (5 juta). Kalau tertukar,
        hasilnya 250.000 — setengah dari yang benar — dan tidak ada satu
        pun angka di slip yang memperlihatkan di mana setengahnya
        hilang, karena dua-duanya "prorata" dan dua-duanya terlihat
        wajar sendirian.
        """
        result = PayrollCalculationService.calculate(
            half_month(
                allowance_lines=[
                    Line(
                        code="TUNJ",
                        basis=PayrollBasis.PERCENT_OF_BASIC,
                        rate=Decimal("10"),
                        is_prorated=True,
                    ),
                ],
            ),
        )

        item = component(result, "TUNJ")

        self.assertEqual(item.amount, Decimal("500000.00"))
        self.assertNotEqual(item.amount, Decimal("250000.00"))

        # Dasarnya tetap gaji sebulan; itu yang membuktikan persennya
        # tidak dihitung dari angka yang sudah diprorata.
        self.assertEqual(item.base_amount, Decimal("10000000.00"))

    def test_persen_tanpa_prorata_tetap_penuh(self):
        result = PayrollCalculationService.calculate(
            half_month(
                allowance_lines=[
                    Line(
                        code="TUNJ",
                        basis=PayrollBasis.PERCENT_OF_BASIC,
                        rate=Decimal("10"),
                        is_prorated=False,
                    ),
                ],
            ),
        )

        self.assertEqual(
            component(result, "TUNJ").amount, Decimal("1000000.00"),
        )

    def test_gaji_pokok_yang_diprorata_tidak_ikut_menggeser_dasarnya(self):
        """
        Komponen `BASIC` pada pegawai yang sama memang jadi 5 juta.
        Tunjangan persennya tetap memakai 10 juta — dua angka yang
        berbeda dari satu sumber, dan keduanya harus tetap berbeda.
        """
        result = PayrollCalculationService.calculate(
            half_month(
                allowance_lines=[
                    Line(
                        code="TUNJ",
                        basis=PayrollBasis.PERCENT_OF_BASIC,
                        rate=Decimal("10"),
                        is_prorated=True,
                    ),
                ],
            ),
        )

        self.assertEqual(
            component(result, "BASIC").amount, Decimal("5000000.00"),
        )
        self.assertEqual(
            component(result, "TUNJ").base_amount, Decimal("10000000.00"),
        )


class DailyAllowanceTest(SimpleTestCase):
    """
    J. Basis per hari.

    Sumber harinya **tidak ditebak**: enum existing sudah membedakan
    tiga sumber yang berbeda, dan yang dipakai adalah yang dipilih HR
    di barisnya. Test ini memastikan tiap enum membaca angka yang
    memang namanya.
    """

    def test_per_hari_hadir(self):
        result = PayrollCalculationService.calculate(
            make_input(
                attendance_days=Decimal("20"),
                allowance_lines=[
                    Line(
                        code="MAKAN",
                        basis=PayrollBasis.PER_ATTENDANCE_DAY,
                        amount=Decimal("25000"),
                        is_prorated=False,
                    ),
                ],
            ),
        )

        item = component(result, "MAKAN")

        self.assertEqual(item.amount, Decimal("500000.00"))
        self.assertEqual(item.quantity, Decimal("20"))
        self.assertIn("25000", item.calculation_note)

    def test_per_hari_dibayar_dan_per_hari_berhak_membaca_angkanya_sendiri(self):
        data = make_input(
            attendance_days=Decimal("20"),
            paid_days=Decimal("18"),
            working_days=Decimal("22"),
            allowance_lines=[
                Line(
                    code="A-HADIR",
                    basis=PayrollBasis.PER_ATTENDANCE_DAY,
                    amount=Decimal("10000"),
                    is_prorated=False,
                ),
                Line(
                    pk=2,
                    code="A-DIBAYAR",
                    basis=PayrollBasis.PER_PAID_DAY,
                    amount=Decimal("10000"),
                    is_prorated=False,
                ),
                Line(
                    pk=3,
                    code="A-BERHAK",
                    basis=PayrollBasis.PER_WORKING_DAY,
                    amount=Decimal("10000"),
                    is_prorated=False,
                ),
            ],
        )

        result = PayrollCalculationService.calculate(data)

        self.assertEqual(
            component(result, "A-HADIR").amount, Decimal("200000.00"),
        )
        self.assertEqual(
            component(result, "A-DIBAYAR").amount, Decimal("180000.00"),
        )
        self.assertEqual(
            component(result, "A-BERHAK").amount, Decimal("220000.00"),
        )

    def test_basis_per_hari_tidak_diprorata_lagi(self):
        """
        Bug yang ditutup keputusan #3.

        Pegawai masuk tanggal 16, hadir 11 hari. Tunjangan makan
        25.000/hari berarti 275.000. Barisnya dikonfigurasi
        `is_prorated=True` — bawaan model — dan sebelum ini faktor 0,5
        dikenakan lagi di atasnya: 137.500, yaitu 5,5 hari untuk 11
        hari kerja.

        Seed memang sudah menulis `is_prorated=False` untuk baris per
        hari, tapi itu kesepakatan yang hidup di seed. Perusahaan yang
        membuat komponennya sendiri dapat bawaan `True`.
        """
        result = PayrollCalculationService.calculate(
            half_month(
                attendance_days=Decimal("11"),
                allowance_lines=[
                    Line(
                        code="MAKAN",
                        basis=PayrollBasis.PER_ATTENDANCE_DAY,
                        amount=Decimal("25000"),
                        is_prorated=True,
                    ),
                ],
            ),
        )

        item = component(result, "MAKAN")

        self.assertEqual(item.amount, Decimal("275000.00"))
        self.assertNotEqual(item.amount, Decimal("137500.00"))

        # Barisnya mengaku apa adanya: dikonfigurasi prorata, tapi tidak
        # diprorata — beserta alasannya.
        self.assertFalse(item.is_prorated)
        self.assertIn("tanpa prorata", item.calculation_note)

    def test_potongan_per_hari_juga_tidak_diprorata_lagi(self):
        """
        Penjagaan yang sama di sisi potongan. Cicilan 50.000 x hari
        alpa yang diprorata lagi menagih pegawai setengah dari yang
        seharusnya.
        """
        result = PayrollCalculationService.calculate(
            half_month(
                absent_days=Decimal("2"),
                deduction_lines=[
                    Line(
                        code="DENDA",
                        basis=PayrollBasis.PER_ABSENT_DAY,
                        amount=Decimal("50000"),
                        is_prorated=True,
                    ),
                ],
            ),
        )

        # 2 x 50.000, **tidak** dikalikan lagi faktor prorata
        # setengah bulan.
        self.assertEqual(
            component(result, "DENDA").amount, Decimal("100000.00"),
        )


class TaxClassificationTest(SimpleTestCase):
    """
    F. Kena pajak vs tidak.

    Yang diuji klasifikasinya, **bukan** rumus PPh21 — rumusnya masih
    PROVISIONAL dan tidak disentuh keputusan ini.
    """

    LINES = [
        Line(
            pk=1,
            code="TUNJ-PAJAK",
            amount=Decimal("1000000"),
            is_taxable=True,
            is_prorated=False,
        ),
        Line(
            pk=2,
            code="TUNJ-BEBAS",
            amount=Decimal("400000"),
            is_taxable=False,
            is_prorated=False,
        ),
    ]

    def test_f_gross_memuat_keduanya_taxable_hanya_satu(self):
        result = PayrollCalculationService.calculate(
            make_input(allowance_lines=self.LINES),
        )

        # Gross: gaji pokok + dua tunjangan.
        self.assertEqual(result.gross_earning, Decimal("11400000.00"))

        # Taxable: gaji pokok + tunjangan yang kena pajak saja.
        self.assertEqual(result.taxable_earning, Decimal("11000000.00"))

        self.assertEqual(
            result.gross_earning - result.taxable_earning,
            Decimal("400000.00"),
        )

    def test_f_totalnya_dipisah_menurut_klasifikasi(self):
        """
        Dua angka yang membuat "tunjangan mana yang menambah dasar
        pajak" bisa dijawab tanpa menjumlahkan baris satu-satu — dan
        yang membuat test bisa menunjuk **sumber** pergeseran dasar
        pajak, bukan cuma selisihnya.
        """
        result = PayrollCalculationService.calculate(
            make_input(allowance_lines=self.LINES),
        )

        self.assertEqual(result.taxable_allowance, Decimal("1000000.00"))
        self.assertEqual(result.non_taxable_allowance, Decimal("400000.00"))

    def test_klasifikasi_ikut_terbawa_ke_barisnya(self):
        result = PayrollCalculationService.calculate(
            make_input(allowance_lines=self.LINES),
        )

        self.assertTrue(component(result, "TUNJ-PAJAK").is_taxable)
        self.assertFalse(component(result, "TUNJ-BEBAS").is_taxable)


class MinMaxAmountTest(SimpleTestCase):
    """
    G, H. Plafon.

    Urutannya: nilai mentah → prorata → jepit → bulatkan. Jadi plafon
    berarti "paling banyak/sedikit segini yang dibayar **bulan ini**",
    bukan plafon atas angka sebulan yang kemudian diprorata di
    bawahnya. Itu perilaku yang sudah berjalan sebelum keputusan #3;
    yang baru cuma bahwa ia tertulis dan diuji.
    """

    def test_g_di_bawah_minimum_dinaikkan(self):
        result = PayrollCalculationService.calculate(
            make_input(
                allowance_lines=[
                    Line(
                        code="TUNJ",
                        basis=PayrollBasis.PERCENT_OF_BASIC,
                        rate=Decimal("1"),
                        minimum_amount=Decimal("250000"),
                        is_prorated=False,
                    ),
                ],
            ),
        )

        item = component(result, "TUNJ")

        # 1% x 10 juta = 100.000, dinaikkan ke 250.000.
        self.assertEqual(item.amount, Decimal("250000.00"))
        self.assertIn("minimum", item.calculation_note)

    def test_h_di_atas_maksimum_dijepit(self):
        result = PayrollCalculationService.calculate(
            make_input(
                allowance_lines=[
                    Line(
                        code="TUNJ",
                        basis=PayrollBasis.PERCENT_OF_BASIC,
                        rate=Decimal("20"),
                        maximum_amount=Decimal("1500000"),
                        is_prorated=False,
                    ),
                ],
            ),
        )

        item = component(result, "TUNJ")

        # 20% x 10 juta = 2 juta, dijepit 1,5 juta.
        self.assertEqual(item.amount, Decimal("1500000.00"))
        self.assertIn("maksimum", item.calculation_note)

    def test_plafon_dikenakan_sesudah_prorata(self):
        """
        Urutan yang menentukan angkanya, dan yang paling mudah
        tertukar.

        20% x 10 juta = 2 juta, diprorata setengah = 1 juta. Plafon
        1,5 juta karena itu **tidak** mengikat — hasilnya 1 juta.
        Kalau plafon dikenakan lebih dulu (1,5 juta) lalu diprorata,
        hasilnya 750.000.
        """
        result = PayrollCalculationService.calculate(
            half_month(
                allowance_lines=[
                    Line(
                        code="TUNJ",
                        basis=PayrollBasis.PERCENT_OF_BASIC,
                        rate=Decimal("20"),
                        maximum_amount=Decimal("1500000"),
                        is_prorated=True,
                    ),
                ],
            ),
        )

        item = component(result, "TUNJ")

        self.assertEqual(item.amount, Decimal("1000000.00"))
        self.assertNotEqual(item.amount, Decimal("750000.00"))

    def test_plafon_masih_mengikat_sesudah_prorata(self):
        """
        Sisi lain dari urutan yang sama: kalau hasil proratanya masih
        di atas plafon, plafonnya tetap berlaku.
        """
        result = PayrollCalculationService.calculate(
            half_month(
                allowance_lines=[
                    Line(
                        code="TUNJ",
                        basis=PayrollBasis.PERCENT_OF_BASIC,
                        rate=Decimal("20"),
                        maximum_amount=Decimal("800000"),
                        is_prorated=True,
                    ),
                ],
            ),
        )

        self.assertEqual(
            component(result, "TUNJ").amount, Decimal("800000.00"),
        )


class AllowanceIsolationTest(SimpleTestCase):
    """
    Keputusan #2 tidak boleh menyentuh tunjangan.

    Potongan absen dan cuti tidak dibayar mengurangi **gaji pokok**.
    Tunjangan yang ikut susut karena alpa adalah efek tersembunyi:
    tidak ada baris potongan yang menyebutnya, dan selisihnya cuma
    terlihat kalau seseorang menghitung ulang dari konfigurasinya.
    """

    def test_alpa_tidak_mengurangi_tunjangan_nominal(self):
        clean = PayrollCalculationService.calculate(
            make_input(
                allowance_lines=[
                    Line(code="TUNJ", amount=Decimal("1500000")),
                ],
            ),
        )

        absent = PayrollCalculationService.calculate(
            make_input(
                absent_days=Decimal("3"),
                unpaid_leave_days=Decimal("2"),
                deduction_base_days=Decimal("30"),
                allowance_lines=[
                    Line(code="TUNJ", amount=Decimal("1500000")),
                ],
            ),
        )

        self.assertEqual(
            component(clean, "TUNJ").amount,
            component(absent, "TUNJ").amount,
        )

        # Yang berkurang memang ada, tapi di barisnya sendiri —
        # bukan di tunjangannya.
        self.assertIn("ABSENT", codes(absent))
        self.assertIn("UNPAID-LEAVE", codes(absent))

    def test_alpa_tidak_mengurangi_tunjangan_persen(self):
        absent = PayrollCalculationService.calculate(
            make_input(
                absent_days=Decimal("3"),
                deduction_base_days=Decimal("30"),
                allowance_lines=[
                    Line(
                        code="TUNJ",
                        basis=PayrollBasis.PERCENT_OF_BASIC,
                        rate=Decimal("10"),
                    ),
                ],
            ),
        )

        self.assertEqual(
            component(absent, "TUNJ").amount, Decimal("1000000.00"),
        )

    def test_tunjangan_per_hari_hadir_memang_ikut_kehadiran(self):
        """
        Satu pengecualian, dan itu bukan efek tersembunyi melainkan
        basis yang dipilih HR: tunjangan makan per hari hadir memang
        berkurang kalau orangnya tidak masuk. Yang mengurangi jumlah
        harinya, bukan aturan potongan.
        """
        result = PayrollCalculationService.calculate(
            make_input(
                attendance_days=Decimal("17"),
                absent_days=Decimal("3"),
                deduction_base_days=Decimal("30"),
                allowance_lines=[
                    Line(
                        code="MAKAN",
                        basis=PayrollBasis.PER_ATTENDANCE_DAY,
                        amount=Decimal("25000"),
                        is_prorated=False,
                    ),
                ],
            ),
        )

        self.assertEqual(
            component(result, "MAKAN").amount, Decimal("425000.00"),
        )


class SnapshotTraceTest(SimpleTestCase):
    """
    §10. Satu baris komponen harus bisa menjelaskan dirinya sendiri.
    """

    def test_satu_baris_membawa_seluruh_jejaknya(self):
        result = PayrollCalculationService.calculate(
            half_month(
                allowance_lines=[
                    Line(
                        pk=77,
                        code="TUNJ",
                        name="Tunjangan Jabatan",
                        basis=PayrollBasis.PERCENT_OF_BASIC,
                        rate=Decimal("10"),
                        is_taxable=True,
                        is_prorated=True,
                    ),
                ],
            ),
        )

        item = component(result, "TUNJ")

        self.assertEqual(item.code, "TUNJ")
        self.assertEqual(item.name, "Tunjangan Jabatan")
        self.assertEqual(
            item.source, PayrollComponentSource.ALLOWANCE_TEMPLATE,
        )
        self.assertEqual(
            item.reference_type, "payroll.allowance_template_line",
        )
        self.assertEqual(item.reference_id, "77")
        self.assertEqual(item.basis, PayrollBasis.PERCENT_OF_BASIC)
        self.assertEqual(item.rate, Decimal("10"))
        self.assertEqual(item.base_amount, Decimal("10000000.00"))
        self.assertTrue(item.is_taxable)
        self.assertTrue(item.is_prorated)
        self.assertEqual(item.amount, Decimal("500000.00"))

        # Nilai mentah sebelum prorata hanya hidup di keterangan, dan
        # keterangan itu harus menghasilkan angka akhirnya.
        self.assertIn("1000000.00", item.calculation_note)
        self.assertIn("15/30", item.calculation_note)


# ----------------------------------------------------------------------
# Lapis 2 — effective date & kekebalan histori, dengan database
# ----------------------------------------------------------------------


class AllowanceEffectiveDateTest(ProrationTestCase):
    """
    I. Paket tunjangan diambil dari `PayrollAssignment` yang berlaku
    pada periodenya, dan run yang sudah Finalized kebal terhadap
    perubahan masternya.
    """

    def make_template(self, code, *, amount):
        type(self)._counter += 1

        template = AllowanceTemplate.objects.create(
            code=f"{code}-{type(self)._counter}",
            name=f"Paket {code}",
        )

        AllowanceTemplateLine.objects.create(
            template=template,
            code="TUNJ",
            name="Tunjangan Jabatan",
            sequence=10,
            basis=PayrollBasis.FIXED,
            amount=Decimal(amount),
            is_taxable=True,
            is_prorated=False,
        )

        return template

    def finalize(self, run):
        from apps.payroll.models import PayrollRunEmployee

        PayrollRunEmployee.objects.filter(
            run=run, payroll_assignment__isnull=True,
        ).update(
            is_excluded=True,
            status=PayrollRunEmployeeStatus.EXCLUDED,
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

    def test_i_paket_baru_berlaku_periode_berikutnya_saja(self):
        first = self.make_month(2080, 6, 30)
        second = self.make_month(2080, 7, 31)

        cheap = self.make_template("MURAH", amount="500000")
        rich = self.make_template("MAHAL", amount="2000000")

        employee = self.make_employee(basic_salary="10000000")

        # Assignment yang berlaku Juni memakai paket murah.
        PayrollAssignment.objects.filter(employee=employee).update(
            allowance_template=cheap,
        )

        run_june = self.make_run(first)
        PayrollRunService.generate_employees(run=run_june)
        PayrollRunService.calculate(run=run_june)

        line_june = self.line_for(run_june, employee)

        self.assertEqual(
            self.component(line_june, "TUNJ").amount, Decimal("500000.00"),
        )

        run_june = self.finalize(run_june)

        # Assignment baru, efektif Juli, memakai paket mahal —
        # lewat jalur resminya. `PayrollAssignmentService.create`
        # menutup baris sebelumnya (`effective_to`, `is_current=False`)
        # dan membuka yang baru; membuat barisnya sendiri akan
        # menabrak `uniq_current_employee_payroll_assignment` dan,
        # lebih buruk, menghasilkan riwayat yang bukan rentang.
        from apps.hr.api.payroll_assignment.services import (
            PayrollAssignmentService,
        )

        base = PayrollAssignment.objects.filter(employee=employee).first()

        PayrollAssignmentService.create(
            data={
                "employee": employee,
                "payroll_group": base.payroll_group,
                "currency": base.currency,
                "tax_status": base.tax_status,
                "overtime_eligible": False,
                "basic_salary": base.basic_salary,
                "allowance_template": rich,
                "deduction_template": base.deduction_template,
                "effective_from": second.start_date,
            },
        )

        run_july = self.make_run(second)
        PayrollRunService.generate_employees(run=run_july)
        PayrollRunService.calculate(run=run_july)

        line_july = self.line_for(run_july, employee)

        self.assertEqual(
            self.component(line_july, "TUNJ").amount, Decimal("2000000.00"),
        )

        # Juni tidak bergerak.
        line_june.refresh_from_db()
        self.assertEqual(
            self.component(line_june, "TUNJ").amount, Decimal("500000.00"),
        )

    def test_i_mengubah_master_tidak_mengubah_run_yang_final(self):
        period = self.make_month(2081, 6, 30)

        template = self.make_template("BEKU", amount="1200000")
        employee = self.make_employee(basic_salary="10000000")

        PayrollAssignment.objects.filter(employee=employee).update(
            allowance_template=template,
        )

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        run = self.finalize(run)
        line = self.line_for(run, employee)

        self.assertEqual(
            self.component(line, "TUNJ").amount, Decimal("1200000.00"),
        )

        slip = Payslip.objects.get(run_employee=line)
        frozen = slip.snapshot["earnings"]

        # --- masternya diubah sesudah Finalize --------------------
        row = template.lines.get(code="TUNJ")
        row.amount = Decimal("9000000")
        row.is_taxable = False
        row.save(update_fields=["amount", "is_taxable"])

        template.lines.filter(code="TUNJ").update(is_active=False)

        line.refresh_from_db()

        self.assertEqual(
            self.component(line, "TUNJ").amount, Decimal("1200000.00"),
        )
        self.assertTrue(self.component(line, "TUNJ").is_taxable)

        slip.refresh_from_db()
        self.assertEqual(slip.snapshot["earnings"], frozen)

    def test_snapshot_slip_membawa_klasifikasi_pajaknya(self):
        """
        §10. "Kenapa tunjangan ini menambah pajak dan yang itu tidak"
        adalah pertanyaan yang muncul setahun kemudian, waktu
        konfigurasinya sudah berubah.
        """
        period = self.make_month(2082, 6, 30)

        template = self.make_template("KLASIFIKASI", amount="1000000")

        AllowanceTemplateLine.objects.create(
            template=template,
            code="TUNJ-BEBAS",
            name="Tunjangan Bebas Pajak",
            sequence=20,
            basis=PayrollBasis.FIXED,
            amount=Decimal("400000"),
            is_taxable=False,
            is_prorated=False,
        )

        employee = self.make_employee(basic_salary="10000000")

        PayrollAssignment.objects.filter(employee=employee).update(
            allowance_template=template,
        )

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        run = self.finalize(run)
        line = self.line_for(run, employee)

        slip = Payslip.objects.get(run_employee=line)

        totals = slip.snapshot["totals"]
        self.assertEqual(totals["taxable_allowance"], "1000000.00")
        self.assertEqual(totals["non_taxable_allowance"], "400000.00")

        rows = {
            row["code"]: row for row in slip.snapshot["earnings"]
        }
        self.assertTrue(rows["TUNJ"]["is_taxable"])
        self.assertFalse(rows["TUNJ-BEBAS"]["is_taxable"])
