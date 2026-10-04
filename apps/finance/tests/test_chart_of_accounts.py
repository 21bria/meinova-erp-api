"""Bagan akun: hierarki, keunikan, dan pagar akun grup."""

from django.core.exceptions import ValidationError

from apps.finance.models import Account, AccountType, NormalBalance
from apps.finance.services import AccountService

from .base import FinanceTestCase


class ChartOfAccountsTests(FinanceTestCase):
    def test_hierarchy_path_and_level_are_materialised(self):
        company = self.make_company()

        root = self.make_account(
            company, name="Assets",
            account_type=AccountType.ASSET, posting_allowed=False,
        )
        mid = self.make_account(
            company, name="Current Assets", parent=root,
            account_type=AccountType.ASSET, posting_allowed=False,
        )
        leaf = self.make_account(
            company, name="Cash", parent=mid,
            account_type=AccountType.ASSET,
        )

        root.refresh_from_db()
        mid.refresh_from_db()
        leaf.refresh_from_db()

        self.assertEqual(root.level, 0)
        self.assertEqual(mid.level, 1)
        self.assertEqual(leaf.level, 2)

        self.assertEqual(leaf.path, f"/{root.pk}/{mid.pk}/{leaf.pk}/")

        # Jalur itulah yang membuat "seluruh akun di bawah X" jadi satu
        # `LIKE` berprefiks alih-alih rekursi per tingkat.
        subtree = Account.objects.filter(path__startswith=root.path)

        self.assertEqual(subtree.count(), 3)

    def test_moving_a_branch_rewrites_descendant_paths(self):
        """
        Memindahkan induk harus ikut menulis ulang jalur keturunannya.

        Kalau tidak, laporan "seluruh beban di bawah X" diam-diam
        kehilangan cabang yang baru saja dipindah — dan yang hilang
        justru cabang yang barusan disentuh orang.
        """
        company = self.make_company()

        first = self.make_account(
            company, name="Group A",
            account_type=AccountType.EXPENSE, posting_allowed=False,
        )
        second = self.make_account(
            company, name="Group B",
            account_type=AccountType.EXPENSE, posting_allowed=False,
        )
        moving = self.make_account(
            company, name="Sub", parent=first,
            account_type=AccountType.EXPENSE, posting_allowed=False,
        )
        leaf = self.make_account(
            company, name="Leaf", parent=moving,
            account_type=AccountType.EXPENSE,
        )

        AccountService.update(instance=moving, data={"parent": second})

        moving.refresh_from_db()
        leaf.refresh_from_db()
        second.refresh_from_db()

        self.assertTrue(moving.path.startswith(second.path))
        self.assertTrue(leaf.path.startswith(second.path))
        self.assertEqual(leaf.level, 2)

    def test_account_code_is_unique_per_company_only(self):
        first = self.make_company()
        second = self.make_company()

        self.make_account(first, code="1000", name="Cash")

        # Perusahaan lain boleh memakai kode yang sama — bagan akun
        # berdiri sendiri per badan usaha.
        self.make_account(second, code="1000", name="Kas")

        with self.assertRaises(ValidationError):
            self.make_account(first, code="1000", name="Duplicate")

    def test_deleted_code_can_be_reused(self):
        """
        Keunikan dikondisikan ke `is_deleted`.

        Tanpa itu, satu kode yang salah ketik lalu dihapus terkunci
        selamanya oleh baris yang sudah tidak terlihat siapa pun.
        """
        company = self.make_company()

        first = self.make_account(company, code="9999", name="Typo")

        AccountService.soft_delete(instance=first)

        reused = self.make_account(company, code="9999", name="Correct")

        self.assertNotEqual(reused.pk, first.pk)

    def test_group_account_cannot_receive_a_journal_line(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        group = self.make_account(
            company, name="Expenses", posting_allowed=False,
        )
        payable = self.make_account(
            company, name="Payable", account_type=AccountType.LIABILITY,
        )

        journal = self.make_journal(company)

        with self.assertRaises(ValidationError) as ctx:
            from apps.finance.services import JournalService

            JournalService.replace_lines(
                journal=journal,
                lines=self.balanced_lines(group, payable),
            )

        self.assertIn("account", ctx.exception.message_dict)

    def test_inactive_account_is_rejected(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        expense.is_active = False
        expense.save(update_fields=["is_active"])

        journal = self.make_journal(company)

        with self.assertRaises(ValidationError):
            from apps.finance.services import JournalService

            JournalService.replace_lines(
                journal=journal,
                lines=self.balanced_lines(expense, payable),
            )

    def test_parent_must_be_a_group_account(self):
        company = self.make_company()

        posting = self.make_account(company, name="Cash", posting_allowed=True)

        with self.assertRaises(ValidationError) as ctx:
            self.make_account(company, name="Child", parent=posting)

        self.assertIn("parent", ctx.exception.message_dict)

    def test_circular_parent_is_prevented(self):
        company = self.make_company()

        top = self.make_account(company, name="Top", posting_allowed=False)
        middle = self.make_account(
            company, name="Middle", parent=top, posting_allowed=False,
        )

        # Menjadikan induknya sebagai anak dari keturunannya sendiri.
        with self.assertRaises(ValidationError) as ctx:
            AccountService.update(instance=top, data={"parent": middle})

        self.assertIn("parent", ctx.exception.message_dict)

    def test_account_cannot_be_its_own_parent(self):
        company = self.make_company()

        account = self.make_account(company, posting_allowed=False)

        with self.assertRaises(ValidationError):
            AccountService.update(instance=account, data={"parent": account})

    def test_parent_from_another_company_is_rejected(self):
        first = self.make_company()
        second = self.make_company()

        parent = self.make_account(first, posting_allowed=False)

        with self.assertRaises(ValidationError) as ctx:
            self.make_account(second, parent=parent)

        self.assertIn("parent", ctx.exception.message_dict)

    def test_child_must_share_the_parent_account_type(self):
        company = self.make_company()

        parent = self.make_account(
            company, account_type=AccountType.ASSET, posting_allowed=False,
        )

        with self.assertRaises(ValidationError) as ctx:
            self.make_account(
                company, parent=parent, account_type=AccountType.EXPENSE,
            )

        self.assertIn("parent", ctx.exception.message_dict)

    def test_category_must_match_the_account_type(self):
        company = self.make_company()

        with self.assertRaises(ValidationError) as ctx:
            AccountService.create(data={
                "company": company,
                "code": self.next_code("A"),
                "name": "Wrong category",
                "account_type": AccountType.REVENUE,
                "account_category": "fixed_asset",
            })

        self.assertIn("account_category", ctx.exception.message_dict)

    def test_normal_balance_falls_back_to_the_account_type(self):
        company = self.make_company()

        asset = self.make_account(company, account_type=AccountType.ASSET)
        revenue = self.make_account(company, account_type=AccountType.REVENUE)

        self.assertEqual(asset.effective_normal_balance, NormalBalance.DEBIT)
        self.assertEqual(revenue.effective_normal_balance, NormalBalance.CREDIT)

        # Akun kontra tetap boleh menyatakan saldo terbaliknya sendiri.
        contra = self.make_account(
            company,
            account_type=AccountType.ASSET,
        )
        AccountService.update(
            instance=contra, data={"normal_balance": NormalBalance.CREDIT},
        )
        contra.refresh_from_db()

        self.assertEqual(contra.effective_normal_balance, NormalBalance.CREDIT)

    def test_account_with_children_cannot_be_deleted(self):
        company = self.make_company()

        parent = self.make_account(company, posting_allowed=False)
        self.make_account(company, parent=parent)

        with self.assertRaises(ValidationError):
            AccountService.soft_delete(instance=parent)

    def test_account_used_by_a_journal_cannot_be_deleted(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        with self.assertRaises(ValidationError) as ctx:
            AccountService.soft_delete(instance=expense)

        self.assertIn("account", ctx.exception.message_dict)

    def test_tree_is_built_from_a_single_query_result(self):
        company = self.make_company()

        root = self.make_account(
            company, code="1000", name="Assets",
            account_type=AccountType.ASSET, posting_allowed=False,
        )
        self.make_account(
            company, code="1100", name="Cash", parent=root,
            account_type=AccountType.ASSET,
        )

        tree = AccountService.tree(
            AccountService.list().filter(company=company)
        )

        self.assertEqual(len(tree), 1)
        self.assertEqual(tree[0]["code"], "1000")
        self.assertEqual(len(tree[0]["children"]), 1)
        self.assertEqual(tree[0]["children"][0]["code"], "1100")
        self.assertFalse(tree[0]["posting_allowed"])
        self.assertTrue(tree[0]["children"][0]["posting_allowed"])

    def test_rebuild_tree_restores_paths(self):
        company = self.make_company()

        root = self.make_account(company, posting_allowed=False)
        leaf = self.make_account(company, parent=root)

        # Merusaknya seperti yang dilakukan impor massal yang menulis
        # langsung ke model.
        Account.objects.filter(pk__in=[root.pk, leaf.pk]).update(
            path="", level=0,
        )

        AccountService.rebuild_tree(company_id=company.pk)

        root.refresh_from_db()
        leaf.refresh_from_db()

        self.assertEqual(root.path, f"/{root.pk}/")
        self.assertEqual(leaf.path, f"/{root.pk}/{leaf.pk}/")
        self.assertEqual(leaf.level, 1)
