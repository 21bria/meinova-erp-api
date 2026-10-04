"""
PF-0G — run koreksi payroll: identitas, rantai, wewenang, dan akibat
akuntansinya.

Modelnya **REPLACEMENT**: run koreksi berisi hasil payroll periode itu
yang sudah benar, seluruhnya — bukan selisihnya. Mesin hitung memang
hanya bisa menghitung run utuh, dan slip gaji adalah pernyataan lengkap,
bukan selisih.

Akibat akuntansinya bergantung pada nasib proyeksi lama:

* **Case A** — jurnal lama masih DRAFT: satu transaksi mencabut
  keberlakuannya (kejadian SUPERSEDED, jurnal CANCELLED) dan menerbitkan
  penggantinya. Nol dampak buku besar.
* **Case B** — jurnal lama sudah POSTED: sejarahnya tidak disentuh.
  Penggantinya terbit DRAFT dan **tidak bisa diposting** sampai aktor
  Finance membalik jurnal lamanya.
* **Case C** — run lama/historis tanpa proyeksi: koreksi ditolak.

Yang asli tidak pernah berubah: baris, slip, payload, digest, kejadian,
dan jurnalnya tetap apa adanya.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError

from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import AuthorityMode, Role
from apps.accounts.services.role_assignment import grant_role
from apps.administration.models import Company
from apps.finance.models import (
    AccountingEvent,
    AccountingEventStatus,
    Journal,
    JournalLine,
    JournalStatus,
)
from apps.finance.services import (
    FinancePostingService,
    FinanceReversalService,
)
from apps.payroll.models import (
    PayrollRun,
    PayrollRunEmployee,
    PayrollRunStatus,
    PayrollRunType,
    Payslip,
)
from apps.payroll.services import PayrollRunService
from apps.payroll.services.accounting import PayrollAccountingError
from apps.payroll.services.accounting_bridge import (
    PayrollAccountingBridge,
    idempotency_key,
)
from apps.payroll.services.accounting_gate import PayrollAccountingGate

from .test_payroll_flow import PayrollFlowTestCase


User = get_user_model()


class PayrollCorrectionTestCase(PayrollFlowTestCase):

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    def approved_run(self, *employees, period=None, correction_of=None):
        """Run siap finalisasi, berisi **hanya** pegawai yang dioper."""
        period = period or self.make_period()
        employees = employees or (self.make_employee(),)

        if correction_of is None:
            run = self.make_run(period)
        else:
            run = PayrollRunService.create(
                data={
                    "period": period,
                    "run_type": PayrollRunType.CORRECTION,
                    "corrects_run": correction_of,
                },
                user=self.corrector(),
            )

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        PayrollRunEmployee.objects.filter(run=run).exclude(
            employee__in=employees,
        ).update(
            is_excluded=True, status="excluded",
            exclusion_reason="Milik test lain (fixture).",
        )

        PayrollRunService._refresh_totals(run=run)
        PayrollRunService.validate(run=run)
        PayrollRunService.acknowledge(run=run)

        PayrollRun.objects.filter(pk=run.pk).update(
            status=PayrollRunStatus.APPROVED,
        )

        return PayrollRun.objects.get(pk=run.pk)

    def finalized_original(self):
        """Satu pegawai, run asli yang sudah final + proyeksinya."""
        employee = self.make_employee()
        run = self.approved_run(employee)

        PayrollRunService.finalize(run=run, user=self.corrector())

        return PayrollRun.objects.get(pk=run.pk), employee

    def correction_for(self, target, employee, *, user=None):
        run = self.approved_run(
            employee, period=target.period, correction_of=target,
        )

        return PayrollRunService.finalize(
            run=run, user=user or self.corrector(),
        ), PayrollRun.objects.get(pk=run.pk)

    # ------------------------------------------------------------------
    # Aktor
    # ------------------------------------------------------------------

    @classmethod
    def user_with(cls, *codenames, name="actor", unrestricted=True):
        cls._counter += 1
        username = f"{name}-{cls._counter}"

        user = User.objects.create_user(
            username=username, email=f"{username}@uji.local",
            password="Uji#12345",
        )

        role = Role.objects.create(
            code=f"{name.upper()}-{cls._counter}", name=username,
        )

        for label in codenames:
            app_label, codename = label.split(".")
            role.permissions.add(Permission.objects.get(
                content_type__app_label=app_label, codename=codename,
            ))

        if unrestricted:
            grant_role(user, role, mode=AuthorityMode.UNRESTRICTED)
        else:
            grant_role(user, role, mode=AuthorityMode.EXPLICIT)

        return User.objects.get(pk=user.pk)

    @classmethod
    def corrector(cls):
        """Berwenang memfinalisasi **dan** mengoreksi."""
        return cls.user_with(
            "payroll.change_payrollrun",
            "payroll.correct_payrollrun",
            "payroll.view_payrollrun",
            name="corrector",
        )

    # ------------------------------------------------------------------
    # Pembacaan Finance
    # ------------------------------------------------------------------

    def event_of(self, run):
        return AccountingEvent.objects.filter(
            idempotency_key=idempotency_key(run.pk),
        ).first()

    def journal_of(self, run):
        return Journal.objects.filter(
            source_module="payroll", source_type="payroll_run",
            source_id=str(run.pk),
        ).first()

    def snapshot(self, run):
        """Sidik lengkap proyeksi sebuah run — isi, bukan sekadar status."""
        event = self.event_of(run)
        journal = self.journal_of(run)

        return (
            event.payload,
            event.idempotency_key,
            event.generated_journal_id,
            tuple(journal.lines.order_by("id").values_list(
                "account_id", "debit", "credit", "description",
                "is_posted", "department_id", "cost_center_id",
            )),
            str(journal.total_debit),
            tuple(sorted((journal.metadata or {}).items())),
        )

    def payslip_snapshot(self, run):
        return tuple(
            Payslip.objects.filter(run=run).order_by("id").values_list(
                "id", "document_number", "net_pay", "gross_earning",
            )
        )


# ======================================================================
# Relasi koreksi
# ======================================================================


class CorrectionRelationTests(PayrollCorrectionTestCase):

    def unsaved(self, **fields):
        """
        Run koreksi yang belum disimpan, untuk menguji `full_clean()` saja.

        Periodenya hanya dibuat kalau pemanggil tidak mengoper satu:
        rentang tanggal periode payroll unik per company + grup, jadi
        membuatnya cuma-cuma akan menabrak periode yang sudah ada.
        """
        data = {
            "company": self.company,
            "run_type": PayrollRunType.CORRECTION,
        }
        data.update(fields)

        if data.get("period") is None:
            data["period"] = self.make_period()

        return PayrollRun(**data)

    def rival_period(self):
        """Periode payroll lain yang sah — bulan berikutnya, bukan salinan."""
        from datetime import date

        from apps.payroll.models import PayrollPeriod

        self.ensure_finance_calendar(date(2026, 10, 31))

        return PayrollPeriod.objects.create(
            company=self.company,
            payroll_group=self.payroll_group,
            code="2026-10-rival",
            name="Oktober 2026",
            start_date=date(2026, 10, 1),
            end_date=date(2026, 10, 31),
            payment_date=date(2026, 11, 5),
            working_days=31,
        )

    def test_correction_requires_a_target(self):
        run = self.unsaved()

        with self.assertRaises(ValidationError) as caught:
            run.full_clean()

        self.assertIn("corrects_run", caught.exception.message_dict)

    def test_ordinary_run_cannot_point_at_a_target(self):
        original, _ = self.finalized_original()

        run = self.unsaved(
            run_type=PayrollRunType.REGULAR,
            corrects_run=original,
            period=original.period,
        )

        with self.assertRaises(ValidationError) as caught:
            run.full_clean()

        self.assertIn("corrects_run", caught.exception.message_dict)

    def test_target_must_be_finalized(self):
        target = self.approved_run()

        run = self.unsaved(corrects_run=target, period=target.period)

        with self.assertRaises(ValidationError) as caught:
            run.full_clean()

        self.assertIn("belum difinalisasi", str(caught.exception))

    def test_target_must_share_the_payroll_period(self):
        original, _ = self.finalized_original()

        run = self.unsaved(corrects_run=original, period=self.rival_period())

        with self.assertRaises(ValidationError) as caught:
            run.full_clean()

        self.assertIn("periode payroll yang sama", str(caught.exception))

    def test_target_must_share_the_company(self):
        original, _ = self.finalized_original()

        rival = Company.objects.create(
            code=f"RIV{original.pk}", name="Rival",
        )

        run = self.unsaved(
            corrects_run=original, period=original.period, company=rival,
        )

        with self.assertRaises(ValidationError) as caught:
            run.full_clean()

        self.assertIn("company", str(caught.exception).lower())

    def test_a_run_cannot_correct_itself(self):
        original, _ = self.finalized_original()

        original.run_type = PayrollRunType.CORRECTION
        original.corrects_run = original

        with self.assertRaises(ValidationError) as caught:
            original.full_clean()

        self.assertIn("dirinya sendiri", str(caught.exception))

    def test_correction_chain_cannot_loop(self):
        original, employee = self.finalized_original()
        _, correction = self.correction_for(original, employee)

        # A ← B sudah ada; mencoba membuat A menunjuk B menutup lingkaran.
        original.run_type = PayrollRunType.CORRECTION
        original.corrects_run = correction

        with self.assertRaises(ValidationError) as caught:
            original.full_clean()

        self.assertIn("melingkar", str(caught.exception))


# ======================================================================
# Rantai: satu penerus aktif
# ======================================================================


class CorrectionChainTests(PayrollCorrectionTestCase):

    def create_correction(self, target, user=None):
        return PayrollRunService.create(
            data={
                "period": target.period,
                "run_type": PayrollRunType.CORRECTION,
                "corrects_run": target,
            },
            user=user or self.corrector(),
        )

    def test_second_active_correction_is_refused(self):
        original, _ = self.finalized_original()

        first = self.create_correction(original)

        with self.assertRaises(ValidationError) as caught:
            self.create_correction(original)

        self.assertIn("koreksi aktif", str(caught.exception))
        self.assertEqual(
            PayrollRun.objects.filter(corrects_run=original).count(), 1,
        )
        self.assertEqual(first.status, PayrollRunStatus.DRAFT)

    def test_cancelling_a_draft_correction_releases_the_slot(self):
        original, _ = self.finalized_original()

        first = self.create_correction(original)
        PayrollRunService.cancel(run=first, user=self.corrector())

        second = self.create_correction(original)

        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(
            PayrollRunService.active_successor(original).pk, second.pk,
        )

    def test_a_finalized_correction_never_releases_the_slot(self):
        original, employee = self.finalized_original()
        _, correction = self.correction_for(original, employee)

        self.assertEqual(correction.status, PayrollRunStatus.FINALIZED)

        with self.assertRaises(ValidationError):
            self.create_correction(original)

    def test_a_correction_can_itself_be_corrected(self):
        original, employee = self.finalized_original()
        _, first = self.correction_for(original, employee)

        _, second = self.correction_for(first, employee)

        self.assertEqual(second.corrects_run_id, first.pk)
        self.assertEqual(first.corrects_run_id, original.pk)

        # Rantai, bukan cabang.
        self.assertEqual(
            PayrollRun.objects.filter(corrects_run=original).count(), 1,
        )

    def test_the_database_itself_refuses_a_second_active_successor(self):
        """
        Aturan service dan constraint database harus sepakat. Di sini
        jalur service dilewati dengan sengaja.
        """
        from django.db import IntegrityError, transaction

        original, _ = self.finalized_original()

        self.create_correction(original)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PayrollRun.objects.create(
                    period=original.period,
                    company=original.company,
                    run_type=PayrollRunType.CORRECTION,
                    corrects_run=original,
                    document_number=f"RAW-{original.pk}",
                    status=PayrollRunStatus.DRAFT,
                )

    def test_correction_relation_cannot_be_moved_afterwards(self):
        original, _ = self.finalized_original()

        correction = self.create_correction(original)

        PayrollRunService.update(
            instance=correction,
            data={"corrects_run": None, "run_type": PayrollRunType.REGULAR},
            user=self.corrector(),
        )

        correction.refresh_from_db()

        self.assertEqual(correction.corrects_run_id, original.pk)
        self.assertEqual(correction.run_type, PayrollRunType.CORRECTION)


# ======================================================================
# Wewenang
# ======================================================================


class CorrectionAuthorityTests(PayrollCorrectionTestCase):

    def attempt(self, original, user):
        return PayrollRunService.create(
            data={
                "period": original.period,
                "run_type": PayrollRunType.CORRECTION,
                "corrects_run": original,
            },
            user=user,
        )

    def test_finalize_permission_alone_cannot_correct(self):
        original, _ = self.finalized_original()

        user = self.user_with("payroll.change_payrollrun", name="finalizer")

        with self.assertRaises(PermissionDenied):
            self.attempt(original, user)

        self.assertFalse(
            PayrollRun.objects.filter(corrects_run=original).exists(),
        )

    def test_account_without_any_role_cannot_correct(self):
        original, _ = self.finalized_original()

        self._counter += 1
        bare = User.objects.create_user(
            username=f"bare-{self._counter}",
            email=f"bare-{self._counter}@uji.local", password="x",
        )

        with self.assertRaises(PermissionDenied):
            self.attempt(original, bare)

    def test_finance_authority_cannot_correct_payroll(self):
        original, _ = self.finalized_original()

        user = self.user_with(
            "finance.post_journal", "finance.reverse_journal",
            "finance.change_journal", name="finance",
        )

        with self.assertRaises(PermissionDenied):
            self.attempt(original, user)

    def test_correction_permission_outside_scope_is_denied(self):
        """Izin benar, cakupan tidak memuat run-nya."""
        original, _ = self.finalized_original()

        user = self.user_with(
            "payroll.correct_payrollrun", "payroll.change_payrollrun",
            name="outscope", unrestricted=False,
        )

        with self.assertRaises(PermissionDenied):
            self.attempt(original, user)

    def test_correction_permission_with_scope_is_allowed(self):
        original, _ = self.finalized_original()

        run = self.attempt(original, self.corrector())

        self.assertEqual(run.corrects_run_id, original.pk)
        self.assertEqual(run.run_type, PayrollRunType.CORRECTION)

    def test_finalizing_a_correction_also_needs_correction_authority(self):
        original, employee = self.finalized_original()

        run = self.approved_run(
            employee, period=original.period, correction_of=original,
        )

        finalizer = self.user_with(
            "payroll.change_payrollrun", name="onlyfinalize",
        )

        with self.assertRaises(PermissionDenied):
            PayrollRunService.finalize(run=run, user=finalizer)

        run.refresh_from_db()

        self.assertEqual(run.status, PayrollRunStatus.APPROVED)
        self.assertIsNone(self.event_of(run))


# ======================================================================
# Case A — proyeksi lama belum diposting
# ======================================================================


class CorrectionCaseATests(PayrollCorrectionTestCase):

    def test_correction_supersedes_the_unposted_projection(self):
        original, employee = self.finalized_original()

        old_event = self.event_of(original)
        old_journal = self.journal_of(original)
        before = self.snapshot(original)
        payslips_before = self.payslip_snapshot(original)

        result, correction = self.correction_for(original, employee)

        # Identitas terpisah.
        self.assertNotEqual(correction.pk, original.pk)
        self.assertNotEqual(
            result["accounting"]["idempotency_key"],
            idempotency_key(original.pk),
        )
        self.assertEqual(
            result["accounting"]["idempotency_key"],
            idempotency_key(correction.pk),
        )

        new_event = self.event_of(correction)
        new_journal = self.journal_of(correction)

        self.assertNotEqual(new_event.pk, old_event.pk)
        self.assertNotEqual(new_journal.pk, old_journal.pk)
        self.assertEqual(new_journal.status, JournalStatus.DRAFT)
        self.assertEqual(
            new_journal.metadata["replaces_event"], old_event.pk,
        )

        # Yang lama: perannya dicabut, isinya utuh.
        old_event.refresh_from_db()
        old_journal.refresh_from_db()

        self.assertEqual(old_event.status, AccountingEventStatus.SUPERSEDED)
        self.assertEqual(old_event.superseded_by_id, new_event.pk)
        self.assertEqual(old_journal.status, JournalStatus.CANCELLED)
        self.assertEqual(
            old_journal.metadata["superseded_by_event"], new_event.pk,
        )
        after = self.snapshot(original)

        # Isinya utuh: payload, penanda idempotensi, jurnal yang
        # dilahirkannya, seluruh barisnya, dan totalnya.
        self.assertEqual(before[:5], after[:5])

        # Metadata jurnalnya bertambah **tepat satu** kunci: penunjuk ke
        # kejadian penggantinya. Tidak ada kunci yang hilang dan tidak
        # ada yang ditulis ulang — pencabutan peran, bukan penyuntingan.
        self.assertEqual(
            dict(after[5]),
            {**dict(before[5]), "superseded_by_event": new_event.pk},
        )

        # Run asli tidak disentuh, slipnya juga.
        original.refresh_from_db()
        self.assertEqual(original.status, PayrollRunStatus.FINALIZED)
        self.assertEqual(self.payslip_snapshot(original), payslips_before)

        # Nol dampak buku besar.
        self.assertFalse(
            JournalLine.objects
            .filter(journal__in=[old_journal, new_journal], is_posted=True)
            .exists(),
        )
        self.assertEqual(result["accounting"]["journal_status"], "draft")
        self.assertEqual(result["accounting"]["supersession"]["mode"], "superseded")

    def test_correction_payslips_are_separate(self):
        original, employee = self.finalized_original()

        before = self.payslip_snapshot(original)
        _, correction = self.correction_for(original, employee)

        after = self.payslip_snapshot(correction)

        self.assertTrue(before)
        self.assertTrue(after)
        self.assertEqual(self.payslip_snapshot(original), before)
        self.assertFalse({row[0] for row in before} & {row[0] for row in after})
        self.assertFalse({row[1] for row in before} & {row[1] for row in after})

    def test_payload_names_the_corrected_run(self):
        original, employee = self.finalized_original()

        old_payload = self.event_of(original).payload

        _, correction = self.correction_for(original, employee)

        payload = self.event_of(correction).payload

        self.assertEqual(payload["run"]["corrects_run_id"], original.pk)
        self.assertEqual(
            payload["run"]["corrects_document_number"],
            original.document_number,
        )
        self.assertEqual(payload["run"]["run_type"], PayrollRunType.CORRECTION)

        # Digest ikut berbeda — blok `run` memang bagian dari sidiknya.
        self.assertNotEqual(payload["digest"], old_payload["digest"])

        # Payload asli tidak berubah sedikit pun.
        self.assertIsNone(old_payload["run"]["corrects_run_id"])
        self.assertEqual(old_payload["run"]["corrects_document_number"], "")

    def test_superseded_projection_cannot_be_posted_afterwards(self):
        original, employee = self.finalized_original()
        self.correction_for(original, employee)

        old_journal = self.journal_of(original)
        old_journal.refresh_from_db()

        poster = self.user_with(
            "finance.post_journal", "finance.view_journal", name="poster",
        )

        with self.assertRaises(ValidationError):
            FinancePostingService.post(journal=old_journal, user=poster)

        old_journal.refresh_from_db()
        self.assertEqual(old_journal.status, JournalStatus.CANCELLED)

    def test_repeating_the_correction_finalize_is_idempotent(self):
        original, employee = self.finalized_original()

        result, correction = self.correction_for(original, employee)

        gate_result = PayrollAccountingBridge.record(
            run=correction,
            gate=PayrollAccountingGate.evaluate(run=correction),
            replaces_run=original,
        )

        self.assertEqual(
            gate_result["event_id"], result["accounting"]["event_id"],
        )
        self.assertEqual(
            gate_result["journal_id"], result["accounting"]["journal_id"],
        )
        self.assertEqual(
            AccountingEvent.objects.filter(
                idempotency_key=idempotency_key(correction.pk),
            ).count(),
            1,
        )
        self.assertEqual(
            Journal.objects.filter(
                source_module="payroll", source_id=str(correction.pk),
            ).count(),
            1,
        )

    def test_mapping_failure_rolls_the_whole_correction_back(self):
        from apps.finance.models import AccountMapping

        original, employee = self.finalized_original()

        before = self.snapshot(original)

        run = self.approved_run(
            employee, period=original.period, correction_of=original,
        )

        mappings = AccountMapping.objects.filter(
            event_type="PAYROLL_POSTED", company=self.company,
            is_deleted=False,
        )
        touched = list(mappings.values_list("pk", flat=True))
        mappings.update(is_deleted=True)

        try:
            with self.assertRaises(PayrollAccountingError):
                PayrollRunService.finalize(run=run, user=self.corrector())
        finally:
            AccountMapping.objects.filter(pk__in=touched).update(
                is_deleted=False,
            )

        run.refresh_from_db()

        # Koreksinya batal seluruhnya…
        self.assertEqual(run.status, PayrollRunStatus.APPROVED)
        self.assertIsNone(self.event_of(run))
        self.assertIsNone(self.journal_of(run))
        self.assertFalse(Payslip.objects.filter(run=run).exists())

        # …dan yang lama tidak setengah tercabut.
        self.assertEqual(self.snapshot(original), before)
        self.assertEqual(
            self.event_of(original).status, AccountingEventStatus.PROCESSED,
        )
        self.assertEqual(
            self.journal_of(original).status, JournalStatus.DRAFT,
        )


# ======================================================================
# Case B — proyeksi lama sudah diposting
# ======================================================================


class CorrectionCaseBTests(PayrollCorrectionTestCase):

    def posted_original(self):
        original, employee = self.finalized_original()

        poster = self.user_with(
            "finance.post_journal", "finance.view_journal", name="poster",
        )

        FinancePostingService.post(
            journal=self.journal_of(original), user=poster,
        )

        return original, employee

    def test_posted_original_is_untouched_by_the_correction(self):
        original, employee = self.posted_original()

        old_event = self.event_of(original)
        old_journal = self.journal_of(original)
        before = self.snapshot(original)

        result, correction = self.correction_for(original, employee)

        old_event.refresh_from_db()
        old_journal.refresh_from_db()

        self.assertEqual(old_event.status, AccountingEventStatus.PROCESSED)
        self.assertIsNone(old_event.superseded_by_id)
        self.assertEqual(old_journal.status, JournalStatus.POSTED)
        self.assertEqual(before[3], self.snapshot(original)[3])
        self.assertEqual(
            result["accounting"]["supersession"]["mode"], "reversal_required",
        )

        self.assertEqual(
            self.journal_of(correction).status, JournalStatus.DRAFT,
        )

    def test_correction_cannot_post_before_the_original_is_reversed(self):
        original, employee = self.posted_original()

        _, correction = self.correction_for(original, employee)

        poster = self.user_with(
            "finance.post_journal", "finance.view_journal", name="poster2",
        )

        with self.assertRaises(ValidationError) as caught:
            FinancePostingService.post(
                journal=self.journal_of(correction), user=poster,
            )

        self.assertIn(
            "correction_predecessor_not_reversed",
            caught.exception.message_dict,
        )

        self.assertEqual(
            self.journal_of(correction).status, JournalStatus.DRAFT,
        )

    def test_payroll_actor_cannot_reverse_the_posted_journal(self):
        original, employee = self.posted_original()
        self.correction_for(original, employee)

        with self.assertRaises(PermissionDenied):
            FinanceReversalService.reverse(
                journal=self.journal_of(original),
                user=self.corrector(),
                reason="mau dikoreksi",
            )

        self.assertEqual(
            self.journal_of(original).status, JournalStatus.POSTED,
        )

    def test_finance_reversal_unblocks_the_correction(self):
        original, employee = self.posted_original()
        _, correction = self.correction_for(original, employee)

        reverser = self.user_with(
            "finance.reverse_journal", "finance.view_journal",
            name="reverser",
        )

        original_journal = self.journal_of(original)

        reversal = FinanceReversalService.reverse(
            journal=original_journal, user=reverser,
            reason="digantikan run koreksi",
        )

        original_journal.refresh_from_db()

        # Tiga jurnal yang berbeda: asli, pembalik, pengganti.
        self.assertEqual(original_journal.status, JournalStatus.REVERSED)
        self.assertEqual(reversal.reversal_of_id, original_journal.pk)
        self.assertNotIn(
            reversal.pk,
            {original_journal.pk, self.journal_of(correction).pk},
        )
        self.assertEqual(reversal.total_debit, original_journal.total_credit)

        poster = self.user_with(
            "finance.post_journal", "finance.view_journal", name="poster3",
        )

        result = FinancePostingService.post(
            journal=self.journal_of(correction), user=poster,
        )

        self.assertEqual(result.journal.status, JournalStatus.POSTED)


# ======================================================================
# Case C — run lama/historis
# ======================================================================


class CorrectionHistoricalTests(PayrollCorrectionTestCase):

    def test_run_without_a_projection_cannot_be_corrected(self):
        """Run yang difinalisasi sebelum PF-0F: tidak ada yang diganti."""
        run = self.approved_run()

        PayrollRun.objects.filter(pk=run.pk).update(
            status=PayrollRunStatus.FINALIZED,
        )
        run.refresh_from_db()

        self.assertIsNone(self.event_of(run))

        with self.assertRaises(PayrollAccountingError) as caught:
            PayrollRunService.create(
                data={
                    "period": run.period,
                    "run_type": PayrollRunType.CORRECTION,
                    "corrects_run": run,
                },
                user=self.corrector(),
            )

        self.assertEqual(
            caught.exception.error_code, "correction_target_without_event",
        )
        self.assertFalse(
            PayrollRun.objects.filter(corrects_run=run).exists(),
        )

    def test_a_superseded_run_cannot_be_corrected_again(self):
        original, employee = self.finalized_original()
        _, correction = self.correction_for(original, employee)

        # `original` sudah digantikan `correction`; yang boleh dikoreksi
        # berikutnya adalah ujung rantainya, bukan pangkalnya.
        self.assertEqual(correction.corrects_run_id, original.pk)

        with self.assertRaises(PayrollAccountingError) as caught:
            PayrollRunService.assert_correctable(
                PayrollRun.objects.get(pk=original.pk),
            )

        self.assertEqual(
            caught.exception.error_code, "correction_target_superseded",
        )


# ======================================================================
# Regresi: run biasa tidak berubah
# ======================================================================


class OrdinaryRunRegressionTests(PayrollCorrectionTestCase):

    def test_regular_finalize_is_unchanged(self):
        run = self.approved_run()

        result = PayrollRunService.finalize(run=run, user=self.corrector())

        run.refresh_from_db()

        self.assertEqual(run.status, PayrollRunStatus.FINALIZED)
        self.assertIsNone(run.corrects_run_id)
        self.assertNotIn("supersession", result["accounting"])
        self.assertIsNone(result["accounting"]["replaces_event_id"])
        self.assertEqual(result["accounting"]["journal_status"], "draft")

        journal = self.journal_of(run)

        self.assertNotIn("replaces_event", journal.metadata)
        self.assertFalse(journal.lines.filter(is_posted=True).exists())

    def test_locked_period_still_refuses_an_ordinary_run(self):
        original, _ = self.finalized_original()

        period = original.period
        period.refresh_from_db()

        from apps.payroll.models import PayrollPeriodStatus

        type(period).objects.filter(pk=period.pk).update(
            status=PayrollPeriodStatus.FINALIZED,
        )
        period.refresh_from_db()

        self.assertTrue(period.is_locked)

        with self.assertRaises(ValidationError) as caught:
            PayrollRunService.create(
                data={"period": period, "run_type": PayrollRunType.REGULAR},
                user=self.corrector(),
            )

        self.assertIn("period", caught.exception.message_dict)

        # Tapi koreksinya boleh — itu seluruh gunanya pengecualian.
        correction = PayrollRunService.create(
            data={
                "period": period,
                "run_type": PayrollRunType.CORRECTION,
                "corrects_run": original,
            },
            user=self.corrector(),
        )

        self.assertEqual(correction.corrects_run_id, original.pk)

    def test_duplicate_finalized_still_fires_for_a_run_outside_the_chain(self):
        """
        Pengecualian duplikat hanya untuk rantai koreksi itu sendiri.

        Run lain di periode yang sama yang memuat pegawai yang sudah
        difinalisasi tetap ditolak — itu pembayaran kedua, bukan
        pengganti.
        """
        original, employee = self.finalized_original()

        rival = PayrollRun.objects.create(
            period=original.period,
            company=self.company,
            run_type=PayrollRunType.OFF_CYCLE,
            document_number=f"PAY-RIVAL-{original.pk}",
        )

        PayrollRunEmployee.objects.create(
            run=rival,
            employee=employee,
            basic_salary=Decimal("1000000"),
            status="calculated",
        )

        summary = PayrollRunService.validate(run=rival)

        self.assertIn(
            "duplicate_finalized",
            {item["code"] for item in summary["errors"]},
        )

    def test_a_correction_may_repeat_the_employees_it_replaces(self):
        original, employee = self.finalized_original()

        correction = self.approved_run(
            employee, period=original.period, correction_of=original,
        )

        summary = PayrollRunService.validate(run=correction)

        self.assertNotIn(
            "duplicate_finalized",
            {item["code"] for item in summary["errors"]},
        )

    def test_correction_type_without_a_target_cannot_enter_a_locked_period(self):
        original, _ = self.finalized_original()

        from apps.payroll.models import PayrollPeriodStatus

        period = original.period
        type(period).objects.filter(pk=period.pk).update(
            status=PayrollPeriodStatus.FINALIZED,
        )
        period.refresh_from_db()

        with self.assertRaises(ValidationError):
            PayrollRunService.create(
                data={
                    "period": period,
                    "run_type": PayrollRunType.CORRECTION,
                },
                user=self.corrector(),
            )
