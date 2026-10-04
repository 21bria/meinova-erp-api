"""
FIN-B1/B2 — wewenang aksi jurnal dan kalender akuntansi.

Celah yang ditutup: `submit/`, `withdraw/`, `cancel/`, `post/`,
`post-all/`, `reverse/` (dan `change-status/`, `generate-periods/`)
adalah `@action` kustom yang tidak dijaga `ModelPermission`, jadi
penjagaannya cuma "sudah login + cakupan company". Akun tanpa penugasan
— yang oleh `DataScopeService` dianggap *tak tersaring* — justru yang
paling bebas.

Invariant yang diuji di sini, per aksi:

* **izin eksplisit** untuk aksinya, dan
* **cakupan baris** dihitung dari izin itu,

dan tidak satu pun menggantikan yang lain. Status alur persetujuan
diuji **terpisah** dari wewenang: yang berwenang tetap tidak bisa
memposting DRAFT yang wajib disetujui.

Penolakan boleh 401/403/404 tergantung lapis mana yang lebih dulu. Yang
tidak boleh terjadi, dan yang diperiksa `assert_untouched`: status
berubah, kolom submitted/approved/posted/cancelled terisi, baris buku
besar tertandai, atau jurnal pembalik lahir.
"""

from datetime import date

from django.core.exceptions import ValidationError
from django.test import RequestFactory

from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import AuthorityMode, Role, User
from apps.accounts.services.role_assignment import grant_role
from apps.finance.api.permissions import FinanceActionPermission
from apps.finance.models import (
    AccountingPeriod,
    FiscalYear,
    Journal,
    JournalLine,
    JournalStatus,
    PeriodStatus,
)
from apps.finance.services import (
    ADD_PERIOD_PERMISSION,
    CHANGE_JOURNAL_PERMISSION,
    CHANGE_PERIOD_PERMISSION,
    POST_JOURNAL_PERMISSION,
    REVERSE_JOURNAL_PERMISSION,
    AccountingPeriodService,
    FinancePostingService,
    FinanceReversalService,
    FiscalYearService,
    JournalService,
)

from .test_access import FinanceScopeTestCase


DENIED = {401, 403, 404}

PAYROLL_PERMISSIONS = (
    "payroll.view_payrollrun",
    "payroll.change_payrollrun",
)

STAMPS = (
    "submitted_at", "submitted_by_id",
    "approved_at", "approved_by_id",
    "posted_at", "posted_by_id",
    "cancelled_at", "cancelled_by_id",
    "reversed_at", "reversed_by_id",
)


