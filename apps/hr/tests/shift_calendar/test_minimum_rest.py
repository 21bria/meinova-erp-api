"""
Jeda istirahat minimum saat **shift berganti**.

Masalah yang dikunci berkas ini terlihat begini di kalender, dan
sebelumnya diterima apa adanya:

    24  Night  19:00–07:00 (+1)
    25  Day    07:00–19:00

Malamnya baru selesai tanggal 25 pukul 07:00 dan Day-nya mulai pukul
07:00 di hari yang sama — nol jam istirahat, dan tidak ada satu pun
lapis yang menolaknya. Yang benar:

    24  Night     19:00–07:00 (+1)
    25  Recovery
    26  Day       07:00–19:00

Enam hal yang dijaga, dan tiap poinnya adalah cara aturan ini bisa
runtuh diam-diam:

1. **Konfigurasi, bukan kode.** Angkanya `RosterPolicy.min_rest_hours`.
   Tidak ada kode shift, tidak ada jam, dan tidak ada "selalu satu hari"
   yang ditulis di kode program — dibuktikan pemindaian sumber di bawah.
2. **Diukur dari datetime sungguhan.** Jumlah hari pemulihan lahir dari
   selisih jam selesai dan jam mulai, jadi jeda 40 jam menyisipkan dua
   hari sedangkan 24 jam menyisipkan satu — tanpa cabang khusus.
3. **Hanya saat shift berganti.** Malam kedua berjarak 12 jam dari malam
   pertama, dan itu jeda harian biasa. Aturan pergantian yang bocor ke
   sana akan menyisipkan hari pemulihan di antara **setiap** dua malam.
4. **Hari pemulihan tidak punya shift, dan tidak menagih presensi.**
   Ditulis sebagai baris `kind=REST`, bukan sebagai baris yang hilang —
   tanggal tanpa baris justru jatuh ke shift permanen pegawainya.
5. **Batas antar blok kerja ikut dihitung.** Blok yang dipisahkan field
   break lolos sendirinya (jedanya ratusan jam); yang bersambungan
   langsung tidak.
6. **Yang sudah hijau tidak berubah.** `min_rest_hours = 0` menghasilkan
   rencana yang sama persis dengan sebelum aturan ini ada, dan itu pula
   bawaan setiap policy yang sudah terlanjur berdiri.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from pathlib import Path

from django.core.exceptions import ValidationError

from apps.administration.models import RosterShiftRotation
from apps.administration.models.references.hr_attendance import Shift
from apps.administration.models.references.roster_policy import (
    MAX_MIN_REST_HOURS,
)
from apps.hr.api.attendance.closing import AttendanceClosingService
from apps.hr.api.attendance.schedule import (
    planned_work_days,
    resolve_shift,
    rest_days,
    scheduled_work_days,
    scheduled_work_days_bulk,
    scheduled_window,
)
from apps.hr.api.shift_calendar.pattern import RosterShiftPatternService
from apps.hr.api.shift_calendar.services import (
    CalendarState,
    EmployeeShiftAssignmentService,
    ShiftCalendarService,
)
from apps.hr.models import (
    Employee,
    EmployeeAttendance,
    EmployeeShiftAssignment,
    RosterSegmentType,
    ShiftAssignmentKind,
    ShiftAssignmentLayer,
)

from .test_effective_shift import BLOCK_START, ShiftCalendarTestCase


def _fresh_shifts(*shifts):
    """
    Baris master yang benar-benar dibaca ulang dari database.

    Pabrik di base membuat shift dengan jam berupa **string**
    (`start_time="19:00"`), dan objek hasil `create()` menyimpannya apa
    adanya sampai ada yang memuatnya ulang. Rumus jeda bekerja dengan
    `datetime.time`, sama seperti seluruh jalur produksi yang selalu
    membaca shift-nya lewat query. Yang dibetulkan di sini fixture-nya,
    bukan rumusnya — memaksa rumus menerima string berarti menyimpan
    dua bentuk jam yang sah, dan yang kedua akan menyelinap ke master.
    """
    return [
        Shift.objects.get(pk=shift.pk)
        for shift in shifts
    ]


def d(offset: int) -> date:
    """Tanggal ke-`offset` sejak awal blok kerja peragaan."""
    return BLOCK_START + timedelta(days=offset)


class _Segment:
    """
    Blok kerja secukupnya untuk `build_plan()`.

    Rumusnya memang tidak menyentuh database sama sekali, dan itu yang
    membuat seluruh kelas pertama di bawah bisa menguji aritmetikanya
    tanpa menyiapkan roster — yang diuji di sana bentuk kalendernya,
    bukan jalur penulisannya.
    """

    def __init__(self, start: date, end: date):
        self.start_date = start
        self.end_date = end


class MinimumRestFormulaTests(ShiftCalendarTestCase):
    """Aritmetikanya, tanpa satu query pun."""

    def setUp(self):
        super().setUp()

        # Shift yang persis disebut laporan UAT: Day 07:00–19:00 dan
        # Night 19:00–07:00 (+1). `day_shift` bawaan base berakhir 17:00
        # dan karena itu tidak memperlihatkan bentuk masalahnya sejelas
        # ini — dua belas jam penuh yang saling menyambung.
        self.long_day, self.night_shift, self.office_shift = _fresh_shifts(
            Shift.objects.create(
                code="AIM-DAY-12",
                name="Site Day 12h",
                start_time=time(7, 0),
                end_time=time(19, 0),
            ),
            self.night_shift,
            self.office_shift,
        )

    def plan(self, *, steps, min_rest_hours, days=28, start=None):
        return RosterShiftPatternService.build_plan(
            segments=[_Segment(BLOCK_START, d(days - 1))],
            steps=steps,
            start=start,
            end=d(days - 1),
            min_rest_hours=min_rest_hours,
        )

    @staticmethod
    def shape(plan):
        """`[(kode shift atau "", mulai, selesai)]` — bentuk yang dibaca."""
        return [
            (getattr(shift, "code", ""), start, end)
            for shift, start, end in plan
        ]

    # ------------------------------------------------------------------
    # Bentuk masalahnya
    # ------------------------------------------------------------------

    def test_night_then_day_gets_a_recovery_day_between_them(self):
        """Night 19:00–07:00 (+1) → Recovery → Day 07:00–19:00."""
        plan = self.plan(
            steps=[(self.night_shift, 7), (self.long_day, 7)],
            min_rest_hours=24,
        )

        self.assertEqual(
            self.shape(plan),
            [
                (self.night_shift.code, d(0), d(6)),
                # Malam terakhir selesai tanggal ini pukul 07:00, jadi
                # Day yang mulai 07:00 hari ini berjarak **nol jam**.
                ("", d(7), d(7)),
                (self.long_day.code, d(8), d(14)),
                # Day selesai 19:00; Night berikutnya mulai 19:00 esok
                # harinya — 24 jam pas, dan pas berarti cukup.
                (self.night_shift.code, d(15), d(21)),
                ("", d(22), d(22)),
                (self.long_day.code, d(23), d(27)),
            ],
        )

    def test_the_day_after_recovery_really_clears_the_gap(self):
        """
        Bukan sekadar "ada hari kosong": jedanya diukur ulang.

        Test di atas memeriksa bentuknya; yang ini memeriksa **angkanya**
        lewat fungsi yang sama yang dipakai generator, supaya kalimat
        "24 jam" di dokumen punya satu tempat yang membuktikannya.
        """
        _, night_end = RosterShiftPatternService.shift_window(
            d(6),
            self.night_shift,
        )

        # Tanpa hari pemulihan: Day mulai di tanggal yang sama dengan
        # jam selesai malamnya.
        self.assertEqual(
            RosterShiftPatternService.rest_hours_between(
                previous_end=night_end,
                day=d(7),
                shift=self.long_day,
            ),
            0,
        )

        self.assertEqual(
            RosterShiftPatternService.rest_hours_between(
                previous_end=night_end,
                day=d(8),
                shift=self.long_day,
            ),
            24,
        )

    # ------------------------------------------------------------------
    # Angkanya konfigurasi, bukan "selalu satu hari"
    # ------------------------------------------------------------------

    def test_a_longer_requirement_inserts_more_than_one_day(self):
        plan = self.plan(
            steps=[(self.night_shift, 7), (self.long_day, 7)],
            min_rest_hours=40,
        )

        # 24 jam belum cukup untuk 40, jadi hari kedua ikut disisipkan;
        # 48 jam cukup, dan yang ketiga tidak lahir.
        self.assertEqual(
            self.shape(plan)[:3],
            [
                (self.night_shift.code, d(0), d(6)),
                ("", d(7), d(8)),
                (self.long_day.code, d(9), d(15)),
            ],
        )

    def test_zero_means_the_rule_is_off(self):
        steps = [(self.night_shift, 7), (self.long_day, 7)]

        self.assertEqual(
            self.shape(self.plan(steps=steps, min_rest_hours=0)),
            [
                (self.night_shift.code, d(0), d(6)),
                (self.long_day.code, d(7), d(13)),
                (self.night_shift.code, d(14), d(20)),
                (self.long_day.code, d(21), d(27)),
            ],
        )

    def test_a_transition_that_already_rests_enough_is_untouched(self):
        """
        Day 07:00–19:00 → Night 19:00 keesokan harinya = 24 jam.

        Aturannya tidak boleh menyisipkan apa pun di sini, dan itu yang
        membedakan "jeda minimum" dari "selalu ada hari pemulihan antar
        shift".
        """
        plan = self.plan(
            steps=[(self.long_day, 7), (self.night_shift, 7)],
            min_rest_hours=24,
            days=14,
        )

        self.assertEqual(
            self.shape(plan),
            [
                (self.long_day.code, d(0), d(6)),
                (self.night_shift.code, d(7), d(13)),
            ],
        )

    def test_the_rule_is_not_about_night_shifts(self):
        """
        Office 10:00–18:00 → Day 07:00 esok harinya = 13 jam.

        Tidak satu pun shift di sini menyeberang tengah malam, dan
        aturannya tetap berlaku — yang menentukan jeda sungguhan, bukan
        sebutan shift-nya.
        """
        plan = self.plan(
            steps=[(self.office_shift, 7), (self.long_day, 7)],
            min_rest_hours=24,
            days=14,
        )

        self.assertEqual(
            self.shape(plan)[:3],
            [
                (self.office_shift.code, d(0), d(6)),
                ("", d(7), d(7)),
                (self.long_day.code, d(8), d(13)),
            ],
        )

    # ------------------------------------------------------------------
    # Hanya saat berganti
    # ------------------------------------------------------------------

    def test_consecutive_days_of_the_same_shift_never_rest(self):
        """
        Malam kedua berjarak 12 jam dari malam pertama.

        Kalau aturannya bocor ke sini, satu blok malam berubah jadi
        selang-seling kerja–pemulihan — dan angkanya tetap terlihat
        "benar" sampai ada yang menghitung hari kerjanya.
        """
        plan = self.plan(
            steps=[(self.night_shift, 28)],
            min_rest_hours=24,
        )

        self.assertEqual(
            self.shape(plan),
            [(self.night_shift.code, d(0), d(27))],
        )

    def test_two_steps_with_the_same_shift_are_not_a_transition(self):
        plan = self.plan(
            steps=[(self.night_shift, 7), (self.night_shift, 7)],
            min_rest_hours=24,
            days=14,
        )

        self.assertEqual(
            self.shape(plan),
            [(self.night_shift.code, d(0), d(13))],
        )

    # ------------------------------------------------------------------
    # Batas antar blok
    # ------------------------------------------------------------------

    def test_the_boundary_between_two_adjacent_blocks_counts_too(self):
        """
        Perputaran mengulang dari langkah pertama di tiap blok kerja,
        jadi blok yang bersambungan langsung bisa menaruh Day tepat
        sesudah Night — pergantian yang tidak diwakili satu baris pun di
        tabel perputaran.
        """
        plan = RosterShiftPatternService.build_plan(
            segments=[
                _Segment(BLOCK_START, d(13)),
                _Segment(d(14), d(27)),
            ],
            steps=[(self.long_day, 7), (self.night_shift, 7)],
            end=d(27),
            min_rest_hours=24,
        )

        self.assertEqual(
            self.shape(plan),
            [
                (self.long_day.code, d(0), d(6)),
                (self.night_shift.code, d(7), d(13)),
                # Blok kedua mulai lagi dari Day — dan malamnya baru
                # selesai pukul 07:00 di tanggal ini.
                ("", d(14), d(14)),
                (self.long_day.code, d(15), d(21)),
                (self.night_shift.code, d(22), d(27)),
            ],
        )

    def test_blocks_separated_by_a_field_break_need_no_recovery(self):
        """
        Dua minggu field break di antaranya = 336 jam.

        Tidak ada cabang khusus yang mengenali field break; yang
        menjawab aritmetika yang sama. Itu sebabnya jeda apa pun di
        antara dua blok tidak perlu didaftarkan di mana pun.
        """
        plan = RosterShiftPatternService.build_plan(
            segments=[
                _Segment(BLOCK_START, d(13)),
                _Segment(d(28), d(41)),
            ],
            steps=[(self.long_day, 7), (self.night_shift, 7)],
            end=d(41),
            min_rest_hours=24,
        )

        self.assertEqual(
            self.shape(plan),
            [
                (self.long_day.code, d(0), d(6)),
                (self.night_shift.code, d(7), d(13)),
                (self.long_day.code, d(28), d(34)),
                (self.night_shift.code, d(35), d(41)),
            ],
        )

    # ------------------------------------------------------------------
    # Jangkar
    # ------------------------------------------------------------------

    def test_the_pattern_is_still_anchored_to_the_block_start(self):
        """
        Menerapkan pola dari pertengahan blok harus mendarat di hari
        yang sama dengan menerapkannya dari awal — hari pemulihannya
        ikut.

        Sejak hari pemulihan bisa disisipkan, itu tidak lagi bisa
        dijawab satu modulo, dan simulasinya karena itu selalu berangkat
        dari awal blok walau yang diminta cuma ekornya.
        """
        steps = [(self.night_shift, 7), (self.long_day, 7)]

        full = self.plan(steps=steps, min_rest_hours=24)

        partial = self.plan(
            steps=steps,
            min_rest_hours=24,
            start=d(10),
        )

        expected = [
            (code, max(start, d(10)), end)
            for code, start, end in self.shape(full)
            if end >= d(10)
        ]

        self.assertEqual(self.shape(partial), expected)


class RecoveryRowTests(ShiftCalendarTestCase):
    """Hari pemulihan sebagai baris, dan apa yang membacanya."""

    def setUp(self):
        super().setUp()

        self.long_day, self.night_shift, self.office_shift = _fresh_shifts(
            Shift.objects.create(
                code="AIM-DAY-12",
                name="Site Day 12h",
                start_time=time(7, 0),
                end_time=time(19, 0),
            ),
            self.night_shift,
            self.office_shift,
        )

        # Shift permanen sengaja diisi: tanpa itu, "hari pemulihan tidak
        # menghasilkan shift" akan lolos karena memang tidak ada cadangan
        # apa pun untuk jatuh ke sana.
        self.employee = self.make_site_employee(shift=self.long_day)

        self.block = self.make_block(self.employee, days=28)

        self.steps = [(self.night_shift, 7), (self.long_day, 7)]

    def apply(self, *, min_rest_hours=24, **kwargs):
        kwargs.setdefault("employee", self.employee)
        kwargs.setdefault("steps", self.steps)
        kwargs.setdefault("start", BLOCK_START)
        kwargs.setdefault("end", d(27))

        return RosterShiftPatternService.apply(
            min_rest_hours=min_rest_hours,
            **kwargs,
        )

    def rows(self):
        return list(
            EmployeeShiftAssignment.objects
            .filter(
                employee=self.employee,
                is_deleted=False,
                layer=ShiftAssignmentLayer.BASELINE,
            )
            .order_by("start_date"),
        )

    # ------------------------------------------------------------------
    # Bentuk barisnya
    # ------------------------------------------------------------------

    def test_recovery_is_written_as_a_row_without_a_shift(self):
        result = self.apply()

        rest = [row for row in self.rows() if row.kind == ShiftAssignmentKind.REST]

        self.assertEqual([row.start_date for row in rest], [d(7), d(22)])

        for row in rest:
            self.assertIsNone(row.shift_id)
            self.assertEqual(row.layer, ShiftAssignmentLayer.BASELINE)

        self.assertEqual(result["rest_days"], 2)
        self.assertEqual(result["min_rest_hours"], 24)

    def test_the_recap_names_the_recovery_blocks(self):
        result = self.apply()

        kinds = [block["kind"] for block in result["blocks"]]

        self.assertEqual(
            kinds,
            ["work", "rest", "work", "work", "rest", "work"],
        )

        rest_block = result["blocks"][1]

        self.assertIsNone(rest_block["shift_id"])
        self.assertEqual(rest_block["shift_code"], "")

    # ------------------------------------------------------------------
    # Apa yang membacanya
    # ------------------------------------------------------------------

    def test_a_recovery_day_is_not_a_scheduled_work_day(self):
        self.apply()

        planned = planned_work_days(self.employee, BLOCK_START, d(27))
        scheduled = scheduled_work_days(self.employee, BLOCK_START, d(27))

        # Rosternya **tidak** berubah: dua puluh delapan hari kerja
        # tetap dua puluh delapan.
        self.assertEqual(len(planned), 28)

        self.assertEqual(len(scheduled), 26)

        self.assertNotIn(d(7), scheduled)
        self.assertIn(d(7), planned)

        self.assertEqual(
            rest_days(self.employee, BLOCK_START, d(27)),
            {d(7), d(22)},
        )

    def test_the_bulk_path_answers_the_same(self):
        """
        Laporan memakai jalur borongan. Dua jawaban yang berbeda untuk
        satu pertanyaan adalah cara rekap bulanan mulai menyimpang dari
        kalender tanpa satu pun dari keduanya terlihat salah.
        """
        self.apply()

        bulk = scheduled_work_days_bulk(
            [self.employee],
            BLOCK_START,
            d(27),
        )

        self.assertEqual(
            bulk[self.employee.id],
            scheduled_work_days(self.employee, BLOCK_START, d(27)),
        )

    def test_recovery_does_not_fall_back_to_the_permanent_shift(self):
        """
        Ini jalur gagal yang paling berbahaya: tanpa baris `REST`,
        tanggalnya cuma "tidak punya rencana" — dan resolver turun ke
        shift permanen pegawainya lalu menerbitkan hari kerja biasa.
        """
        self.apply()

        self.assertIsNone(resolve_shift(self.employee, d(7)))

        self.assertEqual(
            scheduled_window(self.employee, d(7)),
            (None, None),
        )

        # Tanggal sebelum dan sesudahnya tetap punya shift-nya.
        self.assertEqual(
            resolve_shift(self.employee, d(6)).shift_code,
            self.night_shift.code,
        )

        self.assertEqual(
            resolve_shift(self.employee, d(8)).shift_code,
            self.long_day.code,
        )

    def test_recovery_produces_no_attendance_obligation(self):
        self.apply()

        AttendanceClosingService.close(start=BLOCK_START, end=d(13))

        rows = EmployeeAttendance.objects.filter(
            employee=self.employee,
            is_deleted=False,
        )

        # Empat belas hari kerja menurut roster, satu di antaranya hari
        # pemulihan — tiga belas baris, dan tidak ada mangkir di
        # tanggalnya.
        self.assertEqual(rows.count(), 13)

        self.assertFalse(rows.filter(work_date=d(7)).exists())

    # ------------------------------------------------------------------
    # Kalender
    # ------------------------------------------------------------------

    def test_the_calendar_calls_it_recovery_and_not_off(self):
        self.apply()

        calendar = ShiftCalendarService.build(
            employee=self.employee,
            start=BLOCK_START,
            end=d(27),
        )

        cells = {cell["date"]: cell for cell in calendar["days"]}

        recovery = cells[d(7)]

        self.assertEqual(recovery["rotation_state"], CalendarState.RECOVERY)
        self.assertEqual(recovery["rotation_state_label"], "Recovery")
        self.assertFalse(recovery["is_scheduled"])
        self.assertEqual(recovery["shift_code"], "")
        self.assertIsNone(recovery["scheduled_check_in"])

        self.assertEqual(calendar["recovery_days"], 2)
        self.assertEqual(calendar["scheduled_days"], 26)

        # Hari sebelum dan sesudahnya tetap On Site dengan shift-nya.
        self.assertEqual(cells[d(6)]["shift_code"], self.night_shift.code)
        self.assertEqual(cells[d(8)]["shift_code"], self.long_day.code)

    def test_a_rest_row_outside_the_work_block_stays_field_break(self):
        """
        Baris pemulihan boleh membentang melewati blok off, sama seperti
        baris shift — dan pada tanggal itu ia tidak berarti apa-apa.
        Field break yang tiba-tiba berbunyi "Recovery" akan terbaca
        seperti rosternya yang berubah.
        """
        self.make_segment(
            self.employee,
            rotation=self.block.rotation,
            sequence=2,
            segment_type=RosterSegmentType.FIELD_BREAK,
            start=d(28),
            days=7,
        )

        EmployeeShiftAssignmentService.create(
            data={
                "employee": self.employee,
                "shift": None,
                "kind": ShiftAssignmentKind.REST,
                "layer": ShiftAssignmentLayer.BASELINE,
                "start_date": d(28),
                "end_date": d(30),
            },
        )

        calendar = ShiftCalendarService.build(
            employee=self.employee,
            start=d(28),
            end=d(34),
        )

        states = {cell["date"]: cell["rotation_state"] for cell in calendar["days"]}

        self.assertEqual(states[d(28)], CalendarState.FIELD_BREAK)
        self.assertEqual(calendar["recovery_days"], 0)

    # ------------------------------------------------------------------
    # Lapis
    # ------------------------------------------------------------------

    def test_an_adjustment_wins_over_a_recovery_day(self):
        """
        Penyesuaian supervisor tetap lapis teratas. Aturan jeda menyusun
        **rencana**; keputusan orang di atasnya adalah keputusan orang,
        dan menguncinya di sini berarti hari pemulihan tidak bisa
        dibatalkan saat site benar-benar kekurangan orang.
        """
        self.apply()

        EmployeeShiftAssignmentService.create(
            data={
                "employee": self.employee,
                "shift": self.long_day,
                "layer": ShiftAssignmentLayer.OVERRIDE,
                "start_date": d(7),
                "end_date": d(7),
                "reason": "Coverage plant shutdown",
            },
        )

        self.assertNotIn(
            d(7),
            rest_days(self.employee, BLOCK_START, d(27)),
        )

        self.assertIn(
            d(7),
            scheduled_work_days(self.employee, BLOCK_START, d(27)),
        )

        self.assertEqual(
            resolve_shift(self.employee, d(7)).shift_code,
            self.long_day.code,
        )

    def test_an_adjustment_can_also_declare_a_rest_day(self):
        self.apply(min_rest_hours=0)

        EmployeeShiftAssignmentService.create(
            data={
                "employee": self.employee,
                "shift": None,
                "kind": ShiftAssignmentKind.REST,
                "layer": ShiftAssignmentLayer.OVERRIDE,
                "start_date": d(3),
                "end_date": d(3),
                "reason": "Istirahat setelah lembur panjang",
            },
        )

        self.assertNotIn(
            d(3),
            scheduled_work_days(self.employee, BLOCK_START, d(27)),
        )

        self.assertIsNone(resolve_shift(self.employee, d(3)))

    # ------------------------------------------------------------------
    # Rekonsiliasi
    # ------------------------------------------------------------------

    def test_reapplying_the_pattern_is_still_idempotent(self):
        first = self.apply()

        before = [
            (row.kind, row.shift_id, row.start_date, row.end_date)
            for row in self.rows()
        ]

        second = self.apply()

        after = [
            (row.kind, row.shift_id, row.start_date, row.end_date)
            for row in self.rows()
        ]

        self.assertEqual(before, after)
        self.assertEqual(first["created"], second["created"])

    def test_clearing_a_partially_touched_recovery_row_keeps_its_kind(self):
        """
        Baris yang cuma tersentuh sebagian dipotong, bukan dibuang — dan
        ekornya diterbitkan ulang. Ekor hari pemulihan yang lahir sebagai
        baris kerja tanpa shift ditolak `clean()`; yang lahir dengan
        shift justru lolos diam-diam lalu menagih presensi di hari
        istirahat.
        """
        EmployeeShiftAssignmentService.create(
            data={
                "employee": self.employee,
                "shift": None,
                "kind": ShiftAssignmentKind.REST,
                "layer": ShiftAssignmentLayer.BASELINE,
                "start_date": d(0),
                "end_date": d(9),
            },
        )

        RosterShiftPatternService.clear_baseline(
            employee=self.employee,
            start=d(2),
            end=d(4),
        )

        tail = (
            EmployeeShiftAssignment.objects
            .filter(employee=self.employee, is_deleted=False, start_date=d(5))
            .first()
        )

        self.assertIsNotNone(tail)
        self.assertEqual(tail.kind, ShiftAssignmentKind.REST)
        self.assertIsNone(tail.shift_id)


class MinimumRestConfigurationTests(ShiftCalendarTestCase):
    """Aturannya dibaca dari master, dan hanya dari sana."""

    def setUp(self):
        super().setUp()

        self.long_day, self.night_shift, self.office_shift = _fresh_shifts(
            Shift.objects.create(
                code="AIM-DAY-12",
                name="Site Day 12h",
                start_time=time(7, 0),
                end_time=time(19, 0),
            ),
            self.night_shift,
            self.office_shift,
        )

        self.employee = self.make_site_employee()

        self.make_block(self.employee, days=28)

        for sequence, shift in enumerate(
            (self.night_shift, self.long_day),
            start=1,
        ):
            RosterShiftRotation.objects.create(
                policy=self.policy,
                sequence=sequence,
                shift=shift,
                block_days=7,
            )

    def set_min_rest(self, hours):
        self.policy.min_rest_hours = hours
        self.policy.save(update_fields=["min_rest_hours"])

        # Pegawainya dibaca ulang: relasi `employment.roster_policy`
        # di-cache pada instance begitu disentuh, jadi tanpa baris ini
        # sinkronisasi kedua masih melihat angka yang lama — dan
        # "aturannya tidak berubah" akan terbaca sebagai bug produksi.
        self.employee = Employee.objects.get(pk=self.employee.pk)

    def rest_row_dates(self):
        return sorted(
            row.start_date
            for row in EmployeeShiftAssignment.objects.filter(
                employee=self.employee,
                is_deleted=False,
                kind=ShiftAssignmentKind.REST,
            )
        )

    def test_sync_reads_the_number_from_the_policy(self):
        self.set_min_rest(24)

        result = RosterShiftPatternService.sync(employee=self.employee)

        self.assertEqual(result["min_rest_hours"], 24)
        self.assertEqual(self.rest_row_dates(), [d(7), d(22)])

    def test_turning_the_rule_off_removes_the_recovery_days(self):
        """
        Satu angka di layar Roster Policy, dan seluruh jadwalnya
        berubah — tanpa satu baris kode pun disentuh, dan tanpa migrasi.
        """
        self.set_min_rest(24)

        RosterShiftPatternService.sync(employee=self.employee)

        self.assertTrue(self.rest_row_dates())

        self.set_min_rest(0)

        RosterShiftPatternService.sync(employee=self.employee)

        self.assertEqual(self.rest_row_dates(), [])

    def test_a_policy_without_the_number_behaves_exactly_as_before(self):
        RosterShiftPatternService.sync(employee=self.employee)

        self.assertEqual(self.rest_row_dates(), [])

        self.assertEqual(
            len(scheduled_work_days(self.employee, BLOCK_START, d(27))),
            28,
        )

    def test_the_manual_pattern_button_honours_the_policy_too(self):
        """
        `apply()` tanpa `min_rest_hours` membacanya dari policy
        pegawainya. Aturannya milik site, bukan milik pola yang kebetulan
        sedang diketik seseorang di dialog.
        """
        self.set_min_rest(24)

        RosterShiftPatternService.apply(
            employee=self.employee,
            shifts=[self.night_shift, self.long_day],
            rotation_days=7,
            start=BLOCK_START,
            end=d(27),
        )

        self.assertEqual(self.rest_row_dates(), [d(7), d(22)])

    def test_an_employee_without_a_policy_gets_zero(self):
        office = self.make_employee()

        self.assertEqual(
            RosterShiftPatternService.min_rest_hours_for(office),
            0,
        )


class MinimumRestValidationTests(ShiftCalendarTestCase):
    """Pagar di master dan di baris."""

    def test_a_rest_row_may_not_point_at_a_shift(self):
        employee = self.make_site_employee()

        with self.assertRaises(ValidationError) as raised:
            EmployeeShiftAssignmentService.create(
                data={
                    "employee": employee,
                    "shift": self.night_shift,
                    "kind": ShiftAssignmentKind.REST,
                    "layer": ShiftAssignmentLayer.BASELINE,
                    "start_date": BLOCK_START,
                    "end_date": BLOCK_START,
                },
            )

        self.assertIn("shift", raised.exception.message_dict)

    def test_a_working_row_still_requires_one(self):
        employee = self.make_site_employee()

        with self.assertRaises(ValidationError) as raised:
            EmployeeShiftAssignmentService.create(
                data={
                    "employee": employee,
                    "shift": None,
                    "layer": ShiftAssignmentLayer.BASELINE,
                    "start_date": BLOCK_START,
                    "end_date": BLOCK_START,
                },
            )

        self.assertIn("shift", raised.exception.message_dict)

    def test_rest_rows_still_may_not_overlap_within_a_layer(self):
        employee = self.make_site_employee()

        EmployeeShiftAssignmentService.create(
            data={
                "employee": employee,
                "shift": None,
                "kind": ShiftAssignmentKind.REST,
                "layer": ShiftAssignmentLayer.BASELINE,
                "start_date": BLOCK_START,
                "end_date": d(2),
            },
        )

        with self.assertRaises(ValidationError):
            EmployeeShiftAssignmentService.create(
                data={
                    "employee": employee,
                    "shift": self.night_shift,
                    "layer": ShiftAssignmentLayer.BASELINE,
                    "start_date": d(1),
                    "end_date": d(4),
                },
            )

    def test_an_absurd_minimum_rest_is_rejected_at_the_policy(self):
        self.policy.min_rest_hours = MAX_MIN_REST_HOURS + 1

        with self.assertRaises(ValidationError) as raised:
            self.policy.full_clean()

        self.assertIn("min_rest_hours", raised.exception.message_dict)


PATTERN_SOURCE = "apps/hr/api/shift_calendar/pattern.py"


class NoHardcodedRestRuleTests(ShiftCalendarTestCase):
    """
    Pemindaian sumber, alasan yang sama dengan
    `NoHardcodedBehaviourTests`: begitu satu kode shift atau satu angka
    jam muncul di penyusun rencana, konfigurasi berhenti menentukan
    hasil — dan tidak ada test perilaku yang bisa menunjukkannya selama
    data ujinya kebetulan cocok.
    """

    def _source(self):
        root = Path(__file__).resolve().parents[4]

        return (root / PATTERN_SOURCE).read_text(encoding="utf-8")

    def test_the_generator_names_no_shift(self):
        source = self._source()

        for literal in (
            "SHIFT-1",
            "SHIFT-2",
            "SHIFT-3",
            '"NIGHT"',
            "'NIGHT'",
            '"DAY"',
            "'DAY'",
        ):
            self.assertNotIn(
                literal,
                source,
                msg=(
                    f"{PATTERN_SOURCE} menyebut {literal}; aturan jeda "
                    "harus berlaku untuk pergantian shift mana pun."
                ),
            )

    def test_the_generator_hardcodes_no_rest_threshold(self):
        """
        Angka 24 tidak boleh jadi bawaan tersembunyi. Yang boleh ada
        cuma `min_rest_hours: int = 0` — nol berarti "tidak diperiksa",
        dan itu bukan kebijakan.
        """
        source = self._source()

        self.assertIn("min_rest_hours: int = 0", source)

        for literal in (
            "min_rest_hours = 24",
            "min_rest_hours: int = 24",
            "MIN_REST_HOURS = ",
        ):
            self.assertNotIn(literal, source)

    def test_the_generator_never_assumes_one_day(self):
        """
        Jumlah hari pemulihan lahir dari pengukuran ulang, bukan dari
        satu penambahan. Dibuktikan perilakunya di atas (40 jam = dua
        hari); yang di sini menjaga bentuk kodenya tetap begitu.
        """
        source = self._source()

        self.assertIn("rest_hours_between", source)

        self.assertNotIn("recovery_days = 1", source)
