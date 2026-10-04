"""
Gerbang akuntansi Finalize (PF-0D), di atas tenant sungguhan.

Yang diuji di sini justru bagian yang tidak bisa diuji PF-0C: pemuat
yang membaca database, dan Finalize yang menolak mengunci run ketika
fakta payroll tidak bisa dinormalisasi jadi fakta akuntansi yang sah.

Satu kelas, dan itu disengaja: `TenantTestCase` membangun schema tenant
sekali per **kelas**, jadi memecahnya jadi lima kelas berarti membayar
lima kali. Tiap test membuat run-nya sendiri dan hanya membaca miliknya
— tidak ada rollback per-test di django-tenants.

PF-0D **tidak** menerbitkan jurnal. Sejak PF-0F, Finalize yang berhasil
menerbitkan tepat satu kejadian `PAYROLL_POSTED` dan satu jurnal DRAFT —
jadi test di sini tidak lagi menuntut tabel Finance kosong, melainkan
bahwa run yang **ditolak** tidak meninggalkan satu baris Finance pun.
Detail jembatannya diuji di `test_accounting_bridge`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import AuthorityMode, Role
from apps.accounts.services.role_assignment import grant_role
from apps.administration.models import Company, Currency
from apps.finance.models import AccountingEvent, Journal, JournalLine
from apps.finance.services.integration import FinanceAccountingConfigService
from apps.payroll.api.payroll_runs.views import PayrollRunViewSet
from apps.payroll.models import (
    PayrollPeriod,
    PayrollRun,
    PayrollRunEmployee,
    PayrollRunStatus,
    Payslip,
)
from apps.payroll.services import PayrollRunService
from apps.payroll.services.accounting import (
    PayrollAccountingError,
    PayrollAccountingService,
    digest,
)
from apps.payroll.services.accounting_bridge import idempotency_key
from apps.payroll.services.accounting_gate import PayrollAccountingGate

from .test_payroll_flow import PayrollFlowTestCase


User = get_user_model()


class AccountingGateTest(PayrollFlowTestCase):
    factory = APIRequestFactory()

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    def approved_run(self, *, employees=1, basic_salary="10000000", period=None):
        """
        Run yang sudah dihitung dan disetujui, siap difinalisasi.

        `period` boleh dioper supaya dua run bisa hidup di periode yang
        sama — `uniq_active_payroll_period_range` menolak periode kedua
        dengan rentang tanggal yang sama, dan tiap test di sini memakai
        rentang yang sama persis.
        """
        period = period or self.make_period()

        for _ in range(employees):
            self.make_employee(basic_salary=basic_salary)

        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        # Pegawai milik test lain yang ikut tertarik ke run ini — dan
        # baris tanpa konfigurasi lengkap — dikeluarkan, persis seperti
        # jalan keluar bisnisnya.
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

        PayrollRun.objects.filter(pk=run.pk).update(
            status=PayrollRunStatus.APPROVED,
        )

        return PayrollRun.objects.get(pk=run.pk)

    def lines(self, run):
        return PayrollRunEmployee.objects.filter(
            run=run, is_deleted=False, is_excluded=False,
        )

    def assert_not_finalized(self, run):
        run.refresh_from_db()

        self.assertEqual(run.status, PayrollRunStatus.APPROVED)
        self.assertIsNone(run.finalized_at)
        self.assertFalse(Payslip.objects.filter(run=run).exists())

    def finance_rows(self, run) -> tuple[int, int]:
        """
        `(kejadian, jurnal)` milik run ini.

        Per run, bukan hitungan tabel: `TenantTestCase` tidak me-rollback
        antar test, dan sejak PF-0F setiap Finalize yang berhasil di kelas
        ini meninggalkan kejadian dan jurnal drafnya sendiri.
        """
        return (
            AccountingEvent.objects.filter(
                idempotency_key=idempotency_key(run.pk),
            ).count(),
            Journal.objects.filter(
                source_module="payroll",
                source_type="payroll_run",
                source_id=str(run.pk),
            ).count(),
        )

    def finance_is_untouched(self, run):
        return self.finance_rows(run) == (0, 0)

    def period_without_finance_calendar(self, year):
        """
        Periode payroll di tahun yang **tidak** punya tahun buku.

        Tidak lewat `make_period()`, yang sejak PF-0F ikut menyiapkan
        kalender Finance-nya.
        """
        type(self)._counter += 1

        return PayrollPeriod.objects.create(
            company=self.company,
            payroll_group=self.payroll_group,
            code=f"{year}-09-{self._counter}",
            name=f"September {year}",
            start_date=date(year, 9, 1),
            end_date=date(year, 9, 30),
            payment_date=date(year, 10, 5),
            working_days=30,
        )

    # ------------------------------------------------------------------
    # Pemuat di atas database sungguhan
    # ------------------------------------------------------------------

    def test_loader_builds_payload_from_the_database(self):
        run = self.approved_run(employees=2)

        payload = PayrollAccountingService.build_payload(run=run)

        semantics = {row["semantic"] for row in payload["components"]}

        self.assertIn("BASIC_SALARY", semantics)
        self.assertIn("NET_PAY", semantics)
        self.assertEqual(payload["currency"], "IDR")
        self.assertEqual(payload["run"]["id"], run.pk)
        self.assertEqual(payload["run"]["document_number"], run.document_number)
        self.assertEqual(
            payload["control"]["total_debit"],
            payload["control"]["total_credit"],
        )
        self.assertEqual(
            Decimal(payload["control"]["net_pay"]),
            sum(line.net_pay for line in self.lines(run)),
        )

        # Dimensi yang dibekukan ikut, dan tidak ada identitas pegawai.
        row = next(
            row for row in payload["components"]
            if row["semantic"] == "BASIC_SALARY"
        )
        self.assertEqual(row["department_id"], self.department.pk)
        self.assertEqual(row["location_id"], self.location.pk)

    def test_loader_query_count_does_not_grow_with_employees(self):
        # Dua run di **satu** periode: yang kedua dibuat setelah tiga
        # pegawai lagi lahir, jadi barisnya pasti lebih banyak.
        period = self.make_period()

        small = self.approved_run(employees=1, period=period)
        large = self.approved_run(employees=3, period=period)

        self.assertGreater(self.lines(large).count(), self.lines(small).count())

        with CaptureQueriesContext(connection) as first:
            PayrollAccountingService.build_payload(run=small)

        with CaptureQueriesContext(connection) as second:
            PayrollAccountingService.build_payload(run=large)

        self.assertEqual(len(first), len(second))
        self.assertLessEqual(len(second), 10)

    def test_payload_is_deterministic_on_real_data(self):
        run = self.approved_run(employees=2)

        first = PayrollAccountingService.build_payload(run=run)
        second = PayrollAccountingService.build_payload(run=run)

        self.assertEqual(first, second)
        self.assertEqual(first["digest"], digest(second))

    # ------------------------------------------------------------------
    # Finalize yang berhasil
    # ------------------------------------------------------------------

    def test_finalize_passes_the_gate_and_records_one_draft_journal(self):
        run = self.approved_run(employees=2)

        result = PayrollRunService.finalize(run=run)

        run.refresh_from_db()

        self.assertEqual(run.status, PayrollRunStatus.FINALIZED)
        self.assertIsNotNone(run.finalized_at)
        self.assertEqual(result["employees"], self.lines(run).count())
        self.assertTrue(Payslip.objects.filter(run=run).exists())

        # PF-0D berhenti sebelum Finance; PF-0F memindahkan batas itu.
        # Tepat satu kejadian dan satu jurnal — dan jurnalnya DRAFT.
        self.assertEqual(self.finance_rows(run), (1, 1))
        self.assertEqual(result["accounting"]["journal_status"], "draft")

    def test_gate_reports_finance_configuration_context(self):
        run = self.approved_run(
            period=self.period_without_finance_calendar(2097),
        )

        result = PayrollAccountingGate.evaluate(run=run)

        self.assertEqual(result.currency, "IDR")
        self.assertEqual(result.base_currency, "IDR")
        self.assertEqual(result.digest, result.payload["digest"])
        # Kalender Finance belum disusun di tenant test, dan itu
        # **tidak** menghalangi Finalize — ia cuma dilaporkan.
        self.assertEqual(result.period_code, "")
        self.assertNotEqual(result.period_problem, "")

    def test_gate_itself_does_not_block_on_a_missing_calendar(self):
        """
        Keputusan PF-0D yang **tetap**: gerbangnya tidak melempar karena
        kalender Finance belum disusun — ia cuma melaporkannya.
        """
        run = self.approved_run(
            period=self.period_without_finance_calendar(2096),
        )

        result = PayrollAccountingGate.evaluate(run=run)

        self.assertNotEqual(result.period_problem, "")

    def test_finalize_is_blocked_when_finance_calendar_is_missing(self):
        """
        **PF-0F membalik keputusan PF-0D ini dengan sengaja.**

        Dulu Finalize tetap berjalan tanpa kalender Finance, karena belum
        ada jurnal yang diterbitkan. Sekarang jurnal draf adalah bagian
        dari Finalize, dan jurnal tanpa periode akuntansi tidak bisa ada —
        jadi Finalize batal seluruhnya, bukan terkunci tanpa jurnalnya.
        """
        run = self.approved_run(
            period=self.period_without_finance_calendar(2095),
        )

        with self.assertRaises(PayrollAccountingError) as caught:
            PayrollRunService.finalize(run=run)

        self.assertEqual(caught.exception.error_code, "accounting_journal_failed")
        self.assert_not_finalized(run)
        self.assertTrue(self.finance_is_untouched(run))

    # ------------------------------------------------------------------
    # Gerbang yang menolak
    # ------------------------------------------------------------------

    def assert_blocked(self, run, code):
        with self.assertRaises(PayrollAccountingError) as caught:
            PayrollRunService.finalize(run=run)

        self.assertEqual(caught.exception.error_code, code)
        self.assert_not_finalized(run)
        self.assertTrue(self.finance_is_untouched(run))

        return caught.exception

    def test_missing_currency_blocks_finalize(self):
        run = self.approved_run(employees=2)

        self.lines(run).update(currency=None)

        self.assert_blocked(run, "currency_missing")

    def test_mixed_currency_blocks_finalize(self):
        run = self.approved_run(employees=2)

        usd = Currency.objects.create(code="USD", name="Dollar", symbol="$")
        first = self.lines(run).order_by("pk").first()
        PayrollRunEmployee.objects.filter(pk=first.pk).update(currency=usd)

        self.assert_blocked(run, "currency_mixed")

    def test_company_mismatch_blocks_finalize(self):
        run = self.approved_run()

        other = Company.objects.create(code="OTH", name="Other Company")
        self.lines(run).update(company=other)

        self.assert_blocked(run, "company_mismatch")

    def test_non_base_currency_blocks_finalize(self):
        run = self.approved_run()

        # Buku besar berjalan dalam mata uang lain, payroll tidak.
        Currency.objects.filter(pk=self.currency.pk).update(
            is_base_currency=False,
        )
        base = Currency.objects.create(
            code="SGD", name="Singapore Dollar", symbol="S$",
            is_base_currency=True,
        )

        try:
            error = self.assert_blocked(run, "accounting_currency_not_base")
            message = " ".join(error.messages)

            self.assertIn("IDR", message)
            self.assertIn("SGD", message)
        finally:
            Currency.objects.filter(pk=base.pk).delete()
            Currency.objects.filter(pk=self.currency.pk).update(
                is_base_currency=True,
            )

    def test_missing_base_currency_blocks_finalize(self):
        run = self.approved_run()

        Currency.objects.filter(pk=self.currency.pk).update(
            is_base_currency=False,
        )

        try:
            self.assert_blocked(run, "finance_base_currency_missing")
        finally:
            Currency.objects.filter(pk=self.currency.pk).update(
                is_base_currency=True,
            )

    def test_payroll_validation_speaks_before_the_normalizer(self):
        period = self.make_period()
        self.make_employee()
        # Pegawai tanpa `PayrollAssignment` — temuan payroll biasa.
        self.make_employee(with_assignment=False)

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)
        PayrollRunService.validate(run=run)
        PayrollRunService.acknowledge(run=run)

        # Mata uangnya **juga** rusak; yang harus terdengar tetap temuan
        # payroll-nya.
        PayrollRunEmployee.objects.filter(run=run).update(currency=None)

        PayrollRun.objects.filter(pk=run.pk).update(
            status=PayrollRunStatus.APPROVED,
        )
        run.refresh_from_db()

        with self.assertRaises(ValidationError) as caught:
            PayrollRunService.finalize(run=run)

        self.assertNotIsInstance(caught.exception, PayrollAccountingError)
        self.assert_not_finalized(run)

    def test_gate_failure_rolls_back_the_whole_transaction(self):
        run = self.approved_run(employees=2)

        # Total yang sengaja salah. Finalize memperbaikinya lewat
        # `_refresh_totals` **sebelum** gerbang, jadi kalau transaksinya
        # tidak dibatalkan seutuhnya, angka ini ikut tersimpan.
        PayrollRun.objects.filter(pk=run.pk).update(total_net=Decimal("1.00"))
        self.lines(run).update(currency=None)

        with self.assertRaises(PayrollAccountingError):
            PayrollRunService.finalize(run=run)

        run.refresh_from_db()

        self.assertEqual(run.total_net, Decimal("1.00"))
        self.assertEqual(run.status, PayrollRunStatus.APPROVED)
        self.assertFalse(
            PayrollRunEmployee.objects
            .filter(run=run, status="finalized")
            .exists(),
        )
        self.assertFalse(Payslip.objects.filter(run=run).exists())

    # ------------------------------------------------------------------
    # Run yang sudah terkunci
    # ------------------------------------------------------------------

    def test_finalized_run_is_not_renormalized_or_mutated(self):
        run = self.approved_run()

        PayrollRunService.finalize(run=run)
        run.refresh_from_db()

        before = {
            "finalized_at": run.finalized_at,
            "total_net": run.total_net,
            "payslips": list(
                Payslip.objects.filter(run=run)
                .values_list("document_number", flat=True)
            ),
        }

        with self.assertRaises(ValidationError):
            PayrollRunService.finalize(run=run)

        run.refresh_from_db()

        self.assertEqual(run.finalized_at, before["finalized_at"])
        self.assertEqual(run.total_net, before["total_net"])
        self.assertEqual(
            list(
                Payslip.objects.filter(run=run)
                .values_list("document_number", flat=True)
            ),
            before["payslips"],
        )
        # Finalize kedua ditolak, dan Finance tidak menerima apa pun lagi:
        # tetap satu kejadian dan satu jurnal dari Finalize pertama.
        self.assertEqual(self.finance_rows(run), (1, 1))

    # ------------------------------------------------------------------
    # Wewenang
    # ------------------------------------------------------------------

    @classmethod
    def make_account(cls, name, *, permissions=()):
        cls._counter += 1

        user = User.objects.create_user(
            username=f"{name}-{cls._counter}",
            email=f"{name}-{cls._counter}@uji.local",
            password="Uji#12345",
        )

        role = Role.objects.create(
            code=f"{name.upper()}-{cls._counter}",
            name=f"{name} {cls._counter}",
        )

        if permissions:
            role.permissions.add(
                *Permission.objects.filter(
                    content_type__app_label="payroll",
                    codename__in=list(permissions),
                )
            )

        grant_role(user, role, mode=AuthorityMode.UNRESTRICTED)

        return user

    def test_account_without_the_permission_cannot_finalize(self):
        run = self.approved_run()
        user = self.make_account("reader", permissions=["view_payrollrun"])

        with self.assertRaises(PermissionDenied):
            PayrollRunService.finalize(run=run, user=user)

        self.assert_not_finalized(run)

    def test_account_with_the_permission_may_finalize(self):
        run = self.approved_run()
        user = self.make_account(
            "operator",
            permissions=["view_payrollrun", "change_payrollrun"],
        )

        PayrollRunService.finalize(run=run, user=user)

        run.refresh_from_db()

        self.assertEqual(run.status, PayrollRunStatus.FINALIZED)
        self.assertEqual(run.finalized_by_id, user.pk)

    def test_superuser_keeps_working(self):
        run = self.approved_run()

        admin = User.objects.create_superuser(
            username=f"root-{self._counter}",
            email=f"root-{self._counter}@uji.local",
            password="Uji#12345",
        )

        PayrollRunService.finalize(run=run, user=admin)

        run.refresh_from_db()
        self.assertEqual(run.status, PayrollRunStatus.FINALIZED)

    def test_api_action_cannot_bypass_the_service_gate(self):
        run = self.approved_run()
        user = self.make_account("apireader", permissions=["view_payrollrun"])

        request = self.factory.post(
            f"/api/payroll/payroll-runs/{run.pk}/finalize/",
        )
        force_authenticate(request, user=user)

        view = PayrollRunViewSet.as_view({"post": "finalize"})
        response = view(request, pk=run.pk)

        # **403 atau 404, dan keduanya benar** — yang menolak duluan
        # ditentukan saklar `ROLE_AWARE_DATA_SCOPE`:
        #
        # * menyala → cakupan aksi `finalize` dihitung dari
        #   `payroll.change_payrollrun` (lihat `action_scope_permissions`),
        #   akun ini tidak memegangnya, jadi barisnya tidak terlihat sama
        #   sekali: **404**, sebelum service sempat bicara.
        # * mati → cakupan jatuh ke gabungan seluruh penugasan, barisnya
        #   ketemu, dan yang menolak `assert_may_finalize`: **403**.
        #
        # Yang diuji di sini bukan angkanya melainkan bahwa endpoint
        # **tidak** bisa menembus gerbang service.
        self.assertIn(response.status_code, (403, 404))
        self.assert_not_finalized(run)

    # ------------------------------------------------------------------
    # Kontrak baca Finance
    # ------------------------------------------------------------------

    def test_finance_read_contract_reports_base_currency(self):
        config = FinanceAccountingConfigService.configuration_for(
            company=self.company,
        )

        self.assertEqual(config.base_currency_code, "IDR")
        self.assertTrue(config.has_base_currency)
        self.assertFalse(config.has_period)

    def test_finance_read_contract_writes_nothing(self):
        before = (
            Journal.objects.count(),
            JournalLine.objects.count(),
            AccountingEvent.objects.count(),
        )

        FinanceAccountingConfigService.configuration_for(
            company=self.company,
            on_date=self.make_period().end_date,
        )

        self.assertEqual(
            before,
            (
                Journal.objects.count(),
                JournalLine.objects.count(),
                AccountingEvent.objects.count(),
            ),
        )