class JournalAuthorizationTestCase(FinanceScopeTestCase):

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    def stage(self, *, status=JournalStatus.DRAFT):
        company = self.make_company()
        self.make_fiscal_year(company)
        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        if status == JournalStatus.POSTED:
            FinancePostingService.post(journal=journal)
        elif status != JournalStatus.DRAFT:
            Journal.objects.filter(pk=journal.pk).update(status=status)

        journal.refresh_from_db()

        return company, journal

    def bare_user(self):
        """Akun tanpa penugasan apa pun — cakupannya *tak tersaring*."""
        username = self.next_code("bare")

        return User.objects.create_user(
            username=username, email=f"{username}@finance.test",
            password="x",
        )

    def unrestricted_user(self, permissions=PAYROLL_PERMISSIONS):
        """Penugasan bercakupan se-tenant, tanpa izin Finance."""
        from django.contrib.auth.models import Permission

        username = self.next_code("wide")

        user = User.objects.create_user(
            username=username, email=f"{username}@finance.test",
            password="x",
        )
        role = Role.objects.create(
            code=self.next_code("WIDE"), name="Wide role",
        )

        for label in permissions:
            app_label, codename = label.split(".")
            role.permissions.add(Permission.objects.get(
                content_type__app_label=app_label, codename=codename,
            ))

        grant_role(user, role, mode=AuthorityMode.UNRESTRICTED)

        return user

    def holder(self, company, *permissions):
        return self.make_scoped_user(
            companies=[company],
            permissions=[*permissions, "finance.view_journal"],
        )

    def make_definition(self, company):
        from apps.workflow.models import (
            ApproverScope,
            ApproverType,
            WorkflowDefinition,
            WorkflowStatus,
            WorkflowStep,
        )

        role, _ = Role.objects.get_or_create(
            code="FINANCE-MANAGER",
            is_deleted=False,
            defaults={"name": "Finance Manager"},
        )

        definition = WorkflowDefinition.objects.create(
            code=self.next_code("FIN-JOURNAL-"),
            name="Journal — Standar",
            module="finance",
            document_type="journal",
            company=company,
            status=WorkflowStatus.ACTIVE,
        )

        WorkflowStep.objects.create(
            definition=definition,
            sequence=1,
            name="Approved By (Finance Manager)",
            approver_type=ApproverType.ROLE,
            approver_role=role,
            approver_scope=ApproverScope.COMPANY,
        )

        return definition

    def make_approver(self, company):
        """Pemegang meja FINANCE-MANAGER di company itu."""
        from apps.hr.models import Employee, OrganizationAssignment

        code = self.next_code("apr")

        user = User.objects.create_user(
            username=code.lower(), email=f"{code.lower()}@finance.test",
            password="x",
        )

        role = Role.objects.get(code="FINANCE-MANAGER", is_deleted=False)
        grant_role(user, role, mode=AuthorityMode.PLACEMENT, level="company")

        employee = Employee.objects.create(
            employee_number=f"FIN-{code}", first_name="Finance",
            last_name=code, user=user,
        )
        OrganizationAssignment.objects.create(
            employee=employee, company=company,
            organization_effective_date=date(2020, 1, 1),
        )

        return user

    def call(self, user, journal, verb, data=None):
        client = self.api(user) if user is not None else self.anonymous()

        return client.post(
            f"/api/finance/journals/{journal.pk}/{verb}/",
            data or {},
            format="json",
        )

    def anonymous(self):
        from rest_framework.test import APIClient

        return APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

    def snapshot(self, journal):
        journal.refresh_from_db()

        return (
            journal.status,
            tuple(getattr(journal, field) for field in STAMPS),
        )

    def assert_untouched(self, journal, before):
        """Penolakan yang benar tidak meninggalkan jejak apa pun."""
        self.assertEqual(self.snapshot(journal), before)

        if before[0] != JournalStatus.POSTED:
            self.assertFalse(
                JournalLine.objects.filter(
                    journal=journal, is_posted=True,
                ).exists(),
            )

        self.assertFalse(Journal.objects.filter(reversal_of=journal).exists())


# ======================================================================
# post/ — tindakan paling berisiko
# ======================================================================


