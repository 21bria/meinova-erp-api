"""
Mengunci jalur **pengajuan** cuti terhadap Leave Policy.

Bedanya dengan `test_non_balance_policy`: yang itu menguji arah
**kartu** (jatah terbit atau tidak), yang ini menguji arah **dokumen** —
apa yang terjadi saat seseorang benar-benar membuat pengajuannya.
Keduanya berangkat dari `LeavePolicyResolver` yang sama, dan itu justru
alasan keduanya perlu dikunci terpisah: aturan yang menang untuk kartu
seseorang harus aturan yang menang untuk pengajuannya.

Empat kegagalan yang dijaga di sini, dan **tiga di antaranya diam**:

1. Saldo tidak pernah diperiksa. Pegawai bersisa 2 hari mengajukan 3
   hari, dokumennya tersimpan, disetujui, lalu kartunya berbunyi −1 —
   dan tidak ada satu pun pesan di sepanjang jalan itu. Ini keadaan
   sebelum perubahan ini.
2. Saldo diperiksa terhadap sisa yang **sudah dikurangi dokumen itu
   sendiri**. Cuti 3 hari yang diperpanjang jadi 4 ditolak walau
   saldonya jelas cukup, dengan angka yang tidak cocok dengan angka
   mana pun di kartunya.
3. Jenis cuti tanpa saldo ikut diperiksa saldonya. Setiap cuti menikah
   ditolak oleh angka yang memang tidak pernah ada.
4. Resolver memakai pegawai yang **login**, bukan pegawai pemilik
   dokumen. Admin Section yang mengajukan untuk anak buahnya mendapat
   kalender, saldo, dan alur miliknya sendiri.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from apps.core.testing.tenant import ReusableTenantTestCase

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
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    LeaveBalance,
    LeaveStatus,
    OrganizationAssignment,
)
from apps.workflow.models import WorkflowDefinition, WorkflowStatus
from apps.workflow.services.definition_service import (
    WorkflowDefinitionResolver,
)


YEAR = 2026

# Lama bekerja — supaya masa tunggu 12 bulan sudah lewat di seluruh
# test kecuali yang memang mengujinya.
JOIN_DATE = date(2020, 3, 10)

# Senin. Dipakai sebagai jangkar seluruh rentang supaya jumlah hari
# kerjanya tidak bergantung pada hari apa test dijalankan.
MONDAY = date(2026, 6, 1)


class LeaveRequestTestBase(ReusableTenantTestCase):
    reusable_schema_name = "fast_leave_rules"

    """Master bersama: satu company, satu kalender Senin–Jumat."""

    @classmethod
    def build_baseline(cls):

        cls.company, _ = Company.objects.get_or_create(
            code='LRQ',
            is_deleted=False,
            defaults={
                "name": 'Leave Req Co',
            },
        )

        cls.office, _ = Location.objects.get_or_create(
            code='LRQ-HO',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": 'Jakarta HO',
            },
        )

        cls.site, _ = Location.objects.get_or_create(
            code='LRQ-SITE',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": 'Gebe Site',
            },
        )

        cls.calendar, _ = WorkCalendar.objects.get_or_create(
            code='LRQ-OFFICE',
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
            code='LRQ-ANNUAL',
            is_deleted=False,
            defaults={
                "name": 'Cuti Tahunan',
            },
        )

        cls.annual_policy, _ = LeavePolicy.objects.get_or_create(
            code='LRQ-ANNUAL-STD',
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

    _counter = 0

    @classmethod
    def make_employee(
        cls,
        *,
        join_date=JOIN_DATE,
        location=None,
        calendar=None,
        roster_crew=None,
    ) -> Employee:
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"LRQ{cls._counter:04d}",
            first_name="Rian",
            last_name=f"Saputra {cls._counter}",
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

    def request_leave(
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
        `total_days` selalu dioper eksplisit kecuali test-nya memang
        sedang menguji perhitungannya. Kalau dibiarkan dihitung
        `LeaveDayCalculator`, angkanya bergantung pada hari apa tanggal
        itu jatuh — dan test yang lulus bulan ini lalu gagal bulan
        depan tidak memberi tahu siapa pun apa-apa.
        """
        span = max(int(days) - 1, 0)

        payload = {
            "employee": employee,
            "leave_type": leave_type,
            "start_date": start,
            "end_date": start + timedelta(days=span),
            "total_days": Decimal(days),
            "status": status,
            **extra,
        }

        return EmployeeLeaveService.create(data=payload)

    def report_for(self, instance):
        return EmployeeLeaveService.evaluate_rules(instance=instance)

    @staticmethod
    def codes(report):
        return {row.code for row in report.findings}


