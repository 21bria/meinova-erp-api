"""
PF-0E — kebijakan akuntansi `PAYROLL_POSTED` dan `auto_post`.

Dua janji yang diuji di sini, dan keduanya baru:

1. **`AccountingPolicy.auto_post`.** Bawaannya `True`, jadi seluruh
   kebijakan yang sudah ada tetap membukukan langsung seperti
   sebelumnya. Kebijakan gaji satu-satunya yang mematikannya, dan
   jurnalnya terbit `DRAFT` — tidak ada stempel posting, tidak ada
   dampak buku besar, dan alur persetujuan Finance tetap yang
   memutuskan kapan ia jadi fakta.

2. **Kebijakan semantik gaji.** Ia membaca kontrak `payroll.posting/v1`
   (PF-0C) — `semantic`/`detail`/`program`, bukan nama komponen — dan
   menerbitkan ayat yang seimbang lewat pemetaan akun, tanpa satu pun
   kode akun di sisi payroll maupun di aturan kebijakannya.

**Payload di berkas ini ditulis tangan, bukan dihasilkan payroll.** Itu
disengaja: Finance tidak boleh mengimpor satu pun model payroll, dan
test yang memanggil normalizer payroll untuk menyusun fixture-nya
menjadikan Finance bergantung pada modul sumber lewat pintu belakang.
Yang menjaga keduanya tidak menyimpang satu test tersendiri —
`test_every_payroll_semantic_has_a_rule` — dan ia mengimpor kontraknya
**di dalam** fungsi, bukan di kepala berkas.
"""

from datetime import date
from decimal import Decimal

from apps.administration.models import (
    Branch,
    CostCenter,
    Department,
    Division,
    Location,
    Section,
)
from apps.finance.models import (
    AccountMapping,
    AccountType,
    AccountingEvent,
    AccountingEventStatus,
    AccountingPolicy,
    AccountingPolicyLine,
    AccountingPolicyRule,
    Journal,
    JournalStatus,
    PostingSide,
)
from apps.finance.seeds import seed_chart_of_accounts, seed_payroll_policy
from apps.finance.seeds.policies import (
    MAPPING_ACCOUNTS,
    legacy_mapping_code,
    legacy_policy_code,
    mapping_code,
    policy_code,
)
from apps.finance.services import (
    AccountingEventProcessor,
    AccountMappingService,
)

from .base import FinanceTestCase


EVENT_DATE = date(2027, 3, 31)

RUN_REFERENCE = "PAY-2027-00009"

DIMENSION_KEYS = (
    "branch_id",
    "location_id",
    "division_id",
    "department_id",
    "section_id",
    "cost_center_id",
)


def component(semantic, amount, *, detail="", program="", **dimensions) -> dict:
    """Satu baris `payload["components"]` menurut kontrak PF-0C."""
    row = {
        "semantic": semantic,
        "detail": detail,
        "program": program,
        "amount": amount,
        "reference": RUN_REFERENCE,
    }

    row.update({key: None for key in DIMENSION_KEYS})
    row.update(dimensions)

    return row


def payload(*components) -> dict:
    """
    Amplop `payroll.posting/v1` yang lengkap.

    Amplopnya ikut disertakan walau kebijakan cuma membaca `components`:
    kalau suatu saat sebuah aturan mulai membaca `_parent`, fixture ini
    sudah berbentuk seperti yang benar-benar dikirim payroll.
    """
    return {
        "schema": "payroll.posting/v1",
        "run": {
            "id": 9,
            "document_number": RUN_REFERENCE,
            "run_type": "regular",
            "company_id": 0,
            "period_code": "2027-03",
            "period_start": "2027-03-01",
            "period_end": "2027-03-31",
            "corrects_run_id": None,
            "corrects_document_number": "",
        },
        "currency": "IDR",
        "control": {},
        "components": list(components),
        "digest": "0" * 64,
    }


# ----------------------------------------------------------------------
# auto_post
# ----------------------------------------------------------------------