class PostAuthorizationTests(JournalAuthorizationTestCase):

    def assert_post_denied(self, user, journal, *, service_too=True):
        before = self.snapshot(journal)

        response = self.call(user, journal, "post")

        self.assertIn(response.status_code, DENIED, response.content)
        self.assert_untouched(journal, before)

        if service_too and user is not None:
            with self.assertRaises(PermissionDenied):
                FinancePostingService.post(journal=journal, user=user)

            self.assert_untouched(journal, before)

    # ---------------------------------------------------------- ditolak

    def test_anonymous_cannot_post(self):
        _, journal = self.stage()

        self.assert_post_denied(None, journal)

    def test_account_without_any_role_cannot_post(self):
        """#1 — tanpa penugasan = cakupan tak tersaring, tetap ditolak."""
        _, journal = self.stage()

        self.assert_post_denied(self.bare_user(), journal)

    def test_unrestricted_scope_without_finance_permission_cannot_post(self):
        """#3 — cakupan se-tenant bukan izin membukukan."""
        _, journal = self.stage()

        self.assert_post_denied(self.unrestricted_user(), journal)

    def test_payroll_permission_cannot_post(self):
        company, journal = self.stage()

        user = self.make_scoped_user(
            companies=[company], permissions=PAYROLL_PERMISSIONS,
        )

        self.assert_post_denied(user, journal)

    def test_edit_permission_is_not_post_permission(self):
        """`change_journal` menyunting draf, tidak membukukannya."""
        company, journal = self.stage()

        self.assert_post_denied(
            self.holder(company, CHANGE_JOURNAL_PERMISSION), journal,
        )

    def test_post_permission_outside_company_scope_cannot_post(self):
        """#4 — izin tanpa cakupan perusahaan jurnalnya."""
        _, journal = self.stage()
        elsewhere = self.make_company()

        self.assert_post_denied(
            self.holder(elsewhere, POST_JOURNAL_PERMISSION), journal,
        )

    def test_scope_from_another_role_does_not_lend_itself(self):
        """
        Izin posting dari role bercakupan company lain + cakupan company
        jurnal dari role tanpa izin posting = ditolak. Cakupan dihitung
        dari role yang **memberi izin itu**, bukan gabungan.
        """
        company, journal = self.stage()
        elsewhere = self.make_company()

        user = self.holder(elsewhere, POST_JOURNAL_PERMISSION)

        from apps.accounts.models import (
            AuthorityResourceType,
            RoleAssignment,
            RoleAssignmentAuthority,
        )

        reader = Role.objects.create(
            code=self.next_code("READ"), name="Reader",
        )
        assignment = RoleAssignment.objects.create(
            user=user, role=reader, authority_mode=AuthorityMode.EXPLICIT,
        )
        RoleAssignmentAuthority.objects.create(
            assignment=assignment,
            resource_type=AuthorityResourceType.COMPANY,
            resource_id=company.pk,
        )

        self.assert_post_denied(user, journal)

    def test_unauthorized_request_on_posted_journal_learns_nothing(self):
        """Tanpa izin tidak ada jawaban "sudah diposting" yang 200."""
        _, journal = self.stage(status=JournalStatus.POSTED)

        self.assert_post_denied(self.bare_user(), journal)

    # ------------------------------------------------ alur persetujuan

    def test_authorized_poster_cannot_skip_required_approval(self):
        """#5 — wewenang + cakupan tetap tidak melompati FIN-JOURNAL-STD."""
        company, journal = self.stage()
        self.make_definition(company)

        user = self.holder(company, POST_JOURNAL_PERMISSION)
        before = self.snapshot(journal)

        response = self.call(user, journal, "post")

        self.assertEqual(response.status_code, 400, response.content)
        self.assert_untouched(journal, before)

        with self.assertRaises(ValidationError) as caught:
            FinancePostingService.post(journal=journal, user=user)

        self.assertIn("status", caught.exception.message_dict)
        self.assert_untouched(journal, before)

    def test_internal_caller_cannot_skip_required_approval_either(self):
        """`user=None` melewati wewenang, **tidak** melewati alur."""
        company, journal = self.stage()
        self.make_definition(company)
        before = self.snapshot(journal)

        with self.assertRaises(ValidationError):
            FinancePostingService.post(journal=journal)

        self.assert_untouched(journal, before)

    def test_rejected_journal_cannot_be_posted(self):
        company, journal = self.stage(status=JournalStatus.REJECTED)

        user = self.holder(company, POST_JOURNAL_PERMISSION)
        before = self.snapshot(journal)

        with self.assertRaises(ValidationError):
            FinancePostingService.post(journal=journal, user=user)

        self.assert_untouched(journal, before)

    def test_submitted_journal_cannot_be_posted(self):
        company, journal = self.stage(status=JournalStatus.SUBMITTED)

        user = self.holder(company, POST_JOURNAL_PERMISSION)
        before = self.snapshot(journal)

        response = self.call(user, journal, "post")

        self.assertEqual(response.status_code, 400, response.content)
        self.assert_untouched(journal, before)

    # ------------------------------------------------------- diizinkan

    def test_authorized_poster_posts_an_approved_journal(self):
        """#6 — izin + cakupan + status yang benar."""
        company, journal = self.stage(status=JournalStatus.APPROVED)
        self.make_definition(company)

        user = self.holder(company, POST_JOURNAL_PERMISSION)

        response = self.call(user, journal, "post")

        self.assertEqual(response.status_code, 200, response.content)

        journal.refresh_from_db()

        self.assertEqual(journal.status, JournalStatus.POSTED)
        self.assertEqual(journal.posted_by, user)
        self.assertEqual(
            JournalLine.objects.filter(journal=journal, is_posted=False).count(),
            0,
        )

    def test_draft_without_workflow_is_postable_by_an_authorized_poster(self):
        """Tenant tanpa alur persetujuan jurnal: DRAFT langsung boleh."""
        company, journal = self.stage()

        user = self.holder(company, POST_JOURNAL_PERMISSION)

        result = FinancePostingService.post(journal=journal, user=user)

        self.assertEqual(result.journal.status, JournalStatus.POSTED)

    # --------------------------------------------------------- post-all

    def test_post_all_without_permission_touches_nothing(self):
        company, journal = self.stage()

        user = self.holder(company, CHANGE_JOURNAL_PERMISSION)
        before = self.snapshot(journal)

        response = self.api(user).post(
            "/api/finance/journals/post-all/",
            {"ids": [journal.pk]},
            format="json",
        )

        self.assertIn(response.status_code, DENIED, response.content)
        self.assert_untouched(journal, before)

        with self.assertRaises(PermissionDenied):
            FinancePostingService.post_many(journals=[journal], user=user)

        self.assert_untouched(journal, before)

    def test_post_all_posts_only_the_journals_in_scope(self):
        company, mine = self.stage()
        _, theirs = self.stage()

        user = self.holder(company, POST_JOURNAL_PERMISSION)
        before = self.snapshot(theirs)

        result = FinancePostingService.post_many(
            journals=[mine, theirs], user=user,
        )

        self.assertEqual(result["posted"], 1)
        self.assertEqual(len(result["failed"]), 1)

        mine.refresh_from_db()

        self.assertEqual(mine.status, JournalStatus.POSTED)
        self.assert_untouched(theirs, before)