# ----------------------------------------------------------------------
# 1–2, 11 — cuti bersaldo
# ----------------------------------------------------------------------


class AnnualLeaveBalanceTestCase(LeaveRequestTestBase):
    """`uses_balance=True`: saldonya dibaca, dan kurangnya menolak."""

    def test_sufficient_balance_is_accepted(self):
        """Sisa 7, diminta 2 — lolos, dan laporannya menyebut angkanya."""
        employee = self.make_employee()

        self.give_balance(employee, self.annual, 7)

        leave = self.request_leave(employee, self.annual, days=2)

        self.assertEqual(leave.status, LeaveStatus.DRAFT)

        report = self.report_for(leave)

        self.assertNotIn("insufficient_balance", self.codes(report))
        self.assertTrue(report.balance_evaluated)
        self.assertTrue(report.balance["sufficient"])
        self.assertEqual(report.balance["available"], "7.0")
        self.assertEqual(report.balance["requested"], "2.0")

    def test_insufficient_balance_is_rejected(self):
        """Sisa 2, diminta 3 — ditolak, dan pesannya menyebut keduanya."""
        employee = self.make_employee()

        self.give_balance(employee, self.annual, 2)

        with self.assertRaises(ValidationError) as caught:
            self.request_leave(employee, self.annual, days=3)

        message = str(caught.exception)

        self.assertIn("2.0", message)
        self.assertIn("3.0", message)

    def test_used_days_shrink_the_available_balance(self):
        """
        Saldo yang dibaca adalah **sisa**, bukan jatah.

        Jatah 12 dengan 10 sudah terpakai berarti sisa 2 — dan
        pengajuan 3 hari harus ditolak walau jatahnya jelas 12.
        """
        employee = self.make_employee()

        self.give_balance(employee, self.annual, 12)

        self.request_leave(
            employee,
            self.annual,
            start=MONDAY,
            days=10,
            status=LeaveStatus.RECORDED,
        )

        with self.assertRaises(ValidationError):
            self.request_leave(
                employee,
                self.annual,
                start=MONDAY + timedelta(days=60),
                days=3,
            )

    def test_editing_a_deducting_document_returns_its_own_days(self):
        """
        Dokumen yang sudah memotong saldo mengembalikan potongannya
        sendiri sebelum diadu dengan sisanya.

        Tanpa itu, cuti RECORDED 3 hari dari jatah 5 diadu dengan sisa
        2 — dan memperpanjangnya jadi 4 ditolak walau saldonya cukup.
        """
        employee = self.make_employee()

        self.give_balance(employee, self.annual, 5)

        leave = self.request_leave(
            employee,
            self.annual,
            days=3,
            status=LeaveStatus.RECORDED,
        )

        leave.refresh_from_db()

        report = self.report_for(leave)

        # Sisa kartu 2, tapi yang tersedia untuk dokumen ini 5.
        self.assertEqual(report.balance["remaining"], "2.0")
        self.assertEqual(report.balance["available"], "5.0")
        self.assertTrue(report.balance["sufficient"])

        updated = EmployeeLeaveService.update(
            instance=leave,
            data={
                "end_date": MONDAY + timedelta(days=3),
                "total_days": Decimal("4"),
            },
        )

        self.assertEqual(updated.total_days, Decimal("4.0"))

    def test_zero_day_request_never_blocks(self):
        """
        Nol hari tidak memotong apa pun, jadi tidak ada yang bisa
        kurang. Pegawai roster yang cuti saat blok off-nya persis di
        keadaan ini — menolaknya memaksa mereka mengarang tanggal.
        """
        employee = self.make_employee()

        self.give_balance(employee, self.annual, 0)

        leave = self.request_leave(employee, self.annual, days=0)

        self.assertEqual(leave.total_days, Decimal("0.0"))

    def test_recorded_path_is_never_blocked_by_balance(self):
        """
        HR mencatat cuti yang **sudah terjadi**, dan Travel Request
        menerbitkannya sesudah alurnya disetujui. Menolak di titik itu
        berarti fakta yang sudah terjadi tidak punya tempat tersimpan,
        dan pesannya muncul di layar orang yang tidak bisa
        memperbaikinya.
        """
        employee = self.make_employee()

        self.give_balance(employee, self.annual, 1)

        leave = self.request_leave(
            employee,
            self.annual,
            days=5,
            status=LeaveStatus.RECORDED,
        )

        self.assertEqual(leave.total_days, Decimal("5.0"))

        # Tidak ditahan, tapi tetap dilaporkan — kalau temuannya ikut
        # hilang, tidak ada satu pun tanda bahwa saldonya jebol.
        leave.refresh_from_db()

        self.assertIn(
            "insufficient_balance",
            self.codes(self.report_for(leave)),
        )

    def test_missing_card_for_ineligible_employee_is_blocked(self):
        """
        Belum berhak = jatahnya memang nol, dan itu bisa dijawab tanpa
        menebak. Pesannya menyebut tanggal ia mulai berhak.
        """
        employee = self.make_employee(
            join_date=date(YEAR, 3, 1),
        )

        with self.assertRaises(ValidationError) as caught:
            self.request_leave(
                employee,
                self.annual,
                start=date(YEAR, 6, 1),
                days=2,
            )

        self.assertIn("01/03/2027", str(caught.exception))

    def test_missing_card_for_eligible_employee_only_warns(self):
        """
        Kartunya belum terbit tapi orangnya sudah berhak: ini kekurangan
        penyiapan data, bukan kesalahan pengajunya. Menolak di sini
        mengunci orang pada hal yang tidak bisa ia perbaiki sendiri.
        """
        employee = self.make_employee()

        leave = self.request_leave(employee, self.annual, days=2)

        report = self.report_for(leave)

        self.assertIn("balance_missing", self.codes(report))
        self.assertEqual(report.blocking, [])
        self.assertTrue(report.needs_review)
        self.assertFalse(report.balance["exists"])

    def test_request_never_creates_a_balance_row(self):
        """
        Pengajuan membaca kartu, tidak pernah menerbitkannya. Kalau ia
        ikut membuat baris, jatah yang belum dihitung siapa pun akan
        lahir dari layar cuti.
        """
        employee = self.make_employee()

        self.request_leave(employee, self.annual, days=2)

        self.assertEqual(
            LeaveBalance.objects.filter(
                employee=employee,
                is_deleted=False,
            ).count(),
            0,
        )


