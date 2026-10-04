"""
PF-0F — `POST /api/finance/accounting-events/{id}/retry/` harus berizin.

Sebelum PF-0F, `retry/` adalah `@action` kustom yang tidak dijaga
`ModelPermission` (hanya aksi CRUD baku yang dijaga di sana), jadi
penjagaannya cuma "sudah login + cakupan company". Padahal memproses
ulang **menerbitkan** jurnal — dan untuk kebijakan `auto_post=True`,
memostingnya ke buku besar. PF-0F mulai mencatat kejadian `PAYROLL_POSTED`
sungguhan, jadi celah itu tidak boleh ikut melebar.

Yang ditegakkan sekarang, di **service** (`assert_may_retry`) dan di
cakupan aksi viewset (`action_scope_permissions`):

* izin eksplisit `finance.change_accountingevent`;
* cakupan baris dihitung dari izin itu sendiri.

Yang diuji di sini bukan kode status saja. Kode status bisa 403 (service
menolak) atau 404 (cakupan aksi menyembunyikan barisnya) tergantung lapis
mana yang lebih dulu — keduanya penolakan yang benar. Yang **tidak boleh**
terjadi, dan yang diperiksa setiap test: kejadiannya bergeser dari
PENDING, atau satu jurnal pun terbit.
"""

from datetime import date

from rest_framework.exceptions import PermissionDenied

from apps.accounts.models import User
from apps.finance.models import (
    AccountingEventStatus,
    AccountingPolicy,
    AccountingPolicyLine,
    AccountingPolicyRule,
    Journal,
    JournalStatus,
    PostingSide,
)
from apps.finance.services import RETRY_PERMISSION, AccountingEventProcessor

from .test_access import FinanceScopeTestCase


EVENT_DATE = date(2027, 3, 31)

DENIED = {401, 403, 404}