# ======================================================================
# submit/ · withdraw/ · cancel/
# ======================================================================


class DraftLifecycleAuthorizationTests(JournalAuthorizationTestCase):

    def unauthorized_users(self, company):
        elsewhere = self.make_company()

        return {
            "no role": self.bare_user(),
            "unrestricted, no finance permission": self.unrestricted_user(),
            "payroll permission": self.make_scoped_user(
                companies=[company], permissions=PAYROLL_PERMISSIONS,
            ),
            "post permission only": self.holder(
                company, POST_JOURNAL_PERMISSION,
            ),
            "change permission, wrong company": self.holder(
                elsewhere, CHANGE_JOURNAL_PERMISSION,
            ),
        }

    def assert_denied_for_everyone(self, journal, company, verb, service):
        before = self.snapshot(journal)

        response = self.call(None, journal, verb, {"reason": "x"})
        self.assertIn(response.status_code, DENIED)

        for label, user in self.unauthorized_users(company).items():
            with self.subTest(user=label):
                response = self.call(user, journal, verb, {"reason": "x"})

                self.assertIn(response.status_code, DENIED, response.content)
                self.assert_untouched(journal, before)

                with self.assertRaises(PermissionDenied):
                    service(journal, user)

                self.assert_untouched(journal, before)

    # ----------------------------------------------------------- submit

    def test_submit_requires_change_permission_and_scope(self):
        company, journal = self.stage()
        self.make_definition(company)

        self.assert_denied_for_everyone(
            journal, company, "submit",
            lambda j, u: JournalService.submit(journal=j, user=u),
        )

    def test_authorized_submit_enters_the_workflow(self):
        company, journal = self.stage()
        self.make_definition(company)
        self.make_approver(company)

        user = self.holder(company, CHANGE_JOURNAL_PERMISSION)

        response = self.call(user, journal, "submit")

        self.assertEqual(response.status_code, 200, response.content)

        journal.refresh_from_db()

        self.assertEqual(journal.status, JournalStatus.SUBMITTED)
        self.assertEqual(journal.submitted_by, user)
        self.assertIsNone(journal.approved_by_id)
        self.assertIsNone(journal.posted_by_id)

    def test_submitting_a_posted_journal_is_a_state_error(self):
        company, journal = self.stage(status=JournalStatus.POSTED)

        user = self.holder(company, CHANGE_JOURNAL_PERMISSION)
        before = self.snapshot(journal)

        with self.assertRaises(ValidationError):
            JournalService.submit(journal=journal, user=user)

        self.assert_untouched(journal, before)

    # --------------------------------------------------------- withdraw

    def submitted(self):
        company, journal = self.stage()
        self.make_definition(company)
        self.make_approver(company)

        JournalService.submit(
            journal=journal,
            user=self.holder(company, CHANGE_JOURNAL_PERMISSION),
        )
        journal.refresh_from_db()

        self.assertEqual(journal.status, JournalStatus.SUBMITTED)

        return company, journal

    def test_withdraw_requires_change_permission_and_scope(self):
        company, journal = self.submitted()

        self.assert_denied_for_everyone(
            journal, company, "withdraw",
            lambda j, u: JournalService.withdraw(journal=j, user=u),
        )

    def test_authorized_withdraw_returns_to_draft(self):
        company, journal = self.submitted()

        user = self.holder(company, CHANGE_JOURNAL_PERMISSION)

        response = self.call(user, journal, "withdraw")

        self.assertEqual(response.status_code, 200, response.content)

        journal.refresh_from_db()

        self.assertEqual(journal.status, JournalStatus.DRAFT)

    def test_withdrawing_a_draft_is_a_state_error(self):
        company, journal = self.stage()

        user = self.holder(company, CHANGE_JOURNAL_PERMISSION)

        with self.assertRaises(ValidationError):
            JournalService.withdraw(journal=journal, user=user)

    # ----------------------------------------------------------- cancel

    def test_cancel_requires_change_permission_and_scope(self):
        company, journal = self.stage()

        self.assert_denied_for_everyone(
            journal, company, "cancel",
            lambda j, u: JournalService.cancel(journal=j, user=u, reason="x"),
        )

    def test_authorized_cancel_of_a_draft(self):
        company, journal = self.stage()

        user = self.holder(company, CHANGE_JOURNAL_PERMISSION)

        response = self.call(user, journal, "cancel", {"reason": "salah"})

        self.assertEqual(response.status_code, 200, response.content)

        journal.refresh_from_db()

        self.assertEqual(journal.status, JournalStatus.CANCELLED)
        self.assertEqual(journal.cancelled_by, user)

    def test_submitted_journal_must_be_withdrawn_before_cancel(self):
        """
        Membatalkan yang masih menunggu persetujuan meninggalkan instance
        alur PENDING — dan persetujuan sesudahnya akan menghidupkan
        jurnal yang sudah batal kembali ke APPROVED.
        """
        company, journal = self.submitted()

        user = self.holder(company, CHANGE_JOURNAL_PERMISSION)
        before = self.snapshot(journal)

        with self.assertRaises(ValidationError):
            JournalService.cancel(journal=journal, user=user, reason="x")

        self.assert_untouched(journal, before)

    def test_posted_journal_cannot_be_cancelled(self):
        company, journal = self.stage(status=JournalStatus.POSTED)

        user = self.holder(company, CHANGE_JOURNAL_PERMISSION)
        before = self.snapshot(journal)

        with self.assertRaises(ValidationError):
            JournalService.cancel(journal=journal, user=user, reason="x")

        self.assert_untouched(journal, before)


