"""
Dua bentuk file, satu engine.

`ImportProfile.options.attendance.row_mode` yang membedakan berapa
kejadian lahir dari satu baris:

* **`raw_tap`** — satu baris = satu tekan. Bentuk mesin sidik jari site:
  `No.ID` + `Tgl/Waktu`.
* **`daily_in_out`** — satu baris = satu tanggal, dengan jam masuk dan
  jam pulang di dua kolom terpisah. Bentuk rekap harian kantor:
  `no` + `ymd` + `work1` + `work2`.

Yang dijaga berkas ini, dan tiap poinnya pernah jadi cara file harian
gagal terbaca:

1. **Mode harian tidak menuntut kolom timestamp.** Percobaan pertama
   gagal persis di situ: file yang memang tidak punya kolom itu dibalas
   "Timestamp '' could not be read", dan pesannya menuntun orang ke
   tempat yang salah.
2. **Satu baris harian melahirkan dua event**, bukan satu. Membuang
   kolom jam pulang adalah cara paling sunyi untuk melaporkan hari
   kerja yang terlihat lengkap padahal separuh.
3. **Sisi yang tidak ada tidak pernah dikarang.** Jam pulang kosong
   menghasilkan satu event bertanda `INCOMPLETE DAY`, bukan jam pulang
   yang disamakan dengan jam masuk.
4. **Kedua mode memakai importer yang sama** — tidak ada cabang HO/Site
   di kode.
"""

from __future__ import annotations

import collections
from datetime import date
from decimal import Decimal

from apps.administration.models import AttendancePolicy
from apps.framework.imports import ImportPipelineService, get_importer
from apps.hr.api.attendance.schedule import WALL_CLOCK_TZ
from apps.hr.imports.attendance import statuses
from apps.hr.models import AttendanceStatus, EmployeeAttendance

from .base import FIXTURES, MODULE, AttendanceImportTestCase


DAILY_FILE = FIXTURES / "ho_daily_in_out.csv"
SITE_FILE = FIXTURES / "site_fingerprint_tab.csv"

# Rabu dan Kamis — dua hari kerja kantor berturut-turut.
DAY_ONE = date(2026, 7, 1)
DAY_TWO = date(2026, 7, 2)


def run(profile, path, *, commit=False):
    call = (
        ImportPipelineService.execute
        if commit
        else ImportPipelineService.preview
    )

    return call(
        module=MODULE,
        file_path=path,
        source_type="csv",
        parser_options=profile.parser_options,
        mapping=profile.mapping or None,
        defaults=profile.defaults or None,
        value_mapping=profile.value_mapping or None,
        date_formats=profile.datetime_formats or None,
        options=profile.options or None,
        profile=profile,
    )


def rows_for(result, machine_id):
    return [
        row
        for row in result["rows"]
        if row["raw_employee_id"] == machine_id
    ]


