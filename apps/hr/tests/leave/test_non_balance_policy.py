"""
Mengunci pemisahan cuti bersaldo dan cuti per kejadian.

Satu saklar (`LeavePolicy.uses_balance`) membelah modul cuti jadi dua
jalur yang tidak pernah bertemu, dan **tiga** dari empat kegagalannya
diam:

1. Aturan tanpa saldo menerbitkan `LeaveBalance`. Kartu cuti menikah
   berbunyi "0 dari 12" — dan yang membacanya menyimpulkan jatahnya
   sudah habis, bukan bahwa jenis cuti itu memang tidak berjatah.
2. Aturan bersaldo **berhenti** menerbitkan saldo. Ini satu-satunya
   yang berbunyi, dan bunyinya baru terdengar saat ada yang mengajukan
   cuti tahunan.
3. Batas hari, kewajiban dokumen, dan riwayat tersimpan rapi lalu tidak
   pernah dibaca siapa pun — keadaan persis sebelum perubahan ini, dan
   tidak ada satu pun tanda di layar yang membedakannya.
4. Yang seharusnya cuma memperingatkan malah menolak. Orang bisa
   menikahkan anak keduanya; pengajuan yang ditolak otomatis tidak
   punya tempat dibantah.

Sengaja tidak menyentuh Annual: jalur go-live, saldo awal, dan carry
over sudah dikunci `test_go_live_flow` dan `test_opening_balance`. Yang
diuji di sini justru bahwa keduanya **tidak** ikut berubah.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from apps.core.testing.tenant import ReusableTenantTestCase

from apps.administration.models import Company, LeavePolicy, LeaveType
from apps.administration.models.references.leave_policy import (
    LeaveHistoryAction,
)
from apps.hr.api.leave.entitlement import (
    LeaveBalanceGenerator,
    LeaveEntitlementCalculator,
)
from apps.hr.api.leave.rules import RuleLevel
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.api.leave_opening.services import LeaveOpeningBalanceService
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    LeaveBalance,
    LeaveStatus,
    OrganizationAssignment,
)


YEAR = 2026

JOIN_DATE = date(2020, 3, 10)


# ----------------------------------------------------------------------
# Aturan bentuk policy — murni, tanpa database
# ----------------------------------------------------------------------


class LeavePolicyValidationTestCase(SimpleTestCase):
    """
    `clean()` menolak setelan yang **tersimpan lalu tidak pernah
    dibaca**. Itu bentuk kegagalan paling mahal di master seperti ini:
    yang mengisinya yakin sudah mengatur sesuatu, dan tidak ada satu
    pun tanda di layar yang menyanggahnya.

    Tanpa database dengan sengaja — seluruh pemeriksaannya memang murni
    operasi atas nilai kolomnya sendiri. Begitu ada yang menambahkan
    query ke `clean()`, berkas ini yang pertama gagal.
    """

    def policy(self, **kwargs) -> LeavePolicy:
        defaults = {
            "code": "X-STD",
            "name": "X",
            "uses_balance": True,
        }

        return LeavePolicy(**{**defaults, **kwargs})

    def test_carry_over_needs_balance(self):
        with self.assertRaises(ValidationError) as caught:
            self.policy(
                uses_balance=False,
                allow_carry_over=True,
            ).clean()

        self.assertIn("allow_carry_over", caught.exception.message_dict)

    def test_per_event_conflicts_with_balance(self):
        with self.assertRaises(ValidationError) as caught:
            self.policy(uses_balance=True, per_event=True).clean()

        self.assertIn("per_event", caught.exception.message_dict)

    def test_history_action_needs_history_check(self):
        with self.assertRaises(ValidationError) as caught:
            self.policy(
                uses_balance=False,
                history_check=False,
                history_action=LeaveHistoryAction.REVIEW,
            ).clean()

        self.assertIn("history_check", caught.exception.message_dict)

    def test_negative_max_days_rejected(self):
        with self.assertRaises(ValidationError) as caught:
            self.policy(
                uses_balance=False,
                max_days=Decimal("-1"),
            ).clean()

        self.assertIn("max_days", caught.exception.message_dict)

    def test_valid_event_policy_passes(self):
        # Bentuk yang diseed untuk cuti menikah. Kalau ini gagal,
        # seluruh seed policy ikut gagal.
        self.policy(
            uses_balance=False,
            max_days=Decimal("3"),
            per_event=True,
            document_required=True,
            history_check=True,
            history_action=LeaveHistoryAction.REVIEW,
        ).clean()

    def test_valid_annual_policy_passes(self):
        self.policy(
            uses_balance=True,
            entitlement_days=Decimal("12"),
            eligible_after_months=12,
        ).clean()


# ----------------------------------------------------------------------
# Perilaku di dalam tenant
# ----------------------------------------------------------------------


class NonBalanceLeavePolicyTestCase(ReusableTenantTestCase):
    reusable_schema_name = "fast_leave_nonbalance"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "leave-rules-test"
        tenant.name = "Leave Rules Test"

    @classmethod
    def build_baseline(cls):

        cls.company, _ = Company.objects.get_or_create(
            code='EVT',
            is_deleted=False,
            defaults={
                "name": 'Event Co',
            },
        )

        cls.annual, _ = LeaveType.objects.get_or_create(
            code='ANNUAL-EVT',
            is_deleted=False,
            defaults={
                "name": 'Cuti Tahunan',
            },
        )

        cls.marriage, _ = LeaveType.objects.get_or_create(
            code='MARRIAGE-EVT',
            is_deleted=False,
            defaults={
                "name": 'Cuti Menikah',
            },
        )

        cls.hajj, _ = LeaveType.objects.get_or_create(
            code='HAJJ-EVT',
            is_deleted=False,
            defaults={
                "name": 'Cuti Ibadah Haji',
            },
        )

        cls.annual_policy, _ = LeavePolicy.objects.get_or_create(
            code='ANNUAL-EVT-STD',
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

        cls.marriage_policy, _ = LeavePolicy.objects.get_or_create(
            code='MARRIAGE-EVT-STD',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "leave_type": cls.marriage,
                "name": 'Cuti Menikah',
                "uses_balance": False,
                "entitlement_days": Decimal('0'),
                "max_days": Decimal('3'),
                "per_event": True,
                "document_required": True,
                "history_check": True,
                "history_action": LeaveHistoryAction.REVIEW,
            },
        )

        # Satu-satunya yang benar-benar menolak, supaya bedanya dengan
        # REVIEW di atas terkunci — bukan cuma diasumsikan.
        cls.hajj_policy, _ = LeavePolicy.objects.get_or_create(
            code='HAJJ-EVT-ONCE',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "leave_type": cls.hajj,
                "name": 'Cuti Haji Sekali',
                "uses_balance": False,
                "entitlement_days": Decimal('0'),
                "per_event": True,
                "history_check": True,
                "history_action": LeaveHistoryAction.BLOCK,
            },
        )

    _counter = 0

    @classmethod
    def make_employee(cls) -> Employee:
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"EVT{cls._counter:04d}",
            first_name="Rian",
            last_name=f"Saputra {cls._counter}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            organization_effective_date=JOIN_DATE,
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=JOIN_DATE,
        )

        return Employee.objects.get(pk=employee.pk)

    def leave(self, employee, leave_type, *, start, days, **extra):
        """
        `total_days` selalu dioper eksplisit.

        Kalau dibiarkan dihitung `LeaveDayCalculator`, angkanya
        bergantung pada hari apa tanggal itu jatuh — dan test yang
        lulus di bulan ini lalu gagal di bulan depan tidak memberi tahu
        siapa pun apa-apa.
        """
        return EmployeeLeaveService.create(
            data={
                "employee": employee,
                "leave_type": leave_type,
                "start_date": start,
                "end_date": start + timedelta(days=int(days) - 1),
                "total_days": Decimal(days),
                "status": LeaveStatus.RECORDED,
                **extra,
            },
        )

    def balances(self, employee, leave_type):
        return LeaveBalance.objects.filter(
            employee=employee,
            leave_type=leave_type,
            year=YEAR,
            is_deleted=False,
        )

    # ------------------------------------------------------------------
    # 1 — saldo tidak pernah terbit dari aturan per kejadian
    # ------------------------------------------------------------------

    def test_generator_skips_non_balance_policy(self):
        employee = self.make_employee()

        result = LeaveBalanceGenerator.run(
            year=YEAR,
            employees=[employee],
            leave_types=[self.annual, self.marriage],
        )

        self.assertEqual(result["non_balance"], 1)

        self.assertEqual(self.balances(employee, self.marriage).count(), 0)

        # Yang bersaldo tetap terbit — kalau ikut mati, satu saklar
        # mematikan seluruh cuti tahunan tenant.
        annual = self.balances(employee, self.annual).first()

        self.assertIsNotNone(annual)
        self.assertEqual(annual.entitlement, Decimal("12.00"))

    def test_default_leave_types_exclude_non_balance(self):
        """
        Pemanggil yang tidak menyebut `leave_types` (perintah
        `generate_leave_balances`, dan `EmploymentService` tiap kali
        penempatan disimpan) juga tidak boleh kebagian.
        """
        employee = self.make_employee()

        LeaveBalanceGenerator.run(year=YEAR, employees=[employee])

        self.assertEqual(self.balances(employee, self.marriage).count(), 0)
        self.assertEqual(self.balances(employee, self.annual).count(), 1)

    def test_entitlement_keeps_policy_but_refuses_balance(self):
        """
        `has_policy` tetap True: aturannya memang ada dan namanya harus
        tetap bisa disebut di layar. Yang False `issues_balance` —
        penanda tersendiri, karena "tidak ada aturan" dan "aturannya
        bukan aturan bersaldo" adalah dua keadaan yang berbeda dan cuma
        salah satunya perlu diperbaiki HR.
        """
        employee = self.make_employee()

        result = LeaveEntitlementCalculator.for_employee(
            employee=employee,
            leave_type=self.marriage,
            year=YEAR,
        )

        self.assertTrue(result.has_policy)
        self.assertFalse(result.issues_balance)
        self.assertEqual(result.days, Decimal("0"))
        self.assertIn("MARRIAGE-EVT-STD", result.reason)

    def test_opening_balance_rejects_non_balance_type(self):
        employee = self.make_employee()

        with self.assertRaises(ValidationError) as caught:
            LeaveOpeningBalanceService.create(
                data={
                    "employee": employee,
                    "leave_type": self.marriage,
                    "days": Decimal("3"),
                    "opening_date": date(YEAR, 9, 1),
                },
            )

        self.assertIn("leave_type", caught.exception.message_dict)

    # ------------------------------------------------------------------
    # 2 — batas hari
    # ------------------------------------------------------------------

    def test_max_days_blocks_request(self):
        employee = self.make_employee()

        with self.assertRaises(ValidationError) as caught:
            self.leave(
                employee,
                self.marriage,
                start=date(YEAR, 2, 2),
                days=5,
                status=LeaveStatus.DRAFT,
            )

        self.assertIn("total_days", caught.exception.message_dict)

    def test_max_days_allows_request_within_limit(self):
        employee = self.make_employee()

        leave = self.leave(
            employee,
            self.marriage,
            start=date(YEAR, 3, 2),
            days=3,
            status=LeaveStatus.DRAFT,
        )

        self.assertEqual(leave.total_days, Decimal("3.0"))

    def test_max_days_does_not_block_recording(self):
        """
        HR mencatat cuti yang **sudah terjadi**, dan Travel Request
        menerbitkannya sesudah alurnya disetujui. Menolak di titik itu
        berarti fakta yang sudah terjadi tidak punya tempat tersimpan,
        dan pesannya muncul di layar orang yang tidak bisa
        memperbaikinya.
        """
        employee = self.make_employee()

        leave = self.leave(
            employee,
            self.marriage,
            start=date(YEAR, 4, 6),
            days=5,
        )

        self.assertEqual(leave.status, LeaveStatus.RECORDED)

        # Tidak ditahan, tapi juga tidak didiamkan.
        report = EmployeeLeaveService.evaluate_rules(instance=leave)

        self.assertIn(
            "max_days",
            [row.code for row in report.blocking],
        )

    # ------------------------------------------------------------------
    # 3 — dokumen pendukung
    # ------------------------------------------------------------------

    def test_document_required_allows_draft(self):
        """
        Surat dokter lazim baru ada sesudah orangnya pulang berobat.
        Mewajibkannya sejak draft membuat isian yang sudah diketik
        tidak bisa disimpan sama sekali.
        """
        employee = self.make_employee()

        leave = self.leave(
            employee,
            self.marriage,
            start=date(YEAR, 5, 4),
            days=2,
            status=LeaveStatus.DRAFT,
        )

        self.assertIsNone(leave.uploaded_file_id)

    def test_document_required_blocks_submit(self):
        employee = self.make_employee()

        leave = self.leave(
            employee,
            self.marriage,
            start=date(YEAR, 6, 1),
            days=2,
            status=LeaveStatus.DRAFT,
        )

        with self.assertRaises(ValidationError) as caught:
            EmployeeLeaveService.assert_policy_rules(
                {},
                instance=leave,
                require_document=True,
            )

        self.assertIn("uploaded_file", caught.exception.message_dict)

    # ------------------------------------------------------------------
    # 4 — riwayat
    # ------------------------------------------------------------------

    def test_history_warns_without_blocking(self):
        employee = self.make_employee()

        self.leave(
            employee,
            self.marriage,
            start=date(YEAR, 7, 6),
            days=3,
        )

        # Pernikahan kedua tetap berhak — yang tidak bisa diputuskan
        # kode adalah apakah kejadiannya memang berbeda.
        second = self.leave(
            employee,
            self.marriage,
            start=date(YEAR + 1, 7, 5),
            days=3,
            status=LeaveStatus.DRAFT,
        )

        report = EmployeeLeaveService.evaluate_rules(instance=second)

        finding = next(
            row for row in report.findings if row.code == "history"
        )

        self.assertEqual(finding.level, RuleLevel.REVIEW)
        self.assertFalse(finding.is_blocking)
        self.assertTrue(report.needs_review)
        self.assertEqual(report.history_total, 1)

    def test_history_spans_years_when_per_event(self):
        """
        Hak yang melekat pada kejadian tidak reset tiap Januari, jadi
        riwayatnya dibaca seumur bekerja — bukan sebatas tahun yang
        sama. Kalau disempitkan ke tahun berjalan, pemeriksaan cuti
        menikah praktis tidak pernah menemukan apa pun.
        """
        employee = self.make_employee()

        self.leave(
            employee,
            self.marriage,
            start=date(YEAR - 2, 8, 3),
            days=3,
        )

        report = EmployeeLeaveService.evaluate_rules(
            {
                "employee": employee,
                "leave_type": self.marriage,
                "start_date": date(YEAR, 8, 3),
                "total_days": Decimal("3"),
            },
        )

        self.assertEqual(report.history_total, 1)

    def test_history_block_rejects_second_request(self):
        employee = self.make_employee()

        self.leave(
            employee,
            self.hajj,
            start=date(YEAR, 9, 7),
            days=2,
        )

        with self.assertRaises(ValidationError) as caught:
            self.leave(
                employee,
                self.hajj,
                start=date(YEAR + 1, 9, 6),
                days=2,
                status=LeaveStatus.DRAFT,
            )

        self.assertIn("leave_type", caught.exception.message_dict)

    def test_history_ignores_own_document_on_update(self):
        """
        Dokumen tidak boleh jadi riwayat bagi dirinya sendiri —
        menyunting satu huruf di catatan akan menolaknya sebagai
        pengajuan kedua.
        """
        employee = self.make_employee()

        leave = self.leave(
            employee,
            self.hajj,
            start=date(YEAR, 10, 5),
            days=2,
            status=LeaveStatus.DRAFT,
        )

        EmployeeLeaveService.update(
            instance=leave,
            data={"notes": "Nomor porsi menyusul"},
        )

        report = EmployeeLeaveService.evaluate_rules(instance=leave)

        self.assertEqual(report.history_total, 0)

    # ------------------------------------------------------------------
    # 5 — cuti bersaldo tidak ikut berubah
    # ------------------------------------------------------------------

    def test_annual_request_untouched_by_event_rules(self):
        employee = self.make_employee()

        LeaveBalanceGenerator.run(
            year=YEAR,
            employees=[employee],
            leave_types=[self.annual],
        )

        leave = self.leave(
            employee,
            self.annual,
            start=date(YEAR, 11, 2),
            days=5,
            status=LeaveStatus.DRAFT,
        )

        report = EmployeeLeaveService.evaluate_rules(instance=leave)

        self.assertTrue(report.uses_balance)
        self.assertEqual(report.findings, [])
        self.assertEqual(leave.total_days, Decimal("5.0"))