# ======================================================================
# approve — lewat kotak masuk alur, bukan endpoint jurnal
# ======================================================================


class ApprovalAuthorityTests(JournalAuthorizationTestCase):

    def test_finance_permissions_do_not_make_someone_the_approver(self):
        """
        Setuju/tolak dijaga `WorkflowApprovalService.check_right`: hanya
        approver meja itu, penerima kuasanya, atau superuser. Memegang
        seluruh izin jurnal tidak menjadikan seseorang approver.
        """
        from apps.workflow.services.workflow_service import WorkflowService

        company, journal = self.stage()
        self.make_definition(company)
        self.make_approver(company)

        instance = JournalService.submit(
            journal=journal,
            user=self.holder(company, CHANGE_JOURNAL_PERMISSION),
        )
        journal.refresh_from_db()
        before = self.snapshot(journal)

        outsider = self.holder(
            company,
            CHANGE_JOURNAL_PERMISSION,
            POST_JOURNAL_PERMISSION,
            REVERSE_JOURNAL_PERMISSION,
        )

        with self.assertRaises(ValidationError):
            WorkflowService.approve(instance=instance, user=outsider)

        self.assert_untouched(journal, before)

    def test_the_designated_approver_approves_and_a_poster_posts(self):
        from apps.workflow.registry import completion_handler
        from apps.workflow.services.workflow_service import WorkflowService

        company, journal = self.stage()
        self.make_definition(company)
        approver = self.make_approver(company)

        instance = JournalService.submit(
            journal=journal,
            user=self.holder(company, CHANGE_JOURNAL_PERMISSION),
        )

        WorkflowService.approve(
            instance=instance,
            user=approver,
            on_complete=completion_handler(
                module="finance", document_type="journal",
            ),
        )

        journal.refresh_from_db()

        self.assertEqual(journal.status, JournalStatus.APPROVED)
        self.assertEqual(journal.approved_by, approver)
        self.assertIsNone(journal.posted_by_id)

        poster = self.holder(company, POST_JOURNAL_PERMISSION)

        result = FinancePostingService.post(journal=journal, user=poster)

        self.assertEqual(result.journal.status, JournalStatus.POSTED)
        self.assertEqual(result.journal.posted_by, poster)