class AccountingPolicyAutoPostTests(FinanceTestCase):
    """
    Perilaku `auto_post` sendirian, dengan kebijakan yang dibuat tangan.

    Sengaja tidak memakai seed: yang diuji di sini kolomnya dan
    pengaruhnya pada pemroses kejadian, bukan isi kebijakan gaji.
    """

    def stage(self, *, auto_post=None):
        company = self.make_company()
        self.make_fiscal_year(company)
        expense, payable = self.make_pair(company)

        fields = {
            "code": self.next_code("POL"),
            "name": "Simple posting",
            "company": company,
            "event_type": "WIDGET_SOLD",
            "journal_type": "automatic",
        }

        if auto_post is not None:
            fields["auto_post"] = auto_post

        policy = AccountingPolicy.objects.create(**fields)

        rule = AccountingPolicyRule.objects.create(
            policy=policy,
            sequence=10,
            name="Both sides",
            conditions={},
        )

        AccountingPolicyLine.objects.create(
            rule=rule,
            sequence=1,
            side=PostingSide.DEBIT,
            account=expense,
            amount_source="amount",
        )

        AccountingPolicyLine.objects.create(
            rule=rule,
            sequence=2,
            side=PostingSide.CREDIT,
            account=payable,
            amount_source="amount",
        )

        return company, policy

    def fire(self, company, *, key: str, post: bool = True):
        return AccountingEventProcessor.record(
            event_type="WIDGET_SOLD",
            source_module="sales",
            source_type="widget",
            source_id=key,
            company=company,
            event_date=EVENT_DATE,
            payload={"amount": "1000.00"},
            idempotency_key=f"pf0e:{key}",
            process=False,
        )

    # 1
    def test_auto_post_defaults_to_true(self):
        _, policy = self.stage()

        self.assertTrue(policy.auto_post)

        policy.refresh_from_db()

        self.assertTrue(policy.auto_post)

    # 2
    def test_existing_auto_post_policy_still_posts_to_the_ledger(self):
        company, _ = self.stage()

        event = self.fire(company, key=self.next_code("E"))
        event = AccountingEventProcessor.process(event=event)

        self.assertEqual(
            event.status, AccountingEventStatus.PROCESSED, event.error_message,
        )

        journal = event.generated_journal

        self.assertEqual(journal.status, JournalStatus.POSTED)
        self.assertTrue(journal.is_posted)
        self.assertIsNotNone(journal.posted_at)

        # Kolom turunan pada barisnya ikut dicap — itu yang dibaca buku
        # besar, dan itu yang membedakan "terbit" dari "dibukukan".
        self.assertEqual(
            set(journal.lines.values_list("is_posted", flat=True)), {True},
        )

    # 5, 6
    def test_auto_post_false_leaves_the_journal_in_draft(self):
        company, _ = self.stage(auto_post=False)

        event = self.fire(company, key=self.next_code("E"))
        event = AccountingEventProcessor.process(event=event)

        self.assertEqual(
            event.status, AccountingEventStatus.PROCESSED, event.error_message,
        )

        journal = event.generated_journal

        self.assertEqual(journal.status, JournalStatus.DRAFT)
        self.assertFalse(journal.is_posted)

        # Tidak ada satu pun stempel posting — bukan sekadar statusnya
        # yang beda. Kalau `posted_at` terisi pada jurnal draft, setiap
        # laporan yang menyaring "sudah dibukukan" lewat stempel akan
        # memungutnya.
        self.assertIsNone(journal.posted_at)
        self.assertIsNone(journal.posted_by_id)

        self.assertEqual(
            set(journal.lines.values_list("is_posted", flat=True)), {False},
        )
        self.assertEqual(
            set(journal.lines.values_list("accounting_period_id", flat=True)),
            {None},
        )

    def test_caller_cannot_force_posting_on_a_non_auto_post_policy(self):
        """
        `post=True` **tidak** mengalahkan kebijakan.

        Kalau argumen pemanggil bisa memaksanya, seluruh gunanya hilang:
        yang memfinalisasi payroll tinggal mengirim `post=True` dan
        jurnal gaji masuk buku besar tanpa satu pun persetujuan Finance.
        """
        company, _ = self.stage(auto_post=False)

        event = self.fire(company, key=self.next_code("E"))
        event = AccountingEventProcessor.process(event=event, post=True)

        self.assertEqual(event.generated_journal.status, JournalStatus.DRAFT)

    def test_post_false_still_holds_back_an_auto_post_policy(self):
        """Arah sebaliknya tidak ikut berubah: `post=False` tetap menahan."""
        company, _ = self.stage()

        event = self.fire(company, key=self.next_code("E"))
        event = AccountingEventProcessor.process(event=event, post=False)

        self.assertEqual(event.generated_journal.status, JournalStatus.DRAFT)

    def test_draft_journal_from_an_event_is_still_submittable(self):
        """
        `auto_post=False` **tidak** menciptakan alur kedua.

        Jurnalnya jurnal biasa: draft yang bisa diajukan ke alur Finance
        yang sudah ada. Kalau ia lahir dalam keadaan yang tidak bisa
        diajukan, PF-0F tidak punya jalan menyelesaikannya.
        """
        from apps.finance.services import JournalService

        company, _ = self.stage(auto_post=False)

        event = self.fire(company, key=self.next_code("E"))
        event = AccountingEventProcessor.process(event=event)

        journal = event.generated_journal

        JournalService.assert_editable(journal)
        JournalService.assert_balanced(journal)


# ----------------------------------------------------------------------
# Kebijakan semantik gaji
# ----------------------------------------------------------------------


