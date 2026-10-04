"""
Alur roster ujung ke ujung: setup → baseline → penyesuaian → kredit.

`TenantTestCase` django-tenants **tidak** memanggil
`super().setUpClass()`, jadi tidak ada rollback per-test dan
`setUpTestData` tidak pernah jalan. Konsekuensinya tiap test membuat
pegawainya sendiri dan hanya membaca miliknya — kalau tidak, urutan
eksekusi menentukan hasilnya.

Menutup kasus uji C (bulk satu section, jangkar berbeda), D (go-live di
tengah siklus), E (saldo awal kredit), F (perpanjangan kerja: baseline
utuh, masa depan dihitung ulang), J (perubahan policy permanen), K
(tanpa pasangan back-to-back), dan M (pegawai HO tidak diproses).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.administration.models import (
    Company,
    Location,
    RosterPolicy,
)
from apps.administration.seeds.numbering import seed_numbering
from apps.hr.api.roster.adjustment_service import RosterAdjustmentService
from apps.hr.api.roster.credit_service import RotationCreditService
from apps.hr.api.roster.recalculation import RosterRecalculationService
from apps.hr.api.roster.services import (
    RosterGenerationService,
    RosterValidator,
)
from apps.hr.api.roster.schema.adjustment import ROSTER_ADJUSTMENT_ACTIONS
from apps.hr.api.roster.schema.setup import ROSTER_SETUP_ACTIONS
from apps.hr.api.roster.setup_service import (
    RosterSetupLineService,
    RosterSetupService,
)
from apps.hr.models import (
    AdjustmentKind,
    AdjustmentStatus,
    CreditEntryType,
    CreditImpact,
    Employee,
    EmploymentAssignment,
    OrganizationAssignment,
    RosterSegmentType,
    RosterSetupLineStatus,
    RosterSetupStatus,
    RotationPeriod,
    SiteRotation,
    SiteRotationStatus,
)


User = get_user_model()

# Sabtu. Dijangkarkan supaya jumlah hari kerja dan batas siklusnya tidak
# bergantung pada hari apa test dijalankan — pola yang sama dengan
# `TRIAL_DATE` di test Attendance Permission.
#
# Jangkar tetap saja **tidak cukup**; lihat `setUpClass()`.
AS_OF = date(2026, 8, 1)


class RosterFlowTestCase(TenantTestCase):
    """Satu company, satu site, dua policy — 6:2 dan 8:2."""

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "roster-flow"
        tenant.name = "Roster Flow"

    @classmethod
    def setUpClass(cls):
        # ------------------------------------------------------------------
        # Jam dibekukan ke `AS_OF`.
        #
        # **Perbaikan bom waktu, bukan pelonggaran aturan.**
        # `RosterSetupService.approve()` mengunci segmen ber-`end_date`
        # lebih kecil dari `timezone.localdate()` — dan itu aturan yang
        # benar: jadwal yang sudah dijalani memang tidak boleh dihitung
        # ulang. Yang salah bukan aturannya, melainkan bahwa test ini
        # menua terhadapnya. Berkas ini menyusun jadwal yang berjangkar
        # 2026-08-01; begitu tanggal hari ini melewati blok itu, seluruh
        # skenario penyesuaian jadi "menyentuh jadwal terkunci" dan
        # ditolak. Enam test merah pada 2026-09-15, tanpa satu baris kode
        # pun berubah.
        #
        # Yang dibekukan **hanya** `localdate`. `timezone.now()` sengaja
        # dibiarkan berjalan: ia cuma mengisi stempel audit
        # (`applied_at`, `submitted_at`, `updated_at`) yang tidak masuk
        # satu pun assertion, dan membekukan yang tidak perlu dibekukan
        # membuat test berhenti menguji perilaku yang sebenarnya.
        # Diverifikasi terpisah: 39/39 hijau dengan `localdate` saja.
        #
        # **Bukan** `AS_OF = localdate() + n hari`. Jangkar yang bergulir
        # menukar satu ketergantungan kalender dengan yang lain:
        # tanggalnya berbeda tiap run sehingga kegagalan tidak bisa
        # direproduksi dengan angka yang sama, dan jarak amannya jadi
        # asumsi diam-diam terhadap offset mundur terbesar yang dipakai
        # test (`AS_OF - timedelta(days=20)`).
        # ------------------------------------------------------------------
        clock = mock.patch(
            "django.utils.timezone.localdate",
            return_value=AS_OF,
        )
        clock.start()
        cls.addClassCleanup(clock.stop)

        super().setUpClass()

        # Deret nomor dokumen. Diseed di sini karena tenant test lahir
        # kosong: tanpa ini `document_number` terbit kosong — perilaku
        # yang memang benar (dokumen tetap tersimpan), tapi membuat test
        # nomor dokumen tidak menguji apa pun.
        seed_numbering()

        cls.company = Company.objects.create(code="FLW", name="Flow Test")

        cls.site = Location.objects.create(
            company=cls.company,
            code="SITE",
            name="Site Test",
        )

        cls.head_office = Location.objects.create(
            company=cls.company,
            code="HOFF",
            name="Head Office Test",
        )

        cls.policy = RosterPolicy.objects.create(
            company=cls.company,
            location=cls.site,
            code="FLW-6-2",
            name="Roster 6:2",
            cycle_work_days=42,
            cycle_off_days=14,
            default_travel_out_days=1,
            default_travel_in_days=1,
            rolling_horizon_months=12,
            credit_enabled=True,
        )

        cls.policy_8_2 = RosterPolicy.objects.create(
            company=cls.company,
            location=cls.site,
            code="FLW-8-2",
            name="Roster 8:2",
            cycle_work_days=56,
            cycle_off_days=14,
            default_travel_out_days=1,
            default_travel_in_days=1,
            rolling_horizon_months=12,
            credit_enabled=True,
        )

        # Policy tanpa pola siklus: hanya memuat aturan site, dan
        # sengaja tidak bisa menghasilkan jadwal.
        cls.policy_no_pattern = RosterPolicy.objects.create(
            company=cls.company,
            location=cls.site,
            code="FLW-RULES-ONLY",
            name="Site Rules Only",
        )

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(cls, *, location=None, policy=None, cycle_start=None):
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"FLW{cls._counter:04d}",
            first_name="Flow",
            last_name=f"Employee {cls._counter}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=location or cls.site,
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
    def make_plan(cls, employee, *, policy=None, cycle_start=AS_OF):
        plan = RosterGenerationService.commit(
            employee=employee,
            policy=policy or cls.policy,
            cycle_start=cycle_start,
            as_of_date=AS_OF,
        )

        return RosterGenerationService.lock_baseline(plan=plan)

    @staticmethod
    def segments(plan, *, version=None):
        if version is None:
            queryset = RotationPeriod.objects.filter(
                rotation=plan,
                is_deleted=False,
                version_to__isnull=True,
            )
        else:
            queryset = RosterGenerationService.segments_of(
                plan, version=version,
            )

        return list(queryset.order_by("start_date", "sequence"))


# ----------------------------------------------------------------------
# Validasi
# ----------------------------------------------------------------------


class RosterValidatorTests(RosterFlowTestCase):
    def test_employee_without_policy_is_blocked(self):
        """Kasus M: pegawai HO tanpa policy tidak diproses generator."""
        employee = self.make_employee(location=self.head_office)

        findings = RosterValidator.check(
            employee=employee,
            policy=None,
            cycle_start=AS_OF,
            as_of_date=AS_OF,
        )

        codes = {item.code for item in findings if item.level == "blocking"}

        self.assertIn("no_policy", codes)

    def test_policy_without_pattern_is_blocked(self):
        employee = self.make_employee()

        findings = RosterValidator.check(
            employee=employee,
            policy=self.policy_no_pattern,
            cycle_start=AS_OF,
            as_of_date=AS_OF,
        )

        codes = {item.code for item in findings if item.level == "blocking"}

        self.assertIn("policy_without_pattern", codes)

    def test_missing_cycle_start_is_blocked(self):
        employee = self.make_employee()

        findings = RosterValidator.check(
            employee=employee,
            policy=self.policy,
            cycle_start=None,
            as_of_date=AS_OF,
        )

        codes = {item.code for item in findings if item.level == "blocking"}

        self.assertIn("no_cycle_start", codes)

    def test_missing_back_to_back_partner_is_only_a_warning(self):
        """
        Kasus K. Pasangan back-to-back adalah **referensi**, dan tidak
        boleh ada satu jalur pun yang memblokir karena kolom ini kosong.
        """
        employee = self.make_employee()

        findings = RosterValidator.check(
            employee=employee,
            policy=self.policy,
            cycle_start=AS_OF,
            as_of_date=AS_OF,
        )

        partner = [item for item in findings if item.code == "no_b2b_partner"]

        self.assertEqual(len(partner), 1)
        self.assertEqual(partner[0].level, "warning")

        self.assertFalse(
            [item for item in findings if item.level == "blocking"],
        )

    def test_second_active_plan_is_blocked_and_names_the_document(self):
        employee = self.make_employee()

        plan = self.make_plan(employee)

        findings = RosterValidator.check(
            employee=employee,
            policy=self.policy,
            cycle_start=AS_OF,
            as_of_date=AS_OF,
        )

        blocking = [
            item for item in findings
            if item.code == "active_plan_exists"
        ]

        self.assertEqual(len(blocking), 1)

        # Pesannya menyebut nomor dokumennya — "sudah punya roster
        # aktif" tidak bisa ditindaklanjuti siapa pun.
        self.assertIn(plan.document_number, blocking[0].message)

    def test_stale_anchor_warns_without_blocking(self):
        employee = self.make_employee()

        findings = RosterValidator.check(
            employee=employee,
            policy=self.policy,
            cycle_start=date(2025, 1, 1),
            as_of_date=AS_OF,
        )

        self.assertIn(
            "stale_anchor",
            {item.code for item in findings},
        )

        self.assertFalse(
            [item for item in findings if item.level == "blocking"],
        )


# ----------------------------------------------------------------------
# Baseline
# ----------------------------------------------------------------------


class BaselineTests(RosterFlowTestCase):
    def test_commit_creates_plan_version_and_segments(self):
        employee = self.make_employee()

        plan = RosterGenerationService.commit(
            employee=employee,
            policy=self.policy,
            cycle_start=AS_OF,
            as_of_date=AS_OF,
        )

        self.assertTrue(plan.document_number)
        self.assertEqual(plan.current_version.version_no, 1)
        self.assertIsNone(plan.baseline_version_id)

        rows = self.segments(plan)

        self.assertTrue(rows)

        # Pola dibekukan ke dokumen, bukan dibaca ulang dari master.
        self.assertEqual(plan.cycle_work_days, 42)
        self.assertEqual(plan.travel_out_days, 1)

    def test_lock_baseline_is_idempotent(self):
        employee = self.make_employee()

        plan = self.make_plan(employee)

        first = plan.baseline_version_id

        RosterGenerationService.lock_baseline(plan=plan)

        plan.refresh_from_db()

        self.assertEqual(plan.baseline_version_id, first)
        self.assertEqual(plan.status, SiteRotationStatus.ACTIVE)

    def test_go_live_mid_cycle_keeps_the_running_block(self):
        """
        Kasus D. Pegawai yang sedang di tengah blok kerja saat sistem
        dipasang mendapat sisa harinya, bukan kehilangan seluruh blok.
        """
        employee = self.make_employee()

        plan = self.make_plan(
            employee,
            cycle_start=AS_OF - timedelta(days=20),
        )

        first = self.segments(plan)[0]

        self.assertEqual(first.segment_type, RosterSegmentType.WORK)
        self.assertLess(first.start_date, AS_OF)
        self.assertGreaterEqual(first.end_date, AS_OF)

    def test_extend_horizon_appends_without_touching_existing_rows(self):
        employee = self.make_employee()

        plan = self.make_plan(employee)

        before = self.segments(plan)

        rows = RosterGenerationService.extend_horizon(
            plan=plan,
            until=plan.horizon_end + timedelta(days=200),
        )

        self.assertTrue(rows)

        after = self.segments(plan)

        # Baris lama tetap ada persis seperti sebelumnya.
        self.assertEqual(
            [(row.pk, row.start_date, row.end_date) for row in before],
            [
                (row.pk, row.start_date, row.end_date)
                for row in after[:len(before)]
            ],
        )

        # Dan sambungannya bersambung, tanpa lubang maupun tumpang
        # tindih di titik sambung.
        for previous, current in zip(after, after[1:]):
            self.assertEqual(
                (current.start_date - previous.end_date).days,
                1,
                f"{previous.segment_type} → {current.segment_type}",
            )


# ----------------------------------------------------------------------
# Setup massal
# ----------------------------------------------------------------------


class BulkSetupTests(RosterFlowTestCase):
    def make_setup(self, *, anchors):
        setup = RosterSetupService.create(
            data={
                "company": self.company,
                "location": self.site,
                "as_of_date": AS_OF,
                "horizon_months": 12,
            },
        )

        employees = []

        for offset in anchors:
            employee = self.make_employee()

            employees.append(employee)

            RosterSetupLineService.create(
                data={
                    "request": setup,
                    "employee": employee,
                    "roster_policy": self.policy,
                    "current_cycle_start": AS_OF - timedelta(days=offset),
                },
            )

        return setup, employees

    def test_bulk_preview_keeps_per_employee_anchors(self):
        """
        Kasus C: satu batch, satu section — tapi datanya tetap per
        pegawai, dan jangkar yang berbeda-beda justru keadaan normal di
        site yang gelombangnya bergantian.
        """
        setup, _ = self.make_setup(anchors=[0, 20, 40])

        preview = RosterSetupService.preview(request=setup)

        self.assertEqual(preview["total_lines"], 3)
        self.assertEqual(preview["blocking_lines"], 0)
        self.assertTrue(preview["can_submit"])

        starts = {
            row["current_cycle_start"] for row in preview["lines"]
        }

        self.assertEqual(len(starts), 3)

        for row in preview["lines"]:
            self.assertTrue(row["segments"])
            self.assertTrue(row["can_commit"])

    def test_commit_issues_one_locked_plan_per_line(self):
        setup, employees = self.make_setup(anchors=[0, 20])

        RosterSetupService.commit(request=setup)

        setup.refresh_from_db()

        self.assertEqual(setup.status, RosterSetupStatus.COMMITTED)
        self.assertEqual(setup.commit_error, "")

        for employee in employees:
            plan = SiteRotation.objects.get(
                employee=employee, is_deleted=False,
            )

            self.assertIsNotNone(plan.baseline_version_id)
            self.assertEqual(plan.status, SiteRotationStatus.ACTIVE)

            # Penempatan pegawai ikut diperbarui — kalau tidak, form
            # pegawai menampilkan keadaan yang berbeda dari jadwalnya.
            employment = EmploymentAssignment.objects.get(employee=employee)

            self.assertEqual(employment.roster_policy_id, self.policy.pk)

    def test_commit_is_repeatable_and_skips_committed_lines(self):
        setup, employees = self.make_setup(anchors=[0])

        RosterSetupService.commit(request=setup)

        RosterSetupService.commit(request=setup)

        self.assertEqual(
            SiteRotation.objects.filter(
                employee=employees[0], is_deleted=False,
            ).count(),
            1,
        )

    def test_failing_line_does_not_cancel_the_others(self):
        setup, employees = self.make_setup(anchors=[0, 20])

        # Satu baris dibuat gagal: pegawainya sudah punya rencana
        # berjalan yang dibuat di luar dokumen ini.
        self.make_plan(employees[0])

        RosterSetupService.commit(request=setup)

        setup.refresh_from_db()

        self.assertEqual(
            setup.status, RosterSetupStatus.PARTIALLY_COMMITTED,
        )

        lines = list(setup.lines.order_by("employee__employee_number"))

        statuses = {line.employee_id: line.status for line in lines}

        self.assertEqual(
            statuses[employees[0].pk], RosterSetupLineStatus.FAILED,
        )
        self.assertEqual(
            statuses[employees[1].pk], RosterSetupLineStatus.COMMITTED,
        )

        failed = next(
            line for line in lines if line.employee_id == employees[0].pk
        )

        self.assertIn("roster", failed.commit_error.lower())

    def test_opening_credit_becomes_a_ledger_entry(self):
        """
        Kasus E. Saldo awal dicatat sebagai transaksi, bukan diketik
        langsung ke saldo — angka tanpa jejak asal-usul tidak bisa
        dipertanggungjawabkan saat pegawainya bertanya.
        """
        setup = RosterSetupService.create(
            data={
                "company": self.company,
                "location": self.site,
                "as_of_date": AS_OF,
            },
        )

        employee = self.make_employee()

        RosterSetupLineService.create(
            data={
                "request": setup,
                "employee": employee,
                "roster_policy": self.policy,
                "current_cycle_start": AS_OF,
                "opening_rotation_credit": Decimal("10.00"),
            },
        )

        RosterSetupService.commit(request=setup)

        entries = list(employee.rotation_credits.filter(is_deleted=False))

        self.assertEqual(len(entries), 1)
        self.assertEqual(
            entries[0].entry_type, CreditEntryType.OPENING_BALANCE,
        )
        self.assertEqual(entries[0].days, Decimal("10.00"))
        self.assertEqual(entries[0].source_type, "roster_setup")

        balance = RotationCreditService.balance_for(employee)

        self.assertEqual(balance.balance, Decimal("10.00"))

    def test_head_office_employee_is_refused_by_the_service(self):
        """
        Pegawai kantor pusat tidak pernah masuk roster site, dan
        ditolak **saat barisnya dibuat** — bukan dibiarkan tersimpan
        lalu ketahuan di preview. Yang menerima id kiriman klien adalah
        service ini, jadi di sinilah penjagaannya.
        """
        setup, _ = self.make_setup(anchors=[0])

        stray = self.make_employee(location=self.head_office)

        with self.assertRaises(ValidationError) as caught:
            RosterSetupLineService.create(
                data={
                    "request": setup,
                    "employee": stray,
                    "roster_policy": self.policy,
                    "current_cycle_start": AS_OF,
                },
            )

        self.assertIn(stray.employee_number, str(caught.exception))

    def test_mixed_site_batch_is_blocked(self):
        """
        Lapis kedua, dan ia tetap dibutuhkan: baris yang **sah saat
        dibuat** bisa jadi tidak sah kemudian, karena pegawainya
        dipindahkan sesudah masuk dokumen. Karena itu barisnya dibuat
        langsung ke model di sini — lewat service, keadaan ini tidak
        bisa dibuat sama sekali.
        """
        setup, _ = self.make_setup(anchors=[0])

        stray = self.make_employee()

        RosterSetupLineService.create(
            data={
                "request": setup,
                "employee": stray,
                "roster_policy": self.policy,
                "current_cycle_start": AS_OF,
            },
        )

        # Pindah ke kantor pusat sesudah barisnya tersimpan.
        organization = stray.organization

        organization.location = self.head_office

        organization.save(update_fields=["location"])

        preview = RosterSetupService.preview(request=setup)

        codes = {
            item["code"] for item in preview["document_validations"]
        }

        self.assertIn("mixed_location", codes)
        self.assertFalse(preview["can_submit"])

    def test_empty_document_cannot_be_submitted(self):
        setup = RosterSetupService.create(
            data={
                "company": self.company,
                "location": self.site,
                "as_of_date": AS_OF,
            },
        )

        preview = RosterSetupService.preview(request=setup)

        self.assertFalse(preview["can_submit"])

        self.assertIn(
            "no_lines",
            {item["code"] for item in preview["document_validations"]},
        )


# ----------------------------------------------------------------------
# Perhitungan ulang
# ----------------------------------------------------------------------


class RecalculationTests(RosterFlowTestCase):
    def test_past_segments_are_shared_not_rewritten(self):
        """
        Jaminan inti: baris yang berakhir sebelum tanggal berlaku tidak
        di-UPDATE, tidak ditutup, dan tidak disalin. Itu yang membuat
        `TravelRequest.rotation_period` yang menunjuknya tetap sah.
        """
        employee = self.make_employee()

        plan = self.make_plan(employee)

        rows = self.segments(plan)

        cutoff = rows[4].start_date

        untouched = [
            (row.pk, row.start_date, row.end_date)
            for row in rows
            if row.end_date < cutoff
        ]

        RosterRecalculationService.recalculate(
            plan=plan,
            effective_date=cutoff,
            reason="Uji perhitungan ulang.",
        )

        plan.refresh_from_db()

        after = self.segments(plan)

        surviving = [
            (row.pk, row.start_date, row.end_date)
            for row in after
            if row.end_date < cutoff
        ]

        self.assertEqual(untouched, surviving)

    def test_baseline_stays_readable_after_recalculation(self):
        employee = self.make_employee()

        plan = self.make_plan(employee)

        baseline = plan.baseline_version

        before = [
            (row.segment_type, row.start_date, row.end_date)
            for row in self.segments(plan, version=baseline)
        ]

        RosterRecalculationService.recalculate(
            plan=plan,
            effective_date=self.segments(plan)[4].start_date,
            reason="Uji.",
        )

        plan.refresh_from_db()

        after = [
            (row.segment_type, row.start_date, row.end_date)
            for row in self.segments(plan, version=baseline)
        ]

        self.assertEqual(before, after)

        # Dan versinya memang bertambah.
        self.assertEqual(plan.current_version.version_no, 2)

    def test_locked_segments_refuse_recalculation(self):
        employee = self.make_employee()

        plan = self.make_plan(employee)

        rows = self.segments(plan)

        RotationPeriod.objects.filter(pk=rows[2].pk).update(is_locked=True)

        with self.assertRaises(ValidationError) as caught:
            RosterRecalculationService.recalculate(
                plan=plan,
                effective_date=rows[2].start_date,
                reason="Seharusnya ditolak.",
            )

        message = str(caught.exception)

        # Pesannya menyebut batas amannya, bukan cuma "ada yang
        # terkunci".
        self.assertIn(str(rows[2].end_date), message)

    def test_sequence_numbers_are_never_reused(self):
        employee = self.make_employee()

        plan = self.make_plan(employee)

        original = {row.sequence for row in self.segments(plan)}

        RosterRecalculationService.recalculate(
            plan=plan,
            effective_date=self.segments(plan)[4].start_date,
            reason="Uji.",
        )

        plan.refresh_from_db()

        # Baris yang ditutup tetap memegang nomornya, jadi baris
        # pengganti wajib memakai nomor berikutnya — kalau tidak,
        # `uniq_active_hr_rotation_period_sequence` yang menolaknya.
        replacements = [
            row for row in self.segments(plan)
            if row.version_from_id == plan.current_version_id
        ]

        self.assertTrue(replacements)

        self.assertFalse(
            {row.sequence for row in replacements} & original,
        )

    def test_schedule_stays_contiguous_after_recalculation(self):
        employee = self.make_employee()

        plan = self.make_plan(employee)

        RosterRecalculationService.extend_block(
            plan=plan,
            effective_date=self.segments(plan)[0].end_date,
            days=7,
            reason="Uji perpanjangan.",
        )

        plan.refresh_from_db()

        rows = self.segments(plan)

        for previous, current in zip(rows, rows[1:]):
            self.assertEqual(
                (current.start_date - previous.end_date).days,
                1,
                f"{previous.segment_type} → {current.segment_type}",
            )

    def test_extend_block_does_not_shorten_the_field_break(self):
        """
        Yang tertahan di site seminggu tetap berhak atas field break
        penuh. Memotongnya berarti perusahaan mengambil dua kali.
        """
        employee = self.make_employee()

        plan = self.make_plan(employee)

        RosterRecalculationService.extend_block(
            plan=plan,
            effective_date=self.segments(plan)[0].end_date,
            days=7,
            reason="Uji.",
        )

        plan.refresh_from_db()

        rows = self.segments(plan)

        work = rows[0]
        field_break = next(
            row for row in rows
            if row.segment_type == RosterSegmentType.FIELD_BREAK
        )

        self.assertEqual(work.total_days, 49)
        self.assertEqual(field_break.total_days, 14)

    def test_planned_dates_carry_so_the_shift_is_visible(self):
        employee = self.make_employee()

        plan = self.make_plan(employee)

        original = self.segments(plan)[2]

        RosterRecalculationService.extend_block(
            plan=plan,
            effective_date=self.segments(plan)[0].end_date,
            days=7,
            reason="Uji.",
        )

        plan.refresh_from_db()

        replacement = next(
            row for row in self.segments(plan)
            if row.segment_type == original.segment_type
            and row.cycle_number == original.cycle_number
        )

        self.assertEqual(
            replacement.planned_start_date, original.start_date,
        )

        self.assertEqual(
            (replacement.start_date - replacement.planned_start_date).days,
            7,
        )

    def test_simulate_matches_what_recalculate_writes(self):
        """
        Preview dan penerapan memakai `compute()` yang sama. Kalau
        berbeda, orang menyetujui satu jadwal dan mendapat jadwal yang
        lain.
        """
        employee = self.make_employee()

        plan = self.make_plan(employee)

        cutoff = self.segments(plan)[4].start_date

        simulated = RosterRecalculationService.simulate(
            plan=plan,
            effective_date=cutoff,
        )

        RosterRecalculationService.recalculate(
            plan=plan,
            effective_date=cutoff,
            reason="Uji.",
        )

        plan.refresh_from_db()

        written = [
            row for row in self.segments(plan)
            if row.version_from_id == plan.current_version_id
        ]

        self.assertEqual(
            [
                (row["segment_type"], row["start_date"], row["end_date"])
                for row in simulated["segments"]
            ],
            [
                (row.segment_type, row.start_date, row.end_date)
                for row in written
            ],
        )


# ----------------------------------------------------------------------
# Dokumen penyesuaian
# ----------------------------------------------------------------------


class AdjustmentTests(RosterFlowTestCase):
    def make_adjustment(self, plan, **overrides):
        data = {
            "plan": plan,
            "adjustment_kind": AdjustmentKind.WORK_EXTENSION,
            "effective_date": self.segments(plan)[0].end_date,
            "days": 7,
            "reason": "Kapal pengganti terlambat.",
        }

        data.update(overrides)

        return RosterAdjustmentService.create(data=data)

    def test_credit_days_are_derived_from_the_pattern_ratio(self):
        """
        Kasus G di jalur dokumen: 42:14 = rasio 3, jadi 7 hari lebih
        menghasilkan 2 kredit. Rasionya dihitung dari pola pegawai
        sendiri, bukan didaftar per pola di master.
        """
        employee = self.make_employee()

        plan = self.make_plan(employee)

        adjustment = self.make_adjustment(plan)

        self.assertEqual(adjustment.credit_impact, CreditImpact.EARN)
        self.assertEqual(adjustment.credit_days, Decimal("2.00"))

        self.assertTrue(adjustment.document_number)

    def test_apply_extends_the_block_and_records_the_credit(self):
        """Kasus F."""
        employee = self.make_employee()

        plan = self.make_plan(employee)

        baseline = plan.baseline_version

        baseline_rows = [
            (row.start_date, row.end_date)
            for row in self.segments(plan, version=baseline)
        ]

        adjustment = self.make_adjustment(plan)

        adjustment.status = AdjustmentStatus.APPROVED
        adjustment.save(update_fields=["status"])

        RosterAdjustmentService.apply(adjustment=adjustment)

        adjustment.refresh_from_db()
        plan.refresh_from_db()

        self.assertEqual(adjustment.status, AdjustmentStatus.APPLIED)
        self.assertIsNotNone(adjustment.applied_at)
        self.assertEqual(adjustment.apply_error, "")
        self.assertIsNotNone(adjustment.resulting_version_id)

        self.assertEqual(self.segments(plan)[0].total_days, 49)

        # Baseline tidak bergeser satu hari pun.
        self.assertEqual(
            baseline_rows,
            [
                (row.start_date, row.end_date)
                for row in self.segments(plan, version=baseline)
            ],
        )

        self.assertEqual(
            RotationCreditService.balance_for(employee).balance,
            Decimal("2.00"),
        )

    def test_apply_is_idempotent(self):
        employee = self.make_employee()

        plan = self.make_plan(employee)

        adjustment = self.make_adjustment(plan)

        adjustment.status = AdjustmentStatus.APPROVED
        adjustment.save(update_fields=["status"])

        RosterAdjustmentService.apply(adjustment=adjustment)
        RosterAdjustmentService.apply(adjustment=adjustment)

        plan.refresh_from_db()

        self.assertEqual(
            RotationCreditService.balance_for(employee).balance,
            Decimal("2.00"),
        )

        # Dan versinya tidak bertambah dua kali.
        self.assertEqual(plan.current_version.version_no, 2)

    def test_loyalty_changes_nothing_but_still_explains_itself(self):
        employee = self.make_employee()

        plan = self.make_plan(employee)

        before = [
            (row.pk, row.start_date, row.end_date)
            for row in self.segments(plan)
        ]

        adjustment = self.make_adjustment(
            plan,
            adjustment_kind=AdjustmentKind.LOYALTY,
            days=5,
            reason="Cuti dimundurkan tanpa persetujuan.",
        )

        self.assertFalse(adjustment.changes_schedule)

        adjustment.status = AdjustmentStatus.APPROVED
        adjustment.save(update_fields=["status"])

        RosterAdjustmentService.apply(adjustment=adjustment)

        plan.refresh_from_db()

        self.assertEqual(
            before,
            [
                (row.pk, row.start_date, row.end_date)
                for row in self.segments(plan)
            ],
        )

        # Tidak berubah, tapi tetap ada jawaban tertulisnya — diam
        # adalah jawaban terburuk untuk "kenapa jadwal saya tetap".
        explanation = RosterAdjustmentService.credit_explanation(adjustment)

        self.assertEqual(explanation["impact"], CreditImpact.NONE)
        self.assertIn("loyalitas", explanation["reason"].lower())

    def test_no_impact_leaves_the_schedule_alone(self):
        """Kasus I: variansi travel bukan otomatis rotation credit."""
        employee = self.make_employee()

        plan = self.make_plan(employee)

        adjustment = self.make_adjustment(
            plan,
            adjustment_kind=AdjustmentKind.NO_IMPACT,
            days=1,
            reason="Pesawat cancel.",
        )

        self.assertEqual(adjustment.credit_impact, CreditImpact.NONE)
        self.assertEqual(adjustment.credit_days, Decimal("0.00"))

        adjustment.status = AdjustmentStatus.APPROVED
        adjustment.save(update_fields=["status"])

        RosterAdjustmentService.apply(adjustment=adjustment)

        self.assertEqual(
            RotationCreditService.balance_for(employee).balance,
            Decimal("0.00"),
        )

    def test_two_open_adjustments_are_blocked(self):
        employee = self.make_employee()

        plan = self.make_plan(employee)

        first = self.make_adjustment(plan)

        first.status = AdjustmentStatus.SUBMITTED
        first.save(update_fields=["status"])

        second = self.make_adjustment(plan)

        findings = RosterAdjustmentService.validate(second)

        self.assertIn(
            "open_adjustment_exists",
            {item.code for item in findings if item.level == "blocking"},
        )

    def test_adjustment_on_a_draft_plan_is_blocked(self):
        employee = self.make_employee()

        plan = RosterGenerationService.commit(
            employee=employee,
            policy=self.policy,
            cycle_start=AS_OF,
            as_of_date=AS_OF,
        )

        adjustment = self.make_adjustment(plan)

        findings = RosterAdjustmentService.validate(adjustment)

        codes = {item.code for item in findings if item.level == "blocking"}

        self.assertIn("no_baseline", codes)

    def test_preview_and_apply_agree(self):
        employee = self.make_employee()

        plan = self.make_plan(employee)

        adjustment = self.make_adjustment(plan)

        preview = RosterAdjustmentService.preview(adjustment=adjustment)

        self.assertTrue(preview["can_submit"])
        self.assertIsNotNone(preview["schedule"])

        expected = [
            (row["segment_type"], row["start_date"], row["end_date"])
            for row in preview["schedule"]["segments"]
        ]

        adjustment.status = AdjustmentStatus.APPROVED
        adjustment.save(update_fields=["status"])

        RosterAdjustmentService.apply(adjustment=adjustment)

        plan.refresh_from_db()

        written = [
            (row.segment_type, row.start_date, row.end_date)
            for row in self.segments(plan)
            if row.version_from_id == plan.current_version_id
        ]

        self.assertEqual(expected, written)


# ----------------------------------------------------------------------
# Perubahan policy permanen
# ----------------------------------------------------------------------


class PolicyChangeTests(RosterFlowTestCase):
    def test_new_era_leaves_the_old_plan_intact(self):
        """
        Kasus J: 8:2 → 6:2 permanen. Era lama **ditutup**, era baru
        berdiri sebagai rencana tersendiri — bukan dihitung ulang.
        Kalau semuanya jadi adjustment, "pola apa yang berlaku tahun
        lalu" tidak bisa dijawab lagi.
        """
        employee = self.make_employee()

        old = self.make_plan(employee, policy=self.policy_8_2)

        self.assertEqual(old.cycle_work_days, 56)

        old_rows = [
            (row.start_date, row.end_date, row.total_days)
            for row in self.segments(old)
        ]

        switch = AS_OF + timedelta(days=120)

        old.effective_to = switch - timedelta(days=1)

        old.save(update_fields=["effective_to"])

        new = RosterGenerationService.commit(
            employee=employee,
            policy=self.policy,
            cycle_start=switch,
            as_of_date=switch,
        )

        self.assertEqual(new.cycle_work_days, 42)
        self.assertNotEqual(new.pk, old.pk)

        old.refresh_from_db()

        # Jadwal era lama tidak ditulis ulang satu baris pun.
        self.assertEqual(
            old_rows,
            [
                (row.start_date, row.end_date, row.total_days)
                for row in self.segments(old)
            ],
        )


class PreviewRequestShapeTests(RosterFlowTestCase):
    """
    Preview dibuka lewat **GET**, dan itu menentukan bentuk
    permintaannya: browser menolak GET yang membawa body — termasuk
    body kosong `{}` — dengan "Request with GET/HEAD method cannot have
    body". Servernya tidak pernah melihat permintaan itu, jadi test
    server saja tidak bisa menangkapnya; yang bisa dijaga di sini
    **kontraknya**, dan itu dua sisi.

    Sisi pertama: endpoint-nya memang menjawab tanpa body sama sekali —
    seluruh masukannya dokumen yang sudah tersimpan. Sisi kedua: aksi
    GET di schema tidak boleh punya `fields`, karena setiap isian
    berarti frontend merakit body lagi dan bug yang sama kembali lewat
    pintu yang berbeda. Filter opsional untuk aksi GET jalannya query
    param.
    """

    def setUp(self):
        super().setUp()

        self.client = TenantClient(self.tenant)

        self.user = User.objects.create_user(
            username="roster.preview",
            email="roster.preview@example.test",
            password="preview-pass-1",
            is_superuser=True,
            is_staff=True,
        )

    def make_setup(self):
        setup = RosterSetupService.create(
            data={
                "company": self.company,
                "location": self.site,
                "as_of_date": AS_OF,
                "horizon_months": 12,
            },
        )

        RosterSetupLineService.create(
            data={
                "request": setup,
                "employee": self.make_employee(),
                "roster_policy": self.policy,
                "current_cycle_start": AS_OF,
            },
        )

        return setup

    def get_preview(self, setup, query=None):
        return self.client.get(
            f"/api/hr/roster-setups/{setup.pk}/preview/",
            data=query or None,
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(self.user).access_token}"
            ),
        )

    def test_preview_answers_a_get_without_any_request_body(self):
        response = self.get_preview(self.make_setup())

        self.assertEqual(response.status_code, 200, response.content)

        payload = response.json()["data"]

        self.assertEqual(payload["total_lines"], 1)
        self.assertEqual(payload["blocking_lines"], 0)
        self.assertTrue(payload["lines"])

    def test_preview_reads_the_saved_document_not_the_request(self):
        """
        Query param asing tidak mengubah hasilnya — buktinya seluruh
        masukan preview datang dari baris yang tersimpan, jadi tidak ada
        alasan endpoint ini berubah jadi POST.
        """
        setup = self.make_setup()

        plain = self.get_preview(setup).json()["data"]
        noisy = self.get_preview(
            setup, query={"anything": "ignored"},
        ).json()["data"]

        self.assertEqual(plain["total_lines"], noisy["total_lines"])
        self.assertEqual(len(plain["lines"]), len(noisy["lines"]))

    def test_submit_can_reach_the_workflow_definition_resolver(self):
        """
        `assert_batch_definition_supported` sempat mengimpor
        `WorkflowDefinitionResolver` dari `apps.workflow.resolver` —
        modul yang tidak memuatnya (tempatnya di
        `apps.workflow.services`). Akibatnya **setiap** submit setup
        roster berakhir 500, dan tidak ada satu pun test yang
        menyentuhnya karena test yang ada memanggil `commit()`
        langsung, melewati alur persetujuan.

        Yang dijaga di sini cuma satu: impornya nyambung. Kalau tenant
        test tidak punya definisi workflow yang cocok, `ValidationError`
        adalah jawaban yang benar — yang tidak boleh muncul adalah
        `ImportError`.
        """
        setup = self.make_setup()

        scope = {
            "company": setup.company,
            "branch": None,
            "location": setup.location,
        }

        try:
            RosterSetupService.assert_batch_definition_supported(scope=scope)
        except ImportError as exc:
            self.fail(f"impor resolver workflow putus: {exc}")
        except ValidationError:
            pass

    def test_get_actions_carry_no_fields(self):
        for actions, source in (
            (ROSTER_SETUP_ACTIONS, "roster setup"),
            (ROSTER_ADJUSTMENT_ACTIONS, "roster adjustment"),
        ):
            for item in actions:
                method = str(item.get("method") or "post").lower()

                if method not in {"get", "head"}:
                    continue

                self.assertFalse(
                    item.get("fields"),
                    f"Aksi {method.upper()} '{item['key']}' di {source} "
                    f"punya isian — GET tidak bisa membawanya sebagai "
                    f"body; jadikan query param atau ubah ke POST.",
                )