# ======================================================================
# reverse/
# ======================================================================


class ReverseAuthorizationTests(JournalAuthorizationTestCase):

    def test_reverse_is_denied_without_reverse_permission_and_scope(self):
        """#11 — pembalikan setara dijaga."""
        company, journal = self.stage(status=JournalStatus.POSTED)
        elsewhere = self.make_company()

        before = self.snapshot(journal)

        users = {
            "no role": self.bare_user(),
            "unrestricted, no finance permission": self.unrestricted_user(),
            "payroll permission": self.make_scoped_user(
                companies=[company], permissions=PAYROLL_PERMISSIONS,
            ),
            "post permission only": self.holder(
                company, POST_JOURNAL_PERMISSION,
            ),
            "reverse permission, wrong company": self.holder(
                elsewhere, REVERSE_JOURNAL_PERMISSION,
            ),
        }

        response = self.call(None, journal, "reverse", {"reason": "x"})
        self.assertIn(response.status_code, DENIED)

        for label, user in users.items():
            with self.subTest(user=label):
                response = self.call(user, journal, "reverse", {"reason": "x"})

                self.assertIn(response.status_code, DENIED, response.content)
                self.assert_untouched(journal, before)

                with self.assertRaises(PermissionDenied):
                    FinanceReversalService.reverse(
                        journal=journal, user=user, reason="x",
                    )

                self.assert_untouched(journal, before)

    def test_authorized_reverse_posts_the_reversal(self):
        """
        Pembalik terbit dan terposting walau alur persetujuan ada — jalan
        tepercaya `REVERSAL`, karena wewenangnya barusan ditagih.
        """
        company, journal = self.stage(status=JournalStatus.POSTED)
        self.make_definition(company)

        user = self.holder(company, REVERSE_JOURNAL_PERMISSION)

        response = self.call(user, journal, "reverse", {"reason": "koreksi"})

        self.assertEqual(response.status_code, 200, response.content)

        journal.refresh_from_db()

        self.assertEqual(journal.status, JournalStatus.REVERSED)
        self.assertEqual(journal.reversed_by.status, JournalStatus.POSTED)
        self.assertEqual(journal.reversed_by_user, user)

    def test_reversing_a_draft_is_a_state_error(self):
        company, journal = self.stage()

        user = self.holder(company, REVERSE_JOURNAL_PERMISSION)

        with self.assertRaises(ValidationError):
            FinanceReversalService.reverse(
                journal=journal, user=user, reason="x",
            )

        self.assertFalse(Journal.objects.filter(reversal_of=journal).exists())


# ======================================================================
# Kalender akuntansi — change-status/ · generate-periods/
# ======================================================================


