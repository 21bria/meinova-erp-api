"""
Kontrak HTTP layar Create Leave — persis yang dibaca frontend.

Bedanya dengan `test_leave_request_rules`: yang itu memanggil service
langsung, yang ini menembak endpoint-nya. Dua hal yang hanya bisa
dikunci dari sini, dan dua-duanya pernah jadi sumber kegagalan diam di
repo ini:

1. **Panel aturan di layar Create membaca `preview-rules/`**, bukan
   record — karena di layar itu belum ada record. Kalau bentuk
   balasannya bergeser, panelnya berhenti menampilkan saldo tanpa satu
   pun error: form-nya tetap jalan, cuma pengisinya tidak tahu lagi
   sisa cutinya berapa sampai ia menekan Simpan.
2. **Kalimat yang dilihat pengaju harus kalimat yang sama dengan yang
   menolak dokumennya.** Penilaian yang dipakai panel dan penilaian
   yang dipakai jalur simpan wajib berangkat dari evaluator yang sama;
   begitu keduanya berbeda, layar bilang boleh dan server menolak —
   dan yang mengalaminya tidak punya satu pun petunjuk.

Ditambah satu yang tidak kelihatan dari layar Cuti sama sekali:
peringatan `review` harus **sampai ke kotak masuk approver**. Sebelum
`document_context` diekspos, ia berhenti di database.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from apps.core.testing.tenant import ReusableTenantTestCase
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.accounts.models import Role
from apps.administration.models import (
    Company,
    LeavePolicy,
    LeaveType,
    Location,
    RosterCrew,
    WorkCalendar,
    WorkSchedule,
)
from apps.administration.models.references.leave_policy import (
    LeaveHistoryAction,
)
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    LeaveBalance,
    LeaveStatus,
    OrganizationAssignment,
)
from apps.workflow.models import (
    ApproverType,
    WorkflowDefinition,
    WorkflowStatus,
    WorkflowStep,
)

from django.contrib.auth import get_user_model


User = get_user_model()

YEAR = 2026

JOIN_DATE = date(2020, 3, 10)

# Senin — jangkar seluruh rentang, supaya jumlah hari kerjanya tidak
# bergantung pada hari apa test dijalankan.
MONDAY = date(2026, 6, 1)

LEAVES_URL = "/api/hr/leaves/"
PREVIEW_URL = "/api/hr/leaves/preview-rules/"
INBOX_URL = "/api/workflow/approvals/inbox/"


class LeaveApiTestBase(ReusableTenantTestCase):
    reusable_schema_name = "fast_leave_api"

    @classmethod
    def build_baseline(cls):

        cls.company, _ = Company.objects.get_or_create(
            code='API',
            is_deleted=False,
            defaults={
                "name": 'Leave Api Co',
            },
        )

        cls.office, _ = Location.objects.get_or_create(
            code='API-HO',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": 'Jakarta HO',
            },
        )

        cls.site, _ = Location.objects.get_or_create(
            code='API-SITE',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": 'Gebe Site',
            },
        )

        cls.calendar, _ = WorkCalendar.objects.get_or_create(
            code='API-OFFICE',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": 'Office Mon-Fri',
                "monday": True,
                "tuesday": True,
                "wednesday": True,
                "thursday": True,
                "friday": True,
                "saturday": False,
                "sunday": False,
                "is_default": True,
            },
        )

        cls.roster_schedule, _ = WorkSchedule.objects.get_or_create(
            code='API-ROS',
            is_deleted=False,
            defaults={
                "name": 'Roster 42/14',
                "schedule_type": WorkSchedule.ScheduleType.ROSTER,
                "cycle_work_days": 42,
                "cycle_off_days": 14,
            },
        )

        cls.crew, _ = RosterCrew.objects.get_or_create(
            code='API-CREW',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "location": cls.site,
                "name": 'Crew A',
                "work_schedule": cls.roster_schedule,
                "cycle_start_date": date(2026, 6, 1),
            },
        )

        # ---------------- jenis cuti + aturannya ----------------------

        cls.annual, _ = LeaveType.objects.get_or_create(
            code='API-ANNUAL',
            is_deleted=False,
            defaults={
                "name": 'Cuti Tahunan',
            },
        )

        cls.marriage, _ = LeaveType.objects.get_or_create(
            code='API-MARRIAGE',
            is_deleted=False,
            defaults={
                "name": 'Cuti Menikah',
            },
        )

        cls.baptism, _ = LeaveType.objects.get_or_create(
            code='API-BAPTISM',
            is_deleted=False,
            defaults={
                "name": 'Cuti Baptis Anak',
            },
        )

        cls.sick, _ = LeaveType.objects.get_or_create(
            code='API-SICK',
            is_deleted=False,
            defaults={
                "name": 'Cuti Sakit',
            },
        )

        cls.unpaid, _ = LeaveType.objects.get_or_create(
            code='API-UNPAID',
            is_deleted=False,
            defaults={
                "name": 'Cuti Tanpa Upah',
            },
        )

        LeavePolicy.objects.create(
            company=cls.company,
            leave_type=cls.annual,
            code="API-ANNUAL-STD",
            name="Cuti Tahunan 12 Hari",
            uses_balance=True,
            entitlement_days=Decimal("12"),
            eligible_after_months=12,
        )

        LeavePolicy.objects.create(
            company=cls.company,
            leave_type=cls.marriage,
            code="API-MARRIAGE-STD",
            name="Cuti Menikah 3 Hari",
            uses_balance=False,
            entitlement_days=Decimal("0"),
            max_days=Decimal("3"),
            per_event=True,
        )

        LeavePolicy.objects.create(
            company=cls.company,
            leave_type=cls.baptism,
            code="API-BAPTISM-STD",
            name="Cuti Baptis Anak",
            uses_balance=False,
            entitlement_days=Decimal("0"),
            max_days=Decimal("1"),
            per_event=True,
            history_check=True,
            history_action=LeaveHistoryAction.REVIEW,
        )

        # Lamanya tidak dibatasi — yang menentukan surat dokter. Yang
        # diuji di sini justru kewajiban dokumennya.
        LeavePolicy.objects.create(
            company=cls.company,
            leave_type=cls.sick,
            code="API-SICK-STD",
            name="Cuti Sakit",
            uses_balance=False,
            entitlement_days=Decimal("0"),
            document_required=True,
        )

        LeavePolicy.objects.create(
            company=cls.company,
            leave_type=cls.unpaid,
            code="API-UNPAID-STD",
            name="Cuti Tanpa Upah",
            uses_balance=False,
            entitlement_days=Decimal("0"),
        )

    _counter = 0

    @classmethod
    def make_user(cls, *, superuser=False) -> "User":
        cls._counter += 1

        return User.objects.create_user(
            username=f"api.user{cls._counter}",
            email=f"api.user{cls._counter}@example.test",
            password="Test-Only#Pw1",
            is_superuser=superuser,
            is_staff=superuser,
        )

    @classmethod
    def make_employee(
        cls,
        *,
        join_date=JOIN_DATE,
        location=None,
        calendar=None,
        roster_crew=None,
        user=None,
    ) -> Employee:
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"API{cls._counter:04d}",
            first_name="Rian",
            last_name=f"Saputra {cls._counter}",
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=location,
            organization_effective_date=join_date,
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=join_date,
            working_calendar=calendar,
            roster_crew=roster_crew,
            work_schedule=(
                roster_crew.work_schedule if roster_crew else None
            ),
        )

        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def give_balance(cls, employee, leave_type, days, *, year=YEAR):
        return LeaveBalance.objects.create(
            employee=employee,
            leave_type=leave_type,
            year=year,
            entitlement=Decimal(days),
        )

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def setUp(self):
        super().setUp()

        self.client = TenantClient(self.tenant)

        # Superuser supaya yang diuji aturan cutinya, bukan matriks
        # izin — RBAC punya testnya sendiri.
        self.actor = self.make_user(superuser=True)

        self.auth = self.token_for(self.actor)

    @staticmethod
    def token_for(user) -> str:
        return f"Bearer {RefreshToken.for_user(user).access_token}"

    def post(self, path, payload, *, auth=None):
        return self.client.post(
            path,
            data=json.dumps(payload, default=str),
            content_type="application/json",
            HTTP_AUTHORIZATION=auth or self.auth,
        )

    def get(self, path, *, auth=None):
        return self.client.get(
            path,
            HTTP_AUTHORIZATION=auth or self.auth,
        )

    # ------------------------------------------------------------------
    # Helper domain
    # ------------------------------------------------------------------

    def preview(self, employee, leave_type, *, start=MONDAY, days=None, **extra):
        payload = {
            "employee": employee.pk,
            "leave_type": leave_type.pk,
            "start_date": start,
            **extra,
        }

        if days is not None:
            payload.setdefault(
                "end_date",
                start + timedelta(days=max(int(days) - 1, 0)),
            )
            payload.setdefault("total_days", str(days))

        response = self.post(PREVIEW_URL, payload)

        self.assertEqual(response.status_code, 200, response.content)

        return self.body(response)

    def create_leave(
        self,
        employee,
        leave_type,
        *,
        start=MONDAY,
        days,
        status=LeaveStatus.DRAFT,
        **extra,
    ):
        """
        Dua pintu, karena sejak 18 Sep 2026 `status` memang bukan isian
        formulir: POST biasa selalu melahirkan DRAFT, dan pencatatan
        administratif (RECORDED) punya aksi sendiri yang menuntut
        `hr.record_employeeleave`. Mengirim `status` ke salah satunya
        dibalas 400 — yang diuji berkas ini aturan cutinya, bukan
        penjagaan itu (`test_leave_write_governance`).
        """
        payload = {
            "employee": employee.pk,
            "leave_type": leave_type.pk,
            "start_date": start,
            "end_date": start + timedelta(days=max(int(days) - 1, 0)),
            "total_days": str(days),
            **extra,
        }

        if status == LeaveStatus.RECORDED:
            return self.post(f"{LEAVES_URL}record/", payload)

        self.assertEqual(
            status,
            LeaveStatus.DRAFT,
            "Status selain DRAFT/RECORDED tidak punya pintu create.",
        )

        return self.post(LEAVES_URL, payload)

    @staticmethod
    def finding_codes(rules) -> set:
        return {row["code"] for row in (rules or {}).get("findings", [])}

    @staticmethod
    def messages(payload) -> str:
        """Seluruh kalimat error di satu balasan, digabung."""
        return json.dumps(payload)

    @staticmethod
    def body(response):
        """
        Isi balasan, apa pun bungkusnya.

        Bentuknya memang tidak seragam di codebase ini dan itu bukan
        sesuatu yang boleh diseragamkan diam-diam dari sebuah test:
        `create` dan `retrieve` bawaan DRF membalas data serializer
        apa adanya, sementara daftar dan `@action` lewat envelope
        `{success, message, data}`. Test yang menuliskan salah satunya
        akan gagal dengan `KeyError: 'data'` — pesan yang tidak
        menyebut satu pun hal yang sebenarnya salah.
        """
        payload = response.json()

        if isinstance(payload, dict) and "data" in payload:
            payload = payload["data"]

        # `record/` membungkus dokumennya sekali lagi (`{"leave": …}`),
        # sama seperti `submit/` dan kawan-kawannya.
        if isinstance(payload, dict) and set(payload) == {"leave"}:
            return payload["leave"]

        return payload


class CreateLeaveApiTestCase(LeaveApiTestBase):
    # ------------------------------------------------------------------
    # 1–2 — cuti bersaldo
    # ------------------------------------------------------------------

    def test_annual_with_enough_balance(self):
        """Sisa 7, diminta 2 — panel hijau, dokumennya tersimpan."""
        employee = self.make_employee(
            location=self.office,
            calendar=self.calendar,
        )

        self.give_balance(employee, self.annual, 7)

        data = self.preview(employee, self.annual, days=2)

        self.assertTrue(data["evaluated"])

        rules = data["rules"]

        self.assertTrue(rules["balance_evaluated"])
        self.assertTrue(rules["balance"]["sufficient"])
        self.assertEqual(rules["balance"]["available"], "7.0")
        self.assertEqual(rules["balance"]["requested"], "2.0")
        self.assertNotIn("insufficient_balance", self.finding_codes(rules))

        response = self.create_leave(employee, self.annual, days=2)

        self.assertEqual(response.status_code, 201, response.content)

    def test_annual_without_enough_balance(self):
        """
        Sisa 2, diminta 3.

        Yang dikunci di sini bukan cuma penolakannya, tapi bahwa
        **kalimatnya sama persis** dengan yang sudah ditampilkan panel
        sebelum tombol Simpan ditekan. Dua kalimat berbeda untuk satu
        aturan berarti pengisinya membaca satu hal di layar lalu
        ditolak dengan alasan lain.
        """
        employee = self.make_employee(
            location=self.office,
            calendar=self.calendar,
        )

        self.give_balance(employee, self.annual, 2)

        rules = self.preview(employee, self.annual, days=3)["rules"]

        self.assertFalse(rules["balance"]["sufficient"])
        self.assertEqual(rules["balance"]["available"], "2.0")
        self.assertEqual(rules["balance"]["requested"], "3.0")

        blocking = [
            row for row in rules["findings"]
            if row["level"] == "block"
        ]

        self.assertEqual(len(blocking), 1)
        self.assertEqual(blocking[0]["code"], "insufficient_balance")

        response = self.create_leave(employee, self.annual, days=3)

        self.assertEqual(response.status_code, 400, response.content)

        self.assertIn(
            blocking[0]["message"],
            self.messages(response.json()),
        )

    # ------------------------------------------------------------------
    # 3–4 — kartu yang belum ada
    # ------------------------------------------------------------------

    def test_annual_not_yet_eligible(self):
        employee = self.make_employee(
            join_date=date(YEAR, 3, 1),
            location=self.office,
            calendar=self.calendar,
        )

        rules = self.preview(
            employee,
            self.annual,
            start=date(YEAR, 6, 1),
            days=2,
        )["rules"]

        self.assertIn("not_yet_eligible", self.finding_codes(rules))
        self.assertFalse(rules["balance"]["exists"])
        self.assertEqual(rules["balance"]["eligible_date"], "2027-03-01")

        response = self.create_leave(
            employee,
            self.annual,
            start=date(YEAR, 6, 1),
            days=2,
        )

        self.assertEqual(response.status_code, 400, response.content)

    def test_annual_eligible_but_card_not_issued(self):
        """
        Kekurangan penyiapan data, bukan kesalahan pengaju: ditandai
        perlu diperiksa, **tidak** ditahan.
        """
        employee = self.make_employee(
            location=self.office,
            calendar=self.calendar,
        )

        rules = self.preview(employee, self.annual, days=2)["rules"]

        self.assertIn("balance_missing", self.finding_codes(rules))
        self.assertTrue(rules["needs_review"])

        self.assertEqual(
            [row for row in rules["findings"] if row["level"] == "block"],
            [],
        )

        response = self.create_leave(employee, self.annual, days=2)

        self.assertEqual(response.status_code, 201, response.content)

    # ------------------------------------------------------------------
    # 5–8 — cuti tanpa saldo
    # ------------------------------------------------------------------

    def test_marriage_max_days(self):
        employee = self.make_employee(
            location=self.office,
            calendar=self.calendar,
        )

        rules = self.preview(employee, self.marriage, days=5)["rules"]

        self.assertIn("max_days", self.finding_codes(rules))

        # Cuti tanpa saldo tidak boleh menampilkan kotak saldo sama
        # sekali — "Available Balance 0" untuk hak yang memang tidak
        # berjatah terbaca seperti jatah yang sudah habis.
        self.assertFalse(rules["balance_evaluated"])
        self.assertIsNone(rules["balance"])

        response = self.create_leave(employee, self.marriage, days=5)

        self.assertEqual(response.status_code, 400, response.content)

    def test_child_baptism_history_review(self):
        employee = self.make_employee(
            location=self.office,
            calendar=self.calendar,
        )

        first = self.create_leave(
            employee,
            self.baptism,
            start=date(2025, 5, 12),
            days=1,
            status=LeaveStatus.RECORDED,
        )

        self.assertEqual(first.status_code, 201, first.content)

        rules = self.preview(employee, self.baptism, days=1)["rules"]

        self.assertIn("history", self.finding_codes(rules))
        self.assertEqual(rules["history_total"], 1)
        self.assertTrue(rules["history_evaluated"])
        self.assertTrue(rules["needs_review"])
        self.assertEqual(rules["history"][0]["event_date"], "2025-05-12")

        # Peringatan, bukan penolakan.
        second = self.create_leave(employee, self.baptism, days=1)

        self.assertEqual(second.status_code, 201, second.content)

    def test_sick_document_required_blocks_submit_only(self):
        employee = self.make_employee(
            location=self.office,
            calendar=self.calendar,
        )

        rules = self.preview(employee, self.sick, days=2)["rules"]

        self.assertTrue(rules["document_required"])
        self.assertIn("document_required", self.finding_codes(rules))

        # Draft tetap boleh disimpan — surat dokter lazim baru ada
        # sesudah orangnya pulang berobat.
        created = self.create_leave(employee, self.sick, days=2)

        self.assertEqual(created.status_code, 201, created.content)

        leave_id = self.body(created)["id"]

        submitted = self.post(
            f"{LEAVES_URL}{leave_id}/submit/",
            {},
        )

        self.assertEqual(submitted.status_code, 400, submitted.content)

        self.assertIn(
            "dokumen pendukung",
            self.messages(submitted.json()),
        )

    def test_unpaid_leave_does_not_touch_annual(self):
        employee = self.make_employee(
            location=self.office,
            calendar=self.calendar,
        )

        card = self.give_balance(employee, self.annual, 12)

        response = self.create_leave(
            employee,
            self.unpaid,
            days=5,
            status=LeaveStatus.RECORDED,
        )

        self.assertEqual(response.status_code, 201, response.content)

        card.refresh_from_db()

        self.assertEqual(card.used, Decimal("0.0"))
        self.assertEqual(card.remaining, Decimal("12.0"))

        self.assertEqual(
            LeaveBalance.objects.filter(
                employee=employee,
                leave_type=self.unpaid,
                is_deleted=False,
            ).count(),
            0,
        )

    # ------------------------------------------------------------------
    # 9–10 — konteks pegawai
    # ------------------------------------------------------------------

    def test_site_employee_working_days_follow_roster(self):
        """
        Hari kerjanya milik backend, bukan selisih tanggal: 1–7 Juni
        untuk pegawai roster = 7, untuk pegawai kantor = 5.
        """
        site_employee = self.make_employee(
            location=self.site,
            roster_crew=self.crew,
        )

        office_employee = self.make_employee(
            location=self.office,
            calendar=self.calendar,
        )

        self.give_balance(site_employee, self.annual, 12)
        self.give_balance(office_employee, self.annual, 12)

        span = {
            "end_date": MONDAY + timedelta(days=6),
        }

        site = self.preview(site_employee, self.annual, **span)
        office = self.preview(office_employee, self.annual, **span)

        self.assertEqual(site["total_days"], "7")
        self.assertEqual(office["total_days"], "5")

    def test_admin_created_request_keeps_employee_context(self):
        """
        Yang login admin kantor, yang dituju pegawai site. Seluruh
        resolver harus tetap memakai pegawainya — kalau ikut yang
        login, hari cutinya salah tanpa satu pun pesan.
        """
        admin_user = self.make_user(superuser=True)

        self.make_employee(
            location=self.office,
            calendar=self.calendar,
            user=admin_user,
        )

        subject = self.make_employee(
            location=self.site,
            roster_crew=self.crew,
        )

        self.give_balance(subject, self.annual, 12)

        data = self.preview(
            subject,
            self.annual,
            end_date=MONDAY + timedelta(days=6),
        )

        self.assertEqual(data["total_days"], "7")

        response = self.post(
            f"{LEAVES_URL}record/",
            {
                "employee": subject.pk,
                "leave_type": self.annual.pk,
                "start_date": MONDAY,
                "end_date": MONDAY + timedelta(days=6),
            },
            auth=self.token_for(admin_user),
        )

        self.assertEqual(response.status_code, 201, response.content)

        body = self.body(response)

        self.assertEqual(Decimal(body["total_days"]), Decimal("7.0"))
        self.assertEqual(body["location"], self.site.pk)

    # ------------------------------------------------------------------
    # Layar detail
    # ------------------------------------------------------------------

    def test_detail_payload_carries_policy_rules(self):
        """
        Panel di layar detail membaca `policy_rules` dari record, bukan
        dari preview. Kalau kuncinya hilang dari payload, panelnya
        berhenti tampil tanpa satu pun error.
        """
        employee = self.make_employee(
            location=self.office,
            calendar=self.calendar,
        )

        self.give_balance(employee, self.annual, 7)

        created = self.create_leave(employee, self.annual, days=2)

        leave_id = self.body(created)["id"]

        detail = self.get(f"{LEAVES_URL}{leave_id}/")

        self.assertEqual(detail.status_code, 200, detail.content)

        rules = self.body(detail)["policy_rules"]

        self.assertTrue(rules["balance_evaluated"])
        self.assertTrue(rules["history_evaluated"])
        self.assertEqual(rules["balance"]["requested"], "2.0")
        self.assertEqual(rules["policy_code"], "API-ANNUAL-STD")


class LeaveApprovalVisibilityTestCase(LeaveApiTestBase):
    """
    Peringatan `review` harus sampai ke meja approver.

    Sebelum `document_context` diekspos, ia berhenti di database:
    approver memutuskan tanpa tahu dokumennya ditandai perlu diperiksa,
    dan tidak ada satu pun tanda di layarnya.
    """

    @classmethod
    def build_baseline(cls):
        super().build_baseline()

        cls.hr_role = Role.objects.create(code="API-HR", name="HR Admin")

        cls.definition = WorkflowDefinition.objects.create(
            code="API-LEAVE",
            name="Cuti Standar",
            module="hr",
            document_type="leave_request",
            company=cls.company,
            status=WorkflowStatus.ACTIVE,
        )

        WorkflowStep.objects.create(
            definition=cls.definition,
            sequence=1,
            name="HR Review",
            approver_type=ApproverType.ROLE,
            approver_role=cls.hr_role,
        )

    def test_review_warning_reaches_the_inbox(self):
        approver_user = self.make_user()

        approver_user.roles.add(self.hr_role)

        self.make_employee(
            location=self.office,
            calendar=self.calendar,
            user=approver_user,
        )

        employee = self.make_employee(
            location=self.office,
            calendar=self.calendar,
        )

        # Riwayat yang memicu temuan `review`.
        self.create_leave(
            employee,
            self.baptism,
            start=date(2025, 5, 12),
            days=1,
            status=LeaveStatus.RECORDED,
        )

        created = self.create_leave(employee, self.baptism, days=1)

        self.assertEqual(created.status_code, 201, created.content)

        leave_id = self.body(created)["id"]

        submitted = self.post(f"{LEAVES_URL}{leave_id}/submit/", {})

        self.assertEqual(submitted.status_code, 200, submitted.content)

        inbox = self.get(
            INBOX_URL,
            auth=self.token_for(approver_user),
        )

        self.assertEqual(inbox.status_code, 200, inbox.content)

        rows = self.body(inbox)

        self.assertEqual(len(rows), 1, rows)

        context = rows[0]["document_context"]

        self.assertTrue(context["needs_review"])
        self.assertEqual(context["policy_code"], "API-BAPTISM-STD")
        self.assertEqual(context["history_total"], 1)
        self.assertTrue(context["rule_messages"])

        # Kalimat yang dibaca approver = kalimat yang dilihat pengaju.
        detail = self.get(f"{LEAVES_URL}{leave_id}/")

        findings = self.body(detail)["policy_rules"]["findings"]

        self.assertIn(
            context["rule_messages"][0],
            [row["message"] for row in findings],
        )
