"""
Mengunci alur cuti kantor pusat (`HR-HO-LEAVE`) apa adanya.

Ditulis sebagai **audit**, bukan sebagai perbaikan: yang dikunci di
sini adalah perilaku yang benar-benar berjalan hari ini, supaya
pertanyaan "kenapa meja HR Manager dilewati" punya jawaban yang bisa
dijalankan ulang, bukan cuma tangkapan layar.

Tiga hal yang dibuktikan, dan ketiganya sempat tertukar saat dibaca
dari layar Running Documents:

1. **Dokumen pegawai kantor pusat memang memakai `HR-HO-LEAVE`**, bukan
   alur standar. Kalau ini yang salah, seluruh pertanyaan berikutnya
   menanyakan alur yang bukan alur yang berjalan.

2. **Rantainya dua meja: Atasan Langsung → HR Manager.** Meja Kepala
   Departemen **dihapus** dari seed atas keputusan pemilik aturannya
   (21 Ags 2026), dan syarat `total_days >= 5` di meja HR Manager
   **dicabut** (20 Ags 2026) — HR Manager menandatangani semua cuti
   kantor pusat. Dikunci dua arah: cuti 1 hari dan cuti 5 hari
   sama-sama mendarat di kotak masuk Sarah Wibowo lewat cakupan
   `location`, dan tidak ada satu pun kotak Kepala Departemen yang
   ikut terbit.

3. **Saldo tidak bergerak sampai alurnya benar-benar selesai.** DRAFT
   nol, SUBMITTED nol, APPROVED baru memotong.

Alurnya dibangun lewat `apps.workflow.seeds.workflows.seed()` yang
sungguhan, bukan disusun tangan di test. Rantai yang disalin ke test
akan tetap hijau setelah seed-nya berubah, dan itu justru kebalikan
dari yang dibutuhkan berkas ini.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from apps.core.testing.tenant import ReusableTenantTestCase

from apps.accounts.models import Role
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
    EmployeeLeave,
    EmploymentAssignment,
    LeaveBalance,
    LeaveStatus,
    OrganizationAssignment,
)
from apps.workflow.models import (
    ApprovalStatus,
    InstanceStatus,
    WorkflowDefinition,
)
from apps.workflow.seeds import workflows as workflow_seed
from apps.workflow.services.workflow_service import WorkflowService


@contextmanager
def fictional_demo_inbox():
    """
    Kotak masuk peragaan **fiktif** untuk test.

    Alamat sungguhan tetap milik `demo_accounts` (DEMO-1E); test tidak
    perlu, dan tidak boleh, menyebut kotak masuk orang sungguhan. Yang
    diuji tetap sama persis — alamat dibentuk subaddress
    `<INBOX_LOCAL>+<alias>@<INBOX_DOMAIN>` dari konstanta modul — cuma
    konstantanya diganti domain uji, dan `DEMO_EMAILS` (dihitung saat
    impor) dibangun ulang dari kotak masuk yang sama.
    """
    from apps.hr.seeds import demo_accounts

    with mock.patch.multiple(
        demo_accounts,
        INBOX_LOCAL="demo-inbox",
        INBOX_DOMAIN="example.test",
    ):
        rebuilt = {
            username: demo_accounts.demo_address(alias)
            for username, alias in demo_accounts.DEMO_EMAIL_ALIASES.items()
        }

        with mock.patch.dict(demo_accounts.DEMO_EMAILS, rebuilt, clear=True):
            yield


YEAR = 2026

# Senin. Rentangnya dijangkarkan supaya jumlah hari kerjanya tidak
# bergantung pada hari apa test dijalankan.
MONDAY = date(2026, 8, 3)

JOIN_DATE = date(2020, 3, 10)


class HeadOfficeLeaveFlowTestBase(ReusableTenantTestCase):
    reusable_schema_name = "fast_leave_ho"

    """
    Panggung sekecil mungkin yang masih membuat `HR-HO-LEAVE` terpilih.

    Kode lokasinya `JKT-HO` — salah satu yang dicari
    `HEAD_OFFICE_CODES`. Kalau lokasinya dinamai lain, seed melewatkan
    alur HO-nya dengan pesan dan seluruh berkas ini menguji alur
    standar tanpa satu pun test yang gagal.
    """

    @classmethod
    def build_baseline(cls):

        User = get_user_model()

        cls.company, _ = Company.objects.get_or_create(
            code='HOL',
            is_deleted=False,
            defaults={
                "name": 'HO Leave Co',
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
            code='HOL-FIN',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": 'Finance',
            },
        )

        cls.calendar, _ = WorkCalendar.objects.get_or_create(
            code='HOL-OFFICE',
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
            code='HOL-ANNUAL',
            is_deleted=False,
            defaults={
                "name": 'Cuti Tahunan',
            },
        )

        cls.policy, _ = LeavePolicy.objects.get_or_create(
            code='HOL-ANNUAL-STD',
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

        # Alur + role dari seed sungguhan.
        cls.seed_result = workflow_seed.seed()

        cls.ho_leave = WorkflowDefinition.objects.filter(
            code="HR-HO-LEAVE",
            is_deleted=False,
        ).first()

        # Pegawai: staf → atasan langsung. Susunannya meniru HO003 →
        # HO005 di data uji.
        cls.supervisor = cls._make_employee(
            number="HOL0002",
            first_name="Farah",
            last_name="Anindita",
            username="hol.supervisor",
        )

        cls.staff = cls._make_employee(
            number="HOL0001",
            first_name="Bimo",
            last_name="Nugroho",
            username="hol.staff",
            reports_to=cls.supervisor,
        )

        # HR Manager kantor pusat — pemegang role, di lokasi yang sama
        # dengan pegawainya. Inilah yang dicari meja #3 dengan cakupan
        # `location`.
        cls.hr_manager = cls._make_employee(
            number="HOL0003",
            first_name="Sarah",
            last_name="Wibowo",
            username="hol.hrmanager",
            roles=["HR-MANAGER"],
        )

        cls.User = User

    _position_counter = 0

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
        is_manager: bool = False,
        location=None,
    ) -> Employee:
        User = get_user_model()

        cls._position_counter += 1

        position = Position.objects.create(
            company=cls.company,
            department=cls.department,
            code=f"HOL-POS{cls._position_counter}",
            name=f"Jabatan {cls._position_counter}",
            is_manager=is_manager,
        )

        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.test",
            password="Test-Only#Pw1",
            first_name=first_name,
            last_name=last_name,
        )

        if roles:
            user.roles.set(
                Role.objects.filter(code__in=roles, is_deleted=False),
            )

        employee = Employee.objects.create(
            employee_number=number,
            first_name=first_name,
            last_name=last_name,
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=location or cls.head_office,
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

    def give_balance(self, employee, days, *, year=YEAR):
        return LeaveBalance.objects.create(
            employee=employee,
            leave_type=self.annual,
            year=year,
            entitlement=Decimal(days),
        )

    def make_leave(self, employee, *, start, end, total_days):
        return EmployeeLeaveService.create(
            data={
                "employee": employee,
                "leave_type": self.annual,
                "start_date": start,
                "end_date": end,
                "total_days": Decimal(total_days),
                "status": LeaveStatus.DRAFT,
            },
        )

    @staticmethod
    def rows(instance):
        return list(
            instance.approvals
            .select_related("step", "approver")
            .order_by("sequence", "id")
        )

    @staticmethod
    def balance_of(employee, leave_type, year=YEAR):
        return LeaveBalance.objects.get(
            employee=employee,
            leave_type=leave_type,
            year=year,
        )


# ----------------------------------------------------------------------
# 1 — alur mana yang terpilih
# ----------------------------------------------------------------------


class HeadOfficeLeaveSelectionTestCase(HeadOfficeLeaveFlowTestBase):
    """Dokumen pegawai kantor pusat memakai `HR-HO-LEAVE`."""

    def test_seed_creates_the_head_office_flow(self):
        self.assertIsNotNone(
            self.ho_leave,
            "Seed tidak membuat HR-HO-LEAVE — lokasi kantor pusatnya "
            f"tidak ketemu. Dilewati: {self.seed_result['skipped']}",
        )

        self.assertEqual(self.ho_leave.location_id, self.head_office.pk)

    def test_submitted_leave_runs_on_the_head_office_flow(self):
        self.give_balance(self.staff, 5)

        leave = self.make_leave(
            self.staff,
            start=MONDAY,
            end=MONDAY,
            total_days=1,
        )

        workflow = EmployeeLeaveService.submit(
            instance=leave,
            user=self.staff.user,
        )

        self.assertEqual(workflow.definition.code, "HR-HO-LEAVE")

    def test_the_seeded_chain_is_manager_then_hr_manager(self):
        """
        Rantai yang diseed, dan yang memang diminta pemilik aturannya:
        pegawai mengajukan → Atasan Langsung → HR Manager. **Dua meja**,
        tanpa Kepala Departemen.

        Dikunci supaya perubahan rantai tidak bisa lewat tanpa ada yang
        menyetujuinya. Nomor mejanya 1 lalu 3, bukan 1 lalu 2: baris
        Kepala Departemen dipensiunkan di tempatnya supaya dokumen lama
        tidak berubah bunyinya — lihat komentarnya di
        `HEAD_OFFICE_LEAVE_STEPS`.
        """
        steps = list(
            self.ho_leave.steps
            .filter(is_deleted=False, is_active=True)
            .order_by("sequence")
        )

        self.assertEqual(
            [(row.sequence, row.approver_type) for row in steps],
            [(1, "manager"), (3, "role")],
        )

        self.assertEqual(steps[1].approver_role.code, "HR-MANAGER")
        self.assertEqual(steps[1].approver_scope, "location")
        self.assertEqual(steps[1].fallback_role.code, "HR-ADMIN")
        self.assertTrue(steps[1].is_required)

        # Syaratnya kosong, dan itu bagian dari definisi rantainya:
        # meja terakhir berdiri untuk **setiap** cuti kantor pusat.
        self.assertIn(steps[1].condition, ({}, None))

    def test_no_department_head_desk_survives_in_the_flow(self):
        """
        Meja Kepala Departemen tidak boleh ada lagi — dalam bentuk apa
        pun, termasuk sebagai meja "sepengetahuan" yang tinggal
        dilewati.

        Diperiksa lewat `approver_type`, bukan lewat nomor urut: meja
        yang dihidupkan lagi dengan nomor lain akan lolos dari test
        rantai di atas kalau yang dicocokkan cuma panjang daftarnya.
        """
        self.assertFalse(
            self.ho_leave.steps
            .filter(
                is_deleted=False,
                is_active=True,
                approver_type="department_head",
            )
            .exists(),
        )


# ----------------------------------------------------------------------
# 2 — meja #3 berdiri untuk semua cuti
# ----------------------------------------------------------------------


class HeadOfficeLeaveStepThreeTestCase(HeadOfficeLeaveFlowTestBase):
    """
    Meja HR Manager: tanpa syarat, dan approver-nya memang ketemu.

    Berkas ini pernah mengunci kebalikannya — meja #3 bersyarat
    `total_days >= 5`, jadi cuti dua hari melewatinya. Syarat itu
    **dicabut** (20 Ags 2026); yang dikunci sekarang adalah bahwa
    pencabutannya benar-benar berlaku, dan bahwa yang dulu menutupi
    masalahnya tidak kembali diam-diam.

    Dua kegagalan yang sama-sama menghasilkan baris tanpa approver, dan
    keduanya diperiksa terpisah: syarat yang tidak terpenuhi menulis
    "Syarat step ini tidak terpenuhi oleh dokumen." dan membekukan
    syaratnya di `metadata`; approver yang tidak ketemu menulis
    "Dilewati otomatis — <alasan resolver>". Kalau meja ini suatu saat
    kosong lagi, yang membedakan sebabnya adalah dua kalimat itu —
    bukan tangkapan layar.
    """

    def test_step_three_carries_no_condition(self):
        """
        Kosong, dan itu inti perubahannya.

        `{}` berarti "mejanya selalu ada". Baris ini yang pertama gagal
        kalau ada yang mengembalikan syaratnya ke seed tanpa
        menyetujuinya lebih dulu.
        """
        step = self.ho_leave.steps.get(sequence=3)

        self.assertEqual(step.condition, {})

        self.assertTrue(step.is_required)

    def test_short_leave_now_reaches_the_hr_manager(self):
        """
        Cuti 2 hari — kasus UAT Bimo. Dulu SKIPPED, sekarang PENDING di
        kotak masuk Sarah Wibowo.
        """
        self.give_balance(self.staff, 5)

        leave = self.make_leave(
            self.staff,
            start=MONDAY,
            end=date(2026, 8, 4),
            total_days=2,
        )

        workflow = EmployeeLeaveService.submit(
            instance=leave,
            user=self.staff.user,
        )

        row = workflow.approvals.get(sequence=3)

        self.assertEqual(row.status, ApprovalStatus.PENDING)
        self.assertEqual(row.approver_id, self.hr_manager.user_id)

        # Bukan sekadar "tidak SKIPPED": kalimat inilah yang dulu
        # tertulis di barisnya, dan ia tidak boleh ada lagi.
        self.assertNotEqual(
            row.assignment_reference,
            "Syarat step ini tidak terpenuhi oleh dokumen.",
        )

        self.assertIsNone(row.metadata.get("condition"))

    def test_one_day_leave_reaches_it_too(self):
        """
        Batas bawahnya ikut dikunci. Syarat yang dicabut setengah —
        mis. diganti `gte 2` — akan lolos dari test dua hari di atas
        tapi gagal di sini.
        """
        self.give_balance(self.staff, 5)

        leave = self.make_leave(
            self.staff,
            start=MONDAY,
            end=MONDAY,
            total_days=1,
        )

        workflow = EmployeeLeaveService.submit(
            instance=leave,
            user=self.staff.user,
        )

        row = workflow.approvals.get(sequence=3)

        self.assertEqual(row.status, ApprovalStatus.PENDING)
        self.assertEqual(row.approver_id, self.hr_manager.user_id)

    def test_long_leave_resolves_the_hr_manager_at_the_location(self):
        """
        Cuti 5 hari: mejanya terisi Sarah Wibowo, lewat cakupan
        `location` dan bukan cadangan HR-ADMIN.

        Cakupannya yang dikunci, bukan cuma orangnya: tanpa
        `approver_scope = location`, cuti pegawai kantor pusat ikut
        menarik HR Manager site — keduanya memegang role yang sama, dan
        yang menandatangani jadi ditentukan urutan `employee_number`.
        """
        self.give_balance(self.staff, 10)

        leave = self.make_leave(
            self.staff,
            start=MONDAY,
            end=date(2026, 8, 7),
            total_days=5,
        )

        workflow = EmployeeLeaveService.submit(
            instance=leave,
            user=self.staff.user,
        )

        row = workflow.approvals.get(sequence=3)

        self.assertEqual(row.status, ApprovalStatus.PENDING)
        self.assertEqual(row.approver_id, self.hr_manager.user_id)

        self.assertEqual(
            row.metadata.get("resolved_scope"),
            "location",
        )

        self.assertEqual(
            row.metadata.get("resolved_role"),
            "HR-MANAGER",
        )

    def test_two_day_leave_still_creates_the_hr_manager_task(self):
        """
        **Regresi utama task ini.** Cuti kantor pusat 2 hari — persis
        kasus UAT Bimo — tetap menerbitkan tugas persetujuan HR Manager.

        Yang dikunci bukan cuma barisnya ada, melainkan seluruh daftar
        tugasnya: dua kotak, Atasan Langsung lalu HR Manager, keduanya
        PENDING dan keduanya terisi orang. Baris ini yang gagal kalau
        syarat jumlah hari dikembalikan diam-diam, kalau meja HR
        Manager dinonaktifkan, atau kalau ada meja ketiga yang
        dihidupkan lagi.
        """
        self.give_balance(self.staff, 5)

        leave = self.make_leave(
            self.staff,
            start=MONDAY,
            end=date(2026, 8, 4),
            total_days=2,
        )

        workflow = EmployeeLeaveService.submit(
            instance=leave,
            user=self.staff.user,
        )

        self.assertEqual(
            [
                (row.sequence, row.name, row.status, row.approver_id)
                for row in self.rows(workflow)
            ],
            [
                (
                    1,
                    "Approved By (Atasan Langsung)",
                    ApprovalStatus.PENDING,
                    self.supervisor.user_id,
                ),
                (
                    3,
                    "Approved By (HR Manager)",
                    ApprovalStatus.PENDING,
                    self.hr_manager.user_id,
                ),
            ],
        )

        # Dokumennya berdiri di meja pertama, dan meja HR Manager
        # benar-benar menunggu di belakangnya — bukan baris SKIPPED
        # yang kebetulan ikut tercetak di formulir.
        self.assertEqual(workflow.current_step.sequence, 1)

    def test_no_department_head_row_is_created_for_the_document(self):
        """
        Meja Kepala Departemen **dihapus dari rantainya**, jadi kotak
        tanda tangannya tidak terbit sama sekali — tidak juga sebagai
        baris SKIPPED.

        Bedanya penting: sampai 20 Ags 2026 meja itu masih ada dan
        cuma dilewati, dan formulir yang mencetak kotak SKIPPED
        terbaca seolah alurnya masih melewati Kepala Departemen.
        """
        self.give_balance(self.staff, 5)

        leave = self.make_leave(
            self.staff,
            start=MONDAY,
            end=date(2026, 8, 4),
            total_days=2,
        )

        workflow = EmployeeLeaveService.submit(
            instance=leave,
            user=self.staff.user,
        )

        self.assertFalse(
            workflow.approvals.filter(sequence=2).exists(),
        )

        self.assertFalse(
            workflow.approvals
            .filter(step__approver_type="department_head")
            .exists(),
        )


# ----------------------------------------------------------------------
# 3 — saldo
# ----------------------------------------------------------------------


class HeadOfficeLeaveBalanceTimingTestCase(HeadOfficeLeaveFlowTestBase):
    """
    Saldo bergerak **hanya** saat status dokumennya jadi APPROVED.

    Angka yang benar tidak cukup: kalau saldo terpotong saat submit,
    kartu tetap terbaca benar selama pengajuannya disetujui — dan baru
    salah pada pengajuan yang ditolak. Karena itu tiap tahap diperiksa
    sendiri, bukan cuma hasil akhirnya.
    """

    def setUp(self):
        super().setUp()

        self.give_balance(self.staff, 5)

    def test_draft_does_not_touch_the_balance(self):
        self.make_leave(
            self.staff,
            start=MONDAY,
            end=date(2026, 8, 4),
            total_days=2,
        )

        balance = self.balance_of(self.staff, self.annual)

        self.assertEqual(balance.used, Decimal("0.0"))
        self.assertEqual(balance.remaining, Decimal("5.0"))

    def test_submitted_does_not_touch_the_balance(self):
        leave = self.make_leave(
            self.staff,
            start=MONDAY,
            end=date(2026, 8, 4),
            total_days=2,
        )

        EmployeeLeaveService.submit(instance=leave, user=self.staff.user)

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.SUBMITTED)

        balance = self.balance_of(self.staff, self.annual)

        self.assertEqual(balance.used, Decimal("0.0"))
        self.assertEqual(balance.remaining, Decimal("5.0"))

    def test_balance_posts_only_when_the_flow_closes_approved(self):
        """
        5 → used 2 → sisa 3, dan **setelah meja terakhir**, bukan
        setelah meja pertama.

        Sejak syarat 5 hari dicabut, cuti dua hari butuh **dua** tanda
        tangan: Atasan Langsung lalu HR Manager. Yang dikunci di sini
        justru jeda di antaranya — saldo yang terpotong saat atasan
        menekan Approve akan tetap terbaca benar selama dokumennya
        akhirnya disetujui HR Manager, dan baru salah pada dokumen yang
        ditolak di meja terakhir.
        """
        leave = self.make_leave(
            self.staff,
            start=MONDAY,
            end=date(2026, 8, 4),
            total_days=2,
        )

        workflow = EmployeeLeaveService.submit(
            instance=leave,
            user=self.staff.user,
        )

        self.assertEqual(workflow.status, InstanceStatus.PENDING)

        # Masih utuh sementara dokumennya di meja atasan.
        self.assertEqual(
            self.balance_of(self.staff, self.annual).used,
            Decimal("0.0"),
        )

        def close(wf, status):
            return EmployeeLeaveService.apply_workflow_status(
                instance=leave,
                status=status,
                user=self.hr_manager.user,
            )

        WorkflowService.approve(
            instance=workflow,
            user=self.supervisor.user,
            on_complete=close,
        )

        workflow.refresh_from_db()

        # Meja Kepala Departemen sudah tidak ada di rantainya, jadi
        # dokumennya langsung berdiri di meja HR Manager — dan alurnya
        # **belum** selesai.
        self.assertEqual(workflow.status, InstanceStatus.PENDING)

        self.assertEqual(
            workflow.approvals.get(sequence=3).status,
            ApprovalStatus.PENDING,
        )

        # Dan saldonya masih utuh. Inilah baris yang gagal kalau ada
        # yang memindahkan potongan saldo ke meja pertama.
        self.assertEqual(
            self.balance_of(self.staff, self.annual).used,
            Decimal("0.0"),
        )

        WorkflowService.approve(
            instance=workflow,
            user=self.hr_manager.user,
            on_complete=close,
        )

        workflow.refresh_from_db()
        leave.refresh_from_db()

        self.assertEqual(workflow.status, InstanceStatus.APPROVED)
        self.assertEqual(leave.status, LeaveStatus.APPROVED)

        balance = self.balance_of(self.staff, self.annual)

        self.assertEqual(balance.used, Decimal("2.0"))
        self.assertEqual(balance.remaining, Decimal("3.0"))

    def test_rejection_leaves_the_balance_untouched(self):
        leave = self.make_leave(
            self.staff,
            start=MONDAY,
            end=date(2026, 8, 4),
            total_days=2,
        )

        workflow = EmployeeLeaveService.submit(
            instance=leave,
            user=self.staff.user,
        )

        WorkflowService.reject(
            instance=workflow,
            user=self.supervisor.user,
            comment="Tanggalnya bentrok.",
            on_complete=lambda wf, status: (
                EmployeeLeaveService.apply_workflow_status(
                    instance=leave,
                    status=status,
                    user=self.supervisor.user,
                )
            ),
        )

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.REJECTED)

        balance = self.balance_of(self.staff, self.annual)

        self.assertEqual(balance.used, Decimal("0.0"))
        self.assertEqual(balance.remaining, Decimal("5.0"))

    def test_no_leave_row_writes_the_balance_directly(self):
        """
        `LeaveBalance.used` hanya boleh ditulis `LeaveBalanceService`.

        Penjagaan terhadap kemunduran: begitu ada yang memotong saldo
        dengan `F("used") + days` di modul mana pun, penjumlahan ulang
        berhenti jadi satu-satunya kebenaran dan selisihnya hanyut
        tanpa berbunyi.
        """
        import inspect

        from apps.hr.api.leave import services as leave_services

        source = inspect.getsource(leave_services)

        self.assertNotIn("used=F(", source)
        self.assertNotIn("used=models.F(", source)

        # Satu-satunya jalan potong saldo di modul ini.
        self.assertIn("LeaveBalanceService.recalculate_used", source)


# ----------------------------------------------------------------------
# 4 — email akun peragaan
# ----------------------------------------------------------------------


class DemoAccountEmailTestCase(ReusableTenantTestCase):
    reusable_schema_name = "fast_leave_ho_email"

    """
    Daftar email akun peragaan: satu sumber, dipakai dua seed.

    Yang dijaga di sini bukan alamatnya (itu boleh berubah), melainkan
    bahwa dua seed pembentuk akun membaca daftar yang **sama**. Dua
    rumus alamat berarti seed mana yang dijalankan terakhir menentukan
    siapa yang menerima surat approval, dan bedanya tidak terlihat di
    layar mana pun.
    """

    def test_both_seeds_read_the_shared_mapping(self):
        import inspect

        from apps.hr.seeds import demo_employees, demo_workforce

        for module in (demo_employees, demo_workforce):
            source = inspect.getsource(module)

            with self.subTest(module=module.__name__):
                self.assertIn("demo_email(", source)

                # Rumus lama yang diturunkan sendiri sudah tidak ada
                # lagi di jalur akun.
                self.assertNotIn('f"{username}@example.test"', source)
                self.assertNotIn(
                    'f"{person.username}@example.test"',
                    source,
                )

    def test_workflow_actors_have_a_deliverable_address(self):
        from apps.hr.seeds.demo_accounts import DEMO_EMAILS, demo_email

        for username in (
            "demo.hostaff",
            "demo.homanager",
            "demo.hradmin",
            "demo.hrmanager",
            "demo.hrga",
            "demo.siteadmin",
            "demo.deptadmin",
            "demo.ktt",
        ):
            with self.subTest(username=username):
                self.assertIn(username, DEMO_EMAILS)
                self.assertNotIn("example.test", demo_email(username))

    def test_every_seeded_account_has_a_deliverable_address(self):
        """
        Bukan cuma pemegang meja.

        Meja alur persetujuan berpindah tiap susunan perannya disusun
        ulang, dan approver yang baru ikut kemarin tidak akan ada di
        daftar pemegang meja hari ini. Kalau yang di luar daftar jatuh
        ke domain buntu, dokumen yang mampir ke sana melaporkan
        notifikasi terkirim tanpa satu pun surat yang bisa dibuka —
        dan itu terbaca persis seperti alur yang berhenti.
        """
        from apps.hr.seeds import demo_employees, demo_workforce
        from apps.hr.seeds.demo_accounts import (
            DEMO_EMAILS,
            INBOX_DOMAIN,
            INBOX_LOCAL,
        )

        usernames = {
            person.username
            for person in demo_employees.PEOPLE
            if person.username
        }
        usernames |= {
            username for username, _ in demo_workforce.USERS.values()
        }

        self.assertTrue(usernames)

        for username in sorted(usernames):
            with self.subTest(username=username):
                # Terdaftar, bukan cuma kebetulan lolos lewat alias
                # cadangan: daftar itu yang dibaca saat mencari siapa
                # penerima sebuah surat.
                self.assertIn(username, DEMO_EMAILS)

                address = DEMO_EMAILS[username]

                self.assertTrue(address.startswith(f"{INBOX_LOCAL}+"))
                self.assertTrue(address.endswith(f"@{INBOX_DOMAIN}"))

    def test_unlisted_accounts_still_reach_the_inbox(self):
        """
        Akun peragaan yang lupa didaftarkan **tidak** boleh kembali ke
        domain buntu. Yang hilang seharusnya cuma aliasnya yang rapi,
        bukan kemampuan alamatnya menerima surat.
        """
        from apps.hr.seeds.demo_accounts import DEMO_EMAILS, demo_email

        self.assertNotIn("demo.belum.terdaftar", DEMO_EMAILS)

        with fictional_demo_inbox():
            self.assertEqual(
                demo_email("demo.belum.terdaftar"),
                "demo-inbox+belumterdaftar@example.test",
            )

    def test_system_account_is_not_a_demo_account(self):
        """
        `admin` dibentuk `create_superadmin`, bukan seed peragaan, dan
        tidak berawalan `demo.` — jadi penyelaras email tidak akan
        pernah menyentuhnya walau dijalankan di tenant mana pun.
        """
        from apps.hr.seeds.demo_accounts import USERNAME_PREFIX

        self.assertFalse("admin".startswith(USERNAME_PREFIX))

    def test_sync_updates_existing_accounts_without_creating_any(self):
        """
        Yang diperbaiki adalah akun yang **sudah ada**.

        Dua seed pembentuk akun sudah menulis ulang emailnya tiap
        dijalankan, tapi keduanya hanya menyentuh akun yang ada di
        daftar masing-masing. Akun yang dibentuk seed satunya tetap
        memegang alamat lamanya, dan tidak ada baris keluaran yang
        menyebutkannya.
        """
        from django.contrib.auth import get_user_model

        from apps.hr.seeds import demo_account_emails

        User = get_user_model()

        stale = User.objects.create(
            username="demo.hostaff",
            email="demo.hostaff@example.test",
        )
        before = User.objects.count()

        with fictional_demo_inbox():
            result = demo_account_emails.run(log=lambda _: None)

            stale.refresh_from_db()

            self.assertEqual(stale.email, "demo-inbox+employee@example.test")
            self.assertEqual(User.objects.count(), before)
            self.assertEqual(result["changed"], 1)

            # Dijalankan kedua kali tidak menulis apa-apa lagi.
            again = demo_account_emails.run(log=lambda _: None)

            self.assertEqual(again["changed"], 0)
            self.assertEqual(again["unchanged"], result["total"])

    def test_addresses_are_unique_per_account(self):
        """
        Dua meja yang berbagi alamat tidak bisa dibedakan penerimanya —
        dan itu persis pertanyaan yang mau dijawab trial email.
        """
        from apps.hr.seeds.demo_accounts import DEMO_EMAILS

        addresses = list(DEMO_EMAILS.values())

        self.assertEqual(len(addresses), len(set(addresses)))
