"""
Pabrik data bersama untuk test Finance.

**`FastTenantTestCase`, bukan `TenantTestCase`.** Keduanya sama-sama
tidak memanggil `super().setUpClass()`, jadi tidak ada rollback
per-test dan `setUpTestData` tidak pernah jalan — tiap test harus
membuat data yang disentuhnya sendiri dan hanya membaca miliknya, kalau
tidak urutan eksekusi yang menentukan hasilnya. Disiplin itu sama
dengan `apps/hr/tests/travel_request/base.py`.

Bedanya **biaya schema**. `TenantTestCase` membuat schema tenant di
`setUpClass` dan membuangnya di `tearDownClass`, jadi tiap **kelas**
membayar satu `migrate_schemas` penuh — sekitar sembilan menit di mesin
ini. Suite Finance punya sebelas kelas; itu satu setengah jam untuk
menjalankan tes yang perhitungannya sendiri berlangsung beberapa detik.

`FastTenantTestCase` memakai schema `fast_test` yang dibuat **sekali**
lalu dipakai ulang seluruh kelas. Harganya dinyatakan terang-terangan
oleh pustakanya: state bisa bocor antar-kelas. Di suite ini harga itu
sudah dibayar di muka — `next_code()` memberi tiap baris kode unik, dan
tidak satu test pun menghitung baris milik test lain.

Kalau suatu saat ada test yang menganggap tabelnya kosong, itu yang
harus diperbaiki, bukan kelas dasarnya: kembali ke `TenantTestCase`
berarti membayar sembilan menit per kelas lagi.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django_tenants.test.cases import FastTenantTestCase

from apps.administration.models import Company, Currency
from apps.finance.models import (
    Account,
    AccountingPeriod,
    AccountType,
    FiscalYear,
    PeriodStatus,
)
from apps.finance.services import FiscalYearService, JournalService


AS_OF = date(2027, 3, 15)
YEAR = 2027


class FinanceTestCase(FastTenantTestCase):
    """Satu company, satu tahun buku, dan bagan akun minimal."""

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "finance"
        tenant.name = "Finance Test"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Tenant test lahir kosong. Tanpa deret nomor, `journal_number`
        # terbit kosong — perilaku yang memang benar (jurnalnya tetap
        # tersimpan), tapi membuat assertion soal nomor tidak menguji
        # apa pun.
        from apps.administration.seeds.numbering import seed_numbering

        seed_numbering()

        # **`get_or_create`, bukan `create`.** Schema `fast_test` dipakai
        # ulang seluruh kelas dan `setUpClass` tidak ikut di-rollback,
        # jadi kelas kedua akan menabrak `uniq_active_administration_
        # currency_code` kalau barisnya dibuat tanpa syarat — dan
        # galatnya muncul di `setUpClass`, yang terbaca seperti seluruh
        # kelas itu rusak.
        cls.currency, _ = Currency.objects.get_or_create(
            code="IDR",
            is_deleted=False,
            defaults={
                "name": "Rupiah",
                "symbol": "Rp",
                "decimal_places": 2,
                "is_base_currency": True,
            },
        )

    # ------------------------------------------------------------------
    # Pabrik
    # ------------------------------------------------------------------

    @classmethod
    def next_code(cls, prefix: str) -> str:
        FinanceTestCase._counter += 1

        return f"{prefix}{FinanceTestCase._counter:04d}"

    def make_company(self, code: str | None = None) -> Company:
        return Company.objects.create(
            code=code or self.next_code("CO"),
            name=f"Company {code or ''}".strip(),
        )

    def make_fiscal_year(
        self,
        company: Company,
        *,
        year: int = YEAR,
        periods: int = 12,
    ) -> FiscalYear:
        fiscal_year = FiscalYearService.create(
            data={
                "company": company,
                "code": self.next_code("FY"),
                "name": f"Fiscal Year {year}",
                "start_date": date(year, 1, 1),
                "end_date": date(year, 12, 31),
                "status": "open",
            },
        )

        if periods:
            FiscalYearService.generate_periods(
                fiscal_year=fiscal_year,
                count=periods,
            )

        return fiscal_year

    def period_for(self, company: Company, when: date) -> AccountingPeriod:
        return AccountingPeriod.objects.get(
            fiscal_year__company=company,
            start_date__lte=when,
            end_date__gte=when,
            is_deleted=False,
        )

    def make_account(
        self,
        company: Company,
        *,
        code: str | None = None,
        name: str = "Account",
        account_type: str = AccountType.EXPENSE,
        parent: Account | None = None,
        posting_allowed: bool = True,
        is_active: bool = True,
    ) -> Account:
        from apps.finance.services import AccountService

        return AccountService.create(
            data={
                "company": company,
                "code": code or self.next_code("A"),
                "name": name,
                "account_type": account_type,
                "parent": parent,
                "posting_allowed": posting_allowed,
                "is_active": is_active,
            },
        )

    def make_pair(self, company: Company):
        """Satu akun beban dan satu akun utang — pasangan ayat paling lazim."""
        expense = self.make_account(
            company,
            name="Salary Expense",
            account_type=AccountType.EXPENSE,
        )

        payable = self.make_account(
            company,
            name="Payroll Payable",
            account_type=AccountType.LIABILITY,
        )

        return expense, payable

    def make_journal(
        self,
        company: Company,
        *,
        posting_date: date = AS_OF,
        lines: list[dict] | None = None,
        user=None,
    ):
        journal = JournalService.create(
            data={
                "company": company,
                "posting_date": posting_date,
                "description": "Test journal",
            },
            user=user,
        )

        if lines is not None:
            JournalService.replace_lines(
                journal=journal,
                lines=lines,
                user=user,
            )

            journal.refresh_from_db()

        return journal

    def balanced_lines(self, debit_account, credit_account, amount="1000.00"):
        value = Decimal(amount)

        return [
            {"account": debit_account, "debit": value, "credit": Decimal("0.00")},
            {"account": credit_account, "debit": Decimal("0.00"), "credit": value},
        ]

    def grant_finance(self, user, *labels):
        """
        FIN-B1/B2: izin tindakan Finance lewat satu penugasan se-tenant.

        Aksi jurnal kini menagih izin eksplisit, jadi test yang menguji
        hal lain (cap waktu, periode SOFT_CLOSED, approver) memberi
        pelakunya izin yang dipegang role-nya di dunia nyata.
        """
        from django.contrib.auth.models import Permission

        from apps.accounts.models import AuthorityMode, Role
        from apps.accounts.services.role_assignment import grant_role

        role = Role.objects.create(
            code=self.next_code("GRANT"), name="Finance grant",
        )

        for label in labels:
            app_label, codename = label.split(".")
            role.permissions.add(Permission.objects.get(
                content_type__app_label=app_label, codename=codename,
            ))

        grant_role(user, role, mode=AuthorityMode.UNRESTRICTED)

        return type(user).objects.get(pk=user.pk)

    def close_period(self, period: AccountingPeriod, status=PeriodStatus.CLOSED):
        from apps.finance.services import AccountingPeriodService

        return AccountingPeriodService.change_status(
            period=period,
            status=status,
            reason="test",
        )
