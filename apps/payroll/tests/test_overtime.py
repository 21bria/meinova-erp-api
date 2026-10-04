"""
Business Decision #4 — aturan hitung upah lembur.

Satu pertanyaan: **berapa rupiah yang dibayar untuk jam lembur yang
sudah sah.** Jam mana yang lembur bukan urusan berkas ini dan bukan
urusan Payroll — itu milik HR/Attendance/Overtime beserta alur
persetujuannya. Yang diuji di sini harganya.

Yang paling banyak diuji bukan aritmetikanya melainkan **hal-hal yang
tidak boleh terjadi diam-diam**: pengali karangan untuk pegawai tanpa
Overtime Group, tarif per jam yang ikut turun karena gaji pokoknya
diprorata, dan tingkat pengali yang disusun per hari padahal
perusahaannya belum menyatakan apa-apa.

Lapis aritmetikanya memakai `SimpleTestCase` tanpa database — mesin
hitung memang tidak boleh menyentuh ORM; lapis effective-date dan
kekebalan Finalize memakai fixture tenant yang sama dengan test payroll
lainnya.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.hr.models import EmployeeOvertime, PayrollAssignment
from apps.hr.models.overtime import OvertimeStatus
from apps.payroll.models import (
    OvertimeGroup,
    OvertimeGroupTier,
    OvertimeTierBasis,
    PayrollBasis,
    PayrollComponentSource,
    PayrollFindingLevel,
    PayrollRunEmployeeStatus,
    PayrollRunStatus,
    Payslip,
)
from apps.payroll.services import PayrollRunService, PayrollSourceService
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
class Tier:
    """
    Pengganti `OvertimeGroupTier`. Mesin hitung cuma membaca tiga
    atributnya, jadi objek sederhana ini cukup.
    """

    hour_from: Decimal = ZERO
    hour_to: Decimal | None = None
    multiplier: Decimal = Decimal("1")
    sequence: int = 1


def make_input(**overrides) -> CalculationInput:
    """Gaji 10 juta sebulan penuh; yang berbeda tiap test lemburnya."""
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
        overtime_eligible=True,
        overtime_divisor=Decimal("173"),
        overtime_multiplier=Decimal("1.5"),
    )
    defaults.update(overrides)

    return CalculationInput(**defaults)


def component(result, code):
    for item in result.components:
        if item.code == code:
            return item

    raise AssertionError(f"Komponen {code} tidak ada di hasil.")


def codes(result):
    return [item.code for item in result.components]


def finding_codes(result):
    return {item["code"] for item in result.findings}


class LegacyMultiplierTest(SimpleTestCase):
    """
    A. Pengali tunggal — perilaku sebelum keputusan #4, dan angkanya
    tidak boleh bergeser sedikit pun.
    """

    def test_a_sepuluh_jam_kali_satu_setengah(self):
        result = PayrollCalculationService.calculate(
            make_input(overtime_hours=Decimal("10")),
        )

        item = component(result, "OT")

        # 10.000.000 / 173 = 57.803,468208/jam
        #   x 1,5 x 10 jam = 867.052,02
        self.assertEqual(item.amount, Decimal("867052.02"))
        self.assertEqual(item.rate, Decimal("57803.468208"))
        self.assertEqual(item.quantity, Decimal("10"))
        self.assertEqual(item.base_amount, Decimal("10000000.00"))
        self.assertEqual(item.basis, PayrollBasis.PER_OVERTIME_HOUR)
        self.assertEqual(item.source, PayrollComponentSource.OVERTIME)

    def test_a_keterangannya_menghasilkan_angkanya_sendiri(self):
        result = PayrollCalculationService.calculate(
            make_input(overtime_hours=Decimal("10")),
        )

        note = component(result, "OT").calculation_note

        self.assertIn("10000000.00 / 173", note)
        self.assertIn("57803.468208", note)
        self.assertIn("10 jam x 1.5", note)

    def test_a_dua_jam_cocok_dengan_baseline(self):
        result = PayrollCalculationService.calculate(
            make_input(overtime_hours=Decimal("2")),
        )

        self.assertEqual(
            component(result, "OT").amount, Decimal("173410.40"),
        )


class TieredOvertimeTest(SimpleTestCase):
    """B. Tingkat pengali."""

    TIERS = [
        Tier(hour_from=ZERO, hour_to=Decimal("1"), multiplier=Decimal("1.5")),
        Tier(
            hour_from=Decimal("1"),
            hour_to=None,
            multiplier=Decimal("2"),
            sequence=2,
        ),
    ]

    def test_b_empat_jam_satu_lalu_tiga(self):
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("4"),
                overtime_tiers=self.TIERS,
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
            ),
        )

        item = component(result, "OT")

        # 57.803,468208 x (1 x 1,5 + 3 x 2,0) = 57.803,468208 x 7,5
        #   = 433.526,01156 -> 433.526,01
        self.assertEqual(item.amount, Decimal("433526.01"))
        self.assertIn("1 jam x 1.5", item.calculation_note)
        self.assertIn("3 jam x 2", item.calculation_note)

    def test_b_tingkat_mengalahkan_pengali_tunggal(self):
        """
        Pengali tunggal kelompok ini 1,5. Kalau ia yang dipakai,
        hasilnya 4 x 1,5 = 6 jam berbobot, bukan 7,5.
        """
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("4"),
                overtime_multiplier=Decimal("1.5"),
                overtime_tiers=self.TIERS,
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
            ),
        )

        self.assertNotEqual(
            component(result, "OT").amount, Decimal("346820.81"),
        )
        self.assertEqual(
            component(result, "OT").amount, Decimal("433526.01"),
        )

    def test_b_satu_jam_saja_tidak_menyentuh_tingkat_kedua(self):
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("1"),
                overtime_tiers=self.TIERS,
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
            ),
        )

        # 57.803,468208 x 1,5 = 86.705,20
        self.assertEqual(
            component(result, "OT").amount, Decimal("86705.20"),
        )

    def test_tiga_tingkat_juga_bekerja(self):
        """
        Dua tingkat cuma kebetulan cukup untuk contoh. Yang harus
        benar: berapa pun tingkatnya.
        """
        tiers = [
            Tier(ZERO, Decimal("1"), Decimal("1.5")),
            Tier(Decimal("1"), Decimal("3"), Decimal("2"), 2),
            Tier(Decimal("3"), None, Decimal("3"), 3),
        ]

        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("5"),
                overtime_tiers=tiers,
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
            ),
        )

        # 1 x 1,5 + 2 x 2 + 2 x 3 = 11,5 jam berbobot
        # 57.803,468208 x 11,5 = 664.739,884392 -> 664.739,88
        self.assertEqual(
            component(result, "OT").amount, Decimal("664739.88"),
        )


class FractionalHoursTest(SimpleTestCase):
    """C. Jam pecahan."""

    TIERS = [
        Tier(ZERO, Decimal("1"), Decimal("1.5")),
        Tier(Decimal("1"), None, Decimal("2"), 2),
    ]

    def test_c_dua_setengah_jam_dipecah_satu_dan_satu_setengah(self):
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("2.5"),
                overtime_tiers=self.TIERS,
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
            ),
        )

        item = component(result, "OT")

        # 1 x 1,5 + 1,5 x 2 = 4,5 jam berbobot
        # 57.803,468208 x 4,5 = 260.115,606936 -> 260.115,61
        self.assertEqual(item.amount, Decimal("260115.61"))
        self.assertIn("1 jam x 1.5", item.calculation_note)
        self.assertIn("1.5 jam x 2", item.calculation_note)

    def test_c_pecahan_tidak_dibulatkan_ke_jam_penuh(self):
        """
        2,5 jam yang dibulatkan jadi 2 atau 3 mengubah upahnya, dan
        modul sumber tidak punya aturan pembulatan apa pun. Menciptakan
        aturan itu di sini berarti membayar orang untuk jam yang tidak
        pernah tercatat — atau tidak membayar jam yang tercatat.
        """
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("2.5"),
                overtime_tiers=self.TIERS,
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
            ),
        )

        two_hours = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("2"),
                overtime_tiers=self.TIERS,
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
            ),
        )

        self.assertNotEqual(
            component(result, "OT").amount,
            component(two_hours, "OT").amount,
        )

    def test_pecahan_pada_pengali_tunggal(self):
        result = PayrollCalculationService.calculate(
            make_input(overtime_hours=Decimal("2.5")),
        )

        # 57.803,468208 x 1,5 x 2,5 = 216.763,00578 -> 216.763,01
        self.assertEqual(
            component(result, "OT").amount, Decimal("216763.01"),
        )


class TierBasisTest(SimpleTestCase):
    """
    G. Beberapa catatan lembur dalam satu periode.

    Per hari dan total sebulan menghasilkan angka yang **jauh**
    berbeda, dan itu justru inti kenapa sistem tidak memilihkan.
    """

    TIERS = [
        Tier(ZERO, Decimal("1"), Decimal("1.5")),
        Tier(Decimal("1"), None, Decimal("2"), 2),
    ]

    def test_g_basis_harian_menyusun_ulang_tiap_hari(self):
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("4"),
                overtime_daily_hours=[Decimal("1")] * 4,
                overtime_tiers=self.TIERS,
                overtime_tier_basis=OvertimeTierBasis.DAILY,
            ),
        )

        # Empat hari x 1 jam, semuanya jam pertama: 4 x 1,5 = 6.
        # 57.803,468208 x 6 = 346.820,809248 -> 346.820,81
        self.assertEqual(
            component(result, "OT").amount, Decimal("346820.81"),
        )

    def test_g_basis_bulanan_menyusun_sekali(self):
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("4"),
                overtime_daily_hours=[Decimal("1")] * 4,
                overtime_tiers=self.TIERS,
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
            ),
        )

        # Jam yang sama, disusun sekali: 1 x 1,5 + 3 x 2 = 7,5.
        self.assertEqual(
            component(result, "OT").amount, Decimal("433526.01"),
        )

    def test_g_keduanya_memang_berbeda(self):
        """
        Kalau kedua basis menghasilkan angka yang sama, tidak ada yang
        perlu diputuskan. Test ini yang menjaga pertanyaannya tetap
        nyata.
        """
        daily = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("4"),
                overtime_daily_hours=[Decimal("1")] * 4,
                overtime_tiers=self.TIERS,
                overtime_tier_basis=OvertimeTierBasis.DAILY,
            ),
        )
        monthly = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("4"),
                overtime_daily_hours=[Decimal("1")] * 4,
                overtime_tiers=self.TIERS,
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
            ),
        )

        self.assertNotEqual(
            component(daily, "OT").amount,
            component(monthly, "OT").amount,
        )

    def test_tingkat_tanpa_basis_ditolak(self):
        """
        Ada tingkat tapi belum dinyatakan disusun per apa. Menebak
        salah satunya berarti mengambil keputusan bisnis atas nama
        perusahaan — mesinnya berhenti dan menyebutnya.
        """
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("4"),
                overtime_tiers=self.TIERS,
                overtime_tier_basis="",
            ),
        )

        self.assertNotIn("OT", codes(result))
        self.assertIn("overtime_tier_basis_missing", finding_codes(result))

    def test_basis_harian_tanpa_rincian_per_hari_ditolak(self):
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("4"),
                overtime_daily_hours=[],
                overtime_tiers=self.TIERS,
                overtime_tier_basis=OvertimeTierBasis.DAILY,
            ),
        )

        self.assertNotIn("OT", codes(result))
        self.assertIn("overtime_daily_hours_missing", finding_codes(result))


class EligibilityTest(SimpleTestCase):
    """D, E. Siapa yang berhak, dan dengan aturan siapa."""

    def test_d_tidak_eligible_tidak_dibayar(self):
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("10"),
                overtime_eligible=False,
            ),
        )

        self.assertNotIn("OT", codes(result))
        self.assertIn("overtime_not_eligible", finding_codes(result))

    def test_d_jamnya_tetap_disebut_di_temuannya(self):
        """
        "Tidak dibayar" dan "tidak pernah tercatat" harus tetap bisa
        dibedakan. Catatan sumbernya tidak disentuh sama sekali.
        """
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("10"),
                overtime_eligible=False,
            ),
        )

        message = next(
            item["message"]
            for item in result.findings
            if item["code"] == "overtime_not_eligible"
        )

        self.assertIn("10", message)

    def test_e_eligible_tanpa_group_jadi_error_yang_menyebut_namanya(self):
        """
        Sebelum keputusan #4 keadaan ini jatuh ke "pembagi kosong" —
        pesan yang menyuruh orang memperbaiki kolom pada master yang
        belum dipilihnya sama sekali.
        """
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("10"),
                overtime_group_present=False,
                overtime_divisor=ZERO,
                overtime_multiplier=ZERO,
            ),
        )

        self.assertNotIn("OT", codes(result))
        self.assertIn("overtime_group_missing", finding_codes(result))
        self.assertNotIn("overtime_divisor_missing", finding_codes(result))

    def test_e_tidak_ada_fallback_pengali_diam_diam(self):
        """
        Yang paling berbahaya bukan error-nya melainkan kalau tidak ada
        error: pengali 1 yang dikarang mesin akan tetap membayar
        lembur, dengan angka yang tidak pernah disetujui siapa pun.
        """
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("10"),
                overtime_group_present=False,
                overtime_divisor=ZERO,
                overtime_multiplier=ZERO,
            ),
        )

        self.assertEqual(
            [item for item in result.components if item.code == "OT"], [],
        )

    def test_pengali_nol_tanpa_tingkat_ditolak(self):
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("10"),
                overtime_multiplier=ZERO,
            ),
        )

        self.assertNotIn("OT", codes(result))
        self.assertIn("overtime_multiplier_invalid", finding_codes(result))

    def test_pembagi_nol_ditolak(self):
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("10"),
                overtime_divisor=ZERO,
            ),
        )

        self.assertNotIn("OT", codes(result))
        self.assertIn("overtime_divisor_missing", finding_codes(result))

    def test_jam_negatif_ditolak(self):
        result = PayrollCalculationService.calculate(
            make_input(overtime_hours=Decimal("-3")),
        )

        self.assertNotIn("OT", codes(result))
        self.assertIn("overtime_hours_negative", finding_codes(result))


class TierGapAndOverlapTest(SimpleTestCase):
    """
    §15. Konfigurasi tingkat yang cacat tidak boleh diperbaiki
    diam-diam, dan tidak boleh menghasilkan uang.
    """

    def test_celah_antar_tingkat_ditolak(self):
        tiers = [
            Tier(ZERO, Decimal("1"), Decimal("1.5")),
            Tier(Decimal("2"), None, Decimal("2"), 2),
        ]

        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("3"),
                overtime_tiers=tiers,
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
            ),
        )

        self.assertNotIn("OT", codes(result))
        self.assertIn("overtime_tier_gap", finding_codes(result))

    def test_tingkat_teratas_berbatas_menyisakan_jam_tanpa_tarif(self):
        tiers = [
            Tier(ZERO, Decimal("1"), Decimal("1.5")),
            Tier(Decimal("1"), Decimal("2"), Decimal("2"), 2),
        ]

        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("3"),
                overtime_tiers=tiers,
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
            ),
        )

        self.assertNotIn("OT", codes(result))
        self.assertIn("overtime_tier_gap", finding_codes(result))

    def test_tumpang_tindih_ditolak_bukan_dibayar_dua_kali(self):
        tiers = [
            Tier(ZERO, Decimal("2"), Decimal("1.5")),
            Tier(Decimal("1"), None, Decimal("2"), 2),
        ]

        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("3"),
                overtime_tiers=tiers,
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
            ),
        )

        self.assertNotIn("OT", codes(result))
        self.assertIn("overtime_tier_overlap", finding_codes(result))

    def test_tingkat_pertama_tidak_mulai_dari_nol_ditolak(self):
        tiers = [
            Tier(Decimal("1"), None, Decimal("2")),
        ]

        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("3"),
                overtime_tiers=tiers,
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
            ),
        )

        self.assertNotIn("OT", codes(result))
        self.assertIn("overtime_tier_gap", finding_codes(result))


class HourlyRateBasisTest(SimpleTestCase):
    """
    F. Tarif per jam selalu dari gaji **sebulan**.
    """

    def test_f_prorata_tidak_menurunkan_tarif_per_jam(self):
        """
        Pegawai yang masuk tanggal 16 menerima gaji pokok setengah
        bulan, tapi upah lemburnya per jam tidak ikut setengah — ia
        bekerja satu jam penuh, dan satu jam itu harganya sama dengan
        jam rekannya.
        """
        full = PayrollCalculationService.calculate(
            make_input(overtime_hours=Decimal("10")),
        )

        half = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("10"),
                proration_factor=Decimal("0.500000"),
                working_days=Decimal("15"),
                proration_base_days=Decimal("30"),
            ),
        )

        self.assertEqual(
            component(full, "OT").amount,
            component(half, "OT").amount,
        )
        self.assertEqual(
            component(half, "OT").amount, Decimal("867052.02"),
        )

        # Gaji pokoknya memang setengah — dua angka dari satu sumber,
        # dan keduanya harus tetap berbeda.
        self.assertEqual(
            component(half, "BASIC").amount, Decimal("5000000.00"),
        )
        self.assertEqual(
            component(half, "OT").base_amount, Decimal("10000000.00"),
        )

    def test_f_berlaku_juga_untuk_tingkat(self):
        tiers = [
            Tier(ZERO, Decimal("1"), Decimal("1.5")),
            Tier(Decimal("1"), None, Decimal("2"), 2),
        ]

        half = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("4"),
                overtime_tiers=tiers,
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
                proration_factor=Decimal("0.500000"),
                working_days=Decimal("15"),
                proration_base_days=Decimal("30"),
            ),
        )

        self.assertEqual(
            component(half, "OT").amount, Decimal("433526.01"),
        )


class OvertimeTaxabilityTest(SimpleTestCase):
    """
    I. Lembur tetap menambah dasar pajak, persis seperti sebelumnya.

    Apakah *seharusnya* begitu adalah pertanyaan PPh21 — Business
    Decision #6, masih PROVISIONAL. Test ini ada supaya perubahan itu
    tidak terjadi diam-diam sebagai efek samping keputusan #4.
    """

    def test_i_lembur_masuk_taxable_earning(self):
        result = PayrollCalculationService.calculate(
            make_input(overtime_hours=Decimal("10")),
        )

        self.assertTrue(component(result, "OT").is_taxable)
        self.assertEqual(result.gross_earning, result.taxable_earning)

    def test_i_lembur_bertingkat_juga_taxable(self):
        result = PayrollCalculationService.calculate(
            make_input(
                overtime_hours=Decimal("4"),
                overtime_tiers=[
                    Tier(ZERO, Decimal("1"), Decimal("1.5")),
                    Tier(Decimal("1"), None, Decimal("2"), 2),
                ],
                overtime_tier_basis=OvertimeTierBasis.MONTHLY,
            ),
        )

        self.assertTrue(component(result, "OT").is_taxable)

    def test_i_klasifikasinya_belum_configurable_dan_itu_disengaja(self):
        """
        Tidak ada kolom `is_taxable` di `OvertimeGroup`. Menambahkannya
        berarti membuka keputusan #6 lewat pintu belakang, jadi
        nilainya tetap ditanam `True` — dan test ini yang mencatat
        bahwa itu keadaan yang diketahui, bukan yang terlewat.
        """
        self.assertFalse(hasattr(OvertimeGroup, "is_taxable"))


# ----------------------------------------------------------------------
# Lapis 2 — model, adapter, dan kekebalan histori
# ----------------------------------------------------------------------


class TierModelValidationTest(SimpleTestCase):
    """Konfigurasi mustahil ditolak di layar tempat ia ditulis."""

    def test_batas_atas_harus_lebih_besar(self):
        tier = OvertimeGroupTier(
            hour_from=Decimal("2"),
            hour_to=Decimal("1"),
            multiplier=Decimal("2"),
        )

        with self.assertRaises(ValidationError) as raised:
            tier.clean()

        self.assertIn("hour_to", raised.exception.message_dict)

    def test_pengali_nol_ditolak(self):
        tier = OvertimeGroupTier(
            hour_from=ZERO, hour_to=None, multiplier=ZERO,
        )

        with self.assertRaises(ValidationError) as raised:
            tier.clean()

        self.assertIn("multiplier", raised.exception.message_dict)

    def test_batas_bawah_negatif_ditolak(self):
        tier = OvertimeGroupTier(
            hour_from=Decimal("-1"), multiplier=Decimal("2"),
        )

        with self.assertRaises(ValidationError) as raised:
            tier.clean()

        self.assertIn("hour_from", raised.exception.message_dict)

    def test_pembagi_nol_pada_group_ditolak(self):
        group = OvertimeGroup(
            code="X", name="X",
            hourly_divisor=ZERO,
            hourly_multiplier=Decimal("1.5"),
        )

        with self.assertRaises(ValidationError) as raised:
            group.clean()

        self.assertIn("hourly_divisor", raised.exception.message_dict)

    def test_pengali_nol_pada_group_ditolak(self):
        group = OvertimeGroup(
            code="X", name="X",
            hourly_divisor=Decimal("173"),
            hourly_multiplier=ZERO,
        )

        with self.assertRaises(ValidationError) as raised:
            group.clean()

        self.assertIn("hourly_multiplier", raised.exception.message_dict)


class OvertimeTestCase(ProrationTestCase):
    """Fixture bersama untuk lapis yang menyentuh database."""

    def make_group(self, code, *, multiplier="1.5", divisor="173", basis=""):
        type(self)._counter += 1

        return OvertimeGroup.objects.create(
            code=f"{code}-{type(self)._counter}",
            name=f"Overtime {code}",
            hourly_multiplier=Decimal(multiplier),
            hourly_divisor=Decimal(divisor),
            tier_basis=basis,
        )

    @staticmethod
    def add_tier(group, *, sequence, hour_from, hour_to, multiplier):
        return OvertimeGroupTier.objects.create(
            group=group,
            sequence=sequence,
            hour_from=Decimal(hour_from),
            hour_to=Decimal(hour_to) if hour_to is not None else None,
            multiplier=Decimal(multiplier),
        )

    def attach_group(self, employee, group):
        PayrollAssignment.objects.filter(employee=employee).update(
            overtime_group=group, overtime_eligible=True,
        )

    def add_overtime(self, employee, *, day, minutes, period):
        return EmployeeOvertime.objects.create(
            employee=employee,
            company=self.company,
            work_date=period.start_date.replace(day=day),
            start_time="18:00",
            end_time="20:00",
            duration_minutes=minutes,
            status=OvertimeStatus.APPROVED,
            is_paid=True,
        )

    def run_payroll(self, *, period, employee):
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        return self.line_for(run, employee), run


class OvertimeSourceTest(OvertimeTestCase):
    """
    §2 dan §8. Payroll hanya mengonsumsi jam yang sah menurut modul
    sumber, dan membawanya per tanggal.
    """

    def test_hanya_lembur_berbayar_dan_disetujui_yang_terhitung(self):
        period = self.make_month(2090, 6, 30)
        employee = self.make_employee(basic_salary="10000000")

        self.add_overtime(employee, day=5, minutes=120, period=period)

        # Belum disetujui.
        EmployeeOvertime.objects.create(
            employee=employee, company=self.company,
            work_date=period.start_date.replace(day=6),
            start_time="18:00", end_time="21:00",
            duration_minutes=180,
            status=OvertimeStatus.SUBMITTED, is_paid=True,
        )

        # Disetujui tapi memang tidak dibayar (diganti libur).
        EmployeeOvertime.objects.create(
            employee=employee, company=self.company,
            work_date=period.start_date.replace(day=7),
            start_time="18:00", end_time="21:00",
            duration_minutes=180,
            status=OvertimeStatus.APPROVED, is_paid=False,
        )

        facts = PayrollSourceService.collect(
            employee=employee,
            start_date=period.start_date,
            end_date=period.end_date,
        )

        self.assertEqual(facts.overtime_hours, Decimal("2.00"))
        self.assertEqual(facts.overtime_daily_hours, [Decimal("2.00")])

    def test_dua_lembur_di_hari_yang_sama_jadi_satu_hari(self):
        """
        Dua catatan pada tanggal yang sama adalah **satu** hari lembur.
        Menghitungnya sebagai dua akan memberi tarif jam pertama dua
        kali pada perusahaan yang bertingkat harian.
        """
        period = self.make_month(2091, 6, 30)
        employee = self.make_employee(basic_salary="10000000")

        self.add_overtime(employee, day=5, minutes=60, period=period)
        self.add_overtime(employee, day=5, minutes=90, period=period)

        facts = PayrollSourceService.collect(
            employee=employee,
            start_date=period.start_date,
            end_date=period.end_date,
        )

        self.assertEqual(facts.overtime_daily_hours, [Decimal("2.50")])
        self.assertEqual(facts.overtime_hours, Decimal("2.50"))

    def test_menit_dijumlahkan_dulu_baru_diubah_ke_jam(self):
        """
        Dua kali 100 menit adalah 3,33 jam, bukan 1,67 + 1,67 = 3,34.
        """
        period = self.make_month(2092, 6, 30)
        employee = self.make_employee(basic_salary="10000000")

        self.add_overtime(employee, day=5, minutes=100, period=period)
        self.add_overtime(employee, day=6, minutes=100, period=period)

        facts = PayrollSourceService.collect(
            employee=employee,
            start_date=period.start_date,
            end_date=period.end_date,
        )

        self.assertEqual(facts.overtime_hours, Decimal("3.33"))


class OvertimeRunTest(OvertimeTestCase):
    """Lembur bertingkat di atas run sungguhan."""

    def test_tingkat_dibaca_dari_group_pegawai(self):
        period = self.make_month(2093, 6, 30)
        employee = self.make_employee(
            basic_salary="10000000", overtime_eligible=True,
        )

        group = self.make_group("TIER", basis=OvertimeTierBasis.MONTHLY)
        self.add_tier(group, sequence=1, hour_from="0", hour_to="1", multiplier="1.5")
        self.add_tier(group, sequence=2, hour_from="1", hour_to=None, multiplier="2")

        self.attach_group(employee, group)

        self.add_overtime(employee, day=5, minutes=240, period=period)

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.overtime_hours, Decimal("4.00"))
        self.assertEqual(
            self.component(line, "OT").amount, Decimal("433526.01"),
        )

    def test_group_tanpa_tingkat_memakai_pengali_tunggalnya(self):
        """
        §6. Tenant yang belum mengonfigurasi tingkat tidak boleh
        mengalami perubahan angka sama sekali.
        """
        period = self.make_month(2094, 6, 30)
        employee = self.make_employee(
            basic_salary="10000000", overtime_eligible=True,
        )

        group = self.make_group("LEGACY", multiplier="1.5")
        self.attach_group(employee, group)

        self.add_overtime(employee, day=5, minutes=600, period=period)

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(
            self.component(line, "OT").amount, Decimal("867052.02"),
        )

    def test_konfigurasi_tingkat_cacat_jadi_temuan_run(self):
        period = self.make_month(2095, 6, 30)
        employee = self.make_employee(
            basic_salary="10000000", overtime_eligible=True,
        )

        group = self.make_group("CELAH", basis=OvertimeTierBasis.MONTHLY)
        self.add_tier(group, sequence=1, hour_from="0", hour_to="1", multiplier="1.5")
        self.add_tier(group, sequence=2, hour_from="2", hour_to=None, multiplier="2")

        self.attach_group(employee, group)
        self.add_overtime(employee, day=5, minutes=180, period=period)

        _, run = self.run_payroll(period=period, employee=employee)

        run.refresh_from_db()

        errors = {
            item["code"] for item in run.validation_summary.get("errors", [])
        }

        self.assertIn("overtime_tier_gap", errors)

    def test_tingkat_tanpa_basis_jadi_temuan_run(self):
        period = self.make_month(2096, 6, 30)
        employee = self.make_employee(
            basic_salary="10000000", overtime_eligible=True,
        )

        group = self.make_group("TANPA-BASIS")
        self.add_tier(group, sequence=1, hour_from="0", hour_to="1", multiplier="1.5")
        self.add_tier(group, sequence=2, hour_from="1", hour_to=None, multiplier="2")

        self.attach_group(employee, group)
        self.add_overtime(employee, day=5, minutes=180, period=period)

        _, run = self.run_payroll(period=period, employee=employee)

        run.refresh_from_db()

        errors = {
            item["code"] for item in run.validation_summary.get("errors", [])
        }

        self.assertIn("overtime_tier_basis_missing", errors)

    def test_f_join_tengah_periode_tarifnya_tetap_gaji_sebulan(self):
        period = self.make_month(2097, 6, 30)

        employee = self.make_employee(
            basic_salary="10000000",
            join_date=self.day_in(period, 16),
            overtime_eligible=True,
        )

        group = self.make_group("PRORATA", multiplier="1.5")
        self.attach_group(employee, group)

        self.add_overtime(employee, day=20, minutes=600, period=period)

        line, _ = self.run_payroll(period=period, employee=employee)

        # Gaji pokoknya diprorata, upah lemburnya tidak.
        self.assertLess(
            self.component(line, "BASIC").amount, Decimal("10000000.00"),
        )
        self.assertEqual(
            self.component(line, "OT").amount, Decimal("867052.02"),
        )
        self.assertEqual(
            self.component(line, "OT").base_amount, Decimal("10000000.00"),
        )


class OvertimeFinalizedImmunityTest(OvertimeTestCase):
    """
    H. Run yang sudah Finalized kebal terhadap perubahan aturan
    maupun sumbernya.
    """

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

    def test_h_mengubah_aturan_sesudah_final_tidak_mengubah_angkanya(self):
        period = self.make_month(2098, 6, 30)
        employee = self.make_employee(
            basic_salary="10000000", overtime_eligible=True,
        )

        group = self.make_group("BEKU", basis=OvertimeTierBasis.MONTHLY)
        first = self.add_tier(
            group, sequence=1, hour_from="0", hour_to="1", multiplier="1.5",
        )
        self.add_tier(
            group, sequence=2, hour_from="1", hour_to=None, multiplier="2",
        )

        self.attach_group(employee, group)
        overtime = self.add_overtime(
            employee, day=5, minutes=240, period=period,
        )

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        run = self.finalize(run)
        line = self.line_for(run, employee)

        self.assertEqual(
            self.component(line, "OT").amount, Decimal("433526.01"),
        )

        slip = Payslip.objects.get(run_employee=line)
        frozen = slip.snapshot["earnings"]

        # --- seluruh sumbernya diubah sesudah Finalize -------------
        overtime.status = OvertimeStatus.CANCELLED
        overtime.save(update_fields=["status"])

        first.multiplier = Decimal("9")
        first.save(update_fields=["multiplier"])

        group.hourly_multiplier = Decimal("9")
        group.hourly_divisor = Decimal("50")
        group.tier_basis = OvertimeTierBasis.DAILY
        group.save()

        PayrollAssignment.objects.filter(employee=employee).update(
            overtime_eligible=False, overtime_group=None,
        )

        line.refresh_from_db()

        self.assertEqual(
            self.component(line, "OT").amount, Decimal("433526.01"),
        )
        self.assertEqual(line.overtime_hours, Decimal("4.00"))

        slip.refresh_from_db()
        self.assertEqual(slip.snapshot["earnings"], frozen)
