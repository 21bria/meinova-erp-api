"""
PF-0F — jembatan akuntansi Finalize: payload PF-0C → `PAYROLL_POSTED` →
jurnal DRAFT, di atas tenant sungguhan.

Yang dijanjikan tahap ini, dan yang diuji di sini:

1. Finalize yang berhasil menerbitkan **tepat satu** kejadian dan **tepat
   satu** jurnal — seimbang, DRAFT, tidak diposting, tanpa satu pun
   dampak buku besar — karena kebijakan gaji bawaan `auto_post=False`.
2. Payload yang dikirim **persis** milik gerbang PF-0D; tidak dibangun
   ulang.
3. Penanda idempotensinya struktural dan dibekukan; penanda sama dengan
   isi berbeda gagal tertutup.
4. **Gagal = batal seluruhnya.** Pemetaan hilang/ambigu, kebijakan tidak
   ada, akun tidak aktif, periode tertutup, maupun galat tak terduga —
   semuanya membatalkan Finalize, dan tidak meninggalkan kejadian atau
   jurnal yatim.
5. Yang memfinalisasi adalah **aktor sumber**, bukan pemegang wewenang
   Finance.

Satu kelas, dan itu disengaja — `TenantTestCase` membangun schema sekali
per kelas. Tiap test hanya memasukkan pegawainya sendiri ke run-nya
(baris lain dikeluarkan), supaya angkanya pasti dan tidak bergantung
urutan eksekusi.
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from apps.accounts.models import AuthorityMode, Role
from apps.accounts.services.role_assignment import grant_role
from apps.administration.models import (
    Branch,
    Company,
    CostCenter,
    Department,
    Division,
    Section,
)
from apps.finance.models import (
    Account,
    AccountMapping,
    AccountingEvent,
    AccountingEventStatus,
    AccountingPeriod,
    AccountingPolicy,
    Journal,
    JournalLine,
    JournalStatus,
    PeriodStatus,
)
from apps.finance.seeds.policies import mapping_code, policy_code
from apps.finance.services import AccountMappingService
from apps.hr.models import OrganizationAssignment
from apps.payroll.models import (
    PayrollInputStatus,
    PayrollInputType,
    PayrollRun,
    PayrollRunEmployee,
    PayrollRunStatus,
    Payslip,
)
from apps.payroll.services import PayrollInputService, PayrollRunService
from apps.payroll.services.accounting import (
    PayrollAccountingError,
    PayrollAccountingService,
)
from apps.payroll.services.accounting_bridge import (
    PayrollAccountingBridge,
    idempotency_key,
)
from apps.payroll.services.accounting_gate import PayrollAccountingGate

from .test_payroll_flow import PayrollFlowTestCase


User = get_user_model()


class PayrollAccountingBridgeTest(PayrollFlowTestCase):

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    def approved_run(self, *employees, period=None):
        """
        Run yang disetujui, berisi **hanya** pegawai yang dioper.

        Pegawai milik test lain ikut tertarik oleh `generate_employees`
        (tidak ada rollback antar test), jadi baris mereka dikeluarkan —
        jalan keluar bisnis yang sama dengan pegawai yang belum siap.
        """
        period = period or self.make_period()
        employees = employees or (self.make_employee(),)

        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        PayrollRunEmployee.objects.filter(run=run).exclude(
            employee__in=employees,
        ).update(
            is_excluded=True,
            status="excluded",
            exclusion_reason="Milik test lain (fixture).",
        )

        PayrollRunService._refresh_totals(run=run)
        PayrollRunService.validate(run=run)
        PayrollRunService.acknowledge(run=run)

        PayrollRun.objects.filter(pk=run.pk).update(
            status=PayrollRunStatus.APPROVED,
        )

        return PayrollRun.objects.get(pk=run.pk)

    def events(self, run):
        return AccountingEvent.objects.filter(
            idempotency_key=idempotency_key(run.pk),
        )

    def journals(self, run):
        return Journal.objects.filter(
            source_module="payroll",
            source_type="payroll_run",
            source_id=str(run.pk),
        )

    def finance_rows(self, run) -> tuple[int, int]:
        return self.events(run).count(), self.journals(run).count()

    def assert_rolled_back(self, run, *, code=None, error=PayrollAccountingError):
        """Run tetap APPROVED, tanpa slip, tanpa kejadian, tanpa jurnal."""
        with self.assertRaises(error) as caught:
            PayrollRunService.finalize(run=run)

        if code is not None:
            self.assertEqual(caught.exception.error_code, code)

        run.refresh_from_db()

        self.assertEqual(run.status, PayrollRunStatus.APPROVED)
        self.assertIsNone(run.finalized_at)
        self.assertFalse(Payslip.objects.filter(run=run).exists())
        self.assertFalse(
            PayrollRunEmployee.objects
            .filter(run=run, status="finalized")
            .exists(),
        )
        self.assertEqual(self.finance_rows(run), (0, 0))

        return caught.exception

    @classmethod
    def make_operator(cls, name="operator", *, codenames=("view_payrollrun", "change_payrollrun")):
        """Akun yang boleh memfinalisasi payroll — dan tidak lebih."""
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

        role.permissions.add(
            *Permission.objects.filter(
                content_type__app_label="payroll",
                codename__in=list(codenames),
            )
        )

        grant_role(user, role, mode=AuthorityMode.UNRESTRICTED)

        return User.objects.get(pk=user.pk)

    # ------------------------------------------------------------------
    # 1–7 Finalize yang berhasil
    # ------------------------------------------------------------------

    def test_finalize_records_one_event_and_one_draft_journal(self):
        run = self.approved_run()

        result = PayrollRunService.finalize(run=run)

        run.refresh_from_db()
        self.assertEqual(run.status, PayrollRunStatus.FINALIZED)

        # 1, 2
        self.assertEqual(self.finance_rows(run), (1, 1))

        event = self.events(run).get()
        journal = self.journals(run).get()

        self.assertEqual(event.event_type, "PAYROLL_POSTED")
        self.assertEqual(event.source_module, "payroll")
        self.assertEqual(event.source_type, "payroll_run")
        self.assertEqual(event.source_id, str(run.pk))
        self.assertEqual(event.company_id, run.company_id)
        self.assertEqual(event.event_date, run.period.end_date)
        self.assertEqual(event.status, AccountingEventStatus.PROCESSED)
        self.assertEqual(event.generated_journal_id, journal.pk)

        # 3
        self.assertEqual(journal.base_total_debit, journal.base_total_credit)
        self.assertGreater(journal.base_total_debit, Decimal("0.00"))

        # 4, 5
        self.assertEqual(journal.status, JournalStatus.DRAFT)
        self.assertFalse(journal.is_posted)
        self.assertIsNone(journal.posted_at)
        self.assertIsNone(journal.posted_by_id)

        # Provenans: jurnal sistem, bukan jurnal manual.
        self.assertEqual(journal.journal_type, "automatic")
        self.assertEqual(journal.company_id, run.company_id)
        self.assertEqual(journal.posting_date, run.period.end_date)
        self.assertEqual(journal.metadata["accounting_event"], event.pk)
        self.assertEqual(
            journal.metadata["idempotency_key"], idempotency_key(run.pk),
        )
        self.assertEqual(journal.metadata["policy"], policy_code(self.company))
        self.assertTrue(journal.accounting_period.contains(run.period.end_date))

        # Ringkasan yang dikembalikan Finalize ke pemanggilnya.
        self.assertEqual(result["accounting"]["event_id"], event.pk)
        self.assertEqual(result["accounting"]["journal_id"], journal.pk)
        self.assertEqual(result["accounting"]["journal_status"], "draft")

    def test_finalize_leaves_no_ledger_trace(self):
        """
        6 — tidak ada posting. Bukti terkuatnya bukan status kepala
        dokumen: `FinancePostingService.post` sama sekali tidak dipanggil,
        dan tidak satu baris pun membawa stempel yang dibaca buku besar.
        """
        from apps.finance.services import FinancePostingService

        run = self.approved_run()

        with mock.patch.object(
            FinancePostingService,
            "post",
            wraps=FinancePostingService.post,
        ) as posted:
            PayrollRunService.finalize(run=run)

        posted.assert_not_called()

        journal = self.journals(run).get()

        self.assertFalse(
            JournalLine.objects.filter(journal=journal, is_posted=True).exists(),
        )
        self.assertEqual(
            set(
                journal.lines.values_list(
                    "is_posted", "posting_date", "accounting_period_id",
                )
            ),
            {(False, None, None)},
        )

    def test_policy_auto_post_false_is_what_keeps_it_draft(self):
        """
        7 — kebijakannya yang memutuskan, bukan jembatannya.

        Jembatan tidak mengirim `post=False`. Kalau Finance Administrator
        menyalakan `auto_post` pada kebijakan gaji, Finalize **akan**
        memosting — dan itulah bukti bahwa tidak ada keputusan posting
        yang disembunyikan di sisi payroll. Kebijakan bawaannya mati.
        """
        policy = AccountingPolicy.objects.get(
            code=policy_code(self.company), is_deleted=False,
        )

        self.assertFalse(policy.auto_post)

        run = self.approved_run()

        AccountingPolicy.objects.filter(pk=policy.pk).update(auto_post=True)

        try:
            PayrollRunService.finalize(run=run)
        finally:
            AccountingPolicy.objects.filter(pk=policy.pk).update(
                auto_post=False,
            )

        self.assertEqual(self.journals(run).get().status, JournalStatus.POSTED)

    # ------------------------------------------------------------------
    # 8–12 Payload & idempotensi
    # ------------------------------------------------------------------

    def test_exact_gate_payload_is_sent_and_not_rebuilt(self):
        run = self.approved_run()

        captured = {}
        original = PayrollAccountingBridge.record.__func__

        def spy(cls, *, run, gate, user=None, **extra):
            # `**extra` menampung argumen jembatan yang tidak dipedulikan
            # test ini (PF-0G menambah `replaces_run`) — yang diuji di
            # sini cuma payload-nya, dan mata-matanya harus meneruskan
            # apa pun yang dioper Finalize apa adanya.
            captured["gate"] = gate

            return original(cls, run=run, gate=gate, user=user, **extra)

        with mock.patch.object(
            PayrollAccountingService,
            "build_payload",
            wraps=PayrollAccountingService.build_payload,
        ) as built, mock.patch.object(
            PayrollAccountingBridge, "record", classmethod(spy),
        ):
            PayrollRunService.finalize(run=run)

        # Dibangun **sekali**, oleh gerbang. Jembatan tidak membangun
        # ulang, dan Finance tidak membangun apa pun.
        self.assertEqual(built.call_count, 1)

        event = self.events(run).get()
        gate = captured["gate"]

        self.assertEqual(event.payload, gate.payload)
        self.assertEqual(event.payload["digest"], gate.digest)
        self.assertEqual(event.payload["schema"], "payroll.posting/v1")

    def test_idempotency_key_is_structural_and_frozen(self):
        run = self.approved_run()

        PayrollRunService.finalize(run=run)

        self.assertEqual(
            idempotency_key(run.pk), f"payroll:payroll_run:{run.pk}:posted",
        )
        self.assertEqual(
            self.events(run).get().idempotency_key,
            f"payroll:payroll_run:{run.pk}:posted",
        )

    def test_repeated_bridge_call_creates_no_duplicate(self):
        """10, 11 — pemanggilan ulang mengembalikan kejadian yang sama."""
        run = self.approved_run()

        first = PayrollRunService.finalize(run=run)["accounting"]

        run.refresh_from_db()
        gate = PayrollAccountingGate.evaluate(run=run)

        second = PayrollAccountingBridge.record(run=run, gate=gate)

        self.assertEqual(second["event_id"], first["event_id"])
        self.assertEqual(second["journal_id"], first["journal_id"])
        self.assertEqual(self.finance_rows(run), (1, 1))

    def test_payload_digest_is_deterministic_after_finalize(self):
        """Gerbang yang dibaca ulang atas run terkunci memberi digest yang sama."""
        run = self.approved_run()

        PayrollRunService.finalize(run=run)
        run.refresh_from_db()

        again = PayrollAccountingGate.evaluate(run=run)

        self.assertEqual(again.digest, self.events(run).get().payload["digest"])

    def test_same_key_with_different_digest_fails_closed(self):
        """
        12 — penanda sama, isi berbeda: ditolak. Tidak ditimpa, tidak
        dicatat kedua kalinya, dan jurnal yang sudah ada tidak disentuh.
        """
        run = self.approved_run()

        PayrollRunService.finalize(run=run)
        run.refresh_from_db()

        event = self.events(run).get()
        original_payload = event.payload

        gate = PayrollAccountingGate.evaluate(run=run)

        tampered = mock.Mock(
            payload={**gate.payload, "digest": "f" * 64},
            digest="f" * 64,
        )

        with self.assertRaises(PayrollAccountingError) as caught:
            PayrollAccountingBridge.record(run=run, gate=tampered)

        self.assertEqual(
            caught.exception.error_code, "accounting_event_conflict",
        )

        event.refresh_from_db()

        self.assertEqual(event.payload, original_payload)
        self.assertEqual(self.finance_rows(run), (1, 1))

    # ------------------------------------------------------------------
    # 13–18 Gagal = batal seluruhnya
    # ------------------------------------------------------------------

    def test_missing_mapping_rolls_back_finalize(self):
        run = self.approved_run()

        mapping = AccountMapping.objects.get(
            code=mapping_code(self.company, "SALARY_EXPENSE"),
            is_deleted=False,
        )

        AccountMapping.objects.filter(pk=mapping.pk).update(is_active=False)

        try:
            error = self.assert_rolled_back(
                run, code="accounting_journal_failed",
            )
        finally:
            AccountMapping.objects.filter(pk=mapping.pk).update(is_active=True)

        self.assertIn("SALARY_EXPENSE", str(error))

    def test_ambiguous_mapping_rolls_back_finalize(self):
        run = self.approved_run()

        account = Account.objects.get(
            company=self.company, code="6110", is_deleted=False,
        )

        rivals = [
            AccountMappingService.create(data={
                "code": f"BRIDGE-DUP-{run.pk}-{index}",
                "name": f"Rival {index}",
                "mapping_key": "SALARY_EXPENSE",
                "company": self.company,
                "event_type": "PAYROLL_POSTED",
                "selectors": selectors,
                "account": account,
            })
            for index, selectors in enumerate(
                ({"semantic": "BASIC_SALARY"}, {"program": ""}), start=1,
            )
        ]

        try:
            error = self.assert_rolled_back(
                run, code="accounting_journal_failed",
            )
        finally:
            AccountMapping.objects.filter(
                pk__in=[row.pk for row in rivals],
            ).update(is_deleted=True, is_active=False)

        self.assertIn("ambigu", str(error))

    def test_missing_policy_rolls_back_finalize(self):
        """15 — pemrosesan kejadian gagal: tidak ada kebijakan aktif."""
        run = self.approved_run()

        policy = AccountingPolicy.objects.get(
            code=policy_code(self.company), is_deleted=False,
        )

        AccountingPolicy.objects.filter(pk=policy.pk).update(is_active=False)

        try:
            self.assert_rolled_back(run, code="accounting_policy_missing")
        finally:
            AccountingPolicy.objects.filter(pk=policy.pk).update(is_active=True)

    def test_unexpected_processing_error_rolls_back_finalize(self):
        """
        15 — galat yang **bukan** ValidationError juga membatalkan semuanya.

        `process()` hanya menangkap ValidationError; galat lain naik apa
        adanya melewati jembatan, dan transaksi Finalize membatalkan
        kejadian yang sempat tercatat.
        """
        from apps.finance.services.policy import AccountingPolicyService

        run = self.approved_run()

        with mock.patch.object(
            AccountingPolicyService,
            "build_lines",
            side_effect=RuntimeError("simulated engine failure"),
        ):
            self.assert_rolled_back(run, error=RuntimeError)

    def test_inactive_account_rolls_back_finalize(self):
        """16 — penerbitan jurnal gagal: pemetaan menunjuk akun nonaktif."""
        run = self.approved_run()

        mapping = AccountMapping.objects.get(
            code=mapping_code(self.company, "PAYROLL_PAYABLE"),
            is_deleted=False,
        )

        Account.objects.filter(pk=mapping.account_id).update(is_active=False)

        try:
            self.assert_rolled_back(run, code="accounting_journal_failed")
        finally:
            Account.objects.filter(pk=mapping.account_id).update(is_active=True)

    def test_mapping_to_another_companys_account_rolls_back_finalize(self):
        """
        16 — pemetaan **global** yang menunjuk akun perusahaan lain.

        `AccountMapping.clean()` hanya memeriksa pemetaan bercompany;
        pemetaan global bisa menunjuk akun siapa pun. Yang menolaknya
        `JournalLine.full_clean()` saat draf disusun — jadi Finalize batal,
        bukan menerbitkan draf yang baru ketahuan salah saat diposting.
        """
        run = self.approved_run()

        other = Company.objects.create(
            code=f"XCO{run.pk}", name="Foreign Company",
        )

        from apps.finance.services import AccountService

        foreign = AccountService.create(data={
            "company": other,
            "code": "9999",
            "name": "Foreign Expense",
            "account_type": "expense",
            "posting_allowed": True,
        })

        mapping = AccountMapping.objects.get(
            code=mapping_code(self.company, "SALARY_EXPENSE"),
            is_deleted=False,
        )

        AccountMapping.objects.filter(pk=mapping.pk).update(is_active=False)

        global_row = AccountMappingService.create(data={
            "code": f"GLOBAL-SAL-{run.pk}",
            "name": "Global salary",
            "mapping_key": "SALARY_EXPENSE",
            "company": None,
            "event_type": "PAYROLL_POSTED",
            "selectors": {},
            "account": foreign,
        })

        try:
            error = self.assert_rolled_back(
                run, code="accounting_journal_failed",
            )
        finally:
            AccountMapping.objects.filter(pk=global_row.pk).update(
                is_deleted=True, is_active=False,
            )
            AccountMapping.objects.filter(pk=mapping.pk).update(is_active=True)

        self.assertIn("perusahaan lain", str(error))

    def test_closed_finance_period_rolls_back_finalize(self):
        run = self.approved_run()

        period = AccountingPeriod.objects.get(
            fiscal_year__company=self.company,
            start_date__lte=run.period.end_date,
            end_date__gte=run.period.end_date,
            is_deleted=False,
        )

        AccountingPeriod.objects.filter(pk=period.pk).update(
            status=PeriodStatus.CLOSED,
        )

        try:
            self.assert_rolled_back(run, code="accounting_journal_failed")
        finally:
            AccountingPeriod.objects.filter(pk=period.pk).update(
                status=PeriodStatus.OPEN,
            )

    # ------------------------------------------------------------------
    # 19–22 Isi jurnal
    # ------------------------------------------------------------------

    def test_six_dimensions_reach_the_journal_lines(self):
        """
        19 — dimensi organisasi pegawai sampai ke baris jurnal, dan dua
        departemen menghasilkan baris yang terpisah, bukan dijumlahkan.
        """
        branch = Branch.objects.create(
            company=self.company, code=f"BR{self._counter}", name="Branch",
        )
        division = Division.objects.create(
            company=self.company, code=f"DV{self._counter}", name="Division",
        )
        department = Department.objects.create(
            company=self.company, code=f"DP{self._counter}", name="Mining",
        )
        section = Section.objects.create(
            company=self.company, department=department,
            code=f"SC{self._counter}", name="Pit",
        )
        cost_center = CostCenter.objects.create(
            company=self.company, code=f"CC{self._counter}", name="Pit CC",
        )

        placed = self.make_employee(basic_salary="8000000")
        plain = self.make_employee(basic_salary="6000000")

        OrganizationAssignment.objects.filter(employee=placed).update(
            branch=branch,
            division=division,
            department=department,
            section=section,
            cost_center=cost_center,
        )

        run = self.approved_run(placed, plain)

        PayrollRunService.finalize(run=run)

        journal = self.journals(run).get()

        expected = {
            "branch_id": branch.pk,
            "location_id": self.location.pk,
            "division_id": division.pk,
            "department_id": department.pk,
            "section_id": section.pk,
            "cost_center_id": cost_center.pk,
        }

        placed_lines = journal.lines.filter(cost_center=cost_center)

        self.assertTrue(placed_lines.exists())

        for line in placed_lines:
            for field, value in expected.items():
                self.assertEqual(getattr(line, field), value, field)

            # Company tetap milik kepala dokumen.
            self.assertEqual(line.company_id, self.company.pk)

        plain_lines = journal.lines.filter(cost_center__isnull=True)

        self.assertTrue(plain_lines.exists())

        for line in plain_lines:
            self.assertEqual(line.department_id, self.department.pk)
            self.assertIsNone(line.branch_id)

        self.assertEqual(journal.base_total_debit, journal.base_total_credit)

    def test_negative_bucket_reaches_the_opposite_side(self):
        """
        20 — koreksi negatif dari Payroll Input, ujung ke ujung.

        PF-0C mempertahankan tandanya (`OTHER_EARNING/ADJUSTMENT` bernilai
        negatif); Finance membukukannya sebagai **kredit** di akun beban
        penghasilan lain, dan jurnalnya tetap seimbang.
        """
        employee = self.make_employee(basic_salary="10000000")
        period = self.make_period()

        PayrollInputService.create(
            data={
                "period": period,
                "employee": employee,
                "input_type": PayrollInputType.ADJUSTMENT,
                "code": "KOREKSI",
                "name": "Koreksi kelebihan bayar",
                "amount": Decimal("-150000"),
                "status": PayrollInputStatus.CONFIRMED,
            },
        )

        run = self.approved_run(employee, period=period)

        gate = PayrollAccountingGate.evaluate(run=run)

        other = [
            row for row in gate.payload["components"]
            if row["semantic"] == "OTHER_EARNING"
        ]

        self.assertEqual(len(other), 1)
        self.assertEqual(Decimal(other[0]["amount"]), Decimal("-150000.00"))

        PayrollRunService.finalize(run=run)

        journal = self.journals(run).get()

        other_earning = mapping_code(self.company, "OTHER_EARNING_EXPENSE")
        account_id = AccountMapping.objects.get(
            code=other_earning, is_deleted=False,
        ).account_id

        lines = list(journal.lines.filter(account_id=account_id))

        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0].debit, Decimal("0.00"))
        self.assertEqual(lines[0].credit, Decimal("150000.00"))

        self.assertEqual(journal.base_total_debit, journal.base_total_credit)

        for line in journal.lines.all():
            self.assertGreaterEqual(line.debit, Decimal("0.00"))
            self.assertGreaterEqual(line.credit, Decimal("0.00"))

    def test_no_employee_pii_reaches_finance(self):
        """
        21 — tidak ada identitas pegawai, dan tidak ada teks bebas nama
        komponen, di kejadian maupun jurnalnya.
        """
        employee = self.make_employee(basic_salary="9000000")

        # Nama yang khas. `make_employee()` menamai semua pegawai
        # "Payroll …", dan kata itu memang muncul — sah — di keterangan
        # jurnal ("Payroll basic salary"). Tanpa nama khas, test ini
        # menangkap kebetulan, bukan kebocoran.
        from apps.hr.models import Employee

        Employee.objects.filter(pk=employee.pk).update(
            first_name="Zelindra", last_name="Quistorpova",
        )
        employee.refresh_from_db()

        period = self.make_period()

        PayrollInputService.create(
            data={
                "period": period,
                "employee": employee,
                "input_type": PayrollInputType.INCENTIVE,
                "code": "BONUS-RAHASIA",
                "name": "Bonus Rahasia Direksi",
                "amount": Decimal("1234567"),
                "status": PayrollInputStatus.CONFIRMED,
            },
        )

        run = self.approved_run(employee, period=period)

        PayrollRunService.finalize(run=run)

        event = self.events(run).get()
        journal = self.journals(run).get()

        haystack = " | ".join([
            json.dumps(event.payload),
            event.source_reference,
            journal.description,
            json.dumps(journal.metadata),
            *journal.lines.values_list("description", flat=True),
            *journal.lines.values_list("source_reference", flat=True),
        ])

        forbidden = [
            employee.employee_number,
            employee.first_name,
            employee.last_name,
            "Bonus Rahasia Direksi",
            "BONUS-RAHASIA",
            "Tunjangan Transport",
            "BPJS Kesehatan",
        ]

        for needle in forbidden:
            self.assertNotIn(needle, haystack, needle)

        # Jumlah per pegawai hanya muncul lewat bucket agregat, bukan
        # sebagai baris milik seseorang.
        self.assertNotIn("employee", json.dumps(event.payload))

    def test_company_isolation(self):
        """
        22 — perusahaan lain dengan kebijakan dan pemetaannya sendiri tidak
        pernah menyumbang akun ke jurnal run ini.

        Isolasi **tenant** ditegakkan schema: tabel kejadian dan jurnal
        milik tiap tenant terpisah, jadi penanda yang sama di tenant lain
        tidak pernah bertemu. Satu `TenantTestCase` tidak bisa membuka dua
        schema sekaligus; yang diuji di sini batas company-nya.
        """
        from apps.finance.seeds import (
            seed_chart_of_accounts,
            seed_payroll_policy,
        )

        run = self.approved_run()

        rival = Company.objects.create(
            code=f"RIV{run.pk}", name="Rival Company",
        )
        self.ensure_finance_calendar(run.period.end_date, company=rival)
        seed_chart_of_accounts(company=rival)
        seed_payroll_policy(company=rival)

        PayrollRunService.finalize(run=run)

        event = self.events(run).get()
        journal = self.journals(run).get()

        self.assertEqual(event.company_id, self.company.pk)
        self.assertEqual(event.applied_policy.code, policy_code(self.company))
        self.assertEqual(journal.company_id, self.company.pk)
        self.assertEqual(
            set(journal.lines.values_list("account__company_id", flat=True)),
            {self.company.pk},
        )
        self.assertEqual(
            set(journal.lines.values_list("company_id", flat=True)),
            {self.company.pk},
        )

    # ------------------------------------------------------------------
    # 23–24 Aktor & wewenang
    # ------------------------------------------------------------------

    def test_finalizer_is_the_source_actor(self):
        """23 — nama yang memfinalisasi tercatat pada kejadian dan draf."""
        run = self.approved_run()
        operator = self.make_operator()

        PayrollRunService.finalize(run=run, user=operator)

        event = self.events(run).get()
        journal = self.journals(run).get()

        self.assertEqual(event.created_by_id, operator.pk)
        self.assertEqual(journal.created_by_id, operator.pk)

        # Aktor sumber, bukan aktor Finance: tidak ada yang mengajukan,
        # menyetujui, atau memposting atas namanya.
        self.assertIsNone(journal.submitted_by_id)
        self.assertIsNone(journal.approved_by_id)
        self.assertIsNone(journal.posted_by_id)

    def test_finalizer_gains_no_finance_authority(self):
        """
        24 — Finalize tidak memberi, meminjam, atau menuntut izin Finance.

        Operator ini hanya memegang izin payroll. Ia bisa memfinalisasi
        (jembatan tidak menuntut izin jurnal manual), dan sesudahnya
        izinnya persis sama — tidak ada role, izin, atau penugasan baru.
        """
        run = self.approved_run()
        operator = self.make_operator("payonly")

        finance_codes = (
            "finance.add_journal",
            "finance.change_journal",
            "finance.delete_journal",
            "finance.change_accountingevent",
            "finance.post_soft_closed_period",
            "finance.reopen_locked_period",
            # FIN-B1/B2.
            "finance.post_journal",
            "finance.reverse_journal",
        )

        before = set(operator.get_all_permissions())

        for code in finance_codes:
            self.assertFalse(operator.has_perm(code), code)

        PayrollRunService.finalize(run=run, user=operator)

        operator = User.objects.get(pk=operator.pk)

        self.assertEqual(set(operator.get_all_permissions()), before)

        for code in finance_codes:
            self.assertFalse(operator.has_perm(code), code)

        self.assertEqual(self.journals(run).get().status, JournalStatus.DRAFT)

    def test_soft_closed_period_is_not_bypassed_by_the_finalizer(self):
        """
        Periode `SOFT_CLOSED` hanya menerima dokumen dari pemegang
        `finance.post_soft_closed_period`. Jembatan meneruskan aktor
        sebenarnya — bukan `user=None`, yang di Finance berarti pemanggil
        internal dan melewati pemeriksaan ini — jadi operator payroll
        tertolak dan Finalize batal.
        """
        run = self.approved_run()
        operator = self.make_operator("softclose")

        period = AccountingPeriod.objects.get(
            fiscal_year__company=self.company,
            start_date__lte=run.period.end_date,
            end_date__gte=run.period.end_date,
            is_deleted=False,
        )

        AccountingPeriod.objects.filter(pk=period.pk).update(
            status=PeriodStatus.SOFT_CLOSED,
        )

        try:
            with self.assertRaises(PayrollAccountingError) as caught:
                PayrollRunService.finalize(run=run, user=operator)
        finally:
            AccountingPeriod.objects.filter(pk=period.pk).update(
                status=PeriodStatus.OPEN,
            )

        self.assertEqual(
            caught.exception.error_code, "accounting_journal_failed",
        )
        self.assertIn("soft closed", str(caught.exception))

        run.refresh_from_db()
        self.assertEqual(run.status, PayrollRunStatus.APPROVED)
        self.assertEqual(self.finance_rows(run), (0, 0))

    # ------------------------------------------------------------------
    # FIN-B1/B2 — jurnal gaji tidak memberi wewenang kepada pembuatnya
    # ------------------------------------------------------------------

    def journal_state(self, journal):
        journal.refresh_from_db()

        return (
            journal.status,
            journal.submitted_by_id,
            journal.approved_by_id,
            journal.posted_by_id,
            journal.cancelled_by_id,
            journal.lines.filter(is_posted=True).count(),
        )

    def test_finalizer_cannot_act_on_the_generated_journal(self):
        """
        FIN-B1/B2 — `created_by` adalah jejak asal, **bukan** wewenang.

        Operator ini memfinalisasi payroll dengan cakupan se-tenant. Ia
        tetap tidak bisa mengajukan, membatalkan, atau memposting draf
        yang lahir dari Finalize-nya — lewat service maupun API — dan
        tidak satu kolom pun berubah.
        """
        from rest_framework.exceptions import PermissionDenied
        from rest_framework.test import APIClient

        from apps.finance.services import FinancePostingService, JournalService

        run = self.approved_run()
        operator = self.make_operator("finalizer")

        PayrollRunService.finalize(run=run, user=operator)

        journal = self.journals(run).get()
        before = self.journal_state(journal)

        self.assertEqual(before, (JournalStatus.DRAFT, None, None, None, None, 0))
        self.assertEqual(journal.created_by_id, operator.pk)

        for attempt in (
            lambda: FinancePostingService.post(journal=journal, user=operator),
            lambda: JournalService.submit(journal=journal, user=operator),
            lambda: JournalService.cancel(journal=journal, user=operator),
        ):
            with self.assertRaises(PermissionDenied):
                attempt()

            self.assertEqual(self.journal_state(journal), before)

        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)
        client.force_authenticate(user=operator)

        for verb in ("post", "submit", "cancel", "withdraw", "reverse"):
            response = client.post(
                f"/api/finance/journals/{journal.pk}/{verb}/",
                {"reason": "x"},
                format="json",
            )

            self.assertIn(response.status_code, {403, 404}, verb)
            self.assertEqual(self.journal_state(journal), before, verb)

    def finance_poster(self):
        type(self)._counter += 1
        name = f"poster-{self._counter}-{self.company.pk}"

        user = User.objects.create_user(
            username=name, email=f"{name}@uji.local", password="Uji#12345",
        )

        role = Role.objects.create(
            code=f"POSTER-{user.pk}", name=f"Poster {user.pk}",
        )
        role.permissions.add(*Permission.objects.filter(
            content_type__app_label="finance",
            codename__in=["post_journal", "view_journal"],
        ))

        grant_role(user, role, mode=AuthorityMode.UNRESTRICTED)

        return User.objects.get(pk=user.pk)

    def test_independent_finance_poster_is_still_held_by_the_workflow(self):
        """
        Pemegang `finance.post_journal` yang **terpisah** dari payroll:
        tanpa alur persetujuan jurnal ia boleh memposting draf gaji; begitu
        alurnya ada, DRAFT ditolak sampai diajukan dan disetujui.
        """
        from django.core.exceptions import ValidationError

        from apps.finance.services import FinancePostingService
        from apps.workflow.models import WorkflowDefinition, WorkflowStatus

        run = self.approved_run()
        PayrollRunService.finalize(run=run, user=self.make_operator("fin2"))

        journal = self.journals(run).get()
        poster = self.finance_poster()

        WorkflowDefinition.objects.create(
            code=f"FIN-JOURNAL-{run.pk}",
            name="Journal — Standar",
            module="finance",
            document_type="journal",
            company=self.company,
            status=WorkflowStatus.ACTIVE,
        )

        before = self.journal_state(journal)

        with self.assertRaises(ValidationError):
            FinancePostingService.post(journal=journal, user=poster)

        self.assertEqual(self.journal_state(journal), before)

        WorkflowDefinition.objects.filter(company=self.company).delete()

        result = FinancePostingService.post(journal=journal, user=poster)

        self.assertEqual(result.journal.status, JournalStatus.POSTED)
        self.assertEqual(result.journal.posted_by_id, poster.pk)

    # ------------------------------------------------------------------
    # FIN-AJ1 — jurnal gaji dikendalikan sumbernya
    # ------------------------------------------------------------------

    def test_generated_payroll_journal_is_source_controlled(self):
        """
        FIN-AJ1 — pemegang seluruh izin jurnal Finance pun tidak bisa
        menyunting, mengganti baris, menghapus baris, atau membatalkan
        jurnal gaji. Run tetap FINALIZED, kejadian tetap PROCESSED dan
        menunjuk jurnal yang sama, isinya tetap persis proyeksi payload,
        dan pencatatan/retry ulang tidak menerbitkan jurnal kedua.
        """
        from django.core.exceptions import ValidationError

        from apps.finance.services import (
            AccountingEventProcessor,
            AutomaticJournalLocked,
            JournalLineService,
            JournalService,
        )

        run = self.approved_run()
        PayrollRunService.finalize(run=run, user=self.make_operator("aj1"))

        event = self.events(run).get()
        journal = self.journals(run).get()

        type(self)._counter += 1
        name = f"finmgr-{self._counter}-{self.company.pk}"
        manager = User.objects.create_user(
            username=name, email=f"{name}@uji.local", password="Uji#12345",
        )
        role = Role.objects.create(code=f"FINMGR-{manager.pk}", name=name)
        role.permissions.add(*Permission.objects.filter(
            content_type__app_label="finance",
            codename__in=[
                "view_journal", "change_journal", "delete_journal",
                "view_journalline", "change_journalline",
                "delete_journalline", "post_journal",
            ],
        ))
        grant_role(manager, role, mode=AuthorityMode.UNRESTRICTED)
        manager = User.objects.get(pk=manager.pk)

        def lines():
            return list(journal.lines.order_by("id").values_list(
                "account_id", "debit", "credit", "description",
                "department_id", "cost_center_id",
            ))

        before = lines()
        line = journal.lines.order_by("line_number").first()

        for attempt in (
            lambda: JournalService.update(
                instance=journal, data={"description": "x"}, user=manager,
            ),
            lambda: JournalService.replace_lines(
                journal=journal, lines=[], user=manager,
            ),
            lambda: JournalLineService.update(
                instance=line, data={"description": "x"}, user=manager,
            ),
            lambda: JournalLineService.soft_delete(instance=line, user=manager),
            lambda: JournalService.cancel(journal=journal, user=manager),
        ):
            with self.assertRaises(AutomaticJournalLocked):
                attempt()

            self.assertEqual(lines(), before)

        journal.refresh_from_db()
        event.refresh_from_db()
        run.refresh_from_db()

        self.assertEqual(journal.status, JournalStatus.DRAFT)
        self.assertEqual(event.status, AccountingEventStatus.PROCESSED)
        self.assertEqual(event.generated_journal_id, journal.pk)
        self.assertEqual(run.status, PayrollRunStatus.FINALIZED)

        self.assertTrue(
            AccountingEventProcessor.verify_projection(event)["matches"],
        )

        with self.assertRaises(ValidationError):
            AccountingEventProcessor.retry(event=event)

        again = PayrollAccountingBridge.record(
            run=run, gate=PayrollAccountingGate.evaluate(run=run),
        )

        self.assertEqual(again["journal_id"], journal.pk)
        self.assertEqual(self.finance_rows(run), (1, 1))
        self.assertFalse(journal.lines.filter(is_posted=True).exists())
