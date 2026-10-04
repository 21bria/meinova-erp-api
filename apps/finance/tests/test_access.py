"""
Cakupan data, izin, dan isolasi tenant.

Tiga lapis yang sering tertukar, dan di sini ketiganya diuji terpisah:

* `ModelPermission`  → "boleh **mengubah** tabel ini?"
* `DataScopeService` → "**baris yang mana** yang boleh dilihat?"
* schema tenant      → "tenant lain sama sekali tidak ada."
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.urls import reverse

from django_tenants.test.cases import FastTenantTestCase
from django_tenants.utils import get_public_schema_name, schema_context

from rest_framework.test import APIClient

from apps.accounts.models import (
    AuthorityMode,
    AuthorityResourceType,
    Role,
    RoleAssignment,
    RoleAssignmentAuthority,
    User,
)
from apps.administration.models import Location
from apps.finance.models import Account, Journal
from apps.finance.services import (
    FinancePostingService,
    JournalService,
    LedgerFilters,
    TrialBalanceQueryService,
)

from .base import AS_OF, FinanceTestCase


class FinanceScopeTestCase(FinanceTestCase):
    def make_scoped_user(self, *, companies=(), locations=(), permissions=()):
        """
        Akun dengan satu penugasan bercakupan eksplisit.

        **Kewenangan dinyatakan saat penugasan dibuat**, bukan lewat
        `user.roles.add()` — yang terakhir tidak memberi akses data sama
        sekali, dan penugasan tanpa kewenangan berarti tidak melihat apa
        pun.
        """
        username = self.next_code("user")

        # Email unik: `auth_users_email_key` menolak dua akun ber-email
        # kosong, dan test FIN-B1/B2 membuat beberapa akun per test.
        user = User.objects.create_user(
            username=username, email=f"{username}@finance.test",
            password="x",
        )

        role = Role.objects.create(
            code=self.next_code("ROLE"), name="Finance test role",
        )

        if permissions:
            from django.contrib.auth.models import Permission

            for label in permissions:
                app_label, codename = label.split(".")

                role.permissions.add(
                    Permission.objects.get(
                        content_type__app_label=app_label,
                        codename=codename,
                    )
                )

        assignment = RoleAssignment.objects.create(
            user=user,
            role=role,
            authority_mode=AuthorityMode.EXPLICIT,
        )

        for company in companies:
            RoleAssignmentAuthority.objects.create(
                assignment=assignment,
                resource_type=AuthorityResourceType.COMPANY,
                resource_id=company.pk,
            )

        for location in locations:
            RoleAssignmentAuthority.objects.create(
                assignment=assignment,
                resource_type=AuthorityResourceType.LOCATION,
                resource_id=location.pk,
            )

        return user

    def api(self, user) -> APIClient:
        # Host tenant test, bukan `testserver`. `TenantMainMiddleware`
        # memetakan host yang tidak dikenal ke schema public dan
        # **membiarkan koneksinya di sana** sesudah request — seluruh
        # test sesudahnya di kelas yang sama lalu gagal dengan
        # "relation ... does not exist". Pola yang sama dengan test HR.
        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)
        client.force_authenticate(user=user)

        return client


class JournalScopeTests(FinanceScopeTestCase):
    def test_api_does_not_leak_another_companys_journals(self):
        mine = self.make_company()
        theirs = self.make_company()

        self.make_fiscal_year(mine)
        self.make_fiscal_year(theirs)

        a_expense, a_payable = self.make_pair(mine)
        b_expense, b_payable = self.make_pair(theirs)

        ours = self.make_journal(
            mine, lines=self.balanced_lines(a_expense, a_payable),
        )
        foreign = self.make_journal(
            theirs, lines=self.balanced_lines(b_expense, b_payable),
        )

        user = self.make_scoped_user(companies=[mine])

        # Rentangnya sengaja sebulan, bukan setahun.
        # `PeriodScopedListMixin` membatasi daftar transaksional ke 90
        # hari per permintaan dan membalas **400**, bukan daftar kosong
        # — jadi rentang setahun di sini menguji penolakan rentang,
        # bukan cakupan data.
        response = self.api(user).get("/api/finance/journals/", {
            "date_from": "2027-03-01",
            "date_to": "2027-03-31",
        })

        self.assertEqual(response.status_code, 200)

        numbers = {
            row["journal_number"]
            for row in response.json()["data"]
        }

        self.assertIn(ours.journal_number, numbers)
        self.assertNotIn(foreign.journal_number, numbers)

    def test_out_of_scope_journal_is_404_by_id(self):
        """
        Menyembunyikan dari daftar saja tidak cukup — nomor urutnya
        tinggal ditebak.
        """
        mine = self.make_company()
        theirs = self.make_company()

        self.make_fiscal_year(theirs)

        expense, payable = self.make_pair(theirs)

        foreign = self.make_journal(
            theirs, lines=self.balanced_lines(expense, payable),
        )

        user = self.make_scoped_user(companies=[mine])

        response = self.api(user).get(
            f"/api/finance/journals/{foreign.pk}/"
        )

        self.assertEqual(response.status_code, 404)

    def test_creating_a_journal_outside_scope_is_rejected(self):
        """
        `filter_queryset()` menjaga baca, ubah, dan hapus — **`create`
        tidak pernah melewatinya**.

        Lubang yang sama sudah dua kali ditemukan di modul HR; ini
        penutupnya untuk Finance.
        """
        mine = self.make_company()
        theirs = self.make_company()

        self.make_fiscal_year(theirs)

        journal = self.make_journal(theirs)

        user = self.make_scoped_user(companies=[mine])

        with self.assertRaises(ValidationError) as ctx:
            JournalService.assert_within_scope(journal=journal, user=user)

        self.assertIn("company", ctx.exception.message_dict)

    def test_in_scope_journal_passes_the_write_gate(self):
        mine = self.make_company()

        self.make_fiscal_year(mine)

        journal = self.make_journal(mine)

        user = self.make_scoped_user(companies=[mine])

        # Tidak melempar.
        JournalService.assert_within_scope(journal=journal, user=user)

    def test_site_scope_narrows_to_lines(self):
        """
        Cakupan site disaring lewat **baris**, bukan kepala dokumen:
        satu jurnal boleh membebankan tiga site sekaligus.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        mine = Location.objects.create(
            company=company, code=self.next_code("LOC"), name="My site",
        )
        theirs = Location.objects.create(
            company=company, code=self.next_code("LOC"), name="Other site",
        )

        expense, payable = self.make_pair(company)

        ours = self.make_journal(company, lines=[
            {
                "account": expense, "debit": Decimal("100.00"),
                "credit": Decimal("0.00"), "location": mine,
            },
            {
                "account": payable, "debit": Decimal("0.00"),
                "credit": Decimal("100.00"), "location": mine,
            },
        ])

        foreign = self.make_journal(company, lines=[
            {
                "account": expense, "debit": Decimal("100.00"),
                "credit": Decimal("0.00"), "location": theirs,
            },
            {
                "account": payable, "debit": Decimal("0.00"),
                "credit": Decimal("100.00"), "location": theirs,
            },
        ])

        user = self.make_scoped_user(companies=[company], locations=[mine])

        # Rentangnya sengaja sebulan, bukan setahun.
        # `PeriodScopedListMixin` membatasi daftar transaksional ke 90
        # hari per permintaan dan membalas **400**, bukan daftar kosong
        # — jadi rentang setahun di sini menguji penolakan rentang,
        # bukan cakupan data.
        response = self.api(user).get("/api/finance/journals/", {
            "date_from": "2027-03-01",
            "date_to": "2027-03-31",
        })

        numbers = {
            row["journal_number"]
            for row in response.json()["data"]
        }

        self.assertIn(ours.journal_number, numbers)
        self.assertNotIn(foreign.journal_number, numbers)