class CalendarAuthorizationTests(JournalAuthorizationTestCase):

    def test_period_status_change_requires_permission_and_scope(self):
        company = self.make_company()
        self.make_fiscal_year(company)
        elsewhere = self.make_company()

        period = self.period_for(company, date(2027, 3, 15))

        users = {
            "no role": self.bare_user(),
            "unrestricted, no finance permission": self.unrestricted_user(),
            "journal permissions": self.holder(
                company, CHANGE_JOURNAL_PERMISSION, POST_JOURNAL_PERMISSION,
            ),
            "period permission, wrong company": self.make_scoped_user(
                companies=[elsewhere], permissions=[CHANGE_PERIOD_PERMISSION],
            ),
        }

        for label, user in users.items():
            with self.subTest(user=label):
                response = self.api(user).post(
                    f"/api/finance/accounting-periods/{period.pk}/change-status/",
                    {"status": PeriodStatus.SOFT_CLOSED},
                    format="json",
                )

                self.assertIn(response.status_code, DENIED, response.content)

                with self.assertRaises(PermissionDenied):
                    AccountingPeriodService.change_status(
                        period=period,
                        status=PeriodStatus.SOFT_CLOSED,
                        user=user,
                    )

                period.refresh_from_db()
                self.assertEqual(period.status, PeriodStatus.OPEN)
                self.assertIsNone(period.closed_by_id)

        closer = self.make_scoped_user(
            companies=[company],
            permissions=[
                CHANGE_PERIOD_PERMISSION, "finance.view_accountingperiod",
            ],
        )

        response = self.api(closer).post(
            f"/api/finance/accounting-periods/{period.pk}/change-status/",
            {"status": PeriodStatus.SOFT_CLOSED},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)

        period.refresh_from_db()
        self.assertEqual(period.status, PeriodStatus.SOFT_CLOSED)

    def test_generate_periods_requires_permission_and_scope(self):
        company = self.make_company()
        elsewhere = self.make_company()

        year = FiscalYear.objects.create(
            company=company,
            code=self.next_code("FY"),
            name="FY 2031",
            start_date=date(2031, 1, 1),
            end_date=date(2031, 12, 31),
        )

        for user in (
            self.bare_user(),
            self.unrestricted_user(),
            self.make_scoped_user(
                companies=[elsewhere], permissions=[ADD_PERIOD_PERMISSION],
            ),
        ):
            response = self.api(user).post(
                f"/api/finance/fiscal-years/{year.pk}/generate-periods/",
                {"count": 12},
                format="json",
            )

            self.assertIn(response.status_code, DENIED, response.content)

            with self.assertRaises(PermissionDenied):
                FiscalYearService.generate_periods(
                    fiscal_year=year, count=12, user=user,
                )

        self.assertFalse(AccountingPeriod.objects.filter(fiscal_year=year).exists())

        maker = self.make_scoped_user(
            companies=[company],
            permissions=[ADD_PERIOD_PERMISSION, "finance.view_fiscalyear"],
        )

        periods = FiscalYearService.generate_periods(
            fiscal_year=year, count=12, user=maker,
        )

        self.assertEqual(len(periods), 12)


# ======================================================================
# Lapis API: aksi tulis kustom yang tidak dinyatakan = tertutup
# ======================================================================


class FinanceActionPermissionTests(JournalAuthorizationTestCase):

    def check(self, user, action, *, declared=None, method="post"):
        request = getattr(RequestFactory(), method)("/x/")
        request.user = user

        view = type("View", (), {
            "action": action,
            "action_scope_permissions": declared or {},
        })()

        return FinanceActionPermission().has_permission(request, view)

    def test_undeclared_custom_write_action_fails_closed(self):
        user = self.make_scoped_user(permissions=[POST_JOURNAL_PERMISSION])

        self.assertFalse(self.check(user, "brand_new_action"))

    def test_declared_action_requires_the_declared_permission(self):
        declared = {"post_journal": POST_JOURNAL_PERMISSION}

        self.assertFalse(
            self.check(self.bare_user(), "post_journal", declared=declared),
        )
        self.assertTrue(
            self.check(
                self.make_scoped_user(permissions=[POST_JOURNAL_PERMISSION]),
                "post_journal",
                declared=declared,
            ),
        )

    def test_reads_and_crud_are_left_to_the_existing_layers(self):
        user = self.bare_user()

        self.assertTrue(self.check(user, "list", method="get"))
        self.assertTrue(self.check(user, "create"))