class AccountingEventRetryAccessTests(FinanceScopeTestCase):

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    def stage(self, *, auto_post=False):
        """Satu perusahaan, satu kebijakan sederhana, satu kejadian PENDING."""
        company = self.make_company()
        self.make_fiscal_year(company)
        expense, payable = self.make_pair(company)

        event_type = f"RETRY_{self.next_code('T')}"

        policy = AccountingPolicy.objects.create(
            code=self.next_code("POL"),
            name="Retry test policy",
            company=company,
            event_type=event_type,
            journal_type="automatic",
            auto_post=auto_post,
        )

        rule = AccountingPolicyRule.objects.create(
            policy=policy, sequence=10, name="Both sides", conditions={},
        )

        AccountingPolicyLine.objects.create(
            rule=rule, sequence=1, side=PostingSide.DEBIT,
            account=expense, amount_source="amount",
        )
        AccountingPolicyLine.objects.create(
            rule=rule, sequence=2, side=PostingSide.CREDIT,
            account=payable, amount_source="amount",
        )

        key = self.next_code("retry")

        event = AccountingEventProcessor.record(
            event_type=event_type,
            source_module="test",
            source_type="retry",
            source_id=key,
            company=company,
            event_date=EVENT_DATE,
            payload={"amount": "1000.00"},
            idempotency_key=f"pf0f:retry:{key}",
            process=False,
        )

        self.assertEqual(event.status, AccountingEventStatus.PENDING)

        return company, event

    def retry(self, user, event):
        client = self.api(user) if user is not None else self._anonymous()

        return client.post(
            f"/api/finance/accounting-events/{event.pk}/retry/",
        )

    def _anonymous(self):
        from rest_framework.test import APIClient

        return APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

    def assert_untouched(self, event):
        """Penolakan yang benar tidak meninggalkan jejak apa pun."""
        event.refresh_from_db()

        self.assertEqual(event.status, AccountingEventStatus.PENDING)
        self.assertEqual(event.attempts, 0)
        self.assertIsNone(event.generated_journal_id)
        self.assertFalse(
            Journal.objects.filter(metadata__accounting_event=event.pk).exists(),
        )

    # ------------------------------------------------------------------
    # Ditolak
    # ------------------------------------------------------------------

    def test_anonymous_is_denied(self):
        _, event = self.stage()

        response = self.retry(None, event)

        self.assertIn(response.status_code, DENIED)
        self.assert_untouched(event)

    def test_authenticated_without_permission_is_denied(self):
        company, event = self.stage()

        user = self.make_scoped_user(companies=[company])

        response = self.retry(user, event)

        self.assertIn(response.status_code, DENIED)
        self.assert_untouched(event)

    def test_view_permission_alone_is_denied(self):
        company, event = self.stage()

        user = self.make_scoped_user(
            companies=[company],
            permissions=["finance.view_accountingevent"],
        )

        response = self.retry(user, event)

        self.assertIn(response.status_code, DENIED)
        self.assert_untouched(event)

    def test_unrelated_payroll_permission_is_denied(self):
        """Wewenang memfinalisasi payroll tidak memberi wewenang retry."""
        company, event = self.stage()

        user = self.make_scoped_user(
            companies=[company],
            permissions=[
                "payroll.view_payrollrun",
                "payroll.change_payrollrun",
            ],
        )

        response = self.retry(user, event)

        self.assertIn(response.status_code, DENIED)
        self.assert_untouched(event)

    def test_permission_outside_company_scope_is_denied(self):
        company, event = self.stage()
        elsewhere = self.make_company()

        user = self.make_scoped_user(
            companies=[elsewhere],
            permissions=[RETRY_PERMISSION, "finance.view_accountingevent"],
        )

        response = self.retry(user, event)

        self.assertIn(response.status_code, DENIED)
        self.assert_untouched(event)

    def test_account_without_any_assignment_is_denied(self):
        """
        Akun tanpa penugasan berarti cakupan **tak tersaring**, bukan
        kosong. Tanpa pemeriksaan izin, ia justru yang paling bebas.
        """
        _, event = self.stage()

        user = User.objects.create_user(
            username=self.next_code("bare"), password="x",
        )

        response = self.retry(user, event)

        self.assertIn(response.status_code, DENIED)
        self.assert_untouched(event)

    def test_unauthorized_retry_cannot_post_an_auto_post_event(self):
        """
        Celah yang sebenarnya ditutup: kebijakan `auto_post=True` akan
        **memosting** jurnalnya kalau diproses. Tanpa izin, tidak ada
        jurnal yang terbit sama sekali — apalagi terposting.
        """
        company, event = self.stage(auto_post=True)

        user = self.make_scoped_user(companies=[company])

        response = self.retry(user, event)

        self.assertIn(response.status_code, DENIED)
        self.assert_untouched(event)
        self.assertFalse(
            Journal.objects.filter(
                company=company, status=JournalStatus.POSTED,
            ).exists(),
        )

    def test_service_denies_without_the_api(self):
        """
        Penolakannya di service, jadi jalur selain viewset — perintah
        manajemen, pemanggil lain yang menyusul — tidak bisa melewatinya.
        """
        company, event = self.stage()

        user = self.make_scoped_user(companies=[company])

        with self.assertRaises(PermissionDenied):
            AccountingEventProcessor.retry(event=event, user=user)

        self.assert_untouched(event)

    def test_service_denies_out_of_scope_holder(self):
        company, event = self.stage()
        elsewhere = self.make_company()

        user = self.make_scoped_user(
            companies=[elsewhere], permissions=[RETRY_PERMISSION],
        )

        with self.assertRaises(PermissionDenied):
            AccountingEventProcessor.retry(event=event, user=user)

        self.assert_untouched(event)

    # ------------------------------------------------------------------
    # Diizinkan
    # ------------------------------------------------------------------

    def authorized(self, company):
        return self.make_scoped_user(
            companies=[company],
            permissions=[RETRY_PERMISSION, "finance.view_accountingevent"],
        )

    def test_authorized_finance_user_may_retry(self):
        company, event = self.stage()

        response = self.retry(self.authorized(company), event)

        self.assertEqual(response.status_code, 200, response.content)

        event.refresh_from_db()

        self.assertEqual(event.status, AccountingEventStatus.PROCESSED)
        self.assertIsNotNone(event.generated_journal_id)

    def test_authorized_retry_respects_auto_post_false(self):
        company, event = self.stage(auto_post=False)

        self.retry(self.authorized(company), event)

        event.refresh_from_db()

        journal = event.generated_journal

        self.assertEqual(journal.status, JournalStatus.DRAFT)
        self.assertIsNone(journal.posted_at)

    def test_authorized_retry_respects_auto_post_true(self):
        company, event = self.stage(auto_post=True)

        self.retry(self.authorized(company), event)

        event.refresh_from_db()

        self.assertEqual(event.generated_journal.status, JournalStatus.POSTED)

    def test_internal_caller_without_user_still_works(self):
        """
        `user=None` = pemanggil internal di shell server, konvensi yang sama
        dengan Finalize payroll. Jalur API tidak pernah mengirim `None`.
        """
        _, event = self.stage()

        event = AccountingEventProcessor.retry(event=event)

        self.assertEqual(event.status, AccountingEventStatus.PROCESSED)

    def test_retry_remains_the_only_write_action(self):
        """
        Aksi tulis lain pada kejadian tetap tertutup.

        Create ditolak **sebelum** sampai ke `create()` yang membalas 405:
        `ModelPermission` menuntut `finance.add_accountingevent`, yang tidak
        dipegang siapa pun di seed. Dua-duanya penolakan; yang dijaga di
        sini tidak ada kejadian yang lahir atau berubah lewat API.
        PATCH/PUT/DELETE tidak ada di `http_method_names`.
        """
        from apps.finance.models import AccountingEvent

        company, event = self.stage()

        client = self.api(self.authorized(company))

        before = AccountingEvent.objects.count()

        self.assertIn(
            client.post("/api/finance/accounting-events/", {}).status_code,
            {403, 405},
        )
        self.assertEqual(AccountingEvent.objects.count(), before)

        for method in ("patch", "put", "delete"):
            response = getattr(client, method)(
                f"/api/finance/accounting-events/{event.pk}/",
            )

            # 405 kalau izin modelnya dipegang (PATCH/PUT: `change_*`),
            # 403 kalau tidak (DELETE: `delete_*`) — DRF memeriksa izin
            # sebelum metodenya. Dua-duanya penolakan.
            self.assertIn(response.status_code, {403, 405}, method)

        self.assert_untouched(event)
