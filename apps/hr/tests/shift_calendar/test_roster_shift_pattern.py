"""
Mengunci jalur baru: **roster yang menerbitkan rencana shift**.

Sebelum ini pengguna HR menyusun roster di satu layar lalu mengetik
ulang rencana shift-nya di layar kedua, sambil memilih sendiri lapis
"Roster Baseline". Yang dijaga berkas ini bahwa jalur itu tidak perlu
lagi dilewati — dan bahwa jalan pintasnya tidak merusak apa pun yang
sudah terbukti:

1. Pola shift **membaca** blok kerja, tidak pernah menerbitkannya.
2. Urutan shift adalah urutan yang dikirim; tidak ada kode shift yang
   ditulis di kode.
3. Polanya dijangkarkan ke **awal blok kerja**, jadi menekan tombolnya
   dua kali tidak menggeser jadwal siapa pun.
4. Menyusun ulang rencana **tidak menyentuh penyesuaian** — keputusan
   supervisor tidak boleh hilang karena rencananya diperbarui.
5. Baris rencana lama yang cuma tersentuh sebagian **dipotong**, bukan
   dibuang: tanggal di luar rentang tetap punya jadwal.
6. Lapisnya ditentukan alurnya, dan `layer` tidak pernah sampai ke
   pengguna sebagai pilihan.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.hr.api.attendance.schedule import ShiftSource, resolve_shift
from apps.hr.api.shift_calendar.pattern import (
    MAX_PLAN_DAYS,
    MAX_ROTATION_DAYS,
    RosterShiftPatternService,
)
from apps.hr.api.shift_calendar.services import ShiftCalendarService
from apps.administration.models import RosterShiftRotation
from apps.hr.api.site_rotation.services import SiteRotationService
from apps.hr.models import (
    EmployeeShiftAssignment,
    SiteRotation,
    RosterSegmentType,
    ShiftAssignmentLayer,
)

from .test_effective_shift import BLOCK_START, ShiftCalendarTestCase


User = get_user_model()


class RosterShiftPatternTestCase(ShiftCalendarTestCase):
    """Blok kerja 1–28 Agustus 2026, dan sebuah pola tiga shift."""

    def setUp(self):
        super().setUp()

        self.employee = self.make_site_employee()
        self.period = self.make_block(self.employee)
        self.rotation = self.period.rotation

        self.pattern = [
            self.day_shift,
            self.night_shift,
            self.office_shift,
        ]

    def apply_pattern(self, **kwargs):
        kwargs.setdefault("employee", self.employee)
        kwargs.setdefault("shifts", self.pattern)
        kwargs.setdefault("start", BLOCK_START)
        kwargs.setdefault("end", BLOCK_START + timedelta(days=27))

        return RosterShiftPatternService.apply(**kwargs)

    def baselines(self):
        return list(
            EmployeeShiftAssignment.objects
            .filter(
                employee=self.employee,
                is_deleted=False,
                layer=ShiftAssignmentLayer.BASELINE,
            )
            .select_related("shift")
            .order_by("start_date"),
        )

    def code_on(self, day: date) -> str | None:
        resolved = resolve_shift(self.employee, day)

        return None if resolved is None else resolved.shift_code


# ======================================================================
# 1. Roster menerbitkan rencana shift
# ======================================================================


class PatternFromRosterTests(RosterShiftPatternTestCase):
    def test_pattern_covers_the_work_block_in_the_given_order(self):
        result = self.apply_pattern()

        rows = self.baselines()

        self.assertEqual(len(rows), 4, "28 hari ÷ 7 = empat potongan")
        self.assertEqual(result["created"], 4)
        self.assertEqual(result["work_blocks"], 1)

        self.assertEqual(
            [row.shift.code for row in rows],
            [
                self.day_shift.code,
                self.night_shift.code,
                self.office_shift.code,
                self.day_shift.code,
            ],
            "urutan perputaran = urutan yang dikirim, lalu berulang",
        )

        self.assertEqual(rows[0].start_date, BLOCK_START)
        self.assertEqual(rows[0].end_date, BLOCK_START + timedelta(days=6))
        self.assertEqual(rows[-1].end_date, BLOCK_START + timedelta(days=27))

    def test_every_row_is_baseline_and_never_an_adjustment(self):
        """
        Lapisnya ditentukan **alurnya**. Kalau jalur roster bisa
        menerbitkan `override`, penyesuaian supervisor kehilangan
        artinya: yang menang bukan lagi keputusan orang, tapi yang
        kebetulan ditulis belakangan.
        """
        self.apply_pattern()

        self.assertEqual(
            {row.layer for row in self.baselines()},
            {ShiftAssignmentLayer.BASELINE},
        )

        self.assertFalse(
            EmployeeShiftAssignment.objects
            .filter(
                employee=self.employee,
                is_deleted=False,
                layer=ShiftAssignmentLayer.OVERRIDE,
            )
            .exists(),
        )

    def test_one_shift_becomes_one_row_per_block(self):
        """
        Pola satu shift adalah keadaan yang paling lazim di site kecil.
        Satu baris per minggu untuk shift yang tidak pernah berganti
        membuat daftar penugasan panjang tanpa memuat satu keputusan
        pun.
        """
        self.apply_pattern(shifts=[self.day_shift])

        rows = self.baselines()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].start_date, BLOCK_START)
        self.assertEqual(rows[0].end_date, BLOCK_START + timedelta(days=27))

    def test_rotation_length_is_not_hardcoded_to_a_week(self):
        self.apply_pattern(shifts=self.pattern, rotation_days=4)

        rows = self.baselines()

        self.assertEqual(len(rows), 7, "28 hari ÷ 4")
        self.assertEqual(
            (rows[0].end_date - rows[0].start_date).days + 1,
            4,
        )

    def test_pattern_is_anchored_to_the_block_start(self):
        """
        Menerapkan pola dari tengah blok harus mendarat di shift yang
        sama dengan menerapkannya dari awal blok. Kalau dijangkarkan ke
        tanggal tombolnya ditekan, "minggu keberapa saya sekarang"
        berubah tiap kali seseorang memperbarui rencana — dan crew yang
        sudah menghafal jadwalnya menemukan shift lain esok harinya.
        """
        self.apply_pattern()

        expected = {
            BLOCK_START + timedelta(days=offset):
                self.code_on(BLOCK_START + timedelta(days=offset))
            for offset in range(10, 28)
        }

        middle = BLOCK_START + timedelta(days=10)

        self.apply_pattern(start=middle)

        for day, code in expected.items():
            self.assertEqual(self.code_on(day), code, f"{day} bergeser")

    def test_dates_outside_the_work_block_get_no_shift(self):
        """
        Blok kerja berakhir 28 Agustus; rencana shift tidak boleh
        menjulur ke hari off. Rotation tetap yang menjawab **kapan**.
        """
        self.apply_pattern(end=BLOCK_START + timedelta(days=60))

        rows = self.baselines()

        self.assertTrue(rows)
        self.assertLessEqual(
            max(row.end_date for row in rows),
            BLOCK_START + timedelta(days=27),
        )

        self.assertIsNone(self.code_on(BLOCK_START + timedelta(days=30)))

    def test_calendar_shows_the_plan_without_a_second_screen(self):
        """
        Inti seluruh perubahan ini: sesudah roster menetapkan polanya,
        kalender sudah terisi — tanpa satu pun baris diketik di layar
        Shift Assignment.
        """
        self.apply_pattern()

        calendar = ShiftCalendarService.build(
            employee=self.employee,
            start=BLOCK_START,
            end=BLOCK_START + timedelta(days=27),
        )

        cells = {cell["date"]: cell for cell in calendar["days"]}

        first = cells[BLOCK_START]
        second = cells[BLOCK_START + timedelta(days=7)]

        self.assertEqual(first["shift_code"], self.day_shift.code)
        self.assertEqual(second["shift_code"], self.night_shift.code)

        self.assertEqual(first["shift_source"], ShiftSource.BASELINE)
        self.assertEqual(
            first["shift_source_label"],
            "Roster",
            "sumbernya dibacakan sebagai Roster, bukan sebagai nama lapis",
        )

        self.assertFalse(first["is_override"])

    def test_no_calendar_label_ever_says_baseline(self):
        """
        `baseline`/`override` adalah nama lapis di tabel. Nilai
        semantiknya tetap dikirim — yang tidak boleh keluar cuma
        **labelnya**, karena label adalah yang dibaca orang.
        """
        self.apply_pattern()

        calendar = ShiftCalendarService.build(
            employee=self.employee,
            start=BLOCK_START,
            end=BLOCK_START + timedelta(days=27),
        )

        labels = {
            cell["shift_source_label"]
            for cell in calendar["days"]
            if cell["shift_source_label"]
        }

        self.assertEqual(labels, {"Roster"})

        for label in labels:
            self.assertNotIn("baseline", label.lower())
            self.assertNotIn("layer", label.lower())


    def test_the_calendar_carries_the_adjustment_reason(self):
        """
        "Kenapa shift saya diubah" ditanyakan orangnya, bukan oleh yang
        mengubahnya. Alasannya sudah **wajib** diisi saat penyesuaian
        dibuat; kalau ia tidak ikut sampai ke layar, kewajiban itu
        sia-sia dan jawabannya cuma bisa dicari lewat layar admin.
        """
        self.apply_pattern()

        adjusted = BLOCK_START + timedelta(days=3)

        self.assign(
            self.employee,
            self.office_shift,
            adjusted,
            adjusted,
            layer=ShiftAssignmentLayer.OVERRIDE,
            reason="Coverage plant shutdown",
        )

        calendar = ShiftCalendarService.build(
            employee=self.employee,
            start=BLOCK_START,
            end=BLOCK_START + timedelta(days=27),
        )

        cells = {cell["date"]: cell for cell in calendar["days"]}

        self.assertEqual(
            cells[adjusted]["assignment_reason"],
            "Coverage plant shutdown",
        )

        self.assertEqual(
            cells[adjusted]["shift_source_label"],
            "Adjustment",
        )

        self.assertEqual(
            cells[BLOCK_START]["assignment_reason"],
            "",
            "tanggal yang mengikuti roster tidak punya alasan untuk "
            "ditampilkan",
        )


# ======================================================================
# 2. Menyusun ulang rencana
# ======================================================================


class ReapplyTests(RosterShiftPatternTestCase):
    def test_reapplying_replaces_instead_of_colliding(self):
        self.apply_pattern()

        before = len(self.baselines())

        result = self.apply_pattern(shifts=[self.night_shift])

        rows = self.baselines()

        self.assertEqual(result["replaced"], before)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].shift.code, self.night_shift.code)

    def test_an_adjustment_survives_a_new_pattern_and_still_wins(self):
        """
        Yang paling mudah dirusak oleh tombol "susun ulang": penyesuaian
        yang sudah disetujui. Membersihkan kedua lapis sekaligus membuat
        pembaruan rencana diam-diam membatalkan keputusan orang lain.
        """
        self.apply_pattern()

        adjusted_start = BLOCK_START + timedelta(days=9)
        adjusted_end = BLOCK_START + timedelta(days=11)

        self.assign(
            self.employee,
            self.office_shift,
            adjusted_start,
            adjusted_end,
            layer=ShiftAssignmentLayer.OVERRIDE,
            reason="Coverage plant shutdown",
        )

        self.apply_pattern(shifts=[self.day_shift])

        self.assertEqual(
            self.code_on(adjusted_start),
            self.office_shift.code,
        )

        self.assertEqual(
            self.code_on(adjusted_end + timedelta(days=1)),
            self.day_shift.code,
            "tanggal di luar penyesuaian mengikuti rencana baru",
        )

        self.assertEqual(
            EmployeeShiftAssignment.objects
            .filter(
                employee=self.employee,
                is_deleted=False,
                layer=ShiftAssignmentLayer.OVERRIDE,
            )
            .count(),
            1,
        )

    def test_a_row_that_starts_earlier_is_clipped_not_dropped(self):
        self.assign(
            self.employee,
            self.office_shift,
            BLOCK_START - timedelta(days=10),
            BLOCK_START + timedelta(days=3),
        )

        self.apply_pattern()

        survivor = (
            EmployeeShiftAssignment.objects
            .filter(
                employee=self.employee,
                is_deleted=False,
                shift=self.office_shift,
                start_date=BLOCK_START - timedelta(days=10),
            )
            .first()
        )

        self.assertIsNotNone(
            survivor,
            "rencana sebelum rentang tidak boleh ikut terhapus",
        )

        self.assertEqual(
            survivor.end_date,
            BLOCK_START - timedelta(days=1),
        )

    def test_a_row_spanning_the_whole_range_keeps_its_tail(self):
        self.assign(
            self.employee,
            self.office_shift,
            BLOCK_START - timedelta(days=5),
            BLOCK_START + timedelta(days=40),
        )

        window_end = BLOCK_START + timedelta(days=13)

        self.apply_pattern(end=window_end)

        rows = list(
            EmployeeShiftAssignment.objects
            .filter(
                employee=self.employee,
                is_deleted=False,
                shift=self.office_shift,
                layer=ShiftAssignmentLayer.BASELINE,
            )
            .order_by("start_date"),
        )

        self.assertEqual(len(rows), 2, "kepala dan ekornya sama-sama hidup")

        self.assertEqual(rows[0].end_date, BLOCK_START - timedelta(days=1))
        self.assertEqual(rows[1].start_date, window_end + timedelta(days=1))
        self.assertEqual(rows[1].end_date, BLOCK_START + timedelta(days=40))

    def test_a_second_employees_plan_is_never_touched(self):
        other = self.make_site_employee()
        self.make_block(other)

        RosterShiftPatternService.apply(
            employee=other,
            shifts=[self.night_shift],
            start=BLOCK_START,
            end=BLOCK_START + timedelta(days=27),
        )

        self.apply_pattern(shifts=[self.day_shift])

        self.assertEqual(
            EmployeeShiftAssignment.objects
            .filter(employee=other, is_deleted=False)
            .count(),
            1,
        )

        resolved = resolve_shift(other, BLOCK_START)

        self.assertEqual(resolved.shift_code, self.night_shift.code)


# ======================================================================
# 3. Jalur otomatis: konfigurasi policy → baseline
# ======================================================================


class RotationConfigTests(RosterShiftPatternTestCase):
    """
    Yang dijaga: rencana shift lahir dari **konfigurasi**, bukan dari
    dialog yang harus diisi ulang tiap kali — dan lahirnya idempoten.
    """

    def configure(self, *steps):
        """`configure((shift, 7), (shift2, 7))` pada policy pegawainya."""
        RosterShiftRotation.objects.filter(policy=self.policy).delete()

        for index, (shift, days) in enumerate(steps, start=1):
            RosterShiftRotation.objects.create(
                policy=self.policy,
                sequence=index,
                shift=shift,
                block_days=days,
            )

    def test_baseline_is_published_from_the_policy_rotation(self):
        self.configure(
            (self.day_shift, 7),
            (self.night_shift, 7),
        )

        result = RosterShiftPatternService.sync(employee=self.employee)

        rows = self.baselines()

        self.assertEqual(result["skipped"], "")
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            [row.shift.code for row in rows],
            [
                self.day_shift.code,
                self.night_shift.code,
                self.day_shift.code,
                self.night_shift.code,
            ],
        )

    def test_running_it_twice_changes_nothing(self):
        """
        Idempoten, dan itu syarat mati: sinkronisasi dipanggil setiap
        kali roster berubah, jadi yang menambah baris tiap kali dipanggil
        akan menumpuk sampai jadwalnya tidak bisa dibaca lagi.
        """
        self.configure((self.day_shift, 7), (self.night_shift, 7))

        RosterShiftPatternService.sync(employee=self.employee)

        first = [
            (row.shift_id, row.start_date, row.end_date)
            for row in self.baselines()
        ]

        RosterShiftPatternService.sync(employee=self.employee)

        second = [
            (row.shift_id, row.start_date, row.end_date)
            for row in self.baselines()
        ]

        self.assertEqual(first, second)
        self.assertEqual(len(second), 4)

    def test_a_policy_without_a_rotation_writes_nothing(self):
        """
        Banyak site cuma punya satu shift dan memakai shift permanen
        pegawainya. Itu **bukan** kesalahan, dan menebak sebuah shift di
        sini akan menerbitkan jadwal yang tidak pernah diputuskan siapa
        pun.
        """
        RosterShiftRotation.objects.filter(policy=self.policy).delete()

        result = RosterShiftPatternService.sync(employee=self.employee)

        self.assertEqual(result["skipped"], "no_rotation")
        self.assertEqual(result["created"], 0)
        self.assertFalse(self.baselines())

    def test_step_length_is_read_per_step(self):
        """Dua minggu malam lalu satu minggu pagi — pola yang nyata."""
        self.configure(
            (self.night_shift, 14),
            (self.day_shift, 7),
        )

        RosterShiftPatternService.sync(employee=self.employee)

        rows = self.baselines()

        self.assertEqual(
            (rows[0].end_date - rows[0].start_date).days + 1,
            14,
        )
        self.assertEqual(rows[0].shift.code, self.night_shift.code)
        self.assertEqual(rows[1].shift.code, self.day_shift.code)

    def test_the_order_comes_from_sequence_not_from_the_shift_master(self):
        """
        Urutan perputaran ditentukan `sequence` baris konfigurasi —
        bukan `sort_order` master Shift, yang mengatur tampilan dropdown
        dan lazimnya menaik. Pola tambang justru melompat supaya jeda
        antar shift cukup panjang.
        """
        self.configure(
            (self.night_shift, 7),
            (self.office_shift, 7),
            (self.day_shift, 7),
        )

        RosterShiftPatternService.sync(employee=self.employee)

        self.assertEqual(
            [row.shift.code for row in self.baselines()][:3],
            [
                self.night_shift.code,
                self.office_shift.code,
                self.day_shift.code,
            ],
        )

    def test_an_adjustment_survives_a_resync(self):
        self.configure((self.day_shift, 7), (self.night_shift, 7))

        RosterShiftPatternService.sync(employee=self.employee)

        adjusted = BLOCK_START + timedelta(days=2)

        self.assign(
            self.employee,
            self.office_shift,
            adjusted,
            adjusted,
            layer=ShiftAssignmentLayer.OVERRIDE,
            reason="Coverage plant shutdown",
        )

        RosterShiftPatternService.sync(employee=self.employee)

        self.assertEqual(self.code_on(adjusted), self.office_shift.code)

        self.assertEqual(
            EmployeeShiftAssignment.objects
            .filter(
                employee=self.employee,
                is_deleted=False,
                layer=ShiftAssignmentLayer.OVERRIDE,
            )
            .count(),
            1,
        )

    def test_a_roster_change_is_reconciled(self):
        """
        Blok kerja yang digeser membuat rencana shift lama menunjuk
        tanggal yang sudah bukan hari kerja. Sinkronisasi menyusunnya
        ulang — dan itu satu-satunya alasan ia dipanggil dari mutasi
        roster, bukan cuma dari tombol.
        """
        self.configure((self.day_shift, 7), (self.night_shift, 7))

        RosterShiftPatternService.sync(employee=self.employee)

        moved = BLOCK_START + timedelta(days=10)

        self.period.start_date = moved
        self.period.end_date = moved + timedelta(days=27)
        self.period.save(update_fields=["start_date", "end_date"])

        RosterShiftPatternService.sync(employee=self.employee)

        rows = self.baselines()

        self.assertEqual(rows[0].start_date, moved)
        self.assertIsNone(
            self.code_on(BLOCK_START),
            "tanggal yang tidak lagi hari kerja tidak boleh berjadwal",
        )
        self.assertEqual(self.code_on(moved), self.day_shift.code)

    def test_non_work_days_never_receive_a_shift(self):
        self.configure((self.day_shift, 7))

        RosterShiftPatternService.sync(employee=self.employee)

        after_block = BLOCK_START + timedelta(days=40)

        self.assertIsNone(self.code_on(after_block))

        calendar = ShiftCalendarService.build(
            employee=self.employee,
            start=after_block,
            end=after_block,
        )

        cell = calendar["days"][0]

        self.assertFalse(cell["is_scheduled"])
        self.assertEqual(cell["shift_code"], "")

    def test_a_group_without_attendance_gets_no_schedule(self):
        """
        BOARD/BOD: Feature Applicability yang memutuskan, dan hasilnya
        **nol** hari terjadwal — bukan hari terjadwal yang lalu
        dimaafkan.
        """
        director = self.make_site_employee(group=self.no_attendance_group)
        self.make_block(director)

        self.configure((self.day_shift, 7))

        RosterShiftPatternService.sync(employee=director)

        calendar = ShiftCalendarService.build(
            employee=director,
            start=BLOCK_START,
            end=BLOCK_START + timedelta(days=27),
        )

        self.assertEqual(calendar["scheduled_days"], 0)
        self.assertTrue(
            all(
                cell["rotation_state"] == "not_applicable"
                for cell in calendar["days"]
            ),
        )
        self.assertTrue(
            all(not cell["shift_code"] for cell in calendar["days"]),
        )


class AutomaticSyncTests(RosterShiftPatternTestCase):
    """Roster berubah → rencana shift ikut, tanpa tombol ditekan."""

    def setUp(self):
        super().setUp()

        RosterShiftRotation.objects.filter(policy=self.policy).delete()

        for index, shift in enumerate(
            (self.day_shift, self.night_shift),
            start=1,
        ):
            RosterShiftRotation.objects.create(
                policy=self.policy,
                sequence=index,
                shift=shift,
                block_days=7,
            )

    def test_shifting_the_roster_republishes_the_plan(self):
        RosterShiftPatternService.sync(employee=self.employee)

        SiteRotationService.shift_from(
            rotation=self.rotation,
            from_sequence=1,
            days=3,
        )

        self.period.refresh_from_db()

        rows = self.baselines()

        self.assertEqual(
            rows[0].start_date,
            self.period.start_date,
            "rencana shift mengikuti blok kerja yang sudah digeser",
        )

    def test_the_sync_never_takes_the_roster_change_down_with_it(self):
        """
        Roster adalah keputusan pengguna; rencana shift turunannya.
        Turunan yang gagal tidak boleh membatalkan yang asli — kalau
        iya, satu master shift yang terhapus membuat roster tidak bisa
        digeser sama sekali.
        """
        broken = SiteRotationService.sync_shift_baseline(
            SiteRotation(),
            user=None,
        )

        self.assertIn(broken.get("skipped"), {"no_employee", "error"})


# ======================================================================
# 4. Penjagaan
# ======================================================================


class PatternValidationTests(RosterShiftPatternTestCase):
    def assert_field_error(self, field, **kwargs):
        with self.assertRaises(ValidationError) as caught:
            self.apply_pattern(**kwargs)

        self.assertIn(field, caught.exception.message_dict)

    def test_an_empty_pattern_is_rejected(self):
        self.assert_field_error("shifts", shifts=[])

    def test_zero_rotation_days_is_rejected(self):
        self.assert_field_error("rotation_days", rotation_days=0)

    def test_an_absurd_rotation_length_is_rejected(self):
        self.assert_field_error(
            "rotation_days",
            rotation_days=MAX_ROTATION_DAYS + 1,
        )

    def test_end_before_start_is_rejected(self):
        self.assert_field_error(
            "until",
            start=BLOCK_START,
            end=BLOCK_START - timedelta(days=1),
        )

    def test_an_unbounded_range_is_rejected(self):
        self.assert_field_error(
            "until",
            start=BLOCK_START,
            end=BLOCK_START + timedelta(days=MAX_PLAN_DAYS),
        )

    def test_nothing_is_written_when_validation_fails(self):
        try:
            self.apply_pattern(shifts=[])
        except ValidationError:
            pass

        self.assertFalse(self.baselines())


# ======================================================================
# 5. Jalur layar
# ======================================================================


class ApplyShiftPatternEndpointTests(RosterShiftPatternTestCase):
    """Tombol Set Shift Pattern di dokumen Roster Schedule."""

    def setUp(self):
        super().setUp()

        self.client = TenantClient(self.tenant)

        self.user = User.objects.create_user(
            username="roster.pattern",
            email="roster.pattern@example.test",
            password="pattern-pass-1",
            is_superuser=True,
            is_staff=True,
        )

    def post(self, payload, rotation=None):
        rotation = rotation or self.rotation

        return self.client.post(
            f"/api/hr/site-rotations/{rotation.pk}/apply-shift-pattern/",
            data=json.dumps(payload),
            content_type="application/json",
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(self.user).access_token}"
            ),
        )

    def test_the_action_publishes_the_plan_from_the_roster_document(self):
        response = self.post(
            {
                "shifts": [self.day_shift.pk, self.night_shift.pk],
                "rotation_days": 7,
            },
        )

        self.assertEqual(response.status_code, 200, response.content)

        rows = self.baselines()

        self.assertEqual(len(rows), 4)
        self.assertEqual(
            [row.shift.code for row in rows],
            [
                self.day_shift.code,
                self.night_shift.code,
                self.day_shift.code,
                self.night_shift.code,
            ],
        )

    def test_the_payload_order_is_the_rotation_order(self):
        self.post({"shifts": [self.night_shift.pk, self.day_shift.pk]})

        self.assertEqual(self.code_on(BLOCK_START), self.night_shift.code)

    def test_the_range_defaults_to_the_documents_own_schedule(self):
        response = self.post({"shifts": [self.day_shift.pk]})

        self.assertEqual(response.status_code, 200, response.content)

        rows = self.baselines()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].start_date, BLOCK_START)

    def test_an_unknown_shift_comes_back_as_a_field_error(self):
        response = self.post({"shifts": [9_999_999]})

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("shifts", response.json().get("errors", {}))

    def test_a_range_without_work_blocks_says_so(self):
        response = self.post(
            {
                "shifts": [self.day_shift.pk],
                "start": str(BLOCK_START + timedelta(days=60)),
                "until": str(BLOCK_START + timedelta(days=80)),
            },
        )

        self.assertEqual(response.status_code, 200, response.content)

        body = response.json()

        self.assertEqual(body["data"]["created"], 0)
        self.assertIn("Tidak ada blok kerja", body["message"])

        self.assertFalse(self.baselines())

    def test_the_calendar_endpoint_carries_every_cell_key(self):
        """
        `ShiftCalendarDaySerializer` menyebut kolomnya satu per satu,
        jadi kunci baru di `_cell()` **tidak** sampai ke layar sampai ia
        juga ditulis di sana. Gagalnya diam sempurna: service hijau,
        test service hijau, dan yang hilang cuma kolom di payload —
        ketahuannya di layar, itu pun kalau ada yang memperhatikan.
        """
        self.apply_pattern()

        adjusted = BLOCK_START + timedelta(days=3)

        self.assign(
            self.employee,
            self.office_shift,
            adjusted,
            adjusted,
            layer=ShiftAssignmentLayer.OVERRIDE,
            reason="Coverage plant shutdown",
        )

        response = self.client.get(
            "/api/hr/shift-calendar/"
            f"?employee={self.employee.pk}&start={BLOCK_START}"
            f"&end={BLOCK_START + timedelta(days=6)}",
            HTTP_AUTHORIZATION=(
                f"Bearer {RefreshToken.for_user(self.user).access_token}"
            ),
        )

        self.assertEqual(response.status_code, 200, response.content)

        body = response.json()
        days = (body.get("data") or body)["days"]

        expected = set(
            ShiftCalendarService._cell(
                employee=self.employee,
                day=BLOCK_START,
                applicable=True,
                roster=True,
                states={},
                holidays=set(),
                work_days=set(),
                # Dua argumen yang lahir bersama aturan jeda minimum:
                # `planned` hari kerja **sebelum** hari pemulihan
                # dikurangkan, `recovery` yang dikurangkan. Sengaja
                # tanpa nilai bawaan di service — sel yang dibangun
                # tanpa keduanya akan diam-diam menyebut hari pemulihan
                # sebagai On Site tanpa shift.
                planned=set(),
                recovery=set(),
                join_date=None,
                termination_date=None,
                assignments=[],
            ).keys(),
        )

        self.assertEqual(
            set(days[0].keys()),
            expected,
            "payload endpoint kehilangan kolom yang dibuat service",
        )

        cell = next(
            row for row in days
            if row["date"] == str(adjusted)
        )

        self.assertEqual(cell["shift_source_label"], "Adjustment")
        self.assertEqual(cell["assignment_reason"], "Coverage plant shutdown")

    def test_the_action_never_touches_the_roster_itself(self):
        segments_before = list(
            self.rotation.periods
            .filter(is_deleted=False)
            .values_list("segment_type", "start_date", "end_date"),
        )

        self.post({"shifts": [self.night_shift.pk]})

        segments_after = list(
            self.rotation.periods
            .filter(is_deleted=False)
            .values_list("segment_type", "start_date", "end_date"),
        )

        self.assertEqual(segments_before, segments_after)
        self.assertEqual(
            segments_before[0][0],
            RosterSegmentType.WORK,
        )