class DailyInOutTests(AttendanceImportTestCase):
    def setUp(self):
        super().setUp()

        self.people = {
            number: self.make_employee(
                number=number,
                shift=self.office_shift,
            )
            for number in ("HO101", "HO102", "HO103", "HO104")
        }

    def test_one_daily_row_becomes_two_events(self):
        profile = self.daily_profile("AIM-DAILY-1")

        result = run(profile, DAILY_FILE)

        # Enam baris file; yang lengkap melahirkan dua event, sisanya
        # satu. Jumlah baris **file** tetap dilaporkan apa adanya.
        self.assertEqual(result["source_rows"], 6)

        # Enam baris file -> delapan event:
        #   dua baris lengkap  -> 2 in + 2 out
        #   dua baris tanpa pulang / jamnya identik -> 2 in
        #   satu baris tanpa jam sama sekali -> 1 baris bermasalah
        #   satu baris hanya jam pulang -> 1 out
        self.assertEqual(result["total_rows"], 8)

        events = collections.Counter(
            row["log_type"] for row in result["rows"]
        )

        self.assertEqual(events["in"], 4)
        self.assertEqual(events["out"], 3)

        complete = rows_for(result, "HO101")

        self.assertEqual(len(complete), 4)

        first_day = [
            row for row in complete if row["work_date"] == DAY_ONE.isoformat()
        ]

        self.assertEqual(
            [row["log_type"] for row in first_day],
            ["in", "out"],
        )

        # Keduanya menunjuk baris file yang sama.
        self.assertEqual(
            {row["row_number"] for row in first_day},
            {2},
        )

    def test_daily_mode_never_asks_for_a_timestamp_column(self):
        """
        File harian tidak punya kolom timestamp, dan tidak boleh
        dituntut memilikinya — baik di validasi maupun di penjelasan
        format yang dibaca layar import.
        """
        profile = self.daily_profile("AIM-DAILY-2")

        result = run(profile, DAILY_FILE)

        messages = " ".join(row["message"] for row in result["rows"])

        self.assertNotIn("Timestamp", messages)

        described = get_importer(MODULE).describe_profile(profile)

        labels = {item["label"] for item in described["summary"]}

        self.assertNotIn("Timestamp Column", labels)
        self.assertNotIn("Datetime Format", labels)

        self.assertEqual(
            {"Work Date Column", "Check In Column", "Check Out Column"}
            - labels,
            set(),
        )

        summary = {
            item["label"]: item["value"] for item in described["summary"]
        }

        self.assertEqual(summary["Work Date Column"], "ymd")
        self.assertEqual(summary["Check In Column"], "work1")
        self.assertEqual(summary["Check Out Column"], "work2")
        self.assertEqual(summary["Employee ID Column"], "no")
        self.assertIn("Daily In/Out", summary["Row Mode"])

    def test_identifier_and_formats_come_from_the_profile(self):
        profile = self.daily_profile("AIM-DAILY-3")

        result = run(profile, DAILY_FILE)

        resolved = {
            row["employee_code"]
            for row in result["rows"]
            if row["employee_code"]
        }

        # HO103 sengaja tidak ikut: barisnya tidak punya jam sama
        # sekali, jadi ia gagal di tahap waktu dan tidak pernah sampai
        # ke resolusi pegawai. Itu urutan yang benar — mencari orang
        # untuk baris yang jamnya tidak terbaca cuma menghabiskan query.
        self.assertEqual(resolved, {"HO101", "HO102", "HO104"})

        # `2026/07/01` + `09:52` dibaca lewat format profile.
        first = rows_for(result, "HO101")[0]

        self.assertEqual(first["work_date"], DAY_ONE.isoformat())
        self.assertEqual(first["raw_timestamp"], "2026/07/01 09:52")
        self.assertTrue(first["log_time"].startswith("2026-07-01T09:52"))

    def test_missing_check_out_is_flagged_not_invented(self):
        profile = self.daily_profile("AIM-DAILY-4")

        result = run(profile, DAILY_FILE)

        rows = rows_for(result, "HO102")

        by_date = {row["work_date"]: row for row in rows}

        # Jam pulang kosong: satu event saja, ditandai.
        no_out = by_date[DAY_ONE.isoformat()]

        self.assertEqual(no_out["log_type"], "in")
        self.assertEqual(no_out["status"], statuses.INCOMPLETE_DAY)
        self.assertIn("no check out", no_out["message"].lower())

        # Masuk dan pulang identik: satu tap yang tercatat dua kali,
        # bukan hari kerja nol menit.
        identical = by_date[DAY_TWO.isoformat()]

        self.assertEqual(identical["status"], statuses.INCOMPLETE_DAY)
        self.assertIn("identical", identical["message"].lower())

        self.assertEqual(len(rows), 2)

    def test_row_without_any_time_is_reported_not_dropped(self):
        profile = self.daily_profile("AIM-DAILY-5")

        result = run(profile, DAILY_FILE)

        empty = rows_for(result, "HO103")

        self.assertEqual(len(empty), 1)
        self.assertEqual(empty[0]["status"], statuses.INVALID_DATETIME)

        # Pesannya menyebut kolomnya, bukan "timestamp".
        self.assertIn("time", empty[0]["message"].lower())
        self.assertNotIn("Timestamp", empty[0]["message"])

    def test_check_out_without_check_in_still_imports(self):
        profile = self.daily_profile("AIM-DAILY-6")

        result = run(profile, DAILY_FILE)

        only_out = rows_for(result, "HO104")

        self.assertEqual(len(only_out), 1)
        self.assertEqual(only_out[0]["log_type"], "out")
        self.assertEqual(only_out[0]["status"], statuses.INCOMPLETE_DAY)

    def test_commit_writes_one_attendance_row_per_work_date(self):
        profile = self.daily_profile("AIM-DAILY-7")

        result = run(profile, DAILY_FILE, commit=True)

        self.assertEqual(result["source_rows"], 6)

        # Lima baris presensi: HO101 dua hari, HO102 dua hari,
        # HO104 satu hari. HO103 tidak punya jam sama sekali.
        self.assertEqual(
            result["created_rows"] + result["updated_rows"],
            7,
        )

        person = self.people["HO101"]

        first_day = EmployeeAttendance.objects.get(
            employee=person,
            work_date=DAY_ONE,
            is_deleted=False,
        )

        # Dibandingkan pada jam dinding yang sama dengan resolver
        # jadwal. `tzinfo` hasil round-trip database adalah UTC, dan
        # membandingkan di situ menghasilkan 02:52 — benar sebagai
        # instant, tapi bukan yang ditulis mesinnya.
        self.assertEqual(
            first_day.check_in.astimezone(WALL_CLOCK_TZ).strftime("%H:%M"),
            "09:52",
        )

        self.assertEqual(
            first_day.check_out.astimezone(WALL_CLOCK_TZ).strftime("%H:%M"),
            "18:08",
        )

        self.assertFalse(
            EmployeeAttendance.objects
            .filter(employee=self.people["HO103"], is_deleted=False)
            .exists(),
        )

    def test_re_importing_a_daily_file_is_idempotent(self):
        profile = self.daily_profile("AIM-DAILY-8")

        run(profile, DAILY_FILE, commit=True)

        again = run(profile, DAILY_FILE, commit=True)

        self.assertEqual(again["created_rows"], 0)
        self.assertEqual(again["updated_rows"], 0)

        # Tujuh event yang sah dikenali sebagai duplikat. Baris kedelapan
        # — yang tidak punya jam sama sekali — tetap invalid: ia tidak
        # pernah punya sidik jari, jadi tidak ada yang bisa diduplikasi.
        self.assertEqual(again["duplicate_rows"], 7)
        self.assertEqual(again["invalid_rows"], 1)

    def test_late_beyond_policy_threshold_becomes_an_exception(self):
        """
        Ambangnya tetap milik `AttendancePolicy`. Yang dibuktikan di
        sini cuma bahwa jalur harian sampai ke mesin yang sama dengan
        jalur tap mentah.
        """
        AttendancePolicy.objects.create(
            code="AIM-DAILY-POL",
            name="Daily",
            location=self.site,
            late_tolerance_minutes=1,
            early_leave_tolerance_minutes=1,
            late_leave_threshold_minutes=120,
            early_leave_leave_threshold_minutes=120,
            leave_deduction_days=Decimal("1.00"),
        )

        profile = self.daily_profile("AIM-DAILY-9")

        run(profile, DAILY_FILE, commit=True)

        # HO101 tanggal 2: masuk 12:30 terhadap jadwal 10:00 = 150 menit.
        late_day = EmployeeAttendance.objects.get(
            employee=self.people["HO101"],
            work_date=DAY_TWO,
            is_deleted=False,
        )

        self.assertEqual(late_day.status, AttendanceStatus.LATE)
        self.assertEqual(late_day.late_minutes, 149)
        self.assertEqual(late_day.leave_required_days, Decimal("1.00"))
        self.assertEqual(late_day.leave_required_reason, "late")

        # Hari pertama tepat waktu, jadi tidak ada kewajiban apa pun.
        on_time = EmployeeAttendance.objects.get(
            employee=self.people["HO101"],
            work_date=DAY_ONE,
            is_deleted=False,
        )

        self.assertEqual(on_time.leave_required_days, Decimal("0.00"))