class AccountScopeTests(FinanceScopeTestCase):
    def test_account_lookup_is_scoped(self):
        """
        Dropdown adalah jalur bocor yang paling gampang terlewat: ia
        dipakai sebagai pilihan filter di laporan, jadi tanpa cakupan ia
        bisa **memperluas** apa yang terlihat.
        """
        mine = self.make_company()
        theirs = self.make_company()

        ours = self.make_account(mine, name="Our cash")
        foreign = self.make_account(theirs, name="Their cash")

        user = self.make_scoped_user(companies=[mine])

        response = self.api(user).get("/api/finance/lookup/accounts/")

        self.assertEqual(response.status_code, 200)

        payload = response.json()

        rows = payload.get("results", payload.get("data", payload))

        values = {row["value"] for row in rows}

        self.assertIn(ours.pk, values)
        self.assertNotIn(foreign.pk, values)

    def test_account_lookup_excludes_group_accounts(self):
        company = self.make_company()

        group = self.make_account(company, posting_allowed=False)
        posting = self.make_account(company, posting_allowed=True)

        user = self.make_scoped_user(companies=[company])

        response = self.api(user).get("/api/finance/lookup/accounts/")

        payload = response.json()
        rows = payload.get("results", payload.get("data", payload))

        values = {row["value"] for row in rows}

        self.assertIn(posting.pk, values)
        self.assertNotIn(group.pk, values)

    def test_api_does_not_leak_another_companys_accounts(self):
        mine = self.make_company()
        theirs = self.make_company()

        ours = self.make_account(mine, name="Our cash")
        foreign = self.make_account(theirs, name="Their cash")

        user = self.make_scoped_user(companies=[mine])

        response = self.api(user).get("/api/finance/accounts/")

        ids = {row["id"] for row in response.json()["data"]}

        self.assertIn(ours.pk, ids)
        self.assertNotIn(foreign.pk, ids)