# ----------------------------------------------------------------------
# 3–7, 11 — cuti tanpa saldo
# ----------------------------------------------------------------------


class NonBalanceLeaveRequestTestCase(LeaveRequestTestBase):
    """`uses_balance=False`: saldo tidak pernah disebut sama sekali."""

    @classmethod
    def build_baseline(cls):
        super().build_baseline()

        cls.marriage = LeaveType.objects.create(
            code="LRQ-MARRIAGE",
            name="Cuti Menikah",
        )

        cls.baptism = LeaveType.objects.create(
            code="LRQ-BAPTISM",
            name="Cuti Baptis Anak",
        )

        cls.sick = LeaveType.objects.create(
            code="LRQ-SICK",
            name="Cuti Sakit",
        )

        cls.unpaid = LeaveType.objects.create(
            code="LRQ-UNPAID",
            name="Cuti Tanpa Upah",
        )

        cls.marriage_policy = LeavePolicy.objects.create(
            company=cls.company,
            leave_type=cls.marriage,
            code="LRQ-MARRIAGE-STD",
            name="Cuti Menikah 3 Hari",
            uses_balance=False,
            entitlement_days=Decimal("0"),
            max_days=Decimal("3"),
            per_event=True,
            document_required=True,
        )

        cls.baptism_policy = LeavePolicy.objects.create(
            company=cls.company,
            leave_type=cls.baptism,
            code="LRQ-BAPTISM-STD",
            name="Cuti Baptis Anak",
            uses_balance=False,
            entitlement_days=Decimal("0"),
            max_days=Decimal("1"),
            per_event=True,
            history_check=True,
            history_action=LeaveHistoryAction.REVIEW,
        )

        # Sengaja tanpa `max_days`: lamanya ditentukan surat dokter,
        # bukan oleh perusahaan.
        cls.sick_policy = LeavePolicy.objects.create(
            company=cls.company,
            leave_type=cls.sick,
            code="LRQ-SICK-STD",
            name="Cuti Sakit",
            uses_balance=False,
            entitlement_days=Decimal("0"),
        )

        cls.unpaid_policy = LeavePolicy.objects.create(
            company=cls.company,
            leave_type=cls.unpaid,
            code="LRQ-UNPAID-STD",
            name="Cuti Tanpa Upah",
            uses_balance=False,
            entitlement_days=Decimal("0"),
        )

    def test_max_days_blocks_a_longer_request(self):
        employee = self.make_employee()

        with self.assertRaises(ValidationError) as caught:
            self.request_leave(employee, self.marriage, days=5)

        self.assertIn("LRQ-MARRIAGE-STD", str(caught.exception))

    def test_max_days_allows_the_exact_limit(self):
        """Batas 3 hari berarti 3 hari boleh — bukan 2."""
        employee = self.make_employee()

        leave = self.request_leave(employee, self.marriage, days=3)

        self.assertEqual(leave.total_days, Decimal("3.0"))

    def test_history_review_warns_without_blocking(self):
        """
        Orang bisa membaptiskan anak keduanya. Yang tidak bisa
        diputuskan kode adalah apakah kejadiannya berbeda — jadi
        ditandai, bukan ditolak.
        """
        employee = self.make_employee()

        self.request_leave(
            employee,
            self.baptism,
            start=date(2025, 5, 12),
            days=1,
            status=LeaveStatus.RECORDED,
        )

        second = self.request_leave(
            employee,
            self.baptism,
            start=MONDAY,
            days=1,
        )

        report = self.report_for(second)

        self.assertIn("history", self.codes(report))
        self.assertEqual(report.blocking, [])
        self.assertTrue(report.needs_review)
        self.assertEqual(report.history_total, 1)

        # Riwayatnya ikut di payload, bukan cuma jumlahnya: yang
        # membaca peringatan perlu melihat kejadian sebelumnya.
        self.assertEqual(report.history[0]["event_date"], "2025-05-12")

    def test_review_finding_reaches_the_approver(self):
        """
        Peringatan yang tidak sampai ke meja approver sama saja dengan
        tidak ada. Ringkasannya dibekukan ke konteks alur.
        """
        employee = self.make_employee()

        self.request_leave(
            employee,
            self.baptism,
            start=date(2025, 5, 12),
            days=1,
            status=LeaveStatus.RECORDED,
        )

        second = self.request_leave(
            employee,
            self.baptism,
            start=MONDAY,
            days=1,
        )

        context = EmployeeLeaveService.workflow_rule_context(second)

        self.assertTrue(context["needs_review"])
        self.assertEqual(context["policy_code"], "LRQ-BAPTISM-STD")
        self.assertFalse(context["uses_balance"])
        self.assertTrue(context["rule_messages"])

    def test_sick_leave_needs_no_balance_at_all(self):
        """
        Tidak ada kartu, tidak ada eligibility, tidak ada penolakan —
        dan `balance` tetap None supaya layar tidak menampilkan panel
        saldo untuk cuti yang memang tidak berjatah.
        """
        employee = self.make_employee()

        leave = self.request_leave(employee, self.sick, days=4)

        report = self.report_for(leave)

        self.assertEqual(report.blocking, [])
        self.assertFalse(report.uses_balance)
        self.assertIsNone(report.balance)
        self.assertFalse(report.balance_evaluated)

    def test_document_required_allows_draft_but_blocks_submit(self):
        """
        Surat nikah lazim baru ada belakangan; draft yang tidak bisa
        disimpan sampai suratnya lengkap membuat orang mengetik ulang
        seluruh isian. Submit yang mewajibkannya.
        """
        employee = self.make_employee()

        leave = self.request_leave(employee, self.marriage, days=3)

        self.assertEqual(leave.status, LeaveStatus.DRAFT)

        # Temuannya sudah ada sejak draft — cuma tidak menahan.
        self.assertIn(
            "document_required",
            self.codes(self.report_for(leave)),
        )

        with self.assertRaises(ValidationError) as caught:
            EmployeeLeaveService.submit(instance=leave)

        self.assertIn("dokumen pendukung", str(caught.exception))

    def test_unpaid_leave_leaves_the_annual_card_untouched(self):
        employee = self.make_employee()

        card = self.give_balance(employee, self.annual, 12)

        self.request_leave(
            employee,
            self.unpaid,
            days=5,
            status=LeaveStatus.RECORDED,
        )

        card.refresh_from_db()

        self.assertEqual(card.used, Decimal("0.0"))
        self.assertEqual(card.remaining, Decimal("12.0"))

    def test_non_balance_request_creates_no_balance_row(self):
        employee = self.make_employee()

        self.request_leave(
            employee,
            self.marriage,
            days=3,
            status=LeaveStatus.RECORDED,
        )

        self.assertEqual(
            LeaveBalance.objects.filter(
                employee=employee,
                leave_type=self.marriage,
                is_deleted=False,
            ).count(),
            0,
        )


