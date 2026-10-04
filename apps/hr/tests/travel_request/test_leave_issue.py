"""
Penerbitan catatan cuti dari Travel Request — tiga cacat yang **diam**.

Ketiganya tidak melempar error, tidak membuat layar terlihat salah, dan
baru ketahuan berbulan-bulan kemudian saat ada yang membandingkan kartu
cuti dengan dokumen TR. Yang begitu hanya bisa dijaga test.

**M1 — overlap yang belum terbit ikut dianggap terbit.** `find_overlap`
mencari lintas `LEAVE_BLOCKING_STATUSES`, yang memuat SUBMITTED. Baris
TR yang bentrok dengan pengajuan cuti yang **masih menunggu tanda
tangan** dulu ditaut ke pengajuan itu seolah cutinya sudah terbit:
`employee_leave_id` terisi, approve berikutnya melewati barisnya, dan
kalau pengajuan cuti itu akhirnya ditolak, TR menunjuk catatan yang
tidak pernah memotong saldo apa pun.

**M2 — `deducts_leave` bertabrakan dengan Leave Policy non-saldo.**
Master Travel Purpose bilang "memotong", Leave Policy yang berlaku
bilang jenis cuti itu memang tidak punya kartu saldo. Menolak bukan
jawabannya — di titik penerbitan alurnya **sudah** disetujui sampai
meja terakhir. Yang benar: catatan cutinya tetap terbit lewat
`EmployeeLeaveService`, dan selisih masternya berbunyi di log dengan
menyebut nomor TR dan jenis cutinya.

**M3 — baris TR tidak bisa melihat aturan yang berlaku untuknya.**
`deducts_leave` cuma bisa bilang "memotong"; berapa dan apakah ada yang
bisa dipotong ditentukan Leave Policy. `policy_rules` mengembalikan
penilaian dari evaluator Leave **yang sama** dengan modul Cuti — bukan
salinan kedua.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model

from apps.administration.models import (
    LeavePolicy,
    LeaveType,
    RotationPurpose,
)
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.api.travel_request.serializers import (
    TravelRequestPurposeSerializer,
)
from apps.hr.api.travel_request.services import (
    TravelRequestPurposeService,
    TravelRequestService,
)
from apps.hr.models import EmployeeLeave, LeaveStatus

from .base import TravelRequestTestCase


SERVICE_LOGGER = "apps.hr.api.travel_request.services"

# Jangkar tanggal sendiri. `TenantTestCase` tidak me-rollback antar
# test, jadi dokumen milik berkas test tetangga harus jatuh di luar
# jendela pencarian overlap yang dipakai di sini.
WINDOW_START = date(2027, 3, 1)
WINDOW_END = date(2027, 3, 10)


class LeaveIssueTestBase(TravelRequestTestCase):
    """Pabrik TR yang barisnya memang memotong saldo."""

    _leave_type_counter = 0

    @classmethod
    def make_leave_kind(cls, label: str):
        """
        Satu Leave Type + Travel Purpose ber-`deducts_leave` yang cuma
        dipakai satu test.

        `TenantTestCase` **tidak** me-rollback antar test, jadi
        `LeavePolicy` yang dibuat satu test masih ada saat test
        berikutnya jalan. Berbagi satu Leave Type berarti test "belum
        ada aturannya" membaca aturan buatan test sebelumnya dan lulus
        karena sebab yang salah — persis kegagalan yang berkas ini
        seharusnya menangkap.
        """
        cls._leave_type_counter += 1

        suffix = f"{label}{cls._leave_type_counter:02d}"

        leave_type = LeaveType.objects.create(
            code=f"TR-LT-{suffix}",
            name=f"Cuti {suffix}",
        )

        purpose = RotationPurpose.objects.create(
            code=f"TR-RP-{suffix}",
            name=f"Cuti {suffix}",
            deducts_leave=True,
            leave_type=leave_type,
        )

        return leave_type, purpose

    def make_deducting_request(
        self,
        employee=None,
        *,
        purpose=None,
        start: date = WINDOW_START,
        end: date = WINDOW_END,
    ):
        """
        Satu TR dengan **satu** baris Travel Purpose ber-`deducts_leave`.

        Sengaja tidak lewat `make_request(with_purpose=True)`: baris
        bawaannya Field Break, dan Field Break tidak pernah lewat
        `issue_leave_records` sama sekali.
        """
        employee = employee or self.make_employee()

        request = self.make_request(
            employee,
            start_date=start,
            end_date=end,
            with_purpose=False,
        )

        row = TravelRequestPurposeService.create(
            data={
                "request": request,
                "purpose": purpose or self.annual_leave,
                "start_date": start,
                "end_date": end,
            },
        )

        request.refresh_from_db()

        return request, row

    @staticmethod
    def make_existing_leave(
        employee,
        leave_type,
        *,
        status,
        start: date = WINDOW_START,
        end: date = WINDOW_END,
    ) -> EmployeeLeave:
        """
        Cuti yang sudah lebih dulu ada di tanggal yang sama.

        `total_days` dioper eksplisit: pegawai pabrik ini tidak punya
        kalender kerja, dan membiarkan `LeaveDayCalculator` yang
        mengisinya membuat angka test bergantung pada master yang
        bukan sedang diuji.
        """
        return EmployeeLeaveService.create(
            data={
                "employee": employee,
                "leave_type": leave_type,
                "start_date": start,
                "end_date": end,
                "total_days": Decimal("5"),
                "status": status,
            },
        )


# ----------------------------------------------------------------------
# M1 — hanya status yang benar-benar memotong saldo yang boleh ditaut
# ----------------------------------------------------------------------


class ExistingLeaveOverlapTestCase(LeaveIssueTestBase):
    """
    Sengaja **tanpa** `LeavePolicy` sama sekali.

    Yang diuji di sini pemilihan status, bukan pembacaan aturan; policy
    yang ikut nimbrung akan membuat kegagalan berkas ini punya dua
    sebab yang mungkin.
    """

    def test_submitted_overlap_is_skipped_not_linked(self):
        """
        SUBMITTED = sudah memesan tanggal, **belum** memotong saldo.

        Ini M1. Sebelum perbaikan barisnya ditaut ke pengajuan itu dan
        dihitung sebagai penerbitan yang berhasil.
        """
        request, purpose = self.make_deducting_request()

        existing = self.make_existing_leave(
            request.employee,
            self.leave_type,
            status=LeaveStatus.SUBMITTED,
        )

        before = EmployeeLeave.objects.filter(
            employee=request.employee,
        ).count()

        with self.assertLogs(SERVICE_LOGGER, level="WARNING") as captured:
            issued = TravelRequestService.issue_leave_records(
                request=request,
            )

        purpose.refresh_from_db()

        self.assertEqual(issued, 0)

        # Tidak ditaut — justru ini inti M1. `employee_leave_id` yang
        # terisi membuat approve berikutnya melewati baris ini.
        self.assertIsNone(purpose.employee_leave_id)

        # Dan tidak diterbitkan: tanggalnya memang sedang dipesan
        # pengajuan lain, jadi menerbitkan yang kedua akan memotong
        # ganda begitu dua-duanya disetujui.
        self.assertEqual(
            EmployeeLeave.objects.filter(employee=request.employee).count(),
            before,
        )

        message = "\n".join(captured.output)

        # Peringatannya harus bisa ditindaklanjuti tanpa membuka kode:
        # dokumen mana, cuti mana, dan kenapa dilewati.
        self.assertIn(request.document_number, message)
        self.assertIn(str(existing.document_number or existing.pk), message)
        self.assertIn(LeaveStatus.SUBMITTED, message)

    def test_recorded_overlap_of_same_type_is_linked(self):
        """
        RECORDED ada di `LEAVE_DEDUCTING_STATUSES` — perilaku lama yang
        memang benar dan tidak boleh ikut terbawa perubahan M1.
        """
        request, purpose = self.make_deducting_request()

        existing = self.make_existing_leave(
            request.employee,
            self.leave_type,
            status=LeaveStatus.RECORDED,
        )

        issued = TravelRequestService.issue_leave_records(request=request)

        purpose.refresh_from_db()

        # Ditaut, bukan diterbitkan ulang — jadi `issued` tetap 0.
        self.assertEqual(issued, 0)
        self.assertEqual(purpose.employee_leave_id, existing.pk)

    def test_approved_overlap_of_same_type_is_linked(self):
        """APPROVED juga memotong saldo, jadi ikut boleh ditaut."""
        request, purpose = self.make_deducting_request()

        existing = self.make_existing_leave(
            request.employee,
            self.leave_type,
            status=LeaveStatus.APPROVED,
        )

        TravelRequestService.issue_leave_records(request=request)

        purpose.refresh_from_db()

        self.assertEqual(purpose.employee_leave_id, existing.pk)

    def test_submitted_overlap_of_other_type_is_also_skipped(self):
        """
        Status diperiksa **sebelum** jenis cutinya.

        Kalau urutannya terbalik, overlap SUBMITTED berjenis lain akan
        dilaporkan sebagai "bentrok jenis berbeda" — kalimat yang
        menyuruh orang memeriksa saldo yang sebenarnya belum terpotong
        sama sekali.
        """
        request, purpose = self.make_deducting_request()

        other_type = LeaveType.objects.create(
            code="TR-SICK-M1",
            name="Cuti Sakit",
        )

        self.make_existing_leave(
            request.employee,
            other_type,
            status=LeaveStatus.SUBMITTED,
        )

        with self.assertLogs(SERVICE_LOGGER, level="WARNING") as captured:
            TravelRequestService.issue_leave_records(request=request)

        purpose.refresh_from_db()

        self.assertIsNone(purpose.employee_leave_id)

        message = "\n".join(captured.output)

        self.assertIn(LeaveStatus.SUBMITTED, message)
        self.assertNotIn("jenisnya berbeda", message)

    def test_recorded_overlap_of_other_type_still_warns(self):
        """Perilaku lama untuk status yang memang memotong saldo."""
        request, purpose = self.make_deducting_request()

        other_type = LeaveType.objects.create(
            code="TR-SICK-M1B",
            name="Cuti Sakit",
        )

        self.make_existing_leave(
            request.employee,
            other_type,
            status=LeaveStatus.RECORDED,
        )

        with self.assertLogs(SERVICE_LOGGER, level="WARNING") as captured:
            TravelRequestService.issue_leave_records(request=request)

        purpose.refresh_from_db()

        self.assertIsNone(purpose.employee_leave_id)
        self.assertIn("jenisnya berbeda", "\n".join(captured.output))

    def test_no_overlap_still_issues_the_leave(self):
        """
        Jalur normal. Tanpa ini, M1 bisa "lulus" dengan cara yang salah:
        melewati semua baris.
        """
        request, purpose = self.make_deducting_request()

        issued = TravelRequestService.issue_leave_records(request=request)

        purpose.refresh_from_db()

        self.assertEqual(issued, 1)
        self.assertIsNotNone(purpose.employee_leave_id)
        self.assertEqual(
            purpose.employee_leave.status,
            LeaveStatus.RECORDED,
        )


# ----------------------------------------------------------------------
# M2 — deducts_leave di atas Leave Policy yang tidak bersaldo
# ----------------------------------------------------------------------


class NonBalancePolicyIssueTestCase(LeaveIssueTestBase):
    """
    `RotationPurpose.deducts_leave=True` + `LeavePolicy.uses_balance=
    False`. Dua master yang mengatakan hal berbeda tentang cuti yang
    sama.

    Tiap test memakai Leave Type-nya sendiri (`make_leave_kind`) —
    lihat alasannya di sana.
    """

    def policy_for(self, leave_type, *, uses_balance: bool):
        return LeavePolicy.objects.create(
            company=self.company,
            leave_type=leave_type,
            code=f"POL-{leave_type.code}",
            name=f"Policy {leave_type.code}",
            uses_balance=uses_balance,
            **(
                {
                    "entitlement_days": Decimal("12"),
                    "eligible_after_months": 12,
                }
                if uses_balance
                else {}
            ),
        )

    def test_non_balance_policy_still_issues_the_leave(self):
        """
        Ini M2. Yang **tidak** boleh terjadi: pengajuan yang sudah
        disetujui sampai meja terakhir ditolak di detik terakhir karena
        selisih master yang tidak bisa diperbaiki dari layar itu.
        """
        leave_type, purpose_master = self.make_leave_kind("EVT")

        policy = self.policy_for(leave_type, uses_balance=False)

        request, purpose = self.make_deducting_request(
            purpose=purpose_master,
            start=date(2027, 4, 1),
            end=date(2027, 4, 5),
        )

        with self.assertLogs(SERVICE_LOGGER, level="WARNING") as captured:
            issued = TravelRequestService.issue_leave_records(
                request=request,
            )

        purpose.refresh_from_db()

        # Terbit, sah, dan lewat Leave engine yang ada — bukan ditolak
        # dan bukan lewat `objects.create`.
        self.assertEqual(issued, 1)
        self.assertIsNotNone(purpose.employee_leave_id)
        self.assertEqual(
            purpose.employee_leave.status,
            LeaveStatus.RECORDED,
        )
        self.assertEqual(
            purpose.employee_leave.leave_type_id,
            leave_type.pk,
        )

        message = "\n".join(captured.output)

        # Nomor TR dan jenis cutinya wajib disebut: yang membaca log
        # harus bisa langsung membuka dokumennya dan masternya.
        self.assertTrue(request.document_number)
        self.assertIn(request.document_number, message)
        self.assertIn(leave_type.name, message)
        self.assertIn(policy.code, message)
        self.assertIn("uses_balance", message)

    def test_balance_policy_issues_without_warning(self):
        """
        Aturan bersaldo = keadaan yang memang diharapkan. Peringatan di
        sini akan membuat log penuh baris yang tidak berarti apa-apa,
        dan yang begitu berhenti dibaca orang.
        """
        leave_type, purpose_master = self.make_leave_kind("BAL")

        self.policy_for(leave_type, uses_balance=True)

        request, purpose = self.make_deducting_request(
            purpose=purpose_master,
            start=date(2027, 5, 1),
            end=date(2027, 5, 5),
        )

        with self.assertNoLogs(SERVICE_LOGGER, level="WARNING"):
            issued = TravelRequestService.issue_leave_records(
                request=request,
            )

        purpose.refresh_from_db()

        self.assertEqual(issued, 1)
        self.assertIsNotNone(purpose.employee_leave_id)

    def test_missing_policy_is_not_reported_as_non_balance(self):
        """
        `uses_balance` bawaannya **True** saat aturannya belum dibuat.

        Jenis cuti yang masternya belum diisi tidak boleh ikut berbunyi
        di sini — yang dilaporkan hanya aturan yang benar-benar
        menyatakan dirinya tanpa saldo.
        """
        _, purpose_master = self.make_leave_kind("NOPOL")

        request, purpose = self.make_deducting_request(
            purpose=purpose_master,
            start=date(2027, 5, 20),
            end=date(2027, 5, 24),
        )

        with self.assertNoLogs(SERVICE_LOGGER, level="WARNING"):
            issued = TravelRequestService.issue_leave_records(
                request=request,
            )

        purpose.refresh_from_db()

        self.assertEqual(issued, 1)
        self.assertIsNotNone(purpose.employee_leave_id)


# ----------------------------------------------------------------------
# M3 — policy_rules di baris Travel Purpose
# ----------------------------------------------------------------------


class PurposePolicyRulesTestCase(LeaveIssueTestBase):
    """
    Bentuk payload-nya harus **sama** dengan `policy_rules` di modul
    Cuti, karena memang evaluator yang sama. Kalau suatu saat berbeda,
    itu tanda ada salinan kedua yang lahir.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.policy = LeavePolicy.objects.create(
            company=cls.company,
            leave_type=cls.leave_type,
            code="TR-AL-M3",
            name="Cuti Tahunan M3",
            uses_balance=True,
            entitlement_days=Decimal("12"),
            eligible_after_months=12,
        )

    def serialize(self, purpose) -> dict:
        return TravelRequestPurposeSerializer(purpose).data

    def test_policy_rules_is_exposed_for_deducting_row(self):
        _, purpose = self.make_deducting_request(
            start=date(2027, 6, 1),
            end=date(2027, 6, 5),
        )

        rules = self.serialize(purpose)["policy_rules"]

        self.assertIsNotNone(rules)
        self.assertEqual(rules["policy_code"], self.policy.code)
        self.assertTrue(rules["uses_balance"])

        # Bentuk yang sama dengan modul Cuti — kunci-kunci ini yang
        # dibaca komponen temuan di FE.
        for key in (
            "policy_name",
            "per_event",
            "max_days",
            "document_required",
            "needs_review",
            "findings",
            "history",
            "history_total",
            "history_evaluated",
            "balance",
            "balance_evaluated",
        ):
            self.assertIn(key, rules)

    def test_policy_rules_uses_the_same_evaluator_as_leave(self):
        """
        Bukan penilaian tersendiri: hasilnya harus identik dengan yang
        dikeluarkan `EmployeeLeaveService.evaluate_rules` untuk data
        yang sama. Ini yang menjaga M3 tidak berubah jadi salinan
        kedua.
        """
        _, purpose = self.make_deducting_request(
            start=date(2027, 7, 1),
            end=date(2027, 7, 5),
        )

        expected = EmployeeLeaveService.evaluate_rules(
            data={
                "employee": purpose.request.employee,
                "leave_type": self.leave_type,
                "start_date": purpose.start_date,
                "total_days": purpose.total_days,
                "uploaded_file": None,
            },
            with_history=True,
            with_balance=True,
        ).as_dict()

        self.assertEqual(self.serialize(purpose)["policy_rules"], expected)

    def test_issued_row_is_evaluated_against_the_leave_record(self):
        """
        Begitu cutinya terbit, yang dinilai catatan cuti sungguhan —
        `total_days`-nya hasil `LeaveDayCalculator`, bukan hari kalender
        baris TR. Menilai ulang dari tanggal TR akan menampilkan angka
        yang tidak cocok dengan angka mana pun di kartu cutinya.
        """
        request, purpose = self.make_deducting_request(
            start=date(2027, 8, 1),
            end=date(2027, 8, 5),
        )

        TravelRequestService.issue_leave_records(request=request)

        purpose.refresh_from_db()

        self.assertIsNotNone(purpose.employee_leave_id)

        expected = EmployeeLeaveService.evaluate_rules(
            instance=purpose.employee_leave,
            with_history=True,
            with_balance=True,
        ).as_dict()

        self.assertEqual(self.serialize(purpose)["policy_rules"], expected)

    def test_field_break_row_has_no_policy_rules(self):
        """
        Baris yang tidak menyentuh cuti sama sekali. `None`, bukan dict
        kosong — dict kosong terbaca "sudah dinilai, bersih".
        """
        request = self.make_request(
            start_date=date(2027, 9, 1),
            end_date=date(2027, 9, 5),
        )

        purpose = request.purposes.first()

        self.assertIsNotNone(purpose)
        self.assertIsNone(self.serialize(purpose)["policy_rules"])

    def test_policy_rules_is_read_only(self):
        """
        Kolom turunan. Bisa ditulis lewat form berarti penilaian aturan
        bisa dipalsukan dari payload.
        """
        _, purpose = self.make_deducting_request(
            start=date(2027, 10, 1),
            end=date(2027, 10, 5),
        )

        serializer = TravelRequestPurposeSerializer(
            purpose,
            data={"policy_rules": {"uses_balance": False}},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn("policy_rules", serializer.validated_data)

    def test_issuer_is_recorded_on_both_sides(self):
        """
        Penerbitan tetap mencatat siapa yang menekan tombolnya. Dijaga
        di sini karena `user` diteruskan ke `EmployeeLeaveService`
        maupun ke baris TR-nya, dan keduanya mudah lepas saat blok
        penerbitan disunting.
        """
        user = get_user_model().objects.create_user(
            username="tr-issuer",
            password="x",
        )

        request, purpose = self.make_deducting_request(
            start=date(2027, 11, 1),
            end=date(2027, 11, 5),
        )

        TravelRequestService.issue_leave_records(
            request=request,
            user=user,
        )

        purpose.refresh_from_db()

        self.assertEqual(purpose.updated_by_id, user.pk)
        self.assertEqual(purpose.employee_leave.created_by_id, user.pk)