class LedgerScopeTests(FinanceScopeTestCase):
    def test_trial_balance_requires_the_view_permission(self):
        company = self.make_company()

        user = self.make_scoped_user(companies=[company])

        response = self.api(user).get("/api/finance/reports/trial-balance/", {
            "company_id": company.pk,
            "date_from": "2027-03-01",
            "date_to": "2027-03-31",
        })

        self.assertEqual(response.status_code, 403)

    def test_trial_balance_is_row_filtered_for_a_scoped_reader(self):
        """
        Laporan `APIView` tidak lewat `BaseMasterViewSet.filter_queryset`,
        jadi cakupannya dipasang sendiri. Tanpa itu seluruh angka buku
        besar terbuka untuk siapa pun yang bisa membuka layarnya.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        mine = Location.objects.create(
            company=company, code=self.next_code("LOC"), name="Mine",
        )
        theirs = Location.objects.create(
            company=company, code=self.next_code("LOC"), name="Theirs",
        )

        expense, payable = self.make_pair(company)

        for site, amount in ((mine, "100.00"), (theirs, "900.00")):
            journal = self.make_journal(company, lines=[
                {
                    "account": expense, "debit": Decimal(amount),
                    "credit": Decimal("0.00"), "location": site,
                },
                {
                    "account": payable, "debit": Decimal("0.00"),
                    "credit": Decimal(amount), "location": site,
                },
            ])

            FinancePostingService.post(journal=journal)

        user = self.make_scoped_user(
            companies=[company],
            locations=[mine],
            permissions=["finance.view_journalline"],
        )

        response = self.api(user).get("/api/finance/reports/trial-balance/", {
            "company_id": company.pk,
            "date_from": "2027-01-01",
            "date_to": "2027-12-31",
        })

        self.assertEqual(response.status_code, 200)

        totals = response.json()["data"]["totals"]

        # Hanya site-nya sendiri. Kalau 1000 muncul di sini, cakupan
        # laporan tidak terpasang.
        self.assertEqual(Decimal(totals["debit"]), Decimal("100.00"))

    def test_superuser_sees_everything(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )
        FinancePostingService.post(journal=journal)

        admin = User.objects.create_superuser(
            username=self.next_code("admin"), password="x",
        )

        report = TrialBalanceQueryService.build(
            LedgerFilters(
                company_id=company.pk,
                date_from=date(2027, 1, 1),
                date_to=date(2027, 12, 31),
            ),
            user=admin,
        )

        self.assertEqual(report["totals"]["debit"], Decimal("1000.00"))


class TenantIsolationTests(FastTenantTestCase):
    """
    Satu tenant tidak bisa melihat data Finance tenant lain.

    Dijaga schema PostgreSQL, bukan kolom — tapi justru karena itu ia
    harus diuji: satu query yang lupa `schema_context()` akan membaca
    schema yang sedang aktif, dan itu gagal tanpa satu pun pesan.

    Tenant pembandingnya dibuat **di dalam test**, bukan lewat kelas
    dasar: yang diuji justru dua schema yang berdiri bersamaan, dan
    kelas dasar cuma menyediakan satu.
    """

    def test_finance_tables_are_empty_in_a_fresh_schema(self):
        from apps.tenants.models import Client, Domain

        # Tenant kedua, berdiri sendiri. Dibuat dari schema public —
        # django-tenants menolak membuat tenant dari schema tenant lain,
        # dan baris `Client`/`Domain` memang tinggal di public.
        with schema_context(get_public_schema_name()):
            other = Client(
                schema_name="finance_other", code="other", name="Other",
            )
            other.save()

            Domain.objects.create(
                domain="finance-other.localhost",
                tenant=other,
                is_primary=True,
            )

        try:
            with schema_context(other.schema_name):
                from apps.administration.models import Company, Currency
                from apps.administration.seeds.numbering import seed_numbering

                seed_numbering()

                Currency.objects.create(
                    code="IDR", name="Rupiah", symbol="Rp",
                    is_base_currency=True,
                )

                company = Company.objects.create(
                    code="OTHER", name="Other tenant company",
                )

                Account.objects.create(
                    company=company,
                    code="1000",
                    name="Other tenant cash",
                    account_type="asset",
                )

                self.assertEqual(Account.objects.count(), 1)
                self.assertEqual(Journal.objects.count(), 0)

            # Kembali ke schema test: baris tenant lain tidak ada.
            self.assertFalse(
                Account.objects.filter(name="Other tenant cash").exists()
            )
        finally:
            # Test ini berjalan di dalam transaksi `TestCase`, dan baris
            # yang barusan ditulis masih punya pemeriksaan FK tertunda —
            # `DROP SCHEMA` menolaknya dengan "pending trigger events".
            # Dijalankan sekarang, baru schema-nya dibuang.
            from django.db import connection

            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

            with schema_context(get_public_schema_name()):
                other.delete(force_drop=True)
