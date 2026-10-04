"""
Business Decision #3A — BPJS jadi konsep kelas satu.

Yang diuji di sini **bentuknya**, bukan angkanya: tarif dan plafon
sebenarnya masih keputusan bisnis yang terbuka (#3B), jadi seluruh
angka di berkas ini dipilih supaya perhitungannya mudah dicocokkan
tangan — bukan karena ia benar menurut aturan mana pun.

Empat invarian yang paling mudah rusak, dan tiga di antaranya rusak
dengan diam:

* aturan yang berlaku adalah aturan **periode itu**, bukan yang
  terbaru — kalau salah, payroll bulan lalu yang dihitung ulang
  berubah tanpa ada yang menyunting apa pun;
* komposisi dasar yang sudah dipakai **tidak bisa berubah artinya**;
* lembur dan input variabel **tidak pernah** masuk dasar iuran;
* tidak terdaftar berarti **tidak ikut**, dan itu keadaan normal yang
  tidak menerbitkan temuan apa pun.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.hr.models import EmployeeOvertime
from apps.hr.models.overtime import OvertimeStatus
from apps.payroll.models import (
    BpjsBaseComponent,
    BpjsBaseDefinition,
    BpjsDailyBasicMethod,
    BpjsEnrollment,
    BpjsProgram,
    BpjsRiskClass,
    BpjsRule,
    PayrollBasis,
    PayrollComponentSource,
    PayrollComponentType,
    PayrollFindingLevel,
)
from apps.payroll.models import PayrollPeriod, PayrollRunStatus
from apps.payroll.services import PayrollRunService

from .test_payroll_flow import PayrollFlowTestCase


class BpjsTestCase(PayrollFlowTestCase):
    """Satu pegawai, satu program, angka yang mudah dicocokkan tangan."""

    def setUp(self):
        super().setUp()

        # Bersihkan sisa test lain: master BPJS berlaku untuk seluruh
        # tenant, dan `TenantTestCase` tidak me-rollback antar test.
        BpjsEnrollment.objects.all().delete()
        BpjsRule.objects.all().delete()
        BpjsBaseComponent.objects.all().delete()
        BpjsBaseDefinition.objects.all().delete()
        BpjsProgram.objects.all().delete()
        BpjsRiskClass.objects.all().delete()

        self.employee = self.make_employee()

    # ------------------------------------------------------------------
    # Pembantu
    # ------------------------------------------------------------------

    def make_program(self, code="JHT", **overrides):
        payload = {"code": code, "name": f"BPJS {code}"}
        payload.update(overrides)

        return BpjsProgram.objects.create(**payload)

    def make_base(
        self,
        code="UPAH-POKOK",
        version=1,
        include_basic=True,
        **overrides,
    ):
        payload = {
            "code": code,
            "version": version,
            "name": "Upah Pokok",
            "include_basic": include_basic,
        }
        payload.update(overrides)

        definition = BpjsBaseDefinition(**payload)
        definition.full_clean()
        definition.save()

        return definition

    def make_risk_class(self, code="RISK-A", **overrides):
        payload = {"code": code, "name": f"Kelas {code}"}
        payload.update(overrides)

        return BpjsRiskClass.objects.create(**payload)

    def make_rule(self, *, program=None, base=None, **overrides):
        payload = {
            "program": program or self.make_program(),
            "base_definition": base or self.make_base(),
            "company": None,
            "effective_from": date(2020, 1, 1),
            "employee_rate": Decimal("2"),
        }
        payload.update(overrides)

        rule = BpjsRule(**payload)
        rule.full_clean()
        rule.save()

        return rule

    def enroll(self, *, program, employee=None, **overrides):
        payload = {
            "employee": employee or self.employee,
            "program": program,
            "participates": True,
            "enrolled_from": date(2020, 1, 1),
            "membership_number": "123456789",
        }
        payload.update(overrides)

        enrollment = BpjsEnrollment(**payload)
        enrollment.full_clean()
        enrollment.save()

        return enrollment

    def calculated_line(self):
        run = self.make_run(self.make_period())

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        return run, self.line_for(run, self.employee)

    @staticmethod
    def finding_codes(line, level=None):
        return {
            item["code"]
            for item in (line.findings or [])
            if level is None or item["level"] == level
        }


class BpjsCalculationTest(BpjsTestCase):
    """A. Angkanya lahir, dan lewat mesin hitung yang sudah ada."""

    def test_iuran_pegawai_jadi_komponen_bersumber_bpjs(self):
        program = self.make_program()
        self.make_rule(program=program)
        self.enroll(program=program)

        _, line = self.calculated_line()

        component = self.component(line, "BPJS-JHT")

        self.assertEqual(component.source, PayrollComponentSource.BPJS)
        self.assertEqual(
            component.component_type, PayrollComponentType.DEDUCTION,
        )
        self.assertEqual(component.basis, PayrollBasis.PERCENT_OF_RESOLVED_BASE)

        # 2% dari gaji pokok kontraktual.
        self.assertEqual(
            component.amount,
            (line.basic_salary * Decimal("2") / Decimal("100"))
            .quantize(Decimal("0.01")),
        )

    def test_reference_menunjuk_aturannya(self):
        """
        Jejaknya menunjuk aturan, bukan baris template — itu yang
        membuat "angka ini lahir dari aturan mana" bisa dijawab
        setahun kemudian.
        """
        program = self.make_program()
        rule = self.make_rule(program=program)
        self.enroll(program=program)

        _, line = self.calculated_line()

        component = self.component(line, "BPJS-JHT")

        self.assertEqual(component.reference_type, "payroll.bpjs_rule")
        self.assertEqual(component.reference_id, str(rule.pk))

    def test_sisi_perusahaan_jadi_employer_contribution(self):
        program = self.make_program()
        self.make_rule(
            program=program,
            employee_rate=Decimal("2"),
            employer_rate=Decimal("3.7"),
        )
        self.enroll(program=program)

        _, line = self.calculated_line()

        employer = self.component(line, "BPJS-JHT-ER")

        self.assertEqual(
            employer.component_type,
            PayrollComponentType.EMPLOYER_CONTRIBUTION,
        )

        # Sisi perusahaan tidak pernah mengurangi pajak pegawai.
        self.assertFalse(employer.reduces_taxable)

        self.assertGreater(line.employer_contribution, Decimal("0"))

    def test_plafon_menjepit_dasar_bukan_hasilnya(self):
        """
        Bentuk plafon BPJS: "2% dari gaji, maksimal dari 5.000.000".
        Menjepit hasilnya menghasilkan angka yang berbeda.
        """
        program = self.make_program()
        self.make_rule(
            program=program,
            employee_rate=Decimal("2"),
            base_maximum=Decimal("5000000"),
        )
        self.enroll(program=program)

        _, line = self.calculated_line()

        component = self.component(line, "BPJS-JHT")

        self.assertEqual(component.base_amount, Decimal("5000000.00"))
        self.assertEqual(component.amount, Decimal("100000.00"))


class BpjsOptionalSidesTest(BpjsTestCase):
    """B. Sisi yang kosong tidak menerbitkan baris nol yang dikarang."""

    def test_program_bersisi_perusahaan_saja(self):
        program = self.make_program(code="JKK")
        self.make_rule(
            program=program,
            employee_rate=None,
            employer_rate=Decimal("0.24"),
        )
        self.enroll(program=program)

        _, line = self.calculated_line()

        codes = set(line.components.values_list("code", flat=True))

        self.assertIn("BPJS-JKK-ER", codes)

        # Inti test ini: **tidak ada** baris potongan pegawai bertarif
        # nol yang menempel di slip.
        self.assertNotIn("BPJS-JKK", codes)

    def test_program_bersisi_pegawai_saja(self):
        program = self.make_program(code="JP")
        self.make_rule(
            program=program,
            employee_rate=Decimal("1"),
            employer_rate=None,
        )
        self.enroll(program=program)

        _, line = self.calculated_line()

        codes = set(line.components.values_list("code", flat=True))

        self.assertIn("BPJS-JP", codes)
        self.assertNotIn("BPJS-JP-ER", codes)
        self.assertEqual(line.employer_contribution, Decimal("0.00"))

    def test_aturan_tanpa_satu_sisi_pun_ditolak(self):
        rule = BpjsRule(
            program=self.make_program(),
            base_definition=self.make_base(),
            effective_from=date(2020, 1, 1),
            employee_rate=None,
            employer_rate=None,
        )

        with self.assertRaises(ValidationError) as raised:
            rule.full_clean()

        self.assertIn("employee_rate", raised.exception.message_dict)


class BpjsEffectiveDateTest(BpjsTestCase):
    """C. Aturan periode itu, bukan aturan terbaru."""

    def test_aturan_yang_belum_berlaku_tidak_dipakai(self):
        program = self.make_program()
        base = self.make_base()

        self.make_rule(
            program=program,
            base=base,
            effective_from=date(2020, 1, 1),
            effective_to=date(2030, 12, 31),
            employee_rate=Decimal("2"),
        )

        # Berlaku jauh sesudah periode test.
        self.make_rule(
            program=program,
            base=base,
            effective_from=date(2031, 1, 1),
            employee_rate=Decimal("9"),
        )

        self.enroll(program=program)

        _, line = self.calculated_line()

        component = self.component(line, "BPJS-JHT")

        self.assertEqual(component.rate, Decimal("2.0000"))

    def test_aturan_yang_sudah_berakhir_tidak_dipakai(self):
        program = self.make_program()

        self.make_rule(
            program=program,
            effective_from=date(2019, 1, 1),
            effective_to=date(2019, 12, 31),
            employee_rate=Decimal("5"),
        )

        self.enroll(program=program)

        _, line = self.calculated_line()

        self.assertNotIn(
            "BPJS-JHT",
            set(line.components.values_list("code", flat=True)),
        )

        self.assertIn("bpjs_rule_missing", self.finding_codes(line))

    def test_rentang_yang_bertindih_ditolak(self):
        """
        Resolver yang menemukan dua aturan berlaku harus memilih, dan
        pilihan apa pun adalah tebakan. Yang benar: keadaan itu tidak
        pernah tersimpan.
        """
        program = self.make_program()
        base = self.make_base()

        self.make_rule(
            program=program,
            base=base,
            effective_from=date(2020, 1, 1),
            effective_to=date(2026, 12, 31),
        )

        overlapping = BpjsRule(
            program=program,
            base_definition=base,
            effective_from=date(2026, 6, 1),
            employee_rate=Decimal("3"),
        )

        with self.assertRaises(ValidationError) as raised:
            overlapping.full_clean()

        self.assertIn("effective_from", raised.exception.message_dict)


class BpjsCompanyOverrideTest(BpjsTestCase):
    """D. COMPANY → tenant, dan penggantian utuh."""

    def test_aturan_company_mengalahkan_bawaan_tenant(self):
        program = self.make_program()
        base = self.make_base()

        self.make_rule(
            program=program,
            base=base,
            company=None,
            employee_rate=Decimal("2"),
        )

        self.make_rule(
            program=program,
            base=base,
            company=self.company,
            employee_rate=Decimal("4"),
        )

        self.enroll(program=program)

        _, line = self.calculated_line()

        self.assertEqual(
            self.component(line, "BPJS-JHT").rate, Decimal("4.0000"),
        )

    def test_tanpa_aturan_company_jatuh_ke_bawaan_tenant(self):
        program = self.make_program()

        self.make_rule(
            program=program, company=None, employee_rate=Decimal("2"),
        )

        self.enroll(program=program)

        _, line = self.calculated_line()

        self.assertEqual(
            self.component(line, "BPJS-JHT").rate, Decimal("2.0000"),
        )


class BpjsBaseCompositionTest(BpjsTestCase):
    """E. Dasar iuran disusun, bukan dibaca dari gross."""

    def test_tunjangan_yang_disebut_ikut_jadi_dasar(self):
        program = self.make_program()

        base = self.make_base(include_basic=True)

        BpjsBaseComponent.objects.create(
            definition=base, allowance_code="TRANSPORT", sequence=1,
        )

        self.make_rule(
            program=program, base=base, employee_rate=Decimal("10"),
        )
        self.enroll(program=program)

        # Kehadirannya wajib ada: TRANSPORT berbasis per hari hadir,
        # dan tanpa kehadiran nilainya nol — pengujian yang
        # membandingkan "pokok + nol" lolos juga ketika komposisinya
        # dibuang mesin hitung.
        self.make_attendance(self.employee, days=20)

        _, line = self.calculated_line()

        transport = self.component(line, "TRANSPORT")
        component = self.component(line, "BPJS-JHT")

        # 20 hari x Rp 25.000
        self.assertEqual(transport.amount, Decimal("500000.00"))

        self.assertEqual(
            component.base_amount,
            line.basic_salary + transport.amount,
        )
        self.assertNotEqual(component.base_amount, line.basic_salary)

    def test_lembur_tidak_pernah_masuk_dasar(self):
        """
        Inti pemisahan dari `percent_of_gross`: lembur ada di gross,
        tapi tidak pernah jadi kandidat dasar iuran.

        Lemburnya harus benar-benar berbayar, kalau tidak pengujian ini
        cuma membuktikan bahwa nol tidak menambah apa-apa.
        """
        program = self.make_program()

        base = self.make_base(include_basic=True)

        # Menyebut kode komponen lembur sekalipun tidak membuatnya
        # masuk — sumbernya bukan tunjangan.
        BpjsBaseComponent.objects.create(
            definition=base, allowance_code="OT", sequence=1,
        )

        self.make_rule(
            program=program, base=base, employee_rate=Decimal("10"),
        )

        self.employee = self.make_employee(overtime_eligible=True)
        self.make_attendance(self.employee, days=20)

        EmployeeOvertime.objects.create(
            employee=self.employee,
            company=self.company,
            work_date=date(2026, 9, 10),
            start_time="18:00",
            end_time="20:00",
            duration_minutes=120,
            status=OvertimeStatus.APPROVED,
            is_paid=True,
        )

        self.enroll(program=program)

        _, line = self.calculated_line()

        component = self.component(line, "BPJS-JHT")

        # Lembur ada, masuk gross, dan tetap di luar dasar iuran.
        self.assertGreater(self.component(line, "OT").amount, Decimal("0"))
        self.assertGreater(line.gross_earning, line.basic_salary)
        self.assertEqual(component.base_amount, line.basic_salary)

    def test_dasar_memakai_gaji_pokok_kontraktual(self):
        """
        Keputusan #3A butir 4: yang dipakai gaji pokok sebulan menurut
        kontrak, bukan yang sudah diprorata. Prorata dasar iuran adalah
        #3B dan belum diputuskan.
        """
        program = self.make_program()
        self.make_rule(program=program, employee_rate=Decimal("10"))
        self.enroll(program=program)

        _, line = self.calculated_line()

        component = self.component(line, "BPJS-JHT")

        self.assertEqual(component.base_amount, line.basic_salary)

    def test_dasar_nol_menerbitkan_peringatan(self):
        """
        Iuran nol yang lahir dari dasar nol tidak terlihat salah di
        layar mana pun. Pegawai harian adalah kasus nyatanya: gaji
        pokok bulanannya memang kosong.

        Peringatan, bukan penolakan — perlakuan pegawai harian masih
        keputusan #3B yang terbuka.
        """
        program = self.make_program()
        self.make_rule(program=program, employee_rate=Decimal("2"))

        self.employee = self.make_employee(basic_salary="0")
        self.enroll(program=program)

        _, line = self.calculated_line()

        self.assertEqual(
            self.component(line, "BPJS-JHT").amount, Decimal("0.00"),
        )
        self.assertIn(
            "bpjs_base_zero",
            self.finding_codes(line, PayrollFindingLevel.WARNING),
        )

    def test_dasar_nol_yang_punya_lantai_tidak_diperingatkan(self):
        """
        Aturan berlantai upah minimum menjepit dasarnya naik, jadi
        iurannya tidak pernah nol dan peringatannya cuma derau.
        """
        program = self.make_program()
        self.make_rule(
            program=program,
            employee_rate=Decimal("2"),
            base_minimum=Decimal("5000000"),
        )

        self.employee = self.make_employee(basic_salary="0")
        self.enroll(program=program)

        _, line = self.calculated_line()

        component = self.component(line, "BPJS-JHT")

        self.assertEqual(component.base_amount, Decimal("5000000.00"))
        self.assertEqual(component.amount, Decimal("100000.00"))
        self.assertNotIn("bpjs_base_zero", self.finding_codes(line))

    def test_kode_komponen_tak_dikenal_menerbitkan_peringatan(self):
        program = self.make_program()

        base = self.make_base()

        BpjsBaseComponent.objects.create(
            definition=base, allowance_code="TIDAK-ADA", sequence=1,
        )

        self.make_rule(program=program, base=base)
        self.enroll(program=program)

        _, line = self.calculated_line()

        self.assertIn(
            "bpjs_base_component_unknown",
            self.finding_codes(line, PayrollFindingLevel.WARNING),
        )


class BpjsBaseVersioningTest(BpjsTestCase):
    """
    F. Komposisi yang sudah dirujuk tidak bisa berubah artinya.

    Dan kekunciannya **tidak bergantung tanggal**: aturan yang baru
    berlaku tahun depan pun sudah mengunci komposisinya begitu
    tersimpan. Kalau kekuncian bergantung "sudah lewat atau belum",
    arti masa lalu berubah karena waktu berjalan — dan hasil test
    bergantung kapan ia dijalankan.
    """

    def test_komposisi_yang_dirujuk_tidak_bisa_disunting(self):
        base = self.make_base()

        self.make_rule(base=base)

        base.include_basic = False

        with self.assertRaises(ValidationError) as raised:
            base.full_clean()

        self.assertIn("include_basic", raised.exception.message_dict)

    def test_komponen_tidak_bisa_ditambah_ke_komposisi_yang_dirujuk(self):
        base = self.make_base()

        self.make_rule(base=base)

        component = BpjsBaseComponent(
            definition=base, allowance_code="TRANSPORT", sequence=1,
        )

        with self.assertRaises(ValidationError):
            component.full_clean()

    def test_kekunciannya_tidak_bergantung_tanggal_berlaku(self):
        """
        Aturan yang **baru berlaku jauh di depan** tetap mengunci
        komposisinya. Yang mengunci adanya rujukan, bukan berlalunya
        waktu.
        """
        base = self.make_base()

        self.make_rule(base=base, effective_from=date(2099, 1, 1))

        base.include_basic = False

        with self.assertRaises(ValidationError):
            base.full_clean()

    def test_versi_baru_tidak_mengubah_aturan_lama(self):
        program = self.make_program()

        v1 = self.make_base(version=1, include_basic=True)

        rule = self.make_rule(
            program=program, base=v1, employee_rate=Decimal("10"),
        )

        v2 = self.make_base(version=2, include_basic=False)

        BpjsBaseComponent.objects.create(
            definition=v2, allowance_code="TRANSPORT", sequence=1,
        )

        self.enroll(program=program)

        _, line = self.calculated_line()

        # Aturan lama masih menunjuk v1, jadi dasarnya masih gaji pokok.
        rule.refresh_from_db()

        self.assertEqual(rule.base_definition_id, v1.pk)
        self.assertEqual(
            self.component(line, "BPJS-JHT").base_amount, line.basic_salary,
        )
        self.assertNotEqual(v1.pk, v2.pk)


class BpjsEnrollmentTest(BpjsTestCase):
    """G. Tidak terdaftar = tidak ikut, dan itu bukan temuan."""

    def test_tanpa_kepesertaan_tidak_ada_iuran_dan_tidak_ada_temuan(self):
        program = self.make_program()
        self.make_rule(program=program)

        _, line = self.calculated_line()

        self.assertNotIn(
            "BPJS-JHT",
            set(line.components.values_list("code", flat=True)),
        )

        # Inti keputusannya: ketiadaan baris adalah keadaan normal yang
        # sah, jadi ia tidak menerbitkan temuan apa pun.
        codes = self.finding_codes(line)

        self.assertNotIn("bpjs_rule_missing", codes)
        self.assertNotIn("bpjs_enrollment_missing", codes)

    def test_kepesertaan_dimatikan_tidak_menghitung(self):
        program = self.make_program()
        self.make_rule(program=program)
        self.enroll(program=program, participates=False)

        _, line = self.calculated_line()

        self.assertNotIn(
            "BPJS-JHT",
            set(line.components.values_list("code", flat=True)),
        )

    def test_kepesertaan_yang_sudah_berakhir_tidak_menghitung(self):
        program = self.make_program()
        self.make_rule(program=program)
        self.enroll(
            program=program,
            enrolled_from=date(2019, 1, 1),
            enrolled_to=date(2019, 12, 31),
        )

        _, line = self.calculated_line()

        self.assertNotIn(
            "BPJS-JHT",
            set(line.components.values_list("code", flat=True)),
        )

    def test_nomor_kepesertaan_kosong_tetap_dihitung_dengan_peringatan(self):
        program = self.make_program()
        self.make_rule(program=program)
        self.enroll(program=program, membership_number="")

        _, line = self.calculated_line()

        self.assertIn(
            "BPJS-JHT",
            set(line.components.values_list("code", flat=True)),
        )

        self.assertIn(
            "bpjs_membership_missing",
            self.finding_codes(line, PayrollFindingLevel.WARNING),
        )


class BpjsMissingRuleTest(BpjsTestCase):
    """H. Peserta tanpa aturan: ERROR, dan Finalize tertahan."""

    def test_peserta_tanpa_aturan_menerbitkan_error(self):
        program = self.make_program()
        self.enroll(program=program)

        _, line = self.calculated_line()

        self.assertIn(
            "bpjs_rule_missing",
            self.finding_codes(line, PayrollFindingLevel.ERROR),
        )

        # Dan **tidak** ada iuran nol yang dikarang.
        self.assertNotIn(
            "BPJS-JHT",
            set(line.components.values_list("code", flat=True)),
        )

    def test_submit_dan_finalize_tertahan(self):
        from apps.payroll.services import PayrollValidationService

        program = self.make_program()
        self.enroll(program=program)

        run, _ = self.calculated_line()

        summary = PayrollValidationService.validate(run=run)

        codes = {item["code"] for item in summary["errors"]}

        self.assertIn("bpjs_rule_missing", codes)

        # Pintu bersama Submit dan Finalize ada di `PayrollRunService`,
        # dan temuan mesin hitung dinaikkan ke ringkasan run dengan
        # levelnya utuh — jadi ERROR di sini benar-benar menahan
        # keduanya, tanpa gerbang baru.
        with self.assertRaises(ValidationError):
            PayrollRunService.assert_ready(run)


class BpjsEngineUntouchedTest(BpjsTestCase):
    """
    I. Mesin hitung tetap satu.

    Yang membuktikannya bukan ketiadaan berkas kedua, melainkan bahwa
    angka BPJS tunduk pada aturan yang sama dengan potongan lain: net
    tetap gross dikurangi potongan, dan iuran pegawai yang
    `reduces_taxable` benar-benar mengurangi dasar pajak lewat `_tax`
    yang tidak diubah.
    """

    def test_net_tetap_gross_dikurangi_potongan(self):
        program = self.make_program()
        self.make_rule(
            program=program,
            employee_rate=Decimal("2"),
            employer_rate=Decimal("3.7"),
        )
        self.enroll(program=program)

        _, line = self.calculated_line()

        self.assertEqual(
            line.net_pay, line.gross_earning - line.total_deduction,
        )

    def test_reduces_taxable_menurunkan_pajak(self):
        # Tenant pengujian tidak punya baris PPh21 di template
        # bawaannya, jadi `tax_amount` selalu nol dan perbandingan
        # apa pun lolos dengan sendirinya. Barisnya ditambahkan di
        # sini dan dibuang lagi setelahnya: template ini dipakai
        # bersama seluruh berkas pengujian payroll, dan
        # `TenantTestCase` tidak me-rollback antar test.
        from apps.payroll.models import DeductionTemplateLine

        pph21 = DeductionTemplateLine.objects.create(
            template=self.deduction_template,
            code="PPH21",
            name="PPh 21",
            sequence=90,
            basis=PayrollBasis.PPH21_PROGRESSIVE,
        )
        self.addCleanup(
            DeductionTemplateLine.objects.filter(pk=pph21.pk).delete,
        )

        program = self.make_program()

        rule = self.make_rule(
            program=program,
            employee_rate=Decimal("2"),
            reduces_taxable=False,
        )

        run = self.make_run(self.make_period())

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        self.enroll(program=program)

        PayrollRunService.calculate(run=run)

        without = self.line_for(run, self.employee).tax_amount

        BpjsRule.objects.filter(pk=rule.pk).update(reduces_taxable=True)

        PayrollRunService.calculate(run=run)

        with_reducer = self.line_for(run, self.employee).tax_amount

        self.assertGreater(without, Decimal("0"))
        self.assertLess(with_reducer, without)


class BpjsMasterLineGuardTest(BpjsTestCase):
    """J. Basis resolver tidak boleh ditulis di layar master."""

    def test_deduction_template_line_menolak_basis_resolver(self):
        from apps.payroll.models import DeductionTemplateLine

        line = DeductionTemplateLine(
            template=self.deduction_template,
            code="SALAH",
            name="Salah basis",
            sequence=99,
            basis=PayrollBasis.PERCENT_OF_RESOLVED_BASE,
            rate=Decimal("1"),
        )

        with self.assertRaises(ValidationError) as raised:
            line.full_clean()

        self.assertIn("basis", raised.exception.message_dict)


# ======================================================================
# Business Decision #3B.1 — infrastruktur regulasi yang dinamis
# ======================================================================


class BpjsRiskClassGuardTest(BpjsTestCase):
    """
    K. Kelas risiko wajib pada program yang memakainya, dilarang pada
    yang tidak.

    Dijaga di kedua sisi karena kegagalannya asimetris tapi sama-sama
    diam: kelas yang lupa diisi membuat resolver tidak menemukan aturan,
    dan kelas yang terisi pada program yang tidak mengenalnya membuat
    aturan tidak pernah terpilih.
    """

    def test_kepesertaan_program_risiko_wajib_berkelas(self):
        program = self.make_program(code="JKK", uses_risk_class=True)

        enrollment = BpjsEnrollment(
            employee=self.employee,
            program=program,
            enrolled_from=date(2020, 1, 1),
        )

        with self.assertRaises(ValidationError) as raised:
            enrollment.full_clean()

        self.assertIn("risk_class", raised.exception.message_dict)

    def test_kepesertaan_program_biasa_menolak_kelas(self):
        program = self.make_program(code="JHT")
        risk = self.make_risk_class()

        enrollment = BpjsEnrollment(
            employee=self.employee,
            program=program,
            enrolled_from=date(2020, 1, 1),
            risk_class=risk,
        )

        with self.assertRaises(ValidationError) as raised:
            enrollment.full_clean()

        self.assertIn("risk_class", raised.exception.message_dict)

    def test_aturan_program_risiko_wajib_berkelas(self):
        program = self.make_program(code="JKK", uses_risk_class=True)

        rule = BpjsRule(
            program=program,
            base_definition=self.make_base(),
            company=None,
            effective_from=date(2020, 1, 1),
            employer_rate=Decimal("1"),
        )

        with self.assertRaises(ValidationError) as raised:
            rule.full_clean()

        self.assertIn("risk_class", raised.exception.message_dict)

    def test_aturan_program_biasa_menolak_kelas(self):
        program = self.make_program(code="JHT")
        risk = self.make_risk_class()

        rule = BpjsRule(
            program=program,
            base_definition=self.make_base(),
            company=None,
            effective_from=date(2020, 1, 1),
            employee_rate=Decimal("2"),
            risk_class=risk,
        )

        with self.assertRaises(ValidationError) as raised:
            rule.full_clean()

        self.assertIn("risk_class", raised.exception.message_dict)

    def test_dua_kelas_boleh_berlaku_bersamaan(self):
        """
        Inti kasus JKK: satu perusahaan, dua populasi, dua tarif, pada
        rentang tanggal yang sama. Validasi tumpang tindih tidak boleh
        membacanya sebagai bentrokan.
        """
        program = self.make_program(code="JKK", uses_risk_class=True)
        base = self.make_base()

        first = self.make_risk_class(code="RISK-A")
        second = self.make_risk_class(code="RISK-B")

        self.make_rule(
            program=program,
            base=base,
            risk_class=first,
            employee_rate=None,
            employer_rate=Decimal("1"),
        )

        # Tidak melempar.
        self.make_rule(
            program=program,
            base=base,
            risk_class=second,
            employee_rate=None,
            employer_rate=Decimal("5"),
        )

        self.assertEqual(BpjsRule.objects.filter(program=program).count(), 2)


class BpjsRiskResolutionTest(BpjsTestCase):
    """
    L. Resolusi kelas risiko **ketat**.

    Yang dijaga di sini satu kalimat: tarif risiko yang salah kelas
    tetap menghasilkan angka yang kelihatan wajar. Karena itu tidak ada
    jatuh-tempo ke aturan umum dan tidak ada pinjam-tarif antar kelas —
    tidak ketemu berarti ERROR.
    """

    def setUp(self):
        super().setUp()

        self.program = self.make_program(code="JKK", uses_risk_class=True)
        self.base = self.make_base()
        self.risk_a = self.make_risk_class(code="RISK-A")
        self.risk_b = self.make_risk_class(code="RISK-B")

    def test_company_dengan_kelas_persis_menang(self):
        self.make_rule(
            program=self.program,
            base=self.base,
            risk_class=self.risk_a,
            company=None,
            employee_rate=None,
            employer_rate=Decimal("1"),
        )
        self.make_rule(
            program=self.program,
            base=self.base,
            risk_class=self.risk_a,
            company=self.company,
            employee_rate=None,
            employer_rate=Decimal("7"),
        )

        self.enroll(program=self.program, risk_class=self.risk_a)

        _, line = self.calculated_line()

        component = self.component(line, "BPJS-JKK-ER")

        # 7% dari gaji pokok, bukan 1%.
        self.assertEqual(
            component.amount,
            (line.basic_salary * Decimal("7") / Decimal("100"))
            .quantize(Decimal("0.01")),
        )

    def test_global_dengan_kelas_sama_dipakai_saat_company_tidak_ada(self):
        self.make_rule(
            program=self.program,
            base=self.base,
            risk_class=self.risk_a,
            company=None,
            employee_rate=None,
            employer_rate=Decimal("3"),
        )

        self.enroll(program=self.program, risk_class=self.risk_a)

        _, line = self.calculated_line()

        self.assertEqual(
            self.component(line, "BPJS-JKK-ER").amount,
            (line.basic_salary * Decimal("3") / Decimal("100"))
            .quantize(Decimal("0.01")),
        )

    def test_tidak_jatuh_ke_aturan_kelas_lain(self):
        """
        Ada aturan JKK yang berlaku — tapi untuk kelas yang berbeda.
        Meminjamnya berarti menagih perusahaan dengan tarif risiko yang
        bukan risikonya.
        """
        self.make_rule(
            program=self.program,
            base=self.base,
            risk_class=self.risk_b,
            company=None,
            employee_rate=None,
            employer_rate=Decimal("5"),
        )

        self.enroll(program=self.program, risk_class=self.risk_a)

        _, line = self.calculated_line()

        codes = set(line.components.values_list("code", flat=True))

        self.assertNotIn("BPJS-JKK-ER", codes)
        self.assertIn(
            "bpjs_rule_missing",
            self.finding_codes(line, PayrollFindingLevel.ERROR),
        )

    def test_tidak_ada_aturan_kelas_menerbitkan_error(self):
        self.enroll(program=self.program, risk_class=self.risk_a)

        _, line = self.calculated_line()

        self.assertIn(
            "bpjs_rule_missing",
            self.finding_codes(line, PayrollFindingLevel.ERROR),
        )

    def test_pesan_errornya_menyebut_kelasnya(self):
        """
        Tanpa menyebut kelasnya, operator melihat aturan JKK yang sudah
        ada lalu menyangka temuannya keliru.
        """
        self.enroll(program=self.program, risk_class=self.risk_a)

        _, line = self.calculated_line()

        message = next(
            item["message"]
            for item in line.findings
            if item["code"] == "bpjs_rule_missing"
        )

        self.assertIn("RISK-A", message)

    def test_program_biasa_tetap_company_lalu_global(self):
        program = self.make_program(code="JHT")

        self.make_rule(
            program=program, base=self.base, company=None,
            employee_rate=Decimal("2"),
        )
        self.make_rule(
            program=program, base=self.base, company=self.company,
            employee_rate=Decimal("9"),
        )

        self.enroll(program=program)

        _, line = self.calculated_line()

        self.assertEqual(
            self.component(line, "BPJS-JHT").amount,
            (line.basic_salary * Decimal("9") / Decimal("100"))
            .quantize(Decimal("0.01")),
        )


class BpjsRiskHistoryTest(BpjsTestCase):
    """
    M. Perpindahan kelas tidak menulis ulang masa lalu.

    Kelas menempel di kepesertaan yang bertanggal berlaku justru untuk
    ini: reklasifikasi hari ini tidak boleh mengubah JKK periode yang
    sudah lewat.
    """

    def test_periode_lama_tetap_memakai_kelas_yang_berlaku_waktu_itu(self):
        program = self.make_program(code="JKK", uses_risk_class=True)
        base = self.make_base()

        low = self.make_risk_class(code="RISK-A")
        high = self.make_risk_class(code="RISK-E")

        self.make_rule(
            program=program, base=base, risk_class=low,
            employee_rate=None, employer_rate=Decimal("1"),
        )
        self.make_rule(
            program=program, base=base, risk_class=high,
            employee_rate=None, employer_rate=Decimal("5"),
        )

        # Kelas rendah sampai akhir Agustus 2026, kelas tinggi sesudahnya.
        self.enroll(
            program=program,
            risk_class=low,
            enrolled_from=date(2020, 1, 1),
            enrolled_to=date(2026, 8, 31),
        )
        self.enroll(
            program=program,
            risk_class=high,
            enrolled_from=date(2026, 9, 1),
        )

        # Periode pengujian bakunya September 2026 → kelas tinggi.
        _, line = self.calculated_line()

        self.assertEqual(
            self.component(line, "BPJS-JKK-ER").amount,
            (line.basic_salary * Decimal("5") / Decimal("100"))
            .quantize(Decimal("0.01")),
        )

        # Periode Agustus 2026 → kelas rendah, meski kepesertaan
        # terbarunya sudah kelas tinggi.
        august = PayrollPeriod.objects.create(
            company=self.company,
            payroll_group=self.payroll_group,
            code="2026-08-BPJS-RISK",
            name="Agustus 2026",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            payment_date=date(2026, 9, 5),
            working_days=30,
        )

        run = self.make_run(august)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        old_line = self.line_for(run, self.employee)

        self.assertEqual(
            self.component(old_line, "BPJS-JKK-ER").amount,
            (old_line.basic_salary * Decimal("1") / Decimal("100"))
            .quantize(Decimal("0.01")),
        )


class BpjsDailyBaseTest(BpjsTestCase):
    """
    N. Dasar iuran pegawai harian — **kemampuannya**, bukan angkanya.

    Tidak ada satu pun pengali yang dipilihkan sistem: 21, 25, dan 30
    sama-sama dipakai orang, dan yang benar ditentukan regulasi yang
    belum diverifikasi (#3B.2).
    """

    def make_daily_setup(self, *, method, factor=None, daily_rate="200000"):
        from apps.payroll.models import PayrollPayBasis, PayrollPolicy
        from apps.payroll.models import PayrollDailyRateMethod
        from apps.hr.models import PayrollAssignment

        type(self)._counter += 1

        policy = PayrollPolicy(
            company=self.company,
            code=f"BPJSDAILY{type(self)._counter}",
            name="Harian",
            pay_basis=PayrollPayBasis.DAILY,
            daily_rate_method=PayrollDailyRateMethod.ASSIGNMENT_RATE,
            pay_paid_leave="no",
        )
        policy.full_clean()
        policy.save()

        self.employee = self.make_employee(basic_salary="0")

        assignment = PayrollAssignment.objects.get(
            employee=self.employee, is_current=True, is_deleted=False,
        )
        assignment.payroll_policy = policy
        assignment.daily_rate = Decimal(daily_rate)
        assignment.full_clean()
        assignment.save()

        base = self.make_base(
            daily_basic_method=method,
            daily_basic_factor=factor,
        )

        program = self.make_program()
        self.make_rule(program=program, base=base, employee_rate=Decimal("10"))
        self.enroll(program=program)

        return program

    def test_none_mempertahankan_peringatan_dasar_nol(self):
        self.make_daily_setup(method=BpjsDailyBasicMethod.NONE)

        _, line = self.calculated_line()

        self.assertEqual(
            self.component(line, "BPJS-JHT").amount, Decimal("0.00"),
        )
        self.assertIn(
            "bpjs_base_zero",
            self.finding_codes(line, PayrollFindingLevel.WARNING),
        )

    def test_upah_harian_kali_pengali_memakai_pengali_yang_dikonfigurasi(self):
        self.make_daily_setup(
            method=BpjsDailyBasicMethod.DAILY_RATE_X_FACTOR,
            factor=Decimal("25"),
            daily_rate="200000",
        )

        _, line = self.calculated_line()

        component = self.component(line, "BPJS-JHT")

        # 200.000 x 25 = 5.000.000 → 10% = 500.000
        self.assertEqual(component.base_amount, Decimal("5000000.00"))
        self.assertEqual(component.amount, Decimal("500000.00"))
        self.assertNotIn("bpjs_base_zero", self.finding_codes(line))

    def test_pengali_lain_menghasilkan_angka_lain(self):
        """
        Yang membuktikan pengalinya benar-benar dibaca dari konfigurasi,
        bukan dari angka yang tertulis di kode.
        """
        self.make_daily_setup(
            method=BpjsDailyBasicMethod.DAILY_RATE_X_FACTOR,
            factor=Decimal("21"),
            daily_rate="200000",
        )

        _, line = self.calculated_line()

        # 200.000 x 21 = 4.200.000 → 10% = 420.000
        self.assertEqual(
            self.component(line, "BPJS-JHT").base_amount,
            Decimal("4200000.00"),
        )

    def test_hari_dibayar_kali_upah_harian_memakai_hari_sungguhan(self):
        self.make_daily_setup(
            method=BpjsDailyBasicMethod.PAID_DAYS_X_DAILY_RATE,
            daily_rate="200000",
        )

        self.make_attendance(self.employee, days=18)

        _, line = self.calculated_line()

        component = self.component(line, "BPJS-JHT")

        # 18 hari dibayar x 200.000 = 3.600.000 → 10% = 360.000
        self.assertEqual(component.base_amount, Decimal("3600000.00"))
        self.assertEqual(component.amount, Decimal("360000.00"))

    def test_pengali_wajib_diisi_untuk_cara_pengali(self):
        definition = BpjsBaseDefinition(
            code="UPAH-HARIAN",
            version=1,
            name="Upah Harian",
            daily_basic_method=BpjsDailyBasicMethod.DAILY_RATE_X_FACTOR,
        )

        with self.assertRaises(ValidationError) as raised:
            definition.full_clean()

        self.assertIn("daily_basic_factor", raised.exception.message_dict)

    def test_pegawai_bulanan_tidak_terpengaruh_cara_harian(self):
        base = self.make_base(
            daily_basic_method=BpjsDailyBasicMethod.DAILY_RATE_X_FACTOR,
            daily_basic_factor=Decimal("25"),
        )

        program = self.make_program()
        self.make_rule(program=program, base=base, employee_rate=Decimal("10"))
        self.enroll(program=program)

        _, line = self.calculated_line()

        self.assertEqual(
            self.component(line, "BPJS-JHT").base_amount, line.basic_salary,
        )


class BpjsRuleLifecycleTest(BpjsTestCase):
    """
    O. Sejarah aturan dikendalikan tanggal, bukan saklar aktif.

    `is_active` tidak bertanggal: mematikannya menghapus aturan dari
    **seluruh** penghitungan ulang, termasuk periode yang aturan itu
    memang berlaku.
    """

    def test_close_and_publish_menutup_yang_lama_dan_menerbitkan_baru(self):
        from apps.payroll.services import BpjsRuleService

        program = self.make_program()
        base = self.make_base()

        old = self.make_rule(
            program=program, base=base, employee_rate=Decimal("2"),
        )

        new = BpjsRuleService.close_and_publish(
            rule=old,
            data={
                "effective_from": date(2026, 9, 1),
                "employee_rate": Decimal("3"),
            },
        )

        old.refresh_from_db()

        self.assertEqual(old.effective_to, date(2026, 8, 31))
        self.assertEqual(new.effective_from, date(2026, 9, 1))
        self.assertEqual(new.employee_rate, Decimal("3.0000"))
        self.assertTrue(old.is_active)

    def test_periode_lama_tetap_memakai_aturan_lama(self):
        from apps.payroll.services import BpjsRuleService

        program = self.make_program()
        base = self.make_base()

        old = self.make_rule(
            program=program, base=base, employee_rate=Decimal("2"),
        )
        self.enroll(program=program)

        BpjsRuleService.close_and_publish(
            rule=old,
            data={
                "effective_from": date(2026, 9, 1),
                "employee_rate": Decimal("3"),
            },
        )

        august = PayrollPeriod.objects.create(
            company=self.company,
            payroll_group=self.payroll_group,
            code="2026-08-BPJS-LIFE",
            name="Agustus 2026",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            payment_date=date(2026, 9, 5),
            working_days=30,
        )

        run = self.make_run(august)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        old_line = self.line_for(run, self.employee)

        # Agustus tetap 2%, meski aturan 3% sudah terbit.
        self.assertEqual(
            self.component(old_line, "BPJS-JHT").amount,
            (old_line.basic_salary * Decimal("2") / Decimal("100"))
            .quantize(Decimal("0.01")),
        )

        # September memakai yang baru.
        _, line = self.calculated_line()

        self.assertEqual(
            self.component(line, "BPJS-JHT").amount,
            (line.basic_salary * Decimal("3") / Decimal("100"))
            .quantize(Decimal("0.01")),
        )

    def test_close_and_publish_menolak_tanggal_mundur(self):
        from apps.payroll.services import BpjsRuleService

        program = self.make_program()
        old = self.make_rule(program=program, employee_rate=Decimal("2"))

        with self.assertRaises(ValidationError):
            BpjsRuleService.close_and_publish(
                rule=old,
                data={
                    "effective_from": date(2019, 1, 1),
                    "employee_rate": Decimal("3"),
                },
            )

    def test_aturan_yang_sudah_dipakai_tidak_bisa_dinonaktifkan(self):
        from apps.payroll.services import BpjsRuleService

        program = self.make_program()
        rule = self.make_rule(program=program, employee_rate=Decimal("2"))
        self.enroll(program=program)

        self.calculated_line()

        with self.assertRaises(ValidationError) as raised:
            BpjsRuleService.update(
                instance=rule, data={"is_active": False},
            )

        self.assertIn("is_active", raised.exception.message_dict)

    def test_aturan_yang_sudah_dipakai_tidak_bisa_dihapus(self):
        from apps.payroll.services import BpjsRuleService

        program = self.make_program()
        rule = self.make_rule(program=program, employee_rate=Decimal("2"))
        self.enroll(program=program)

        self.calculated_line()

        with self.assertRaises(ValidationError):
            BpjsRuleService.soft_delete(instance=rule)

    def test_run_finalized_tidak_berubah_saat_aturan_diganti(self):
        from apps.payroll.services import BpjsRuleService

        program = self.make_program()
        rule = self.make_rule(program=program, employee_rate=Decimal("2"))
        self.enroll(program=program)

        run, line = self.calculated_line()

        before = self.component(line, "BPJS-JHT").amount

        run.status = PayrollRunStatus.FINALIZED
        run.save(update_fields=["status"])

        BpjsRuleService.close_and_publish(
            rule=rule,
            data={
                "effective_from": date(2026, 9, 1),
                "employee_rate": Decimal("9"),
            },
        )

        line.refresh_from_db()

        self.assertEqual(self.component(line, "BPJS-JHT").amount, before)


# ======================================================================
# Business Decision #3B.2 — konfigurasi statuter yang terverifikasi
# ======================================================================


class BpjsStatutoryPublishTest(BpjsTestCase):
    """
    P. Angka statuter hidup sebagai **konfigurasi**, bukan konstanta.

    Yang diuji di sini dua hal sekaligus: perintah publikasinya
    menerbitkan aturan yang benar, dan mesin hitung menghasilkan angka
    itu tanpa satu baris pun tarif tertulis di dalamnya.

    Angka-angkanya terverifikasi dari teks primer (#3B.2) — bukan dari
    data peragaan, dan bukan dari nilai yang kebetulan cocok.
    """

    def publish(self, *, codes=("TRANSPORT",), effective_from="2026-01-01"):
        from django.core.management import call_command

        args = ["bpjs_publish_statutory", "--apply", "--global"]

        for code in codes:
            args.extend(["--fixed-allowance", code])

        if not codes:
            args.append("--no-fixed-allowance")

        args.extend(["--effective-from", effective_from])

        call_command(*args, verbosity=0)

    # ------------------------------------------------------------------
    # Bentuk konfigurasinya
    # ------------------------------------------------------------------

    def test_program_terbit_tanpa_jkp(self):
        self.publish()

        codes = set(
            BpjsProgram.objects.filter(is_deleted=False)
            .values_list("code", flat=True),
        )

        self.assertEqual(codes, {"JHT", "JP", "JKK", "JKM", "JKN"})

        # JKP sengaja tidak ada: representasi penagihannya belum
        # terjawab, dan menebaknya salah di atas plafon Rp5.000.000.
        self.assertNotIn("JKP", codes)

    def test_jkn_terbit_tanpa_aturan(self):
        """
        Plafonnya terverifikasi, tarifnya tidak. Aturan bertarif nol
        yang dikarang adalah persis yang dilarang keputusan #3A butir 2.
        """
        self.publish()

        program = BpjsProgram.objects.get(code="JKN", is_deleted=False)

        self.assertFalse(
            BpjsRule.objects.filter(program=program, is_deleted=False).exists(),
        )
        self.assertIn("12.000.000", program.description)

    def test_lima_kelas_risiko_jkk(self):
        self.publish()

        program = BpjsProgram.objects.get(code="JKK", is_deleted=False)

        self.assertTrue(program.uses_risk_class)

        rates = sorted(
            BpjsRule.objects
            .filter(program=program, is_deleted=False)
            .values_list("employer_rate", flat=True),
        )

        self.assertEqual(
            [str(rate) for rate in rates],
            ["0.1000", "0.4000", "0.7500", "1.1300", "1.6000"],
        )

        # Sisi pegawai tidak pernah dikarang untuk JKK.
        self.assertTrue(
            all(
                rule.employee_rate is None
                for rule in BpjsRule.objects.filter(
                    program=program, is_deleted=False,
                )
            ),
        )

    def test_jp_berlaku_maret_2026_dengan_plafonnya(self):
        self.publish(effective_from="2026-01-01")

        rule = BpjsRule.objects.get(
            program__code="JP", is_deleted=False,
        )

        # Plafonnya baru berlaku Maret 2026, jadi aturannya pun begitu —
        # bukan tanggal yang dioper operator untuk program lain.
        self.assertEqual(rule.effective_from, date(2026, 3, 1))
        self.assertEqual(rule.base_maximum, Decimal("11086300.00"))
        self.assertEqual(rule.employee_rate, Decimal("1.0000"))
        self.assertEqual(rule.employer_rate, Decimal("2.0000"))

    def test_jp_memakai_komposisi_tanpa_cara_harian(self):
        """
        PP 45/2015 Pasal 29 tidak memuat ketentuan harian sama sekali.
        Memakai x25 di JP berarti mengarang aturan.
        """
        self.publish()

        jp = BpjsRule.objects.get(program__code="JP", is_deleted=False)
        jht = BpjsRule.objects.get(program__code="JHT", is_deleted=False)

        self.assertEqual(
            jp.base_definition.daily_basic_method,
            BpjsDailyBasicMethod.NONE,
        )
        self.assertEqual(
            jht.base_definition.daily_basic_method,
            BpjsDailyBasicMethod.DAILY_RATE_X_FACTOR,
        )
        self.assertEqual(jht.base_definition.daily_basic_factor, Decimal("25.0000"))

    def test_tunjangan_tetap_dari_konfigurasi_bukan_tebakan(self):
        self.publish(codes=("TRANSPORT",))

        definition = BpjsRule.objects.get(
            program__code="JHT", is_deleted=False,
        ).base_definition

        self.assertEqual(
            list(
                definition.components
                .filter(is_deleted=False)
                .values_list("allowance_code", flat=True),
            ),
            ["TRANSPORT"],
        )

    def test_tanpa_kode_dan_tanpa_pernyataan_ditolak(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError) as raised:
            call_command(
                "bpjs_publish_statutory",
                "--global",
                "--effective-from", "2026-01-01",
                "--apply",
                verbosity=0,
            )

        # Yang ditolak pemetaan tunjangannya, bukan cakupannya.
        self.assertIn("--no-fixed-allowance", str(raised.exception))

    def test_dry_run_tidak_menyimpan(self):
        from django.core.management import call_command

        call_command(
            "bpjs_publish_statutory",
            "--global",
            "--no-fixed-allowance",
            "--effective-from", "2026-01-01",
            verbosity=0,
        )

        self.assertFalse(BpjsProgram.objects.filter(is_deleted=False).exists())
        self.assertFalse(BpjsRule.objects.filter(is_deleted=False).exists())

    def test_tidak_menerbitkan_kepesertaan(self):
        """
        Keputusan #3A butir 1. Mendaftarkan orang otomatis persis
        kebalikan dari "tidak terdaftar berarti tidak ikut".
        """
        self.publish()

        self.assertFalse(
            BpjsEnrollment.objects.filter(is_deleted=False).exists(),
        )

    def test_menolak_menimpa_aturan_yang_sudah_ada(self):
        from django.core.management.base import CommandError

        self.publish()

        with self.assertRaises(CommandError):
            self.publish()

    # ------------------------------------------------------------------
    # Angkanya, lewat mesin hitung yang sudah ada
    # ------------------------------------------------------------------

    def test_jht_memotong_dan_membebani_sesuai_tarif_terbit(self):
        self.publish()

        self.enroll(program=BpjsProgram.objects.get(code="JHT"))

        _, line = self.calculated_line()

        basic = line.basic_salary

        self.assertEqual(
            self.component(line, "BPJS-JHT").amount,
            (basic * Decimal("2") / Decimal("100")).quantize(Decimal("0.01")),
        )
        self.assertEqual(
            self.component(line, "BPJS-JHT-ER").amount,
            (basic * Decimal("3.7") / Decimal("100")).quantize(Decimal("0.01")),
        )

    def test_jkm_hanya_membebani_perusahaan(self):
        self.publish()

        self.enroll(program=BpjsProgram.objects.get(code="JKM"))

        _, line = self.calculated_line()

        codes = set(line.components.values_list("code", flat=True))

        self.assertIn("BPJS-JKM-ER", codes)
        self.assertNotIn("BPJS-JKM", codes)

        self.assertEqual(
            self.component(line, "BPJS-JKM-ER").amount,
            (line.basic_salary * Decimal("0.30") / Decimal("100"))
            .quantize(Decimal("0.01")),
        )

    def test_jkk_memakai_tarif_kelas_pegawainya(self):
        self.publish()

        program = BpjsProgram.objects.get(code="JKK")
        risk = BpjsRiskClass.objects.get(code="RISK-4")

        self.enroll(program=program, risk_class=risk)

        _, line = self.calculated_line()

        self.assertEqual(
            self.component(line, "BPJS-JKK-ER").amount,
            (line.basic_salary * Decimal("1.13") / Decimal("100"))
            .quantize(Decimal("0.01")),
        )

    def test_plafon_jp_menjepit_dasarnya(self):
        self.publish()

        self.enroll(program=BpjsProgram.objects.get(code="JP"))

        # Pegawai baku bergaji 10jt; dinaikkan ke atas plafon supaya
        # penjepitannya benar-benar terjadi.
        from apps.hr.models import PayrollAssignment

        assignment = PayrollAssignment.objects.get(
            employee=self.employee, is_current=True, is_deleted=False,
        )
        assignment.basic_salary = Decimal("20000000")
        assignment.save(update_fields=["basic_salary"])

        _, line = self.calculated_line()

        component = self.component(line, "BPJS-JP")

        self.assertEqual(component.base_amount, Decimal("11086300.00"))
        self.assertEqual(component.amount, Decimal("110863.00"))

    def test_iuran_pegawai_belum_mengurangi_pajak(self):
        """
        Metode PPh21 masih beku (#4), jadi tidak satu aturan pun terbit
        dengan `reduces_taxable` menyala.
        """
        self.publish()

        self.assertTrue(
            all(
                rule.reduces_taxable is False
                for rule in BpjsRule.objects.filter(is_deleted=False)
            ),
        )


class BpjsMultiCompanyMappingTest(BpjsTestCase):
    """
    Q. Komposisi tunjangan tetap berbeda per perusahaan.

    Satu tenant berisi beberapa perusahaan yang komponen tunjangan
    tetapnya tidak sama, dan kodenya pun belum tentu sama. Yang dijaga
    di sini: pemetaan satu perusahaan **tidak pernah** diam-diam
    berlaku untuk perusahaan lain.
    """

    def setUp(self):
        super().setUp()

        from apps.administration.models import Company

        self.other_company = Company.objects.filter(
            code="PAY-B", is_deleted=False,
        ).first()

        if self.other_company is None:
            self.other_company = Company.objects.create(
                code="PAY-B", name="Payroll Test B",
            )

    def publish(self, *args):
        from django.core.management import call_command

        call_command(
            "bpjs_publish_statutory",
            *args,
            "--effective-from", "2026-01-01",
            "--apply",
            verbosity=0,
        )

    # ------------------------------------------------------------------
    # Cakupan wajib disebut
    # ------------------------------------------------------------------

    def test_tanpa_cakupan_ditolak(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError) as raised:
            self.publish("--no-fixed-allowance")

        self.assertIn("--global", str(raised.exception))

    def test_global_dan_company_bersamaan_ditolak(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError):
            self.publish(
                "--global", "--company", self.company.code,
                "--no-fixed-allowance",
            )

    def test_kode_perusahaan_tak_dikenal_ditolak(self):
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError) as raised:
            self.publish("--company", "TIDAK-ADA", "--no-fixed-allowance")

        self.assertIn("TIDAK-ADA", str(raised.exception))

    # ------------------------------------------------------------------
    # Validasi kode tunjangan
    # ------------------------------------------------------------------

    def test_kode_tunjangan_tak_dikenal_ditolak(self):
        """
        Kode salah ketik tidak pernah menerbitkan error saat payroll
        dihitung — ia cuma mengecilkan dasar iuran diam-diam.
        """
        from django.core.management.base import CommandError

        with self.assertRaises(CommandError) as raised:
            self.publish("--global", "--fixed-allowance", "SALAH-KETIK")

        self.assertIn("SALAH-KETIK", str(raised.exception))

    def test_kode_tak_dikenal_boleh_lewat_kalau_dinyatakan(self):
        self.publish(
            "--global",
            "--fixed-allowance", "BELUM-ADA",
            "--allow-unknown-allowance",
        )

        self.assertTrue(BpjsRule.objects.filter(is_deleted=False).exists())

    # ------------------------------------------------------------------
    # Pemetaan per perusahaan
    # ------------------------------------------------------------------

    def test_aturan_company_memakai_komposisinya_sendiri(self):
        self.publish("--global", "--no-fixed-allowance")
        self.publish(
            "--company", self.company.code,
            "--fixed-allowance", "TRANSPORT",
        )

        global_rule = BpjsRule.objects.get(
            program__code="JHT", company__isnull=True, is_deleted=False,
        )
        company_rule = BpjsRule.objects.get(
            program__code="JHT", company=self.company, is_deleted=False,
        )

        self.assertNotEqual(
            global_rule.base_definition_id, company_rule.base_definition_id,
        )

        self.assertEqual(
            list(
                global_rule.base_definition.components
                .filter(is_deleted=False)
                .values_list("allowance_code", flat=True),
            ),
            [],
        )
        self.assertEqual(
            list(
                company_rule.base_definition.components
                .filter(is_deleted=False)
                .values_list("allowance_code", flat=True),
            ),
            ["TRANSPORT"],
        )

    def test_pemetaan_satu_company_tidak_menyentuh_yang_lain(self):
        self.publish("--global", "--no-fixed-allowance")
        self.publish(
            "--company", self.company.code,
            "--fixed-allowance", "TRANSPORT",
        )

        # Perusahaan kedua tidak punya aturan sendiri, jadi ia jatuh ke
        # aturan bawaan tenant — yang dasarnya gaji pokok saja.
        self.assertFalse(
            BpjsRule.objects
            .filter(company=self.other_company, is_deleted=False)
            .exists(),
        )

    def test_publikasi_global_tidak_membuat_aturan_company(self):
        self.publish("--global", "--no-fixed-allowance")

        self.assertFalse(
            BpjsRule.objects
            .filter(company__isnull=False, is_deleted=False)
            .exists(),
        )

    def test_publikasi_company_tidak_membuat_aturan_global(self):
        self.publish(
            "--company", self.company.code, "--no-fixed-allowance",
        )

        self.assertFalse(
            BpjsRule.objects
            .filter(company__isnull=True, is_deleted=False)
            .exists(),
        )

    def test_dua_kali_company_yang_sama_ditolak(self):
        from django.core.management.base import CommandError

        self.publish("--company", self.company.code, "--no-fixed-allowance")

        with self.assertRaises(CommandError):
            self.publish(
                "--company", self.company.code, "--no-fixed-allowance",
            )

    # ------------------------------------------------------------------
    # Angkanya
    # ------------------------------------------------------------------

    def test_dasar_iuran_mengikuti_komposisi_perusahaannya(self):
        self.publish("--global", "--no-fixed-allowance")
        self.publish(
            "--company", self.company.code,
            "--fixed-allowance", "TRANSPORT",
        )

        self.enroll(program=BpjsProgram.objects.get(code="JHT"))
        self.make_attendance(self.employee, days=20)

        _, line = self.calculated_line()

        transport = self.component(line, "TRANSPORT")
        component = self.component(line, "BPJS-JHT")

        self.assertEqual(transport.amount, Decimal("500000.00"))

        # Pegawai ini milik company yang punya aturan sendiri, jadi
        # TRANSPORT ikut jadi dasar.
        self.assertEqual(
            component.base_amount, line.basic_salary + transport.amount,
        )

    # ------------------------------------------------------------------
    # Sejarah
    # ------------------------------------------------------------------

    def test_komposisi_company_terkunci_setelah_dipakai(self):
        """
        Keamanan versi berlaku per komposisi, jadi per perusahaan juga:
        satu perusahaan mengubah pemetaannya tidak boleh menulis ulang
        arti payroll perusahaan itu sendiri di masa lalu.
        """
        self.publish(
            "--company", self.company.code,
            "--fixed-allowance", "TRANSPORT",
        )

        definition = BpjsRule.objects.get(
            program__code="JHT", company=self.company, is_deleted=False,
        ).base_definition

        self.assertTrue(definition.is_referenced)

        component = BpjsBaseComponent(
            definition=definition, allowance_code="MEAL", sequence=99,
        )

        with self.assertRaises(ValidationError):
            component.full_clean()