class RawTapStillWorksTests(AttendanceImportTestCase):
    """
    Mode tap mentah tidak boleh ikut berubah gara-gara mode harian
    ditambahkan. Ini yang menahannya.
    """

    def test_site_raw_tap_still_produces_one_event_per_row(self):
        profile = self.site_profile("AIM-RAW-1")

        employee = self.make_employee(roster=True, shift=self.day_shift)

        self.make_roster_days(employee, start=date(2026, 7, 1), days=30)

        device = self.make_device("AIM-RAW-DEV")

        self.map_device_employee(device, "1", employee)

        profile.options = {
            "attendance": {
                **profile.options["attendance"],
                "device_code": device.code,
            },
        }

        profile.save(update_fields=["options"])

        result = run(profile, SITE_FILE)

        # Tujuh baris file, tujuh event — tidak ada pemekaran.
        self.assertEqual(result["source_rows"], 7)
        self.assertEqual(result["total_rows"], 7)

        self.assertEqual(
            {row["log_type"] for row in result["rows"]},
            {"unknown"},
        )

        self.assertEqual(
            {row["row_number"] for row in result["rows"]},
            {2, 3, 4, 5, 6, 7, 8},
        )

    def test_default_row_mode_is_raw_tap(self):
        """
        Profil lama tidak menyebut `row_mode` sama sekali, dan artinya
        tidak boleh berubah.
        """
        from apps.hr.imports.attendance.config import (
            ROW_MODE_RAW_TAP,
            AttendanceImportConfig,
        )

        self.assertEqual(
            AttendanceImportConfig.from_options({}).row_mode,
            ROW_MODE_RAW_TAP,
        )

        self.assertEqual(
            AttendanceImportConfig.from_options(
                {"attendance": {"timezone": "Asia/Jakarta"}},
            ).row_mode,
            ROW_MODE_RAW_TAP,
        )

        # Nilai yang salah ketik jatuh ke bawaan, bukan melempar —
        # profile ditulis manusia lewat JSON.
        self.assertEqual(
            AttendanceImportConfig.from_options(
                {"attendance": {"row_mode": "dayly"}},
            ).row_mode,
            ROW_MODE_RAW_TAP,
        )


