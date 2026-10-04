"""
Siapa boleh **membaca**, siapa boleh **memutuskan**, siapa boleh
**menyunting** — tiga pertanyaan berbeda atas satu dokumen cuti.

Ditulis sesudah bug UAT: email "menunggu persetujuan Anda" mendarat di
kotak masuk atasan langsung, dan tautannya membalas
`No EmployeeLeave matches the given query.` Sebabnya bukan rute email
dan bukan alurnya — kotak masuk approval menagih lewat
`WorkflowApproval`, sedangkan dokumennya disaring kewenangan penugasan,
dan dua lapis itu tidak saling mengenal. Atasan langsung bercakupan
`own`, jadi ia ditagih menyetujui dokumen yang tidak bisa ia buka.

Yang dikunci berkas ini, dan ketiganya sengaja diuji terpisah supaya
perbaikan yang melebar tidak lolos diam-diam:

1. **Membaca.** Peserta alur boleh membuka dokumen yang ditagihkan
   kepadanya. Pegawai lain — bukan pengaju, bukan approver — tetap
   tidak, sebelum maupun sesudah dokumennya diajukan.
2. **Memutuskan.** Approve/Reject/Return tetap dijaga
   `WorkflowApprovalService.check_right`, dan sekarang tombolnya bisa
   ditekan dari layar dokumennya, bukan cuma dari kotak masuk generik.
3. **Menyunting.** Approver **tidak** boleh mengubah isi dokumen yang
   sedang ia nilai — tidak juga sesudah ia mengembalikannya, saat
   dokumennya kembali bisa disunting pengajunya.

Alur dan cakupannya dibangun dari seed sungguhan
(`apps.workflow.seeds.workflows.seed()`), bukan disusun tangan: rantai
yang disalin ke test akan tetap hijau sesudah seed-nya berubah, dan itu
kebalikan dari yang dibutuhkan.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from apps.core.testing.tenant import ReusableTenantTestCase
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.accounts.models import (
    AuthorityMode,
    Role,
)
from apps.accounts.services.role_assignment import grant_role
from apps.administration.models import (
    Company,
    Department,
    LeavePolicy,
    LeaveType,
    Location,
    Position,
    WorkCalendar,
)
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    LeaveBalance,
    LeaveStatus,
    OrganizationAssignment,
)
from apps.workflow.models import InstanceStatus, WorkflowInstance
from apps.workflow.seeds import workflows as workflow_seed


YEAR = 2026

# Senin, supaya jumlah hari kerjanya tidak bergantung pada hari apa
# test dijalankan.
MONDAY = date(2026, 8, 3)
TUESDAY = date(2026, 8, 4)

JOIN_DATE = date(2020, 3, 10)

LEAVES = "/api/hr/leaves/"


class _As:
    """Klien HTTP yang selalu membawa token satu orang."""

    def __init__(self, client, user):
        self.client = client
        self.headers = {
            "HTTP_AUTHORIZATION": (
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
        }

    def get(self, path):
        return self.client.get(path, **self.headers)

    def post(self, path, payload=None, *, format=None):
        return self.client.post(
            path,
            data=json.dumps(payload or {}),
            content_type="application/json",
            **self.headers,
        )

    def patch(self, path, payload=None, *, format=None):
        return self.client.patch(
            path,
            data=json.dumps(payload or {}),
            content_type="application/json",
            **self.headers,
        )


class LeaveAccessTestBase(ReusableTenantTestCase):
    reusable_schema_name = "fast_leave_access"

    """
    Empat orang, dan justru orang keempat yang paling penting.

    Bimo mengajukan, Farah atasannya, Sarah HR Manager. **Yulia** tidak
    ikut apa pun: ia yang membuktikan perbaikan ini tidak melebar jadi
    "semua pegawai boleh membaca cuti semua orang".
    """

    @classmethod
    def build_baseline(cls):

        cls.company, _ = Company.objects.get_or_create(
            code='LAC',
            is_deleted=False,
            defaults={
                "name": 'Leave Access Co',
            },
        )

        cls.head_office, _ = Location.objects.get_or_create(
            code='JKT-HO',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": 'Jakarta Head Office',
            },
        )

        cls.department, _ = Department.objects.get_or_create(
            code='LAC-FIN',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": 'Finance',
            },
        )

        cls.calendar, _ = WorkCalendar.objects.get_or_create(
            code='LAC-OFFICE',
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

        cls.annual, _ = LeaveType.objects.get_or_create(
            code='LAC-ANNUAL',
            is_deleted=False,
            defaults={
                "name": 'Cuti Tahunan',
            },
        )

        cls.policy, _ = LeavePolicy.objects.get_or_create(
            code='LAC-ANNUAL-STD',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "leave_type": cls.annual,
                "name": 'Cuti Tahunan 12 Hari',
                "uses_balance": True,
                "entitlement_days": Decimal('12'),
                "eligible_after_months": 12,
            },
        )

        cls.seed_result = workflow_seed.seed()

        # Role pegawai biasa: cakupannya **data sendiri**. Ini yang
        # dipakai atasan langsung di tenant peragaan, dan justru itu
        # yang membuat bugnya muncul — jabatan tidak memberi cakupan,
        # garis pelaporan juga tidak.
        cls.employee_role, _ = Role.objects.get_or_create(
            code='LAC-EMPLOYEE',
            is_deleted=False,
            defaults={
                "name": 'Employee',
            },
        )

        cls.hr_role = Role.objects.get(code="HR-MANAGER")

        # Izin model CRUD-nya diberikan ke **dua** role: yang dijaga
        # berkas ini penyaringan barisnya, bukan izin tabelnya. Tanpa
        # ini PATCH pengaju atas draft-nya sendiri ditolak
        # `ModelPermission` dan test "boleh menyunting" hijau karena
        # sebab yang salah.
        leave_permissions = Permission.objects.filter(
            content_type__app_label="hr",
            codename__in=[
                "view_employeeleave",
                "add_employeeleave",
                "change_employeeleave",
                "delete_employeeleave",
            ],
        )

        cls.employee_role.permissions.set(leave_permissions)

        # ------------------------------------------------------------------
        # WHERE tiap role — dinyatakan, bukan diturunkan
        # ------------------------------------------------------------------
        #
        # `.roles.set()` telanjang cuma memberi keanggotaan: tanpa
        # WHERE, seluruh test positif di berkas ini merah sementara test
        # negatifnya tetap hijau, karena orang yang tidak melihat
        # apa-apa otomatis lulus "tidak boleh melihat milik orang
        # lain".
        #
        # `employee_role` dicakup ke **data sendiri** (`own`), dan
        # `hr_role` sengaja tanpa batas — maksud yang sudah dinyatakan
        # komentar di atas masing-masing, bukan tebakan dari nama role.
        cls.role_authority = {
            cls.employee_role.pk: (AuthorityMode.EXPLICIT, [("own", None)]),
            cls.hr_role.pk: (AuthorityMode.UNRESTRICTED, []),
        }
        cls.hr_role.permissions.set(leave_permissions)

        cls.supervisor = cls._make_employee(
            number="LAC0002",
            first_name="Farah",
            last_name="Anindita",
            username="lac.supervisor",
            roles=[cls.employee_role],
        )

        cls.staff = cls._make_employee(
            number="LAC0001",
            first_name="Bimo",
            last_name="Nugroho",
            username="lac.staff",
            reports_to=cls.supervisor,
            roles=[cls.employee_role],
        )

        cls.hr_manager = cls._make_employee(
            number="LAC0003",
            first_name="Sarah",
            last_name="Wibowo",
            username="lac.hrmanager",
            roles=[cls.hr_role],
        )

        # Tidak ikut alur mana pun, dan cakupannya sama persis dengan
        # Farah. Kalau ia ikut bisa membaca, yang ditambahkan bukan
        # akses peserta alur melainkan lubang.
        cls.bystander = cls._make_employee(
            number="LAC0004",
            first_name="Yulia",
            last_name="Kartika",
            username="lac.bystander",
            roles=[cls.employee_role],
        )

    _position_counter = 0


    @classmethod
    def grant(cls, user, role):
        """Memberi satu role berikut WHERE yang dinyatakan fixture ini."""
        mode, authorities = cls.role_authority[role.pk]

        grant_role(user, role, mode=mode, authorities=authorities)

    @classmethod
    def _make_employee(
        cls,
        *,
        number: str,
        first_name: str,
        last_name: str,
        username: str,
        reports_to=None,
        roles=None,
    ) -> Employee:
        User = get_user_model()

        cls._position_counter += 1

        position = Position.objects.create(
            company=cls.company,
            department=cls.department,
            code=f"LAC-POS{cls._position_counter}",
            name=f"Jabatan {cls._position_counter}",
        )

        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.test",
            password="Test-Only#Pw1",
            first_name=first_name,
            last_name=last_name,
        )


        for role in roles or ():
            cls.grant(user, role)

        employee = Employee.objects.create(
            employee_number=number,
            first_name=first_name,
            last_name=last_name,
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=cls.head_office,
            department=cls.department,
            position=position,
            reports_to=reports_to,
            organization_effective_date=JOIN_DATE,
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=JOIN_DATE,
            working_calendar=cls.calendar,
        )

        return Employee.objects.get(pk=employee.pk)

    # ------------------------------------------------------------------
    # Pembantu
    # ------------------------------------------------------------------

    def setUp(self):
        super().setUp()

        # `TenantClient`, bukan `APIClient`: request lewat middleware
        # django-tenants, dan client biasa mendarat di schema `public`
        # — yang tabel HR-nya memang tidak ada di sana. Pola yang sama
        # dipakai test kontrak Travel Request.
        self.http = TenantClient(self.tenant)

    def client_for(self, employee) -> "_As":
        """
        Satu pemeran, satu klien. Token JWT sungguhan supaya jalur
        autentikasinya ikut terlewati — yang diuji berkas ini
        penyaringan barisnya, dan itu baru berarti kalau
        `request.user`-nya datang dari jalur yang sama dengan layar.
        """
        return _As(self.http, employee.user)

    def give_balance(self, employee, days, *, year=YEAR):
        return LeaveBalance.objects.create(
            employee=employee,
            leave_type=self.annual,
            year=year,
            entitlement=Decimal(days),
        )

    def make_leave(self, *, start=MONDAY, end=TUESDAY, total_days=2):
        return EmployeeLeaveService.create(
            data={
                "employee": self.staff,
                "leave_type": self.annual,
                "start_date": start,
                "end_date": end,
                "total_days": Decimal(total_days),
                "status": LeaveStatus.DRAFT,
            },
            user=self.staff.user,
        )

    def submitted_leave(self):
        leave = self.make_leave()

        EmployeeLeaveService.submit(instance=leave, user=self.staff.user)

        leave.refresh_from_db()

        return leave

    def detail(self, client, leave):
        return client.get(f"{LEAVES}{leave.pk}/")

    def payload(self, response) -> dict:
        body = response.json()

        return body.get("data", body)

    def balance(self, employee=None):
        return LeaveBalance.objects.get(
            employee=employee or self.staff,
            leave_type=self.annual,
            year=YEAR,
        )

    def instance_for(self, leave) -> WorkflowInstance:
        return (
            WorkflowInstance.objects
            .filter(
                module="hr",
                document_type="leave_request",
                object_id=str(leave.pk),
            )
            .order_by("-id")
            .first()
        )


# ----------------------------------------------------------------------
# 1 — membaca
# ----------------------------------------------------------------------


class LeaveReadAccessTestCase(LeaveAccessTestBase):
    def setUp(self):
        super().setUp()

        self.give_balance(self.staff, 5)

    def test_owner_can_read_own_leave(self):
        leave = self.make_leave()

        response = self.detail(self.client_for(self.staff), leave)

        self.assertEqual(response.status_code, 200)

        self.assertEqual(
            self.payload(response)["document_number"],
            leave.document_number,
        )

    def test_unrelated_employee_cannot_read_it(self):
        leave = self.submitted_leave()

        response = self.detail(self.client_for(self.bystander), leave)

        self.assertEqual(response.status_code, 404)

    def test_unrelated_employee_does_not_see_it_in_the_list(self):
        self.submitted_leave()

        response = self.client_for(self.bystander).get(LEAVES)

        self.assertEqual(response.status_code, 200)

        body = response.json()
        rows = body.get("data", body)
        rows = rows.get("results", rows) if isinstance(rows, dict) else rows

        self.assertEqual(rows, [])

    def test_supervisor_cannot_read_it_before_it_is_submitted(self):
        """
        Aksesnya datang dari **meja yang ditagihkan**, bukan dari garis
        pelaporan. Draft yang belum diajukan belum menagih siapa pun.
        """
        leave = self.make_leave()

        response = self.detail(self.client_for(self.supervisor), leave)

        self.assertEqual(response.status_code, 404)

    def test_supervisor_can_read_it_once_it_reaches_their_desk(self):
        """Bug UAT-nya, dikunci apa adanya."""
        leave = self.submitted_leave()

        response = self.detail(self.client_for(self.supervisor), leave)

        self.assertEqual(response.status_code, 200)

        data = self.payload(response)

        self.assertEqual(data["document_number"], leave.document_number)

        # Bukan cuma terbuka: kotak tanda tangannya ikut terbaca, dan
        # tombolnya memang untuk dia.
        self.assertTrue(data["workflow"]["can_act"])

        self.assertEqual(
            data["workflow"]["current_step"]["name"],
            "Approved By (Atasan Langsung)",
        )

    def test_hr_manager_can_read_it_before_their_turn(self):
        """
        HR Manager melihatnya lewat cakupan role-nya, bukan lewat
        meja — dan itu memang beda yang disengaja: bagian HR harus bisa
        menjawab "pengajuan si A sudah sampai mana".
        """
        leave = self.submitted_leave()

        response = self.detail(self.client_for(self.hr_manager), leave)

        self.assertEqual(response.status_code, 200)

        # Gilirannya belum tiba.
        self.assertFalse(self.payload(response)["workflow"]["can_act"])

    def test_supervisor_keeps_access_after_deciding(self):
        """
        Yang sudah menandatangani tetap bisa membuka yang ia
        tandatangani. Akses yang hilang begitu tombol ditekan membuat
        orang menyimpan tangkapan layar sebagai gantinya.
        """
        leave = self.submitted_leave()

        client = self.client_for(self.supervisor)

        self.assertEqual(
            client.post(f"{LEAVES}{leave.pk}/approve/").status_code,
            200,
        )

        response = self.detail(client, leave)

        self.assertEqual(response.status_code, 200)

        self.assertFalse(self.payload(response)["workflow"]["can_act"])


# ----------------------------------------------------------------------
# 2 — menyunting
# ----------------------------------------------------------------------


class LeaveEditAccessTestCase(LeaveAccessTestBase):
    def setUp(self):
        super().setUp()

        self.give_balance(self.staff, 5)

    def test_owner_can_edit_own_draft(self):
        leave = self.make_leave()

        response = self.client_for(self.staff).patch(
            f"{LEAVES}{leave.pk}/",
            {"notes": "Acara keluarga."},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

        leave.refresh_from_db()

        self.assertEqual(leave.notes, "Acara keluarga.")

    def test_owner_cannot_edit_while_it_is_being_reviewed(self):
        """
        Isi yang sedang dinilai tidak boleh bergeser di bawah tangan
        approver-nya. Ditolak `assert_editable`, bukan disembunyikan —
        pengajunya tetap melihat dokumennya, cuma tidak bisa mengubahnya.
        """
        leave = self.submitted_leave()

        response = self.client_for(self.staff).patch(
            f"{LEAVES}{leave.pk}/",
            {"total_days": "1"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        leave.refresh_from_db()

        self.assertEqual(leave.total_days, Decimal("2"))

    def test_supervisor_cannot_edit_the_document_they_review(self):
        """
        Boleh membuka ≠ boleh mengubah. Yang membuka pintu bacanya
        adalah meja yang ditagihkan kepadanya, dan meja itu tidak
        memberi hak menyunting satu field pun.
        """
        leave = self.submitted_leave()

        response = self.client_for(self.supervisor).patch(
            f"{LEAVES}{leave.pk}/",
            {"notes": "diubah approver"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

        leave.refresh_from_db()

        self.assertNotEqual(leave.notes, "diubah approver")

    def test_hr_manager_cannot_edit_a_document_under_review(self):
        """
        Cakupan datanya seluruh tenant, jadi ia **melihat** barisnya —
        yang menolak di sini statusnya, bukan cakupannya. Dua penjagaan
        yang berbeda, dan dokumen berjalan butuh dua-duanya.
        """
        leave = self.submitted_leave()

        response = self.client_for(self.hr_manager).patch(
            f"{LEAVES}{leave.pk}/",
            {"notes": "dirapikan HR"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        leave.refresh_from_db()

        self.assertNotEqual(leave.notes, "dirapikan HR")

    def test_supervisor_cannot_edit_it_after_returning_it(self):
        """
        **Lubang yang paling mudah terbuka.** Dokumen yang dikembalikan
        kembali berstatus DRAFT — `is_editable` benar lagi — dan
        approver yang mengembalikannya masih terdaftar sebagai peserta
        alur. Kalau akses bacanya ikut membuka jalur tulis, atasan bisa
        membetulkan sendiri dokumen yang ia minta perbaiki.
        """
        leave = self.submitted_leave()

        client = self.client_for(self.supervisor)

        self.assertEqual(
            client.post(
                f"{LEAVES}{leave.pk}/return/",
                {"notes": "Tanggalnya bentrok."},
                format="json",
            ).status_code,
            200,
        )

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.DRAFT)
        self.assertTrue(leave.is_editable)

        response = client.patch(
            f"{LEAVES}{leave.pk}/",
            {"notes": "dibetulkan atasan"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

        leave.refresh_from_db()

        self.assertNotEqual(leave.notes, "dibetulkan atasan")

    def test_can_edit_separates_the_state_from_the_reader(self):
        """
        Kontrak read-only untuk layar: `is_editable` menjawab keadaan
        **dokumennya**, `can_edit` menjawab keadaannya **untuk
        pembacanya**. Layar yang cuma membaca yang pertama akan
        menawarkan formulir yang bisa diketik lalu ditolak API.
        """
        leave = self.submitted_leave()

        owner = self.payload(self.detail(self.client_for(self.staff), leave))
        approver = self.payload(
            self.detail(self.client_for(self.supervisor), leave),
        )

        self.assertFalse(owner["is_editable"])
        self.assertFalse(owner["can_edit"])

        self.assertFalse(approver["is_editable"])
        self.assertFalse(approver["can_edit"])

        # Dikembalikan: dokumennya boleh disunting lagi — tapi hanya
        # oleh pengajunya.
        self.client_for(self.supervisor).post(
            f"{LEAVES}{leave.pk}/return/",
            {"notes": "Tanggalnya bentrok."},
            format="json",
        )

        owner = self.payload(self.detail(self.client_for(self.staff), leave))
        approver = self.payload(
            self.detail(self.client_for(self.supervisor), leave),
        )

        self.assertTrue(owner["is_editable"])
        self.assertTrue(owner["can_edit"])

        self.assertTrue(approver["is_editable"])
        self.assertFalse(approver["can_edit"])

    def test_business_fields_are_locked_by_the_same_signal(self):
        """
        Schema-nya menunjuk `can_edit`, bukan menyalin daftar status ke
        FE. Kalau kontraknya bergeser, di sinilah ketahuannya — bukan
        di layar orang.
        """
        from apps.hr.api.leave.schema import LEAVE_SCHEMA

        fields = LEAVE_SCHEMA["fields"]

        for name in (
            "employee",
            "leave_type",
            "leave_reason",
            "status",
            "start_date",
            "end_date",
            "total_days",
            "uploaded_file",
            "notes",
        ):
            with self.subTest(field=name):
                self.assertEqual(
                    fields[name].get("readonly_when"),
                    {"field": "can_edit", "op": "is_false"},
                )

        # Sinyalnya sendiri tidak boleh jadi kolom tabel.
        self.assertFalse(fields["can_edit"].get("table"))


# ----------------------------------------------------------------------
# 3 — memutuskan
# ----------------------------------------------------------------------


class LeaveWorkflowActionTestCase(LeaveAccessTestBase):
    def setUp(self):
        super().setUp()

        self.give_balance(self.staff, 5)

    def test_supervisor_then_hr_manager_closes_it_approved(self):
        """Rantai HO yang disepakati, dijalankan lewat API dokumennya."""
        leave = self.submitted_leave()

        self.assertEqual(
            self.client_for(self.supervisor)
            .post(f"{LEAVES}{leave.pk}/approve/")
            .status_code,
            200,
        )

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.SUBMITTED)
        self.assertEqual(self.balance().used, Decimal("0.0"))

        self.assertEqual(
            self.client_for(self.hr_manager)
            .post(f"{LEAVES}{leave.pk}/approve/")
            .status_code,
            200,
        )

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.APPROVED)

        self.assertEqual(self.instance_for(leave).status, InstanceStatus.APPROVED)

        balance = self.balance()

        self.assertEqual(balance.used, Decimal("2.0"))
        self.assertEqual(balance.remaining, Decimal("3.0"))

    def test_unrelated_employee_cannot_approve(self):
        leave = self.submitted_leave()

        response = self.client_for(self.bystander).post(
            f"{LEAVES}{leave.pk}/approve/",
        )

        self.assertEqual(response.status_code, 404)

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.SUBMITTED)

    def test_hr_manager_cannot_jump_the_queue(self):
        """
        Melihat duluan bukan berarti boleh memutuskan duluan. Ditolak
        `check_right`, dan alasannya menyebut siapa yang sedang
        ditunggu.
        """
        leave = self.submitted_leave()

        response = self.client_for(self.hr_manager).post(
            f"{LEAVES}{leave.pk}/approve/",
        )

        self.assertEqual(response.status_code, 400)

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.SUBMITTED)

    def test_owner_cannot_approve_their_own_leave(self):
        leave = self.submitted_leave()

        response = self.client_for(self.staff).post(
            f"{LEAVES}{leave.pk}/approve/",
        )

        self.assertEqual(response.status_code, 400)

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.SUBMITTED)


# ----------------------------------------------------------------------
# 4 — dikembalikan lalu diperbaiki
# ----------------------------------------------------------------------


class LeaveReturnFlowTestCase(LeaveAccessTestBase):
    """
    Semantik Return **yang sudah ada di engine**, dikunci apa adanya —
    bukan yang diinginkan berkas ini.

    `WorkflowService.send_back`: baris berjalan ditandai RETURNED, sisa
    baris pending dibatalkan, instance-nya RETURNED dan `current_step`
    dikosongkan. Handler modul cuti memetakan RETURNED → DRAFT, jadi
    dokumennya bisa disunting lagi.

    `WorkflowService.submit` atas dokumen yang RETURNED **menutup
    pengajuan lama sebagai CANCELLED lalu membuat instance baru** —
    jadi pengajuan ulang berangkat dari meja pertama lagi, siapa pun
    yang mengembalikannya. Itu perilaku engine, tertulis di kodenya,
    dan berkas ini menguncinya supaya tidak bergeser diam-diam.
    """

    def setUp(self):
        super().setUp()

        self.give_balance(self.staff, 5)

    def _return_it(self, leave, by):
        return self.client_for(by).post(
            f"{LEAVES}{leave.pk}/return/",
            {"notes": "Tanggalnya bentrok, tolong diperbaiki."},
            format="json",
        )

    def test_return_from_the_supervisor_sends_it_back_to_the_requester(self):
        leave = self.submitted_leave()

        response = self._return_it(leave, self.supervisor)

        self.assertEqual(response.status_code, 200)

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.DRAFT)

        instance = self.instance_for(leave)

        self.assertEqual(instance.status, InstanceStatus.RETURNED)
        self.assertIsNone(instance.current_step_id)

        # Saldonya tidak bergerak — dokumennya belum pernah disetujui.
        self.assertEqual(self.balance().used, Decimal("0.0"))

    def test_requester_can_correct_and_resubmit_after_a_return(self):
        leave = self.submitted_leave()

        self._return_it(leave, self.supervisor)

        client = self.client_for(self.staff)

        self.assertEqual(
            client.patch(
                f"{LEAVES}{leave.pk}/",
                {"notes": "Tanggal sudah dibetulkan."},
                format="json",
            ).status_code,
            200,
        )

        self.assertEqual(
            client.post(f"{LEAVES}{leave.pk}/submit/").status_code,
            200,
        )

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.SUBMITTED)
        self.assertEqual(leave.notes, "Tanggal sudah dibetulkan.")

        # Pengajuan ulang = instance baru, berangkat dari meja pertama.
        instance = self.instance_for(leave)

        self.assertEqual(instance.status, InstanceStatus.PENDING)
        self.assertEqual(instance.current_step.sequence, 1)

        self.assertEqual(
            instance.current_step.name,
            "Approved By (Atasan Langsung)",
        )

    def test_the_returned_instance_is_kept_as_history(self):
        """
        Jejak siapa yang mengembalikan dan alasannya tidak boleh hilang
        gara-gara dokumennya diajukan ulang.
        """
        leave = self.submitted_leave()

        self._return_it(leave, self.supervisor)

        first = self.instance_for(leave)

        self.client_for(self.staff).post(f"{LEAVES}{leave.pk}/submit/")

        first.refresh_from_db()

        self.assertEqual(first.status, InstanceStatus.CANCELLED)

        self.assertEqual(
            WorkflowInstance.objects.filter(
                module="hr",
                document_type="leave_request",
                object_id=str(leave.pk),
            ).count(),
            2,
        )

    def test_return_from_the_hr_manager_restarts_at_the_first_desk(self):
        """
        Yang mengembalikan meja terakhir, tapi pengajuan ulangnya tetap
        berangkat dari meja pertama — atasan langsung menilai ulang isi
        yang sudah berubah. Ini perilaku engine yang sudah ada, bukan
        keputusan baru berkas ini.
        """
        leave = self.submitted_leave()

        self.client_for(self.supervisor).post(f"{LEAVES}{leave.pk}/approve/")

        response = self._return_it(leave, self.hr_manager)

        self.assertEqual(response.status_code, 200)

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.DRAFT)
        self.assertEqual(self.balance().used, Decimal("0.0"))

        client = self.client_for(self.staff)

        client.patch(
            f"{LEAVES}{leave.pk}/",
            {"notes": "Sudah dilengkapi."},
            format="json",
        )

        self.assertEqual(
            client.post(f"{LEAVES}{leave.pk}/submit/").status_code,
            200,
        )

        instance = self.instance_for(leave)

        self.assertEqual(instance.current_step.sequence, 1)

        self.assertEqual(
            [row.sequence for row in instance.approvals.order_by("sequence")],
            [1, 3],
        )

    def test_a_returned_document_stays_closed_to_everyone_else(self):
        leave = self.submitted_leave()

        self._return_it(leave, self.supervisor)

        self.assertEqual(
            self.detail(self.client_for(self.bystander), leave).status_code,
            404,
        )