# ----------------------------------------------------------------------
# 8–10 — konteks pegawai
# ----------------------------------------------------------------------


class LeaveRequestEmployeeContextTestCase(LeaveRequestTestBase):
    """
    Seluruh resolver berangkat dari **pegawai pemilik dokumen**, bukan
    dari siapa yang mengetiknya.
    """

    @classmethod
    def build_baseline(cls):
        super().build_baseline()

        cls.roster_schedule = WorkSchedule.objects.create(
            code="LRQ-ROS",
            name="Roster 42/14",
            schedule_type=WorkSchedule.ScheduleType.ROSTER,
            cycle_work_days=42,
            cycle_off_days=14,
        )

        cls.crew = RosterCrew.objects.create(
            company=cls.company,
            location=cls.site,
            code="LRQ-CREW",
            name="Crew A",
            work_schedule=cls.roster_schedule,
            # Blok kerja 1 Jun – 12 Jul, blok off 13 Jul – 26 Jul.
            cycle_start_date=date(2026, 6, 1),
        )

    def test_office_employee_skips_weekends(self):
        """
        1–5 Juni 2026 (Senin–Jumat) = 5 hari kerja; 1–7 Juni menambah
        akhir pekan dan tetap 5.
        """
        employee = self.make_employee(
            location=self.office,
            calendar=self.calendar,
        )

        self.give_balance(employee, self.annual, 12)

        leave = EmployeeLeaveService.create(
            data={
                "employee": employee,
                "leave_type": self.annual,
                "start_date": MONDAY,
                "end_date": MONDAY + timedelta(days=6),
                "status": LeaveStatus.RECORDED,
            },
        )

        self.assertEqual(leave.total_days, Decimal("5"))

    def test_roster_employee_counts_its_own_cycle(self):
        """
        Pegawai roster memakai siklusnya sebagai kalender: akhir pekan
        ikut terhitung hari kerja saat jatuh di blok kerja.
        """
        employee = self.make_employee(
            location=self.site,
            roster_crew=self.crew,
        )

        self.give_balance(employee, self.annual, 12)

        leave = EmployeeLeaveService.create(
            data={
                "employee": employee,
                "leave_type": self.annual,
                "start_date": MONDAY,
                "end_date": MONDAY + timedelta(days=6),
                "status": LeaveStatus.RECORDED,
            },
        )

        self.assertEqual(leave.total_days, Decimal("7"))

    def test_roster_off_block_costs_nothing(self):
        """
        Cuti yang jatuh di blok off memotong nol hari — dan nol itu sah,
        bukan kesalahan.
        """
        employee = self.make_employee(
            location=self.site,
            roster_crew=self.crew,
        )

        self.give_balance(employee, self.annual, 12)

        leave = EmployeeLeaveService.create(
            data={
                "employee": employee,
                "leave_type": self.annual,
                # 14–18 Juli 2026 jatuh di blok off (13–26 Juli).
                "start_date": date(2026, 7, 14),
                "end_date": date(2026, 7, 18),
                "status": LeaveStatus.RECORDED,
            },
        )

        self.assertEqual(leave.total_days, Decimal("0"))

    def test_admin_created_request_uses_the_subject_employee(self):
        """
        Admin Section mengajukan untuk anak buahnya. Kalender, saldo,
        dan aturannya harus tetap milik **pegawai yang dituju** — kalau
        ikut yang login, pegawai site mendapat kalender kantor si admin
        dan hari cutinya salah tanpa satu pun pesan.
        """
        admin = self.make_employee(
            location=self.office,
            calendar=self.calendar,
        )

        subject = self.make_employee(
            location=self.site,
            roster_crew=self.crew,
        )

        self.give_balance(subject, self.annual, 12)

        leave = EmployeeLeaveService.create(
            data={
                "employee": subject,
                "leave_type": self.annual,
                "start_date": MONDAY,
                "end_date": MONDAY + timedelta(days=6),
                "status": LeaveStatus.RECORDED,
            },
            # Yang mengetik bukan pemilik dokumennya.
            user=None,
        )

        # 7, bukan 5: yang dipakai roster milik `subject`.
        self.assertEqual(leave.total_days, Decimal("7"))

        # Organisasi ikut pegawainya, bukan si admin.
        self.assertEqual(leave.location_id, self.site.pk)
        self.assertNotEqual(leave.location_id, admin.organization.location_id)

        leave.refresh_from_db()

        report = self.report_for(leave)

        # Kartu milik `subject` — 12 hari, 7 di antaranya terpakai
        # dokumen ini sendiri.
        self.assertEqual(report.balance["remaining"], "5.0")
        self.assertEqual(report.balance["available"], "12.0")