class PayrollSemanticPolicyTests(FinanceTestCase):
    """
    Kebijakan `PAYROLL_POSTED` yang diseed, diuji lewat pemroses kejadian.

    Panggungnya dibangun sekali per kelas: satu perusahaan, bagan akun
    contoh, kebijakan hasil seed, lalu **sebelas pemetaan diarahkan ke
    sebelas akun tersendiri**. Template contoh menumpangkan beberapa
    peran pada akun yang sama (lembur di akun gaji, iuran pemberi kerja
    di akun benefit), dan itu wajar untuk template — tapi membuat
    assertion "lembur mendarat di beban lembur" tidak menguji apa pun.
    Mengarahkannya ulang persis yang dilakukan tenant sungguhan.

    Tiap test memakai penanda idempotensi sendiri dan hanya membaca
    jurnal miliknya, jadi tidak ada yang bergantung pada urutan
    eksekusi — disiplin yang sama dengan `base.py`.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        from apps.administration.models import Company

        from apps.finance.services import AccountService, FiscalYearService

        cls.company = Company.objects.create(
            code=cls.next_code("PAYCO"), name="Payroll Co",
        )

        fiscal_year = FiscalYearService.create(data={
            "company": cls.company,
            "code": cls.next_code("FY"),
            "name": "Fiscal Year 2027",
            "start_date": date(2027, 1, 1),
            "end_date": date(2027, 12, 31),
            "status": "open",
        })

        FiscalYearService.generate_periods(fiscal_year=fiscal_year, count=12)

        seed_chart_of_accounts(company=cls.company)
        seed_payroll_policy(company=cls.company)

        # Satu akun per peran, supaya tiap assertion menyebut satu akun.
        cls.accounts = {}

        for index, key in enumerate(MAPPING_ACCOUNTS, start=1):
            account = AccountService.create(data={
                "company": cls.company,
                "code": f"9{index:03d}",
                "name": key.replace("_", " ").title(),
                "account_type": (
                    AccountType.LIABILITY
                    if key.endswith("PAYABLE")
                    else AccountType.EXPENSE
                ),
                "posting_allowed": True,
            })

            cls.accounts[key] = account

            AccountMapping.objects.filter(
                code=mapping_code(cls.company, key),
            ).update(account=account)

        cls.account_code = {
            key: account.code for key, account in cls.accounts.items()
        }

    # ------------------------------------------------------------------
    # Pembantu
    # ------------------------------------------------------------------

    def fire(self, body, *, key=None, company=None):
        company = company or self.company
        key = key or self.next_code("PAYEV")

        return AccountingEventProcessor.record(
            event_type="PAYROLL_POSTED",
            source_module="payroll",
            source_type="payroll_run",
            source_id=key,
            company=company,
            event_date=EVENT_DATE,
            source_reference=RUN_REFERENCE,
            payload=body,
            idempotency_key=f"pf0e:payroll:{key}",
        )

    def amounts(self, journal) -> dict:
        """`{kode akun: (debit, kredit)}`, dijumlahkan per akun."""
        totals: dict[str, list[Decimal]] = {}

        for line in journal.lines.select_related("account"):
            bucket = totals.setdefault(
                line.account.code, [Decimal("0.00"), Decimal("0.00")],
            )

            bucket[0] += line.debit
            bucket[1] += line.credit

        return {code: tuple(value) for code, value in totals.items()}

    def journal_for(self, body):
        event = self.fire(body)

        self.assertEqual(
            event.status, AccountingEventStatus.PROCESSED, event.error_message,
        )

        return event.generated_journal

    def side_of(self, journal, key) -> tuple:
        return self.amounts(journal).get(self.account_code[key])

    def full_payload(self):
        """
        Satu run lengkap, seimbang menurut persamaan kontrol PF-0C.

        Penghasilan 12.800.000, potongan 1.400.000 (termasuk pengurang
        penghasilan 400.000), jadi gaji bersih 11.400.000. Iuran pemberi
        kerja 800.000 berdiri di kedua sisi dan **tidak** mengubah gaji
        bersih.
        """
        return payload(
            component("BASIC_SALARY", "10000000.00"),
            component("ALLOWANCE", "2000000.00", detail="TAXABLE"),
            component("OVERTIME", "500000.00"),
            component("OTHER_EARNING", "300000.00", detail="INCENTIVE"),
            component("EARNING_REDUCTION", "400000.00", detail="ABSENCE"),
            component("EMPLOYEE_INCOME_TAX", "600000.00"),
            component("EMPLOYEE_SOCIAL_DEDUCTION", "250000.00", program="JHT"),
            component("OTHER_EMPLOYEE_DEDUCTION", "150000.00", detail="DEDUCTION"),
            component("EMPLOYER_SOCIAL_CONTRIBUTION", "700000.00", program="JKK"),
            component("OTHER_EMPLOYER_CONTRIBUTION", "100000.00", detail="TEMPLATE"),
            component("NET_PAY", "11400000.00"),
        )

    # ------------------------------------------------------------------
    # Bentuk kebijakan
    # ------------------------------------------------------------------

    # 3
    def test_seeded_payroll_policy_is_not_auto_post(self):
        policy = AccountingPolicy.objects.get(
            code=policy_code(self.company), is_deleted=False,
        )

        self.assertFalse(policy.auto_post)
        self.assertEqual(policy.event_type, "PAYROLL_POSTED")

    def test_no_payroll_rule_stops_on_match(self):
        """
        PF-0B mencatat `stop_on_match` sebagai perilaku yang mencurigakan.

        Kebijakan ini tidak memakainya sama sekali — bukan karena
        perilakunya sudah pasti benar, tapi karena satu aturan yang
        berhenti di baris pertama yang cocok akan membuang sisi lawan
        ayat baris-baris sesudahnya.
        """
        stops = (
            AccountingPolicyRule.objects
            .filter(
                policy__code=policy_code(self.company),
                is_deleted=False,
                stop_on_match=True,
            )
            .count()
        )

        self.assertEqual(stops, 0)

    def test_no_policy_line_names_an_account_directly(self):
        """Akun ditentukan pemetaan, bukan ditanam di aturan."""
        direct = (
            AccountingPolicyLine.objects
            .filter(
                rule__policy__code=policy_code(self.company),
                is_deleted=False,
                account__isnull=False,
            )
            .count()
        )

        self.assertEqual(direct, 0)

    def test_every_payroll_semantic_has_a_rule(self):
        """
        Kontrak PF-0C ↔ kebijakan Finance, dijaga dari kedua sisi.

        Makna yang ditambahkan payroll tanpa aturan di sini akan jatuh
        diam-diam: `build_lines` tidak melempar untuk baris yang tidak
        cocok satu aturan pun, jadi jumlahnya hilang dan jurnalnya
        terbit **tidak seimbang** — yang justru gagal jauh dari
        sebabnya.
        """
        from apps.payroll.services.accounting import Semantic

        expected = {
            value for name, value in vars(Semantic).items()
            if not name.startswith("_") and isinstance(value, str)
        }

        covered = {
            rule.conditions.get("value")
            for rule in AccountingPolicyRule.objects.filter(
                policy__code=policy_code(self.company), is_deleted=False,
            )
        }

        self.assertEqual(covered, expected)

    # ------------------------------------------------------------------
    # Jurnal
    # ------------------------------------------------------------------

    # 4, 5, 6
    def test_full_run_produces_a_balanced_draft_journal(self):
        journal = self.journal_for(self.full_payload())

        self.assertEqual(journal.status, JournalStatus.DRAFT)
        self.assertFalse(journal.is_posted)
        self.assertIsNone(journal.posted_at)
        self.assertIsNone(journal.posted_by_id)

        self.assertEqual(journal.base_total_debit, journal.base_total_credit)
        self.assertEqual(journal.base_total_debit, Decimal("13600000.00"))

        self.assertEqual(
            set(journal.lines.values_list("is_posted", flat=True)), {False},
        )

    def test_draft_journal_leaves_no_ledger_trace(self):
        """
        Buku besar tidak bergerak.

        Yang membuktikannya bukan status kepala dokumen. Seluruh laporan
        buku besar — `LedgerQueryService.base_queryset()`, neraca saldo,
        dan indeks parsial `idx_fin_line_ledger` — menyaring
        `JournalLine.is_posted=True` dan menjumlahkan `posting_date`
        milik barisnya. Selama ketiga stempel itu kosong, tidak ada satu
        laporan pun yang bisa memungut jurnal ini.
        """
        from apps.finance.models import JournalLine

        journal = self.journal_for(self.full_payload())

        self.assertEqual(journal.status, JournalStatus.DRAFT)

        self.assertEqual(
            JournalLine.objects
            .filter(journal=journal, is_posted=True)
            .count(),
            0,
        )

        stamps = journal.lines.values_list(
            "is_posted", "posting_date", "accounting_period_id",
        )

        self.assertEqual(set(stamps), {(False, None, None)})

    # 7, 8, 9, 10, 12, 13, 14, 15, 16, 17
    def test_each_semantic_lands_on_its_own_mapping_key(self):
        journal = self.journal_for(self.full_payload())

        zero = Decimal("0.00")

        expected = {
            # 7 gaji pokok → beban gaji
            "SALARY_EXPENSE": (
                Decimal("10000000.00"),
                # 11 pengurang penghasilan mengkredit beban yang sama
                Decimal("400000.00"),
            ),
            # 8 tunjangan → beban tunjangan
            "ALLOWANCE_EXPENSE": (Decimal("2000000.00"), zero),
            # 9 lembur → beban lembur
            "OVERTIME_EXPENSE": (Decimal("500000.00"), zero),
            # 10 penghasilan lain → beban penghasilan lain
            "OTHER_EARNING_EXPENSE": (Decimal("300000.00"), zero),
            # 12 pajak → utang pajak penghasilan
            "INCOME_TAX_PAYABLE": (zero, Decimal("600000.00")),
            # 13 iuran pegawai + 15 iuran pemberi kerja, satu utang
            "SOCIAL_SECURITY_PAYABLE": (zero, Decimal("950000.00")),
            # 14 potongan lain → utang potongan lain
            "OTHER_DEDUCTION_PAYABLE": (zero, Decimal("150000.00")),
            # 15 iuran pemberi kerja → beban pemberi kerja
            "EMPLOYER_SOCIAL_EXPENSE": (Decimal("700000.00"), zero),
            # 16 benefit pemberi kerja → beban + utang
            "EMPLOYER_BENEFIT_EXPENSE": (Decimal("100000.00"), zero),
            "EMPLOYER_BENEFIT_PAYABLE": (zero, Decimal("100000.00")),
            # 17 gaji bersih → utang gaji
            "PAYROLL_PAYABLE": (zero, Decimal("11400000.00")),
        }

        actual = {key: self.side_of(journal, key) for key in expected}

        self.assertEqual(actual, expected)

    # 11
    def test_earning_reduction_credits_expense_without_a_payable(self):
        """
        Ketidakhadiran mengurangi beban, **bukan** menerbitkan utang.

        Utang potongan yang lahir dari ketidakhadiran tidak akan pernah
        dibayar kepada siapa pun dan tidak akan pernah nol — ia saldo
        yang tumbuh tiap bulan tanpa ada yang bisa menjelaskannya.
        """
        journal = self.journal_for(payload(
            component("BASIC_SALARY", "1000000.00"),
            component("EARNING_REDUCTION", "200000.00", detail="UNPAID_LEAVE"),
            component("NET_PAY", "800000.00"),
        ))

        self.assertEqual(
            self.side_of(journal, "SALARY_EXPENSE"),
            (Decimal("1000000.00"), Decimal("200000.00")),
        )

        self.assertIsNone(self.side_of(journal, "OTHER_DEDUCTION_PAYABLE"))
        self.assertIsNone(self.side_of(journal, "INCOME_TAX_PAYABLE"))
        self.assertIsNone(self.side_of(journal, "SOCIAL_SECURITY_PAYABLE"))

    # 12
    def test_income_tax_is_credited_exactly_once(self):
        journal = self.journal_for(payload(
            component("BASIC_SALARY", "1000000.00"),
            component("EMPLOYEE_INCOME_TAX", "90000.00"),
            component("NET_PAY", "910000.00"),
        ))

        tax_lines = [
            line for line in journal.lines.select_related("account")
            if line.account.code == self.account_code["INCOME_TAX_PAYABLE"]
        ]

        self.assertEqual(len(tax_lines), 1)
        self.assertEqual(tax_lines[0].credit, Decimal("90000.00"))
        self.assertEqual(tax_lines[0].debit, Decimal("0.00"))

    # 15
    def test_employer_social_contribution_does_not_change_net_pay(self):
        """
        Iuran pemberi kerja berdiri di kedua sisi dan berhenti di situ.

        Kalau ia ikut menambah utang gaji, yang dibayarkan ke pegawai
        jadi lebih besar dari yang dihitung payroll — dan selisihnya
        baru ketahuan di rekening koran.
        """
        without = self.journal_for(payload(
            component("BASIC_SALARY", "1000000.00"),
            component("NET_PAY", "1000000.00"),
        ))

        with_employer = self.journal_for(payload(
            component("BASIC_SALARY", "1000000.00"),
            component("EMPLOYER_SOCIAL_CONTRIBUTION", "40000.00", program="JKK"),
            component("NET_PAY", "1000000.00"),
        ))

        self.assertEqual(
            self.side_of(without, "PAYROLL_PAYABLE"),
            self.side_of(with_employer, "PAYROLL_PAYABLE"),
        )

        self.assertEqual(
            self.side_of(with_employer, "EMPLOYER_SOCIAL_EXPENSE"),
            (Decimal("40000.00"), Decimal("0.00")),
        )
        self.assertEqual(
            self.side_of(with_employer, "SOCIAL_SECURITY_PAYABLE"),
            (Decimal("0.00"), Decimal("40000.00")),
        )

        self.assertEqual(
            with_employer.base_total_debit, with_employer.base_total_credit,
        )

    # 18
    def test_all_six_dimensions_reach_the_journal_line(self):
        branch = Branch.objects.create(
            company=self.company, code=self.next_code("BR"), name="Branch",
        )
        location = Location.objects.create(
            company=self.company, code=self.next_code("LOC"), name="Location",
        )
        division = Division.objects.create(
            company=self.company, code=self.next_code("DIV"), name="Division",
        )
        department = Department.objects.create(
            company=self.company, code=self.next_code("DEP"), name="Department",
        )
        section = Section.objects.create(
            company=self.company,
            department=department,
            code=self.next_code("SEC"),
            name="Section",
        )
        cost_center = CostCenter.objects.create(
            company=self.company, code=self.next_code("CC"), name="Cost Center",
        )

        dimensions = {
            "branch_id": branch.pk,
            "location_id": location.pk,
            "division_id": division.pk,
            "department_id": department.pk,
            "section_id": section.pk,
            "cost_center_id": cost_center.pk,
        }

        journal = self.journal_for(payload(
            component("BASIC_SALARY", "1000000.00", **dimensions),
            component("NET_PAY", "1000000.00", **dimensions),
        ))

        for line in journal.lines.all():
            self.assertEqual(line.branch_id, branch.pk)
            self.assertEqual(line.location_id, location.pk)
            self.assertEqual(line.division_id, division.pk)
            self.assertEqual(line.department_id, department.pk)
            self.assertEqual(line.section_id, section.pk)
            self.assertEqual(line.cost_center_id, cost_center.pk)

            # Company tetap milik kepala dokumen — satu jurnal selalu
            # milik satu perusahaan.
            self.assertEqual(line.company_id, self.company.pk)

    def test_dimension_specific_buckets_are_not_collapsed(self):
        """Dua cost center menghasilkan dua baris, bukan satu yang dijumlahkan."""
        first = CostCenter.objects.create(
            company=self.company, code=self.next_code("CC"), name="CC One",
        )
        second = CostCenter.objects.create(
            company=self.company, code=self.next_code("CC"), name="CC Two",
        )

        journal = self.journal_for(payload(
            component("BASIC_SALARY", "600000.00", cost_center_id=first.pk),
            component("BASIC_SALARY", "400000.00", cost_center_id=second.pk),
            component("NET_PAY", "1000000.00"),
        ))

        salary = {
            (line.cost_center_id, line.debit)
            for line in journal.lines.select_related("account")
            if line.account.code == self.account_code["SALARY_EXPENSE"]
        }

        self.assertEqual(
            salary,
            {(first.pk, Decimal("600000.00")), (second.pk, Decimal("400000.00"))},
        )

    # 23
    def test_negative_bucket_reverses_the_side(self):
        """
        Jumlah bertanda negatif dibukukan sebagai nilai mutlak di sisi
        lawan — bukan sebagai debit negatif, yang ditolak baris jurnal.

        PF-0C sengaja mempertahankan tandanya (koreksi penghasilan yang
        melebihi penghasilannya sendiri), jadi Finance harus punya
        jawaban untuknya. Perilakunya generik, milik
        `AccountingPolicyService._lines_for` — tidak ada satu pun cabang
        khusus payroll.
        """
        journal = self.journal_for(payload(
            component("BASIC_SALARY", "1000000.00"),
            component("OTHER_EARNING", "-150000.00", detail="ADJUSTMENT"),
            component("NET_PAY", "850000.00"),
        ))

        self.assertEqual(
            self.side_of(journal, "OTHER_EARNING_EXPENSE"),
            (Decimal("0.00"), Decimal("150000.00")),
        )

        self.assertEqual(journal.base_total_debit, journal.base_total_credit)

        # Tidak ada angka negatif yang tersimpan di baris mana pun.
        for line in journal.lines.all():
            self.assertGreaterEqual(line.debit, Decimal("0.00"))
            self.assertGreaterEqual(line.credit, Decimal("0.00"))

    def test_negative_deduction_bucket_reverses_to_a_debit(self):
        """Arah sebaliknya: potongan negatif jadi debit di akun utangnya."""
        journal = self.journal_for(payload(
            component("BASIC_SALARY", "1000000.00"),
            component("OTHER_EMPLOYEE_DEDUCTION", "-50000.00", detail="ADJUSTMENT"),
            component("NET_PAY", "1050000.00"),
        ))

        self.assertEqual(
            self.side_of(journal, "OTHER_DEDUCTION_PAYABLE"),
            (Decimal("50000.00"), Decimal("0.00")),
        )

    # 24
    def test_zero_amount_does_not_create_a_line(self):
        journal = self.journal_for(payload(
            component("BASIC_SALARY", "1000000.00"),
            component("ALLOWANCE", "0.00", detail="NON_TAXABLE"),
            component("NET_PAY", "1000000.00"),
        ))

        self.assertIsNone(self.side_of(journal, "ALLOWANCE_EXPENSE"))
        self.assertEqual(journal.lines.count(), 2)

    # 25
    def test_descriptions_carry_no_private_payroll_data(self):
        """
        Keterangan disusun dari kolom terkendali saja: makna, detail,
        program, dan nomor dokumen run.

        Yang dijaga bukan sekadar "tidak ada nama pegawai" — payload PF-0C
        memang tidak membawanya. Yang dijaga bahwa keterangan **tidak
        pernah** dirangkai dari kolom bebas: begitu sebuah template
        menyebut `{name}`, teks apa pun yang diketik tenant di master
        komponen ikut masuk ke buku besar dan tidak bisa dicabut lagi.
        """
        journal = self.journal_for(self.full_payload())

        allowed_fragments = {
            "Payroll basic salary",
            "Payroll allowance",
            "Payroll overtime",
            "Payroll other earning",
            "Payroll earning reduction",
            "Payroll income tax",
            "Payroll employee social security",
            "Payroll other deduction",
            "Payroll employer social security",
            "Payroll employer benefit",
            "Payroll net pay",
        }

        for line in journal.lines.all():
            self.assertTrue(
                any(line.description.startswith(x) for x in allowed_fragments),
                f"keterangan tak dikenal: {line.description!r}",
            )

            self.assertIn(RUN_REFERENCE, line.description)

        # Kepala dokumen pun hanya menyebut jenis kejadian dan nomor run.
        self.assertEqual(
            journal.description, f"PAYROLL_POSTED — {RUN_REFERENCE}",
        )

    def test_policy_rules_never_read_a_free_text_payload_key(self):
        """
        Aturan hanya menyebut `semantic`, dan barisnya hanya `amount` —
        tidak ada satu pun template atau syarat yang membaca kunci yang
        isinya diketik tenant.
        """
        rules = AccountingPolicyRule.objects.filter(
            policy__code=policy_code(self.company), is_deleted=False,
        )

        for rule in rules:
            self.assertEqual(rule.conditions.get("field"), "semantic")
            self.assertEqual(rule.iterate_over, "components")

        lines = AccountingPolicyLine.objects.filter(
            rule__policy__code=policy_code(self.company), is_deleted=False,
        )

        allowed = {"semantic", "detail", "program", "reference"}

        for line in lines:
            self.assertEqual(line.amount_source, "amount")

            placeholders = {
                fragment.split("}")[0]
                for fragment in line.description_template.split("{")[1:]
            }

            self.assertTrue(
                placeholders <= allowed,
                f"template menyebut kunci di luar kontrak: {placeholders}",
            )

    # 21
    def test_missing_mapping_fails_closed(self):
        """
        Peran yang belum diarahkan **tidak** menerbitkan jurnal separuh.

        Kejadiannya FAILED beserta sebabnya, dan tidak ada satu baris pun
        yang tertinggal — memperbaiki pemetaannya lalu memproses ulang
        berjalan di kejadian yang sama.
        """
        company = self.company

        mapping = AccountMapping.objects.get(
            code=mapping_code(company, "OVERTIME_EXPENSE"), is_deleted=False,
        )

        AccountMapping.objects.filter(pk=mapping.pk).update(is_active=False)

        try:
            event = self.fire(payload(
                component("BASIC_SALARY", "1000000.00"),
                component("OVERTIME", "100000.00"),
                component("NET_PAY", "1100000.00"),
            ))

            self.assertEqual(event.status, AccountingEventStatus.FAILED)
            self.assertIn("OVERTIME_EXPENSE", event.error_message)
            self.assertIsNone(event.generated_journal_id)

            self.assertFalse(
                Journal.objects
                .filter(metadata__accounting_event=event.pk)
                .exists()
            )
        finally:
            AccountMapping.objects.filter(pk=mapping.pk).update(is_active=True)

    # 22
    def test_ambiguous_mapping_fails_closed(self):
        """
        Dua pemetaan yang sama-sama cocok dan sama-sama khusus menolak,
        bukan memilih salah satunya.

        Keduanya menyebut **satu** syarat, jadi skor kekhususannya sama
        persis — dan itu satu-satunya cara membuat seri: baris yang
        syarat organisasinya identik sudah ditolak
        `uniq_active_finance_mapping_scope` sebelum sempat disimpan.
        """
        company = self.company

        rivals = [
            AccountMappingService.create(data={
                "code": self.next_code("MAPDUP"),
                "name": f"Rival salary expense {index}",
                "mapping_key": "SALARY_EXPENSE",
                "company": company,
                "event_type": "PAYROLL_POSTED",
                "selectors": selectors,
                "account": self.accounts["ALLOWANCE_EXPENSE"],
            })
            for index, selectors in enumerate(
                ({"semantic": "BASIC_SALARY"}, {"program": ""}), start=1,
            )
        ]

        self.assertEqual(
            len({row.specificity for row in rivals}), 1,
        )

        try:
            event = self.fire(payload(
                component("BASIC_SALARY", "1000000.00"),
                component("NET_PAY", "1000000.00"),
            ))

            self.assertEqual(event.status, AccountingEventStatus.FAILED)
            self.assertIn("ambigu", event.error_message)
            self.assertIsNone(event.generated_journal_id)
        finally:
            AccountMapping.objects.filter(
                pk__in=[row.pk for row in rivals],
            ).update(is_deleted=True, is_active=False)


# ----------------------------------------------------------------------
# Pemetaan akun
# ----------------------------------------------------------------------


class PayrollMappingResolutionTests(FinanceTestCase):
    """
    Kekhususan pemetaan tetap berlaku untuk kebijakan gaji.

    Dibangun tangan, tanpa seed: yang diuji urutan pemenangnya, dan itu
    paling jelas dengan dua baris yang bedanya cuma satu syarat.
    """

    def stage(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        policy = AccountingPolicy.objects.create(
            code=self.next_code("POL"),
            name="Payroll posting",
            company=company,
            event_type="PAYROLL_POSTED",
            journal_type="automatic",
            auto_post=False,
        )

        rule = AccountingPolicyRule.objects.create(
            policy=policy,
            sequence=10,
            name="Basic salary",
            conditions={
                "field": "semantic", "op": "eq", "value": "BASIC_SALARY",
            },
            iterate_over="components",
        )

        AccountingPolicyLine.objects.create(
            rule=rule,
            sequence=1,
            side=PostingSide.DEBIT,
            mapping_key="SALARY_EXPENSE",
            amount_source="amount",
            dimension_sources={"department": "department_id"},
        )

        net = AccountingPolicyRule.objects.create(
            policy=policy,
            sequence=20,
            name="Net pay",
            conditions={"field": "semantic", "op": "eq", "value": "NET_PAY"},
            iterate_over="components",
        )

        AccountingPolicyLine.objects.create(
            rule=net,
            sequence=1,
            side=PostingSide.CREDIT,
            mapping_key="PAYROLL_PAYABLE",
            amount_source="amount",
        )

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "Payroll payable",
            "mapping_key": "PAYROLL_PAYABLE",
            "company": company,
            "event_type": "PAYROLL_POSTED",
            "selectors": {},
            "account": payable,
        })

        return company, expense

    def fire(self, company, body, *, key=None):
        key = key or self.next_code("MEV")

        return AccountingEventProcessor.record(
            event_type="PAYROLL_POSTED",
            source_module="payroll",
            source_type="payroll_run",
            source_id=key,
            company=company,
            event_date=EVENT_DATE,
            payload=body,
            idempotency_key=f"pf0e:map:{key}",
        )

    # 19
    def test_company_specific_mapping_beats_the_global_one(self):
        company, expense = self.stage()

        specific = self.make_account(
            company, name="Company salary", account_type=AccountType.EXPENSE,
        )

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "Global salary",
            "mapping_key": "SALARY_EXPENSE",
            "company": None,
            "event_type": "PAYROLL_POSTED",
            "selectors": {},
            "account": expense,
        })

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "Company salary",
            "mapping_key": "SALARY_EXPENSE",
            "company": company,
            "event_type": "PAYROLL_POSTED",
            "selectors": {},
            "account": specific,
        })

        event = self.fire(company, payload(
            component("BASIC_SALARY", "1000000.00"),
            component("NET_PAY", "1000000.00"),
        ))

        self.assertEqual(
            event.status, AccountingEventStatus.PROCESSED, event.error_message,
        )

        codes = {
            line.account.code
            for line in event.generated_journal.lines.select_related("account")
        }

        self.assertIn(specific.code, codes)
        self.assertNotIn(expense.code, codes)

    # 20
    def test_global_mapping_is_used_when_no_company_row_exists(self):
        company, expense = self.stage()

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "Global salary",
            "mapping_key": "SALARY_EXPENSE",
            "company": None,
            "event_type": "PAYROLL_POSTED",
            "selectors": {},
            "account": expense,
        })

        event = self.fire(company, payload(
            component("BASIC_SALARY", "1000000.00"),
            component("NET_PAY", "1000000.00"),
        ))

        self.assertEqual(
            event.status, AccountingEventStatus.PROCESSED, event.error_message,
        )

        codes = {
            line.account.code
            for line in event.generated_journal.lines.select_related("account")
        }

        self.assertIn(expense.code, codes)

    def test_department_specific_mapping_wins_for_that_department_only(self):
        """
        Dimensi yang dibawa baris payload ikut memilih akun — itu yang
        membuat satu kebijakan melayani seluruh perusahaan tanpa aturan
        per departemen.
        """
        company, expense = self.stage()

        department = Department.objects.create(
            company=company, code=self.next_code("DEP"), name="Ops",
        )

        departmental = self.make_account(
            company, name="Ops salary", account_type=AccountType.EXPENSE,
        )

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "Default salary",
            "mapping_key": "SALARY_EXPENSE",
            "company": company,
            "event_type": "PAYROLL_POSTED",
            "selectors": {},
            "account": expense,
        })

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "Ops salary",
            "mapping_key": "SALARY_EXPENSE",
            "company": company,
            "event_type": "PAYROLL_POSTED",
            "department": department,
            "selectors": {},
            "account": departmental,
        })

        event = self.fire(company, payload(
            component("BASIC_SALARY", "600000.00", department_id=department.pk),
            component("BASIC_SALARY", "400000.00"),
            component("NET_PAY", "1000000.00"),
        ))

        self.assertEqual(
            event.status, AccountingEventStatus.PROCESSED, event.error_message,
        )

        by_account = {
            line.account.code: line.debit
            for line in event.generated_journal.lines.select_related("account")
            if line.debit
        }

        self.assertEqual(by_account[departmental.code], Decimal("600000.00"))
        self.assertEqual(by_account[expense.code], Decimal("400000.00"))


# ----------------------------------------------------------------------
# Seed
# ----------------------------------------------------------------------


class PayrollPolicySeedTests(FinanceTestCase):
    """Apa yang dilakukan seed terhadap data yang sudah ada."""

    def seeded_company(self):
        company = self.make_company()
        self.make_fiscal_year(company)
        seed_chart_of_accounts(company=company)

        return company

    def active_policies(self, company):
        return AccountingPolicy.objects.filter(
            company=company, event_type="PAYROLL_POSTED", is_deleted=False,
        )

    def active_mappings(self, company):
        return AccountMapping.objects.filter(
            company=company, event_type="PAYROLL_POSTED", is_deleted=False,
        )

    # 26
    def test_seed_is_idempotent(self):
        company = self.seeded_company()

        first = seed_payroll_policy(company=company)
        second = seed_payroll_policy(company=company)

        self.assertEqual(first["policies"], 1)
        self.assertEqual(first["rules"], 11)
        self.assertEqual(first["mappings"], len(MAPPING_ACCOUNTS))

        self.assertEqual(second["policies"], 0)
        self.assertEqual(second["rules"], 0)
        self.assertEqual(second["mappings"], 0)
        self.assertEqual(second["retired_policies"], 0)
        self.assertEqual(second["retired_mappings"], 0)

        self.assertEqual(self.active_policies(company).count(), 1)
        self.assertEqual(
            self.active_mappings(company).count(), len(MAPPING_ACCOUNTS),
        )

        self.assertEqual(
            AccountingPolicyRule.objects.filter(
                policy__code=policy_code(company), is_deleted=False,
            ).count(),
            11,
        )

    def test_seed_retires_the_legacy_demo_policy(self):
        """
        Kebijakan demo lama **diganti**, bukan dibiarkan berdiri
        berdampingan.

        Dua kebijakan aktif untuk `PAYROLL_POSTED` pada perusahaan yang
        sama berarti `AccountingPolicyService.resolve()` memilih salah
        satunya lewat urutan yang tidak pernah diputuskan siapa pun.
        """
        company = self.seeded_company()

        legacy = AccountingPolicy.objects.create(
            code=legacy_policy_code(company),
            name="Payroll Posting (demo)",
            company=company,
            event_type="PAYROLL_POSTED",
            journal_type="automatic",
        )

        legacy_rule = AccountingPolicyRule.objects.create(
            policy=legacy,
            sequence=10,
            name="Earning components",
            conditions={"field": "category", "op": "eq", "value": "EARNING"},
            iterate_over="components",
        )

        result = seed_payroll_policy(company=company)

        self.assertEqual(result["retired_policies"], 1)

        legacy.refresh_from_db()
        legacy_rule.refresh_from_db()

        self.assertTrue(legacy.is_deleted)
        self.assertFalse(legacy.is_active)
        self.assertTrue(legacy_rule.is_deleted)

        # Tepat satu kebijakan aktif tersisa, dan itu yang semantik.
        self.assertEqual(
            list(self.active_policies(company).values_list("code", flat=True)),
            [policy_code(company)],
        )

    def test_seed_carries_the_account_of_a_retired_demo_mapping(self):
        """
        Tenant demo yang sempat mengarahkan pemetaan lama ke akunnya
        sendiri tidak dikembalikan diam-diam ke akun template.
        """
        company = self.seeded_company()

        chosen = self.make_account(
            company, name="Custom tax payable",
            account_type=AccountType.LIABILITY,
        )

        AccountMappingService.create(data={
            "code": legacy_mapping_code(company, "TAX_PAYABLE"),
            "name": "Tax Payable",
            "mapping_key": "TAX_PAYABLE",
            "company": company,
            "event_type": "PAYROLL_POSTED",
            "selectors": {"component_type": "TAX"},
            "account": chosen,
        })

        result = seed_payroll_policy(company=company)

        self.assertEqual(result["retired_mappings"], 1)

        moved = AccountMapping.objects.get(
            code=mapping_code(company, "INCOME_TAX_PAYABLE"), is_deleted=False,
        )

        self.assertEqual(moved.account_id, chosen.pk)

        retired = AccountMapping.objects.get(
            code=legacy_mapping_code(company, "TAX_PAYABLE"),
        )

        self.assertTrue(retired.is_deleted)

    def test_seed_does_not_touch_mappings_it_does_not_own(self):
        """Baris yang kodenya bukan milik seed tidak disentuh sama sekali."""
        company = self.seeded_company()

        tenant_row = AccountMappingService.create(data={
            "code": self.next_code("TENANT"),
            "name": "Tenant salary expense",
            "mapping_key": "SALARY_EXPENSE",
            "company": company,
            "event_type": "PAYROLL_POSTED",
            "selectors": {"semantic": "BASIC_SALARY"},
            "account": self.make_account(company, name="Tenant salary"),
        })

        seed_payroll_policy(company=company)

        tenant_row.refresh_from_db()

        self.assertFalse(tenant_row.is_deleted)
        self.assertTrue(tenant_row.is_active)

    def test_seeded_mappings_have_no_ambiguous_pairs(self):
        company = self.seeded_company()

        seed_payroll_policy(company=company)

        conflicts = AccountMappingService.detect_conflicts(
            company_id=company.pk,
        )

        self.assertEqual(
            [row for row in conflicts if not row["same_account"]], [],
        )

    def test_seed_without_a_chart_of_accounts_creates_no_mapping(self):
        """
        Tanpa bagan akun, pemetaannya dilewati — dan kejadian gaji
        kemudian gagal tertutup dengan pesan yang menyebut kuncinya,
        bukan menerbitkan jurnal separuh.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        result = seed_payroll_policy(company=company)

        self.assertEqual(result["mappings"], 0)
        self.assertEqual(result["policies"], 1)

    def test_event_without_a_policy_is_skipped_not_failed(self):
        """Perusahaan yang memang tidak membukukan gaji tetap tenang."""
        company = self.make_company()
        self.make_fiscal_year(company)

        event = AccountingEventProcessor.record(
            event_type="PAYROLL_POSTED",
            source_module="payroll",
            source_type="payroll_run",
            source_id=str(company.pk),
            company=company,
            event_date=EVENT_DATE,
            payload=payload(component("BASIC_SALARY", "1000.00")),
            idempotency_key=f"pf0e:nopolicy:{company.pk}",
        )

        self.assertEqual(event.status, AccountingEventStatus.SKIPPED)
        self.assertIsNone(event.generated_journal_id)
        self.assertEqual(
            AccountingEvent.objects.filter(pk=event.pk).count(), 1,
        )