class MissingColumnDiagnosticTests(AttendanceImportTestCase):
    """
    Kolom yang tidak ada dan nilai yang tidak terbaca adalah **dua**
    sebab berbeda, dan keduanya dulu dilaporkan dengan kalimat yang
    sama: "could not be read with this profile's datetime formats".

    Akibatnya nyata: file yang kolomnya bernama `log_time` ditolak oleh
    profile yang mencari `timestamp`, dan pesannya mengirim orang
    mengutak-atik format tanggal — tempat yang sama sekali salah.
    Perbaikannya diperbaiki dengan mengubah `mapping`, bukan
    `datetime_formats`.
    """

    def canonical_file(self):
        return self.write_csv(
            "employee_code,log_time,log_type,device_code",
            "AIMX001,2026-07-01 09:52:00,in,AIM-CANON",
            "AIMX001,2026-07-01 18:08:00,out,AIM-CANON",
        )

    def write_csv(self, *lines):
        import tempfile
        from pathlib import Path

        handle = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".csv",
            delete=False,
            encoding="utf-8",
        )

        handle.write("\n".join(lines) + "\n")
        handle.close()

        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))

        return Path(handle.name)

    def test_missing_timestamp_column_says_so_and_lists_the_file(self):
        profile = self.make_profile(
            "AIM-MISS-1",
            mapping={
                "employee_code": ["employee_code"],
                "log_time": ["timestamp", "datetime"],
            },
        )

        self.make_employee(number="AIMX001", shift=self.office_shift)

        result = run(profile, self.canonical_file())

        row = result["rows"][0]

        self.assertEqual(row["status"], statuses.INVALID_DATETIME)

        message = row["message"]

        # Menyebut target yang gagal, alias yang dicari, dan kolom yang
        # benar-benar ada di file.
        self.assertIn("could not find log_time", message)
        self.assertIn("'timestamp'", message)
        self.assertIn("'log_time'", message)
        self.assertIn("Fix the column mapping", message)

        # Dan **tidak** menyalahkan format tanggal, karena bukan itu
        # sebabnya.
        self.assertNotIn("datetime formats", message)

    def test_missing_identifier_column_says_so(self):
        profile = self.make_profile(
            "AIM-MISS-2",
            mapping={
                "employee_code": ["badgeno"],
                "log_time": ["log_time"],
            },
        )

        result = run(profile, self.canonical_file())

        row = result["rows"][0]

        self.assertEqual(row["status"], statuses.UNKNOWN_EMPLOYEE)
        self.assertIn("could not find employee_code", row["message"])
        self.assertIn("'badgeno'", row["message"])

    def test_unreadable_value_still_blames_the_format(self):
        """
        Kolomnya ada, isinya yang tidak terbaca. Di sinilah pesan lama
        memang benar, dan ia harus tetap muncul.
        """
        profile = self.make_profile(
            "AIM-MISS-3",
            mapping={
                "employee_code": ["employee_code"],
                "log_time": ["log_time"],
            },
            datetime_formats=["%d/%m/%Y %H:%M"],
        )

        self.make_employee(number="AIMX001", shift=self.office_shift)

        path = self.write_csv(
            "employee_code,log_time",
            "AIMX001,not-a-timestamp",
        )

        row = run(profile, path)["rows"][0]

        self.assertEqual(row["status"], statuses.INVALID_DATETIME)
        self.assertIn("datetime formats", row["message"])
        self.assertNotIn("could not find", row["message"])

    def test_template_columns_import_with_an_empty_mapping(self):
        """
        Kolom yang dikeluarkan Download Template harus bisa diimport
        oleh profile yang `mapping`-nya kosong. Template dan alias
        bawaan yang tidak sepakat adalah jebakan yang tidak berbunyi —
        orang mengunduh template, mengisinya, lalu ditolak.
        """
        importer = get_importer(MODULE)

        profile = self.make_profile(
            "AIM-CANON-1",
            mapping={},
            datetime_formats=["%Y-%m-%d %H:%M:%S"],
        )

        self.make_employee(number="AIMX001", shift=self.office_shift)

        header = ",".join(importer.get_template_columns())

        self.assertEqual(
            header,
            "employee_code,log_time,log_type,device_code",
        )

        result = run(profile, self.canonical_file())

        self.assertEqual(result["valid_rows"], 2)
        self.assertEqual(result["invalid_rows"], 0)

        self.assertEqual(
            [row["log_type"] for row in result["rows"]],
            ["in", "out"],
        )

        self.assertEqual(
            {row["employee_code"] for row in result["rows"]},
            {"AIMX001"},
        )