class LeaveWorkflowDefinitionTestCase(LeaveRequestTestBase):
    """
    Alur dipilih resolver dari cakupan **pegawainya**, bukan dari kode
    yang ditulis di modul cuti.

    Kalau kodenya di-hard-code, tenant yang menamai alurnya sendiri
    kehilangan seluruh persetujuan cutinya — dan kegagalannya baru
    terbaca saat ada yang menekan Submit.
    """

    @classmethod
    def build_baseline(cls):
        super().build_baseline()

        cls.global_flow = WorkflowDefinition.objects.create(
            code="LRQ-LEAVE-STD",
            name="Cuti Standar",
            module="hr",
            document_type="leave_request",
            status=WorkflowStatus.ACTIVE,
        )

        cls.site_flow = WorkflowDefinition.objects.create(
            code="LRQ-LEAVE-SITE",
            name="Cuti Site",
            module="hr",
            document_type="leave_request",
            company=cls.company,
            location=cls.site,
            status=WorkflowStatus.ACTIVE,
        )

    def match_for(self, employee):
        scope = WorkflowDefinitionResolver.scope_from_employee(employee)

        return WorkflowDefinitionResolver.match(
            module=EmployeeLeaveService.WORKFLOW_MODULE,
            document_type=EmployeeLeaveService.WORKFLOW_DOCUMENT_TYPE,
            **scope,
        )

    def test_site_employee_matches_the_site_flow(self):
        employee = self.make_employee(location=self.site)

        self.assertEqual(self.match_for(employee), self.site_flow)

    def test_office_employee_falls_back_to_the_global_flow(self):
        """
        Alur site menyebut lokasi tertentu, jadi ia **tidak** berlaku
        untuk pegawai kantor — yang kosong yang berlaku untuk semua.
        """
        employee = self.make_employee(location=self.office)

        self.assertEqual(self.match_for(employee), self.global_flow)

    def test_module_never_names_a_flow_code(self):
        """
        Penjagaan terhadap kemunduran: begitu ada yang menuliskan kode
        alur di modul cuti, cakupan berhenti menentukan apa pun.
        """
        import inspect

        from apps.hr.api.leave import services as leave_services

        source = inspect.getsource(leave_services)

        self.assertNotIn("HR-LEAVE", source)
        self.assertNotIn("HR-HO-LEAVE", source)
