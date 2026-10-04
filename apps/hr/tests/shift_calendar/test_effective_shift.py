"""
Mengunci Shift Calendar: **kapan** bekerja dan **shift apa** adalah dua
pertanyaan berbeda dengan dua sumber kebenaran berbeda.

Yang dijaga berkas ini, dan tiap poinnya adalah cara desain ini bisa
runtuh diam-diam:

1. **Rotation tetap authoritative** untuk WORK/OFF/TRAVEL. Penugasan
   shift tidak pernah menjadwalkan seseorang bekerja.
2. **Shift boleh berganti di dalam satu blok kerja.** Satu crew 6:2
   yang minggu pertama pagi dan minggu kedua malam harus bisa dinyatakan
   tanpa menyentuh pola rosternya.
3. **Adjustment menang, dan hanya pada rentangnya.** Tanggal di
   luarnya kembali ke baseline — rencana aslinya tidak dihancurkan.
4. **Jam datang dari master `Shift`.** Mengubah jam di master mengubah
   jendela terjadwal tanpa satu baris kode pun berubah.
5. **Shift malam menyeberang tengah malam** dan tap pulangnya tetap
   milik hari kerja sebelumnya.
6. **Feature Applicability yang memutuskan siapa yang punya kewajiban
   presensi** — bukan kode group, bukan lokasi, bukan awalan nomor
   pegawai.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

from django.core.exceptions import ValidationError

from apps.administration.models.references.hr_attendance import Shift
from apps.hr.api.attendance.closing import AttendanceClosingService
from apps.hr.api.attendance.policy import AttendancePolicyResolver
from apps.hr.api.attendance.schedule import (
    WALL_CLOCK_TZ,
    ShiftSource,
    resolve_shift,
    rotation_states,
    scheduled_window,
    scheduled_work_days,
)
from apps.hr.api.shift_calendar.services import (
    CalendarState,
    EmployeeShiftAssignmentService,
    ShiftCalendarService,
)
from apps.hr.models import (
    EmployeeAttendance,
    EmployeeShiftAssignment,
    RosterSegmentType,
    RotationPeriod,
    RotationPeriodType,
    ShiftAssignmentLayer,
    SiteRotation,
)
from apps.hr.models.attendance.choices import AttendanceStatus

from ..attendance.base import AttendanceImportTestCase


WIB = WALL_CLOCK_TZ


# Blok kerja peragaan: 1–28 Agustus 2026 WORK, lalu OFF.
BLOCK_START = date(2026, 8, 1)
BLOCK_DAYS = 28


class ShiftCalendarTestCase(AttendanceImportTestCase):
    """
    Pabrik tambahan di atas base Attendance Import.

    Base-nya sudah memuat perkakas yang persis dibutuhkan di sini —
    company, site, roster policy, tiga shift (kantor/siang/malam),
    Employee Group tanpa attendance, dan profil import. Membuat base
    kedua berarti dua tenant test dengan master yang harus dijaga tetap
    sama.
    """

    @classmethod
    def morning(cls):
        return cls.day_shift

    def make_site_employee(self, **kwargs):
        kwargs.setdefault("roster", True)
        kwargs.setdefault("shift", None)

        return self.make_employee(**kwargs)

    def make_block(self, employee, *, start=BLOCK_START, days=BLOCK_DAYS):
        return self.make_roster_days(employee, start=start, days=days)

    def make_segment(
        self,
        employee,
        *,
        rotation,
        sequence,
        segment_type,
        start,
        days,
    ):
        return RotationPeriod.objects.create(
            rotation=rotation,
            employee=employee,
            sequence=sequence,
            period_type=(
                RotationPeriodType.WORK
                if segment_type == RosterSegmentType.WORK
                else RotationPeriodType.OFF
            ),
            segment_type=segment_type,
            start_date=start,
            end_date=start + timedelta(days=days - 1),
            total_days=days,
            cycle_number=1,
        )

    def assign(
        self,
        employee,
        shift,
        start,
        end,
        *,
        layer=ShiftAssignmentLayer.BASELINE,
        reason="",
    ):
        return EmployeeShiftAssignmentService.create(
            data={
                "employee": employee,
                "shift": shift,
                "layer": layer,
                "start_date": start,
                "end_date": end,
                "reason": reason,
            },
        )


# ======================================================================
# 1. Rotation menentukan WORK/OFF — penugasan shift tidak pernah
# ======================================================================


class RotationRemainsAuthoritativeTests(ShiftCalendarTestCase):
    def test_work_day_inside_rotation_period_is_scheduled(self):
        employee = self.make_site_employee()

        self.make_block(employee)

        days = scheduled_work_days(
            employee,
            BLOCK_START,
            BLOCK_START + timedelta(days=BLOCK_DAYS - 1),
        )

        self.assertEqual(len(days), BLOCK_DAYS)
        self.assertIn(BLOCK_START, days)

    def test_day_outside_any_rotation_period_is_not_scheduled(self):
        employee = self.make_site_employee()

        self.make_block(employee)

        off_day = BLOCK_START + timedelta(days=BLOCK_DAYS + 2)

        self.assertEqual(
            scheduled_work_days(employee, off_day, off_day),
            set(),
        )

    def test_shift_assignment_never_creates_an_obligation(self):
        """
        Baris penugasan shift boleh membentang melewati blok OFF, dan
        pada tanggal OFF ia tidak dibaca sama sekali. Kalau ia ikut
        menjadwalkan, satu rencana shift enam minggu akan menerbitkan
        mangkir untuk seluruh masa cutinya.
        """
        employee = self.make_site_employee()

        self.make_block(employee, days=7)

        # Penugasan sebulan penuh, blok kerjanya cuma seminggu.
        self.assign(
            employee,
            self.night_shift,
            BLOCK_START,
            BLOCK_START + timedelta(days=29),
        )

        days = scheduled_work_days(
            employee,
            BLOCK_START,
            BLOCK_START + timedelta(days=29),
        )

        self.assertEqual(len(days), 7)

        off_day = BLOCK_START + timedelta(days=20)

        self.assertEqual(
            scheduled_window(employee, off_day),
            (None, None),
        )

    def test_field_break_and_travel_segments_are_not_scheduled(self):
        """
        Empat jenis segmen, dan hanya WORK yang berarti menekan mesin.
        Hari perjalanan bisa saja `period_type=work` menurut aturan #4
        dokumen Substansi Roster — yang dijawab di sini tetap "orangnya
        seharusnya tap atau tidak", dan yang di kapal tidak tap apa pun.
        """
        employee = self.make_site_employee()

        rotation = SiteRotation.objects.create(
            employee=employee,
            company=self.company,
            location=self.site,
            cycle_work_days=7,
            cycle_off_days=7,
            cycle_travel_days=2,
            start_date=BLOCK_START,
            cycle_count=1,
        )

        self.make_segment(
            employee,
            rotation=rotation,
            sequence=1,
            segment_type=RosterSegmentType.WORK,
            start=BLOCK_START,
            days=7,
        )

        travel_out = BLOCK_START + timedelta(days=7)

        self.make_segment(
            employee,
            rotation=rotation,
            sequence=2,
            segment_type=RosterSegmentType.TRAVEL_OUT,
            start=travel_out,
            days=1,
        )

        field_break = BLOCK_START + timedelta(days=8)

        self.make_segment(
            employee,
            rotation=rotation,
            sequence=3,
            segment_type=RosterSegmentType.FIELD_BREAK,
            start=field_break,
            days=5,
        )

        window_end = BLOCK_START + timedelta(days=13)

        days = scheduled_work_days(employee, BLOCK_START, window_end)

        self.assertEqual(len(days), 7)
        self.assertNotIn(travel_out, days)
        self.assertNotIn(field_break, days)

        states = rotation_states(employee, BLOCK_START, window_end)

        self.assertEqual(states[BLOCK_START], RosterSegmentType.WORK)
        self.assertEqual(
            states[travel_out],
            RosterSegmentType.TRAVEL_OUT,
        )
        self.assertEqual(
            states[field_break],
            RosterSegmentType.FIELD_BREAK,
        )


# ======================================================================
# 2. Shift efektif — termasuk yang berganti di dalam satu blok kerja
# ======================================================================


class EffectiveShiftTests(ShiftCalendarTestCase):
    def test_baseline_assignment_wins_over_permanent_employment_shift(self):
        """
        `EmploymentAssignment.shift` tetap jalur yang sah, tapi ia
        bicara tentang orangnya, bukan tanggalnya. Yang menyebut
        tanggal harus menang — kalau tidak, penugasan shift jadi kolom
        yang tersimpan rapi lalu tidak pernah dibaca.
        """
        employee = self.make_site_employee(shift=self.day_shift)

        self.make_block(employee)

        self.assign(
            employee,
            self.night_shift,
            BLOCK_START,
            BLOCK_START + timedelta(days=6),
        )

        resolved = resolve_shift(employee, BLOCK_START)

        self.assertEqual(resolved.shift_code, self.night_shift.code)
        self.assertEqual(resolved.source, ShiftSource.BASELINE)

        # Di luar rentang penugasan, shift permanennya yang menjawab.
        later = BLOCK_START + timedelta(days=10)

        fallback = resolve_shift(employee, later)

        self.assertEqual(fallback.shift_code, self.day_shift.code)
        self.assertEqual(fallback.source, ShiftSource.EMPLOYMENT)

    def test_shift_changes_inside_one_work_block(self):
        """
        Ini yang tidak bisa dinyatakan sebelum ada tabel penugasan:
        satu blok kerja, tiga shift berbeda per minggu. `RosterCrew`
        cuma menunjuk satu `WorkSchedule`, dan `WorkScheduleDay`
        berbasis hari-dalam-minggu — dua-duanya tidak punya tempat
        untuk "minggu keberapa dalam siklus".
        """
        employee = self.make_site_employee()

        self.make_block(employee)

        plan = [
            (self.office_shift, date(2026, 8, 1), date(2026, 8, 7)),
            (self.night_shift, date(2026, 8, 8), date(2026, 8, 14)),
            (self.day_shift, date(2026, 8, 15), date(2026, 8, 21)),
        ]

        for shift, start, end in plan:
            self.assign(employee, shift, start, end)

        for shift, start, end in plan:
            for offset in range((end - start).days + 1):
                day = start + timedelta(days=offset)

                self.assertEqual(
                    resolve_shift(employee, day).shift_code,
                    shift.code,
                    msg=f"{day} seharusnya {shift.code}",
                )

    def test_calendar_reports_one_cell_per_date(self):
        employee = self.make_site_employee()

        self.make_block(employee)

        self.assign(
            employee,
            self.night_shift,
            date(2026, 8, 8),
            date(2026, 8, 14),
        )

        calendar = ShiftCalendarService.build(
            employee=employee,
            start=date(2026, 8, 1),
            end=date(2026, 8, 31),
        )

        self.assertEqual(len(calendar["days"]), 31)

        cells = {row["date"]: row for row in calendar["days"]}

        work_cell = cells[date(2026, 8, 10)]

        self.assertEqual(work_cell["rotation_state"], CalendarState.WORK)
        self.assertTrue(work_cell["is_scheduled"])
        self.assertEqual(work_cell["shift_code"], self.night_shift.code)
        self.assertTrue(work_cell["crosses_midnight"])
        self.assertEqual(work_cell["shift_source"], ShiftSource.BASELINE)
        self.assertFalse(work_cell["is_override"])

        # 29 Agustus di luar blok 1–28: bukan hari kerja, dan karena
        # itu tidak membawa jam sama sekali.
        off_cell = cells[date(2026, 8, 29)]

        self.assertFalse(off_cell["is_scheduled"])
        self.assertIsNone(off_cell["scheduled_check_in"])
        self.assertEqual(off_cell["shift_code"], "")


# ======================================================================
# 3. Default + override
# ======================================================================


class OverrideTests(ShiftCalendarTestCase):
    def _employee_with_plan(self):
        employee = self.make_site_employee()

        self.make_block(employee)

        self.assign(
            employee,
            self.night_shift,
            date(2026, 8, 8),
            date(2026, 8, 14),
        )

        return employee

    def test_override_wins_inside_its_range(self):
        employee = self._employee_with_plan()

        self.assign(
            employee,
            self.day_shift,
            date(2026, 8, 10),
            date(2026, 8, 12),
            layer=ShiftAssignmentLayer.OVERRIDE,
            reason="Coverage plant shutdown",
        )

        for day in (date(2026, 8, 10), date(2026, 8, 11), date(2026, 8, 12)):
            resolved = resolve_shift(employee, day)

            self.assertEqual(resolved.shift_code, self.day_shift.code)
            self.assertEqual(resolved.source, ShiftSource.OVERRIDE)
            self.assertTrue(resolved.is_override)

    def test_dates_outside_the_override_keep_the_baseline(self):
        """
        Inti pemisahan dua lapis. Kalau override memecah baris
        baseline-nya jadi tiga, rencana 8–14 Agustus hilang dan tidak
        ada lagi yang bisa dijawab saat penyesuaiannya dibatalkan.
        """
        employee = self._employee_with_plan()

        self.assign(
            employee,
            self.day_shift,
            date(2026, 8, 10),
            date(2026, 8, 12),
            layer=ShiftAssignmentLayer.OVERRIDE,
            reason="Coverage plant shutdown",
        )

        expected = {
            date(2026, 8, 8): self.night_shift.code,
            date(2026, 8, 9): self.night_shift.code,
            date(2026, 8, 10): self.day_shift.code,
            date(2026, 8, 11): self.day_shift.code,
            date(2026, 8, 12): self.day_shift.code,
            date(2026, 8, 13): self.night_shift.code,
            date(2026, 8, 14): self.night_shift.code,
        }

        for day, code in expected.items():
            self.assertEqual(
                resolve_shift(employee, day).shift_code,
                code,
                msg=f"{day} seharusnya {code}",
            )

        # Baris baseline-nya masih utuh — satu baris, bukan tiga.
        self.assertEqual(
            EmployeeShiftAssignment.objects.filter(
                employee=employee,
                layer=ShiftAssignmentLayer.BASELINE,
                is_deleted=False,
            ).count(),
            1,
        )

    def test_removing_the_override_restores_the_baseline(self):
        employee = self._employee_with_plan()

        override = self.assign(
            employee,
            self.day_shift,
            date(2026, 8, 10),
            date(2026, 8, 12),
            layer=ShiftAssignmentLayer.OVERRIDE,
            reason="Coverage plant shutdown",
        )

        EmployeeShiftAssignmentService.delete(instance=override)

        self.assertEqual(
            resolve_shift(employee, date(2026, 8, 11)).shift_code,
            self.night_shift.code,
        )

    def test_overlapping_assignments_on_the_same_layer_are_rejected(self):
        employee = self._employee_with_plan()

        with self.assertRaises(ValidationError) as caught:
            self.assign(
                employee,
                self.day_shift,
                date(2026, 8, 12),
                date(2026, 8, 20),
            )

        self.assertIn("start_date", caught.exception.message_dict)

    def test_overlap_across_layers_is_exactly_the_mechanism(self):
        employee = self._employee_with_plan()

        override = self.assign(
            employee,
            self.day_shift,
            date(2026, 8, 10),
            date(2026, 8, 12),
            layer=ShiftAssignmentLayer.OVERRIDE,
            reason="Coverage plant shutdown",
        )

        self.assertIsNotNone(override.pk)

    def test_adjustment_without_a_reason_is_rejected(self):
        employee = self._employee_with_plan()

        with self.assertRaises(ValidationError) as caught:
            self.assign(
                employee,
                self.day_shift,
                date(2026, 8, 10),
                date(2026, 8, 12),
                layer=ShiftAssignmentLayer.OVERRIDE,
            )

        self.assertIn("reason", caught.exception.message_dict)

    def test_end_before_start_is_rejected(self):
        employee = self.make_site_employee()

        with self.assertRaises(ValidationError) as caught:
            self.assign(
                employee,
                self.day_shift,
                date(2026, 8, 12),
                date(2026, 8, 10),
            )

        self.assertIn("end_date", caught.exception.message_dict)


# ======================================================================
# 4. Jam datang dari master, bukan dari kode
# ======================================================================


class ShiftMasterIsTheSourceOfTruthTests(ShiftCalendarTestCase):
    def test_changing_the_shift_master_changes_the_effective_window(self):
        """
        Tidak ada satu baris kode pun yang berubah di test ini — cuma
        dua kolom di master `Shift`. Kalau jendelanya tidak ikut
        bergeser, berarti ada jam yang tersimpan di tempat kedua.
        """
        employee = self.make_site_employee()

        self.make_block(employee)

        shift = Shift.objects.create(
            code="AIM-CONFIG",
            name="Configurable",
            start_time=time(7, 0),
            end_time=time(15, 0),
        )

        self.assign(
            employee,
            shift,
            BLOCK_START,
            BLOCK_START + timedelta(days=6),
        )

        check_in, check_out = scheduled_window(employee, BLOCK_START)

        self.assertEqual(
            check_in.astimezone(WIB),
            datetime(2026, 8, 1, 7, 0, tzinfo=WIB),
        )
        self.assertEqual(
            check_out.astimezone(WIB),
            datetime(2026, 8, 1, 15, 0, tzinfo=WIB),
        )

        shift.start_time = time(6, 30)
        shift.end_time = time(14, 30)
        shift.save(update_fields=["start_time", "end_time"])

        employee.refresh_from_db()

        check_in, check_out = scheduled_window(employee, BLOCK_START)

        self.assertEqual(
            check_in.astimezone(WIB),
            datetime(2026, 8, 1, 6, 30, tzinfo=WIB),
        )
        self.assertEqual(
            check_out.astimezone(WIB),
            datetime(2026, 8, 1, 14, 30, tzinfo=WIB),
        )

    def test_night_shift_window_crosses_midnight(self):
        employee = self.make_site_employee()

        self.make_block(employee)

        self.assign(
            employee,
            self.night_shift,
            date(2026, 8, 25),
            date(2026, 8, 28),
        )

        check_in, check_out = scheduled_window(employee, date(2026, 8, 25))

        self.assertEqual(
            check_in.astimezone(WIB),
            datetime(2026, 8, 25, 19, 0, tzinfo=WIB),
        )

        # Tanggal pulangnya **berikutnya**. Tanpa ini jam kerja
        # terhitung negatif lalu dijepit jadi nol, dan seluruh shift
        # malam tampak nol jam.
        self.assertEqual(
            check_out.astimezone(WIB),
            datetime(2026, 8, 26, 7, 0, tzinfo=WIB),
        )

    def test_a_shift_whose_end_precedes_its_start_also_crosses(self):
        """
        `crosses_midnight` adalah penanda, bukan satu-satunya bukti.
        Master yang lupa mencentangnya tetap tidak boleh menghasilkan
        jam kerja negatif.
        """
        employee = self.make_site_employee()

        self.make_block(employee)

        shift = Shift.objects.create(
            code="AIM-UNFLAGGED",
            name="Unflagged Night",
            start_time=time(23, 0),
            end_time=time(7, 0),
            crosses_midnight=False,
        )

        self.assign(
            employee,
            shift,
            date(2026, 8, 25),
            date(2026, 8, 26),
        )

        _, check_out = scheduled_window(employee, date(2026, 8, 25))

        self.assertEqual(
            check_out.astimezone(WIB),
            datetime(2026, 8, 26, 7, 0, tzinfo=WIB),
        )


# ======================================================================
# 5. Perhitungan presensi shift malam
# ======================================================================


class NightShiftAttendanceTests(ShiftCalendarTestCase):
    def _night_employee(self):
        employee = self.make_site_employee()

        self.make_block(employee, start=date(2026, 8, 20), days=14)

        self.assign(
            employee,
            self.night_shift,
            date(2026, 8, 20),
            date(2026, 8, 31),
        )

        return employee

    def test_late_is_measured_against_the_night_window(self):
        employee = self._night_employee()

        check_in, check_out = scheduled_window(employee, date(2026, 8, 25))

        result = AttendancePolicyResolver.compute(
            scheduled_check_in=check_in,
            scheduled_check_out=check_out,
            check_in=datetime(2026, 8, 25, 19, 25, tzinfo=WIB),
            check_out=datetime(2026, 8, 26, 7, 5, tzinfo=WIB),
            rules=AttendancePolicyResolver.rules_for(employee),
        )

        self.assertEqual(result["late_minutes"], 25)
        self.assertEqual(result["status"], AttendanceStatus.LATE)

    def test_early_leave_after_midnight_is_measured_correctly(self):
        employee = self._night_employee()

        check_in, check_out = scheduled_window(employee, date(2026, 8, 25))

        result = AttendancePolicyResolver.compute(
            scheduled_check_in=check_in,
            scheduled_check_out=check_out,
            check_in=datetime(2026, 8, 25, 18, 55, tzinfo=WIB),
            check_out=datetime(2026, 8, 26, 5, 30, tzinfo=WIB),
            rules=AttendancePolicyResolver.rules_for(employee),
        )

        self.assertEqual(result["early_leave_minutes"], 90)
        self.assertEqual(result["late_minutes"], 0)

    def test_out_after_midnight_maps_back_to_the_previous_work_date(self):
        """
        Jalur importer penuh, dengan shift yang datang dari **penugasan
        per tanggal** — bukan dari `EmploymentAssignment.shift`. Yang
        diuji: satu baris presensi tanggal 25, bukan dua baris setengah.
        """
        employee = self._night_employee()

        profile = self.site_profile("AIM-CAL-NIGHT")

        device = self.make_device("AIM-CAL-DEV")

        self.map_device_employee(device, "77", employee)

        profile.options = {
            "attendance": {
                **profile.options["attendance"],
                "device_code": device.code,
            },
        }

        profile.save(update_fields=["options"])

        path = self._write_taps(
            "77",
            ["25/08/2026 22.55.00", "26/08/2026 07.05.00"],
        )

        from apps.framework.imports import ImportPipelineService

        result = ImportPipelineService.execute(
            module="hr/attendance",
            file_path=path,
            source_type="csv",
            parser_options=profile.parser_options,
            mapping=profile.mapping,
            defaults=profile.defaults or None,
            value_mapping=profile.value_mapping or None,
            date_formats=profile.datetime_formats or None,
            options=profile.options,
            profile=profile,
        )

        self.assertEqual(result["created_rows"], 1)

        rows = list(
            EmployeeAttendance.objects
            .filter(employee=employee, is_deleted=False)
        )

        self.assertEqual(len(rows), 1)

        attendance = rows[0]

        self.assertEqual(attendance.work_date, date(2026, 8, 25))

        self.assertEqual(
            attendance.check_out.astimezone(WIB),
            datetime(2026, 8, 26, 7, 5, tzinfo=WIB),
        )

        self.assertEqual(
            attendance.scheduled_check_out.astimezone(WIB),
            datetime(2026, 8, 26, 7, 0, tzinfo=WIB),
        )

    def _write_taps(self, machine_id, stamps):
        import tempfile

        header = (
            "Departemen\tNama\tNo.ID\tTgl/Waktu\tLokasi ID\tNo.PIN"
            "\tKode Verifikasi\tNo.Kartu"
        )

        lines = [header]

        for stamp in stamps:
            lines.append(
                f'"OUR COMPANY"\t"Night"\t"{machine_id}"\t{stamp}\t"1"\t""'
                f'\t"Sidik Jari"\t""'
            )

        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".csv",
            delete=False,
        )

        handle.write(("\r\n".join(lines) + "\r\n").encode("utf-8"))
        handle.close()

        self.addCleanup(
            lambda: Path(handle.name).unlink(missing_ok=True),
        )

        return Path(handle.name)


# ======================================================================
# 6. Feature Applicability
# ======================================================================


class ApplicabilityTests(ShiftCalendarTestCase):
    def test_off_day_produces_no_absent_row(self):
        employee = self.make_site_employee()

        self.make_block(employee, days=7)

        AttendanceClosingService.close(
            start=BLOCK_START,
            end=BLOCK_START + timedelta(days=13),
        )

        rows = EmployeeAttendance.objects.filter(
            employee=employee,
            is_deleted=False,
        )

        # Tujuh hari kerja jadi tujuh baris mangkir; tujuh hari off
        # tidak menghasilkan apa pun.
        self.assertEqual(rows.count(), 7)

        self.assertEqual(
            rows.filter(status=AttendanceStatus.ABSENT).count(),
            7,
        )

        self.assertFalse(
            rows.filter(
                work_date__gt=BLOCK_START + timedelta(days=6),
            ).exists(),
        )

    def test_group_without_attendance_gets_no_obligation(self):
        employee = self.make_site_employee(group=self.no_attendance_group)

        self.make_block(employee, days=7)

        self.assertEqual(
            scheduled_work_days(
                employee,
                BLOCK_START,
                BLOCK_START + timedelta(days=6),
            ),
            set(),
        )

        AttendanceClosingService.close(
            start=BLOCK_START,
            end=BLOCK_START + timedelta(days=6),
        )

        self.assertFalse(
            EmployeeAttendance.objects
            .filter(employee=employee, is_deleted=False)
            .exists(),
        )

    def test_calendar_marks_every_day_not_applicable(self):
        employee = self.make_site_employee(group=self.no_attendance_group)

        self.make_block(employee, days=7)

        calendar = ShiftCalendarService.build(
            employee=employee,
            start=BLOCK_START,
            end=BLOCK_START + timedelta(days=6),
        )

        self.assertFalse(calendar["attendance_applicable"])
        self.assertEqual(calendar["scheduled_days"], 0)

        for cell in calendar["days"]:
            self.assertEqual(
                cell["rotation_state"],
                CalendarState.NOT_APPLICABLE,
            )
            self.assertFalse(cell["is_scheduled"])
            self.assertIsNone(cell["scheduled_check_in"])

    def test_the_same_group_processed_normally_once_attendance_is_on(self):
        """
        Perilakunya berubah dari **konfigurasi**, bukan dari kode group.
        Group yang sama, satu kolom dibalik, dan kewajibannya kembali.
        """
        group = self.no_attendance_group

        employee = self.make_site_employee(group=group)

        self.make_block(employee, days=7)

        group.attendance_applicable = True
        group.save(update_fields=["attendance_applicable"])

        employee.refresh_from_db()

        self.assertEqual(
            len(
                scheduled_work_days(
                    employee,
                    BLOCK_START,
                    BLOCK_START + timedelta(days=6),
                ),
            ),
            7,
        )

        group.attendance_applicable = False
        group.save(update_fields=["attendance_applicable"])

    def test_a_group_with_attendance_on_is_processed_normally(self):
        from apps.administration.models.references.hr import EmployeeGroup

        group = EmployeeGroup.objects.create(
            code="AIM-MGMT",
            name="Management",
            attendance_applicable=True,
        )

        employee = self.make_site_employee(group=group)

        self.make_block(employee, days=7)

        self.assign(
            employee,
            self.day_shift,
            BLOCK_START,
            BLOCK_START + timedelta(days=6),
        )

        self.assertEqual(
            len(
                scheduled_work_days(
                    employee,
                    BLOCK_START,
                    BLOCK_START + timedelta(days=6),
                ),
            ),
            7,
        )

        check_in, _ = scheduled_window(employee, BLOCK_START)

        self.assertIsNotNone(check_in)


# ======================================================================
# 7. Tidak ada perilaku yang di-hardcode
# ======================================================================


ENGINE_SOURCES = [
    "apps/hr/api/attendance/schedule.py",
    "apps/hr/api/attendance/policy.py",
    "apps/hr/api/shift_calendar/services.py",
    "apps/hr/imports/attendance/workdate.py",
    "apps/hr/imports/attendance/importer.py",
    "apps/hr/imports/attendance/resolver.py",
    "apps/hr/models/shift_assignment.py",
]


class NoHardcodedBehaviourTests(ShiftCalendarTestCase):
    """
    Pemindaian sumber. Bukan gaya: begitu satu kode shift atau satu
    awalan nomor pegawai muncul di engine, konfigurasi master berhenti
    menentukan hasil dan tidak ada test perilaku yang bisa
    menunjukkannya — angkanya tetap terlihat benar untuk data uji yang
    kebetulan cocok.
    """

    def _read(self, relative):
        root = Path(__file__).resolve().parents[4]

        return (root / relative).read_text(encoding="utf-8")

    def test_no_shift_code_literals_in_the_attendance_engine(self):
        forbidden = [
            "SHIFT-1",
            "SHIFT-2",
            "SHIFT-3",
            "SITE-DAY",
            '"NIGHT"',
            "'NIGHT'",
            '"DAY"',
            "OFFICE-10",
        ]

        for relative in ENGINE_SOURCES:
            source = self._read(relative)

            for literal in forbidden:
                self.assertNotIn(
                    literal,
                    source,
                    msg=(
                        f"{relative} menyebut kode shift {literal}; "
                        "jam kerja harus datang dari master."
                    ),
                )

    def test_no_employee_number_prefix_or_location_code_literals(self):
        forbidden = ["SGA", "HO0", "SAGEA", "JKT-HO", "MMR-"]

        for relative in ENGINE_SOURCES:
            source = self._read(relative)

            for literal in forbidden:
                self.assertNotIn(
                    literal,
                    source,
                    msg=(
                        f"{relative} menyebut {literal}; semantik site "
                        "tidak boleh disimpulkan dari nomor pegawai "
                        "atau kode lokasi."
                    ),
                )

    def test_no_group_code_literals_in_the_attendance_engine(self):
        forbidden = ['"BOARD"', "'BOARD'", '"MANAGEMENT"', "'MANAGEMENT'"]

        for relative in ENGINE_SOURCES:
            source = self._read(relative)

            for literal in forbidden:
                self.assertNotIn(
                    literal,
                    source,
                    msg=(
                        f"{relative} menyebut kode Employee Group "
                        f"{literal}; yang memutuskan Feature "
                        "Applicability."
                    ),
                )
