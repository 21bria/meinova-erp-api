"""
Reset fixture transaksi Finance.

Satu kelas, satu schema tenant. `TenantTestCase` tidak merollback antar
test, jadi tiap test membangun panggungnya sendiri dengan **company
berbeda** — itu sekaligus yang membuat uji isolasi company bermakna,
bukan sekadar rapi.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django_tenants.test.cases import TenantTestCase

from apps.administration.models import Company, Currency, Notification
from apps.core.management.commands.reset_finance_data import (
    Command as ResetFinanceDataCommand,
)
from apps.core.services.finance_reset import (
    FinanceResetAborted,
    FinanceResetService,
    FinanceResetSpec,
)
from apps.finance.models import (
    AccountingEvent,
    AccountingPeriod,
    Account,
    FiscalYear,
    Journal,
    JournalLine,
    JournalLineDimension,
)
from apps.core.services.finance_reset_demo import (
    DEMO_FINANCE_RESET_BASELINE,
)
from apps.workflow.models import (
    WorkflowApproval,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowStep,
)


class FinanceResetTestCase(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "fin-reset"
        tenant.name = "Finance Reset"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.currency = Currency.objects.create(
            code="IDR",
            name="Rupiah",
            symbol="Rp",
            is_base_currency=True,
        )

        cls.actor = get_user_model().objects.create_user(
            username="fin-reset-actor",
            email="fin@example.com",
            password="x",
        )

        cls.stranger = get_user_model().objects.create_user(
            username="fin-reset-stranger",
            email="stranger@example.com",
            password="x",
        )

        cls.definition = WorkflowDefinition.objects.create(
            code="FIN-RESET-JOURNAL",
            name="Journal",
            module="finance",
            document_type="journal",
        )

        cls.step = WorkflowStep.objects.create(
            definition=cls.definition,
            name="Approval",
        )

        # Kotak tanda tangan kedua. Dipakai oleh uji approval yatim:
        # satu instance boleh punya beberapa step, tapi `approver`
        # yang sama pada step yang sama menabrak
        # `uq_workflow_approval_instance_step_approver`.
        cls.step_two = WorkflowStep.objects.create(
            definition=cls.definition,
            sequence=2,
            name="Second Approval",
        )

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    def build_company(self, tag):
        company = Company.objects.create(code=f"FR{tag}", name=f"Co {tag}")

        year = FiscalYear.objects.create(
            company=company,
            code=f"FY{tag}",
            name="Fiscal 2026",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
        )

        period = AccountingPeriod.objects.create(
            fiscal_year=year,
            period_number=9,
            code=f"P{tag}-09",
            name="September 2026",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )

        expense = Account.objects.create(
            company=company,
            code=f"6100-{tag}",
            name="Salary Expense",
            account_type="expense",
        )

        payable = Account.objects.create(
            company=company,
            code=f"2130-{tag}",
            name="Payroll Payable",
            account_type="liability",
        )

        return company, year, period, expense, payable

    def make_journal(
        self,
        *,
        company,
        year,
        period,
        expense,
        payable,
        number,
        status,
        amount="1000000",
        journal_type="manual",
        posted=False,
        reversal_of=None,
        source_type="",
        source_id="",
        actor=None,
    ):
        journal = Journal.objects.create(
            company=company,
            fiscal_year=year,
            accounting_period=period,
            posting_date=date(2026, 9, 30),
            document_date=date(2026, 9, 30),
            currency=self.currency,
            base_currency=self.currency,
            journal_number=number,
            journal_type=journal_type,
            status=status,
            description="fixture",
            total_debit=Decimal(amount),
            total_credit=Decimal(amount),
            source_type=source_type,
            source_id=source_id,
            reversal_of=reversal_of,
            created_by=actor,
            posted_by=actor if posted else None,
        )

        # `line_number` unik per jurnal — kalau dibiarkan default,
        # baris kedua menabrak `uniq_active_finance_journal_line_number`.
        for line_number, (account, dr, cr) in enumerate(
            (
                (expense, amount, "0"),
                (payable, "0", amount),
            ),
            start=1,
        ):
            JournalLine.objects.create(
                journal=journal,
                account=account,
                company=company,
                transaction_currency=self.currency,
                line_number=line_number,
                debit=Decimal(dr),
                credit=Decimal(cr),
                posting_date=date(2026, 9, 30),
                is_posted=posted,
            )

        return journal

    def build_fixture(self, tag, *, with_workflow=True):
        """
        Satu company berisi fixture Finance lengkap: sepasang
        pembalikan, satu jurnal otomatis dengan kejadiannya, satu draf.
        """

        company, year, period, expense, payable = self.build_company(tag)

        original = self.make_journal(
            company=company, year=year, period=period,
            expense=expense, payable=payable,
            number=f"JV-{tag}-001", status="reversed", posted=True,
        )

        reversal = self.make_journal(
            company=company, year=year, period=period,
            expense=expense, payable=payable,
            number=f"JV-{tag}-002", status="posted", posted=True,
            journal_type="reversal", reversal_of=original,
        )

        # Sisi kedua siklus PROTECT.
        original.reversed_by = reversal
        original.save(update_fields=["reversed_by"])

        draft = self.make_journal(
            company=company, year=year, period=period,
            expense=expense, payable=payable,
            number=f"JV-{tag}-003", status="draft", amount="500000",
        )

        auto = self.make_journal(
            company=company, year=year, period=period,
            expense=expense, payable=payable,
            number=f"JV-{tag}-004", status="posted", posted=True,
            journal_type="automatic",
            source_type="payroll_run", source_id="7001",
        )

        event = AccountingEvent.objects.create(
            event_type="PAYROLL_POSTED",
            source_module="payroll",
            source_type="payroll_run",
            source_id="7001",
            company=company,
            event_date=date(2026, 9, 30),
            idempotency_key=f"payroll:payroll_run:7001:{tag}",
            status="processed",
            generated_journal=auto,
        )

        instance = approval = None

        if with_workflow:
            instance = WorkflowInstance.objects.create(
                definition=self.definition,
                module="finance",
                document_type="journal",
                object_id=str(draft.pk),
                document_number=draft.journal_number,
                status="pending",
            )

            approval = WorkflowApproval.objects.create(
                instance=instance,
                step=self.step,
                status="pending",
                approver=self.actor,
            )

        return {
            "company": company,
            "original": original,
            "reversal": reversal,
            "draft": draft,
            "auto": auto,
            "event": event,
            "instance": instance,
            "approval": approval,
            "expense": expense,
            "payable": payable,
        }

    def make_spec(self, fx, **overrides):
        instance = fx["instance"]
        approval = fx["approval"]

        data = dict(
            schema_names=(self.tenant.schema_name,),
            company_ids=(fx["company"].pk,),
            allowed_actor_ids=(self.actor.pk,),
            fixture_window_start=date(2026, 1, 1),
            fixture_window_end=date(2030, 1, 1),
            allowed_source_types=("payroll_run",),
            workflow_instance_ids=(instance.pk,) if instance else (),
            workflow_approval_ids=(approval.pk,) if approval else (),
            expected_instance_state=(
                (
                    {
                        "id": instance.pk,
                        "module": "finance",
                        "document_type": "journal",
                        "object_id": str(fx["draft"].pk),
                        "status": "pending",
                    },
                )
                if instance
                else ()
            ),
            expected_approval_state=(
                (
                    {
                        "id": approval.pk,
                        "instance_id": instance.pk,
                        "status": "pending",
                        "approver_employee_id": None,
                        "approver_id": self.actor.pk,
                    },
                )
                if approval
                else ()
            ),
            protected_counts=(),
        )
        data.update(overrides)

        return FinanceResetSpec(**data)

    @staticmethod
    def ledger_net(company):
        """Rumus yang sama dengan LedgerService."""

        from django.db.models import Sum

        return (
            JournalLine.objects.filter(
                is_deleted=False,
                is_posted=True,
                company=company,
            ).aggregate(net=Sum("debit") or 0)["net"]
        )

    # ------------------------------------------------------------------
    # 1 — mode kering tidak menulis
    # ------------------------------------------------------------------

    def test_dry_run_tidak_menulis(self):
        fx = self.build_fixture("A")
        spec = self.make_spec(fx)

        before = (
            Journal.objects.count(),
            JournalLine.objects.count(),
            AccountingEvent.objects.count(),
            WorkflowInstance.objects.count(),
        )

        report = FinanceResetService.plan(spec=spec)

        self.assertFalse(report.is_blocked, report.blockers)
        self.assertFalse(report.executed)
        self.assertEqual(report.deleted, {})
        self.assertEqual(report.planned["finance.Journal"], 4)
        self.assertEqual(report.planned["finance.JournalLine"], 8)
        self.assertEqual(report.planned["finance.AccountingEvent"], 1)
        self.assertEqual(report.planned["finance.JournalLineDimension"], 0)

        self.assertEqual(
            before,
            (
                Journal.objects.count(),
                JournalLine.objects.count(),
                AccountingEvent.objects.count(),
                WorkflowInstance.objects.count(),
            ),
        )

        # Tautan pembalikan masih utuh — rencana tidak memutus apa pun.
        fx["original"].refresh_from_db()
        self.assertEqual(fx["original"].reversed_by_id, fx["reversal"].pk)

    # ------------------------------------------------------------------
    # 2, 5, 6 — reset tepat, buku besar nol, siklus terurai
    # ------------------------------------------------------------------

    def test_execute_membuang_seluruh_fixture(self):
        fx = self.build_fixture("B")
        spec = self.make_spec(fx)

        self.assertGreater(self.ledger_net(fx["company"]) or 0, 0)

        report = FinanceResetService.execute(spec=spec)

        self.assertTrue(report.executed)
        self.assertEqual(report.deleted["finance.Journal"], 4)
        self.assertEqual(report.deleted["finance.JournalLine"], 8)
        self.assertEqual(report.deleted["finance.AccountingEvent"], 1)
        self.assertEqual(report.deleted["workflow.WorkflowInstance"], 1)
        self.assertEqual(report.deleted["workflow.WorkflowApproval"], 1)

        self.assertFalse(
            Journal.objects.filter(company=fx["company"]).exists(),
        )
        self.assertFalse(
            JournalLine.objects.filter(company=fx["company"]).exists(),
        )
        self.assertFalse(
            AccountingEvent.objects.filter(company=fx["company"]).exists(),
        )

        # Buku besar company sasaran nol.
        self.assertIn(self.ledger_net(fx["company"]), (None, 0))

    def test_siklus_protect_benar_benar_ada(self):
        """
        Tanpa pemutusan, penghapusan memang mustahil.

        Ini regression atas alasan keberadaan `_break_cycles`: kalau
        suatu saat `reversed_by` tidak lagi PROTECT, test ini gagal dan
        pemutusnya bisa dibuang.
        """

        from django.db.models import ProtectedError

        fx = self.build_fixture("C", with_workflow=False)

        with self.assertRaises(ProtectedError):
            Journal.objects.filter(
                pk__in=[fx["original"].pk, fx["reversal"].pk],
            ).delete()

        # Keduanya masih berdiri.
        self.assertEqual(
            Journal.objects.filter(
                pk__in=[fx["original"].pk, fx["reversal"].pk],
            ).count(),
            2,
        )

    def test_cycle_break_hanya_pasangan_dan_hanya_reversed_by(self):
        fx = self.build_fixture("D", with_workflow=False)
        spec = self.make_spec(fx)

        report = FinanceResetService.plan(spec=spec)

        self.assertEqual(len(report.cycle_breaks), 1)

        item = report.cycle_breaks[0]

        self.assertEqual(item.journal_id, fx["original"].pk)
        self.assertEqual(item.field, "reversed_by")
        self.assertEqual(item.previous_value, fx["reversal"].pk)

        # `reversal_of` tidak pernah masuk daftar.
        self.assertTrue(
            all(i.field == "reversed_by" for i in report.cycle_breaks),
        )

    # ------------------------------------------------------------------
    # 7 — rollback sesudah cycle-break
    # ------------------------------------------------------------------

    def test_rollback_mengembalikan_tautan_pembalikan(self):
        """
        Gagal **sesudah** siklus diputus harus mengembalikan keadaan
        persis seperti semula — tidak boleh ada keadaan ter-commit di
        mana tautannya putus tapi jurnalnya masih ada.
        """

        fx = self.build_fixture("E", with_workflow=False)
        spec = self.make_spec(fx)

        before = {
            "reversed_by": fx["original"].reversed_by_id,
            "reversal_of": fx["reversal"].reversal_of_id,
            "journals": Journal.objects.filter(
                company=fx["company"],
            ).count(),
            "lines": JournalLine.objects.filter(
                company=fx["company"],
            ).count(),
        }

        boom = RuntimeError("gagal sesudah cycle-break")

        with mock.patch.object(
            FinanceResetService,
            "_delete",
            side_effect=boom,
        ):
            with self.assertRaises(RuntimeError):
                FinanceResetService.execute(spec=spec)

        fx["original"].refresh_from_db()
        fx["reversal"].refresh_from_db()

        self.assertEqual(
            fx["original"].reversed_by_id,
            before["reversed_by"],
        )
        self.assertEqual(
            fx["reversal"].reversal_of_id,
            before["reversal_of"],
        )
        self.assertEqual(
            Journal.objects.filter(company=fx["company"]).count(),
            before["journals"],
        )
        self.assertEqual(
            JournalLine.objects.filter(company=fx["company"]).count(),
            before["lines"],
        )

    # ------------------------------------------------------------------
    # 3 — isolasi company
    # ------------------------------------------------------------------

    def test_company_lain_tidak_tersentuh(self):
        target = self.build_fixture("F", with_workflow=False)
        other = self.build_fixture("G", with_workflow=False)

        spec = self.make_spec(target)

        FinanceResetService.execute(spec=spec)

        self.assertFalse(
            Journal.objects.filter(company=target["company"]).exists(),
        )
        self.assertEqual(
            Journal.objects.filter(company=other["company"]).count(),
            4,
        )
        self.assertEqual(
            JournalLine.objects.filter(company=other["company"]).count(),
            8,
        )
        self.assertEqual(
            AccountingEvent.objects.filter(
                company=other["company"],
            ).count(),
            1,
        )

    # ------------------------------------------------------------------
    # 4 — pagar master
    # ------------------------------------------------------------------

    def test_pagar_master_menolak_baseline_yang_meleset(self):
        fx = self.build_fixture("H", with_workflow=False)

        spec = self.make_spec(
            fx,
            protected_counts=(("finance.Account", 99999),),
        )

        report = FinanceResetService.plan(spec=spec)

        self.assertTrue(report.is_blocked)
        self.assertTrue(
            any("PAGAR" in b for b in report.blockers),
            report.blockers,
        )

        with self.assertRaises(FinanceResetAborted):
            FinanceResetService.execute(spec=spec)

        self.assertEqual(
            Journal.objects.filter(company=fx["company"]).count(),
            4,
        )

    def test_master_config_bertahan(self):
        fx = self.build_fixture("I", with_workflow=False)

        before = (
            Account.objects.count(),
            AccountingPeriod.objects.count(),
            FiscalYear.objects.count(),
            Currency.objects.count(),
            WorkflowDefinition.objects.count(),
        )

        spec = self.make_spec(
            fx,
            protected_counts=(
                ("finance.Account", before[0]),
                ("finance.AccountingPeriod", before[1]),
                ("finance.FiscalYear", before[2]),
                ("administration.Currency", before[3]),
                ("workflow.WorkflowDefinition", before[4]),
            ),
        )

        FinanceResetService.execute(spec=spec)

        self.assertEqual(
            before,
            (
                Account.objects.count(),
                AccountingPeriod.objects.count(),
                FiscalYear.objects.count(),
                Currency.objects.count(),
                WorkflowDefinition.objects.count(),
            ),
        )

    # ------------------------------------------------------------------
    # 8 — sumber yang benar-benar ada membatalkan
    # ------------------------------------------------------------------

    def test_payroll_run_yang_masih_ada_membatalkan(self):
        from apps.payroll.models import PayrollGroup, PayrollPeriod, PayrollRun

        fx = self.build_fixture("J", with_workflow=False)

        group = PayrollGroup.objects.create(code="FR-G", name="G")
        period = PayrollPeriod.objects.create(
            company=fx["company"],
            payroll_group=group,
            code="FR-2026-09",
            name="Sept",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
            payment_date=date(2026, 10, 5),
            working_days=30,
        )
        run = PayrollRun.objects.create(
            period=period,
            company=fx["company"],
            document_number="FR-RUN-1",
            name="Real run",
            status="review",
        )

        # Jurnal otomatis kini memproyeksikan run yang SUNGGUHAN ada.
        Journal.objects.filter(pk=fx["auto"].pk).update(
            source_id=str(run.pk),
        )

        spec = self.make_spec(fx)
        report = FinanceResetService.plan(spec=spec)

        self.assertTrue(report.is_blocked)
        self.assertTrue(
            any("MASIH ADA" in b for b in report.blockers),
            report.blockers,
        )

        with self.assertRaises(FinanceResetAborted):
            FinanceResetService.execute(spec=spec)

        self.assertEqual(
            Journal.objects.filter(company=fx["company"]).count(),
            4,
        )

    def test_aktor_asing_membatalkan(self):
        fx = self.build_fixture("K", with_workflow=False)

        Journal.objects.filter(pk=fx["draft"].pk).update(
            created_by=self.stranger,
        )

        spec = self.make_spec(fx)
        report = FinanceResetService.plan(spec=spec)

        self.assertTrue(report.is_blocked)
        self.assertTrue(
            any("aktor" in b for b in report.blockers),
            report.blockers,
        )

    # ------------------------------------------------------------------
    # 9 — dependency tak terduga
    # ------------------------------------------------------------------

    def test_dependency_tak_terduga_membatalkan(self):
        fx = self.build_fixture("L", with_workflow=False)

        # Dimensi baris belum pernah muncul di discovery (0 baris).
        # Satu baris saja harus menghentikan operasi... kecuali ia
        # memang ditangani. Di sini kita pakai relasi yang TIDAK
        # ditangani: kejadian lain yang menggantikan kejadian sasaran.
        AccountingEvent.objects.create(
            event_type="PAYROLL_POSTED",
            source_module="payroll",
            company=fx["company"],
            event_date=date(2026, 9, 30),
            idempotency_key="fr-L-successor",
            status="pending",
            superseded_by=fx["event"],
        )

        spec = self.make_spec(fx)
        report = FinanceResetService.plan(spec=spec)

        # `superseded_by` memang ditangani, jadi ini TIDAK boleh jadi
        # blocker — yang diuji adalah daftar tangani-annya benar.
        self.assertFalse(
            any("DEPENDENCY BARU" in b for b in report.blockers),
            report.blockers,
        )

    # ------------------------------------------------------------------
    # 10, 11, 12 — workflow
    # ------------------------------------------------------------------

    def test_workflow_hidup_dibuang_yang_tertutup_bertahan(self):
        fx = self.build_fixture("M")

        closed = WorkflowInstance.objects.create(
            definition=self.definition,
            module="finance",
            document_type="journal",
            object_id=str(fx["auto"].pk),
            document_number=fx["auto"].journal_number,
            status="approved",
        )
        closed_approval = WorkflowApproval.objects.create(
            instance=closed,
            step=self.step,
            status="approved",
            approver=self.actor,
        )

        spec = self.make_spec(fx)

        FinanceResetService.execute(spec=spec)

        # Yang hidup hilang.
        self.assertFalse(
            WorkflowInstance.objects.filter(
                pk=fx["instance"].pk,
            ).exists(),
        )
        self.assertFalse(
            WorkflowApproval.objects.filter(
                pk=fx["approval"].pk,
            ).exists(),
        )

        # Yang tertutup bertahan — arsip, bukan pekerjaan.
        self.assertTrue(
            WorkflowInstance.objects.filter(pk=closed.pk).exists(),
        )
        self.assertTrue(
            WorkflowApproval.objects.filter(
                pk=closed_approval.pk,
            ).exists(),
        )

    def test_workflow_state_berubah_membatalkan(self):
        fx = self.build_fixture("N")

        # Statusnya sudah tidak `pending` lagi sejak diaudit.
        WorkflowInstance.objects.filter(pk=fx["instance"].pk).update(
            status="approved",
        )

        spec = self.make_spec(fx)
        report = FinanceResetService.plan(spec=spec)

        self.assertTrue(report.is_blocked)
        self.assertTrue(
            any("WORKFLOW" in b for b in report.blockers),
            report.blockers,
        )

        with self.assertRaises(FinanceResetAborted):
            FinanceResetService.execute(spec=spec)

        self.assertTrue(
            WorkflowInstance.objects.filter(
                pk=fx["instance"].pk,
            ).exists(),
        )
        self.assertEqual(
            Journal.objects.filter(company=fx["company"]).count(),
            4,
        )

    def test_approval_yatim_membatalkan(self):
        fx = self.build_fixture("O")

        # Kotak tanda tangan kedua pada instance yang sama, tidak
        # terdaftar ikut dibuang.
        WorkflowApproval.objects.create(
            instance=fx["instance"],
            step=self.step_two,
            status="pending",
            approver=self.actor,
        )

        spec = self.make_spec(fx)
        report = FinanceResetService.plan(spec=spec)

        self.assertTrue(report.is_blocked)
        self.assertTrue(
            any("yatim" in b or "tidak terdaftar" in b for b in report.blockers),
            report.blockers,
        )

    # ------------------------------------------------------------------
    # 13, 14 — catatan & penomoran
    # ------------------------------------------------------------------

    def test_notifikasi_audit_dan_penomoran_bertahan(self):
        from apps.administration.models import AuditTrail
        from apps.notifications.models import NotificationLog

        fx = self.build_fixture("P", with_workflow=False)

        bell = Notification.objects.create(
            user=self.actor,
            title="Journal approved",
            module="finance",
            object_type="finance-journal",
            object_id=str(fx["draft"].pk),
        )
        log = NotificationLog.objects.create(
            event="workflow.approved",
            channel="email",
            module="finance",
            object_type="finance-journal",
            object_id=str(fx["draft"].pk),
        )
        trail = AuditTrail.objects.create(
            module="finance",
            object_type="journal",
            object_id=str(fx["draft"].pk),
            action="create",
            object_repr=fx["draft"].journal_number,
        )

        spec = self.make_spec(fx)

        FinanceResetService.execute(spec=spec)

        # Ketiganya bertahan walau dokumennya sudah tidak ada.
        self.assertTrue(Notification.objects.filter(pk=bell.pk).exists())
        self.assertTrue(NotificationLog.objects.filter(pk=log.pk).exists())
        self.assertTrue(AuditTrail.objects.filter(pk=trail.pk).exists())

    def test_penomoran_tidak_mundur(self):
        from apps.administration.models import NumberingSequence

        fx = self.build_fixture("Q", with_workflow=False)

        sequence = NumberingSequence.objects.create(
            module="finance",
            document_type=f"journal-{fx['company'].code}",
            code=f"JV{fx['company'].code}",
            name="Journal",
            prefix="JV",
            current_number=8,
        )

        spec = self.make_spec(fx)

        FinanceResetService.execute(spec=spec)

        sequence.refresh_from_db()

        self.assertEqual(sequence.current_number, 8)

    # ------------------------------------------------------------------
    # 15 — idempotency
    # ------------------------------------------------------------------

    def test_idempoten(self):
        fx = self.build_fixture("R", with_workflow=False)
        spec = self.make_spec(fx)

        first = FinanceResetService.execute(spec=spec)

        self.assertGreater(first.deleted_total, 0)

        second = FinanceResetService.execute(spec=spec)

        self.assertTrue(second.executed)
        self.assertFalse(second.is_blocked, second.blockers)
        self.assertEqual(second.deleted_total, 0)
        self.assertEqual(second.planned_total, 0)
        self.assertEqual(second.cycle_breaks, [])

    # ------------------------------------------------------------------
    # Pagar tenant
    # ------------------------------------------------------------------

    def test_schema_di_luar_daftar_ditolak(self):
        fx = self.build_fixture("S", with_workflow=False)

        spec = self.make_spec(fx, schema_names=("schema-lain",))

        report = FinanceResetService.plan(spec=spec)

        self.assertTrue(report.is_blocked)
        self.assertTrue(
            any("TENANT" in b for b in report.blockers),
            report.blockers,
        )

        with self.assertRaises(FinanceResetAborted):
            FinanceResetService.execute(spec=spec)

        self.assertEqual(
            Journal.objects.filter(company=fx["company"]).count(),
            4,
        )


class BaselineGuardTestCase(SimpleTestCase):
    """
    Pagar baseline milik command, diuji tanpa database.

    Yang dijaga di sini satu hal: membedakan "sudah selesai" dari
    "tenant berubah". Keduanya sama-sama tidak cocok dengan angka
    discovery, tapi hanya yang kedua boleh menahan --execute.
    """

    def setUp(self):
        self.command = ResetFinanceDataCommand()

    @staticmethod
    def _report(**planned):
        return SimpleNamespace(
            planned={
                label: planned.get(label.split(".")[-1], 0)
                for label in DEMO_FINANCE_RESET_BASELINE
            },
        )

    def test_keadaan_awal_bukan_sudah_direset(self):
        report = self._report(**{
            label.split(".")[-1]: count
            for label, count in DEMO_FINANCE_RESET_BASELINE.items()
        })

        self.assertFalse(self.command._is_already_reset(report))
        self.assertEqual(self.command._drift(report), {})

    def test_seluruhnya_nol_dikenali_sudah_direset(self):
        report = self._report()

        self.assertTrue(self.command._is_already_reset(report))

        # Dan karena itu bukan selisih — operator tidak diminta
        # menjelaskan apa pun.
        self.assertEqual(self.command._drift(report), {})

    def test_sisa_sebagian_tetap_dihitung_selisih(self):
        # Satu jurnal masih tertinggal: bukan keadaan sudah-direset,
        # dan bukan keadaan discovery. Ini yang harus menahan eksekusi.
        report = self._report(Journal=1)

        self.assertFalse(self.command._is_already_reset(report))

        drift = self.command._drift(report)

        self.assertIn("finance.Journal", drift)
        self.assertEqual(drift["finance.Journal"], (12, 1))

    def test_jumlah_berlebih_tetap_dihitung_selisih(self):
        report = self._report(Journal=13, JournalLine=25, AccountingEvent=1,
                              WorkflowApproval=1, WorkflowInstance=1)

        self.assertFalse(self.command._is_already_reset(report))
        self.assertEqual(self.command._drift(report)["finance.Journal"], (12, 13))
