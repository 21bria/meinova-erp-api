"""
Mengunci Attendance Import yang dikonfigurasi, bukan di-hardcode.

Yang dijaga di sini, dan tiap poinnya pernah jadi cara importer absensi
gagal di lapangan:

1. **Format file datang dari Import Profile.** Delimiter, nama kolom,
   format waktu, zona waktu, dan mode event. Tidak ada satu pun test di
   berkas ini yang lulus karena parser mengenali merek mesin tertentu.
2. **Nomor mesin bukan Employee Number, dan bukan primary key.**
   `0001` di dua mesin berbeda boleh menunjuk dua orang berbeda.
3. **Import tidak pernah membuat pegawai.**
4. **Jadwal datang dari HR**, bukan dari profile — termasuk shift malam
   yang tap pulangnya jatuh di tanggal berikutnya.
5. **Cakupan organisasi dan Feature Applicability tidak bisa dilewati
   dengan menaruh nomor orang lain di CSV.**
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model

from apps.hr.tests.access_helpers import grant_employee_read
from apps.accounts.models import (
    AuthorityMode,
    Role,
)
from apps.accounts.services.role_assignment import grant_role
from apps.framework.imports import ImportPipelineService, get_importer
from apps.hr.imports.attendance import statuses
from apps.hr.imports.attendance.config import AttendanceImportConfig
from apps.hr.imports.attendance.identity import apply_transform
from apps.hr.models import (
    AttendanceLog,
    Employee,
    EmployeeAttendance,
)

from .base import FIXTURES, MODULE, AttendanceImportTestCase


WIB = ZoneInfo("Asia/Jakarta")

SITE_FILE = FIXTURES / "site_fingerprint_tab.csv"
HO_FILE = FIXTURES / "ho_generic_comma.csv"

# Rentang yang dipakai fixture site.
JULY = date(2026, 7, 1)


def run_preview(profile, file_path, *, user=None):
    return ImportPipelineService.preview(
        module=MODULE,
        file_path=file_path,
        source_type=profile.source_type or "csv",
        parser_options=profile.parser_options,
        mapping=profile.mapping or None,
        defaults=profile.defaults or None,
        value_mapping=profile.value_mapping or None,
        date_formats=profile.datetime_formats or None,
        options=profile.options or None,
        user=user,
        profile=profile,
    )


def run_execute(profile, file_path, *, user=None):
    return ImportPipelineService.execute(
        module=MODULE,
        file_path=file_path,
        source_type=profile.source_type or "csv",
        parser_options=profile.parser_options,
        mapping=profile.mapping or None,
        defaults=profile.defaults or None,
        value_mapping=profile.value_mapping or None,
        date_formats=profile.datetime_formats or None,
        options=profile.options or None,
        user=user,
        profile=profile,
    )


def by_row(result) -> dict[int, dict]:
    return {row["row_number"]: row for row in result["rows"]}


# ======================================================================
# Parsing file site nyata
# ======================================================================


class SiteFileParsingTests(AttendanceImportTestCase):
    """
    Bentuk file diambil dari export mesin sidik jari sungguhan: TAB,
    CRLF, nilai teks dikutip, kolom `Tgl/Waktu` berformat
    `DD/MM/YYYY HH.mm.ss`, dan `No.ID` berisi angka seperti 1, 4, 5,
    0001 yang tidak berhubungan dengan Employee Number.
    """

    def test_tab_delimiter_comes_from_the_profile(self):
        profile = self.site_profile("AIM-TAB-1")

        rows = ImportPipelineService.parse_rows(
            source_type="csv",
            file_path=SITE_FILE,
            parser_options=profile.parser_options,
        )

        self.assertEqual(len(rows), 7)

        self.assertIn("no.id", rows[0])
        self.assertIn("tgl/waktu", rows[0])

        # Profil berpemisah koma pada file yang sama tidak menemukan
        # satu pun kolom — buktinya delimiter memang datang dari
        # profile, bukan dari tebakan parser.
        comma = self.make_profile("AIM-TAB-1-COMMA")

        comma_rows = ImportPipelineService.parse_rows(
            source_type="csv",
            file_path=SITE_FILE,
            parser_options=comma.parser_options,
        )

        self.assertNotIn("no.id", comma_rows[0])

    def test_numeric_machine_ids_survive_normalization(self):
        profile = self.site_profile("AIM-TAB-2")

        result = run_preview(profile, SITE_FILE)

        identifiers = [row["raw_employee_id"] for row in result["rows"]]

        # `0001` tidak boleh berubah jadi `1`: nol depan adalah bagian
        # dari nomor mesin, dan menghilangkannya menempelkan tap ke
        # orang lain.
        self.assertEqual(
            identifiers,
            ["1", "1", "4", "5", "0001", "0001", "99999"],
        )

    def test_datetime_format_and_timezone_come_from_the_profile(self):
        profile = self.site_profile("AIM-TAB-3")

        employee = self.make_employee(roster=True, shift=self.day_shift)

        self.make_roster_days(employee, start=JULY, days=30)

        device = self.make_device("AIM-DEV-TZ", profile=profile)

        self.map_device_employee(device, "1", employee)

        profile.options = {
            "attendance": {
                **profile.options["attendance"],
                "device_code": device.code,
            },
        }

        profile.save(update_fields=["options"])

        result = run_preview(profile, SITE_FILE)

        first = by_row(result)[2]

        self.assertEqual(first["status"], statuses.VALID)

        moment = datetime.fromisoformat(first["log_time"])

        # 06.53.11 pada 1 Juli, dibaca sebagai jam dinding Asia/Jakarta.
        self.assertEqual(
            moment.astimezone(WIB),
            datetime(2026, 7, 1, 6, 53, 11, tzinfo=WIB),
        )

    def test_unparseable_timestamp_is_reported_not_guessed(self):
        """
        Format waktu yang tidak diumumkan profile **tidak** ditebak.
        Kalau ditebak, `01/07/2026` yang sah dibaca dua cara akan
        menghasilkan tanggal yang salah tanpa satu pun error.
        """
        profile = self.site_profile("AIM-TAB-4")

        profile.datetime_formats = []
        profile.save(update_fields=["datetime_formats"])

        result = run_preview(profile, SITE_FILE)

        statuses_seen = {row["status"] for row in result["rows"]}

        self.assertEqual(statuses_seen, {statuses.INVALID_DATETIME})

    def test_the_real_client_export_parses_with_this_profile(self):
        """
        File sungguhan dari klien, kalau kebetulan ada di mesin ini.

        Isinya nama pegawai asli, jadi **tidak** ikut disimpan di repo —
        fixture di atas yang menyalin bentuknya. Test ini dilewati di
        CI dan di mesin orang lain, dan itu memang yang diinginkan:
        gunanya membuktikan sekali bahwa bentuk yang disalin memang
        bentuk yang sama.
        """
        from pathlib import Path

        real = (
            Path.home()
            / "Downloads"
            / "Absensi Finger periode 01 - 31 Juli 2026 (1).csv"
        )

        if not real.exists():
            self.skipTest("File export klien tidak ada di mesin ini.")

        profile = self.site_profile("AIM-REAL-1")

        rows = ImportPipelineService.parse_rows(
            source_type="csv",
            file_path=real,
            parser_options=profile.parser_options,
        )

        self.assertGreater(len(rows), 1000)

        result = run_preview(profile, real)

        self.assertEqual(result["total_rows"], len(rows))

        # Tiap baris membawa identifier dan waktu yang terbaca; yang
        # tersisa hanyalah nomor mesin yang belum dipetakan.
        for row in result["rows"]:
            self.assertTrue(row["raw_employee_id"])
            self.assertTrue(row["log_time"])

            self.assertEqual(
                row["status"],
                statuses.UNKNOWN_EMPLOYEE,
            )

    def test_real_export_header_matches_the_fixture(self):
        """
        Header fixture disalin apa adanya dari file mesin yang
        diberikan klien. Kalau ada yang mengubahnya, test lain di
        berkas ini berhenti membuktikan apa pun soal file nyata.
        """
        with SITE_FILE.open("rb") as handle:
            header = handle.readline()

        self.assertEqual(
            header,
            b"Departemen\tNama\tNo.ID\tTgl/Waktu\tLokasi ID\tNo.PIN"
            b"\tKode Verifikasi\tNo.Kartu\r\n",
        )


# ======================================================================
# Identitas mesin -> Employee ERP
# ======================================================================


class DeviceEmployeeMappingTests(AttendanceImportTestCase):
    def test_explicit_mapping_resolves_machine_id(self):
        profile = self.site_profile("AIM-MAP-1")

        employee = self.make_employee(
            number="KW0001",
            roster=True,
            shift=self.day_shift,
        )

        self.make_roster_days(employee, start=JULY, days=30)

        device = self.make_device("AIM-MAP-DEV", profile=profile)

        self.map_device_employee(device, "0001", employee)

        profile.options = {
            "attendance": {
                **profile.options["attendance"],
                "device_code": device.code,
            },
        }

        profile.save(update_fields=["options"])

        rows = by_row(run_preview(profile, SITE_FILE))

        mapped = rows[6]

        self.assertEqual(mapped["raw_employee_id"], "0001")
        self.assertEqual(mapped["employee_code"], "KW0001")
        self.assertEqual(mapped["match_source"], "device_mapping")

    def test_same_machine_id_on_two_devices_means_two_people(self):
        profile = self.site_profile("AIM-MAP-2")

        first = self.make_employee(roster=True, shift=self.day_shift)
        second = self.make_employee(roster=True, shift=self.day_shift)

        self.make_roster_days(first, start=JULY, days=30)
        self.make_roster_days(second, start=JULY, days=30)

        device_a = self.make_device("AIM-DEV-A")
        device_b = self.make_device("AIM-DEV-B")

        self.map_device_employee(device_a, "0001", first)
        self.map_device_employee(device_b, "0001", second)

        def resolved_number(device_code):
            profile.options = {
                "attendance": {
                    **profile.options["attendance"],
                    "device_code": device_code,
                },
            }

            profile.save(update_fields=["options"])

            return by_row(run_preview(profile, SITE_FILE))[6][
                "employee_code"
            ]

        self.assertEqual(
            resolved_number(device_a.code),
            first.employee_number,
        )

        self.assertEqual(
            resolved_number(device_b.code),
            second.employee_number,
        )

    def test_machine_id_is_never_read_as_a_primary_key(self):
        """
        Nomor mesin adalah **teks**, bukan angka dan bukan pk.

        Perangkapnya nyata: pegawai dengan pk kecil ada di setiap
        tenant, dan importer yang malas akan menempelkan seluruh tap
        `No.ID = 1` kepadanya. Di sini nomor mesinnya sengaja dibuat
        **sama persis** dengan pk seorang pegawai yang benar-benar ada.
        """
        profile = self.site_profile("AIM-MAP-3")

        device = self.make_device("AIM-DEV-PK")

        profile.options = {
            "attendance": {
                **profile.options["attendance"],
                "device_code": device.code,
            },
        }

        profile.save(update_fields=["options"])

        decoy = self.make_employee(roster=True, shift=self.day_shift)

        self.make_roster_days(decoy, start=JULY, days=30)

        path = self._file_with_machine_id(str(decoy.pk))

        rows = by_row(run_preview(profile, path))

        self.assertTrue(rows)

        for row in rows.values():
            self.assertIsNone(
                row["employee_id"],
                "Nomor mesin tidak boleh dibaca sebagai primary key.",
            )

            self.assertEqual(
                row["status"],
                statuses.UNKNOWN_DEVICE_EMPLOYEE,
            )

        # Dan begitu nomor itu **dipetakan**, orangnya ketemu — jadi
        # yang barusan gagal memang karena pemetaannya tidak ada, bukan
        # karena filenya tidak terbaca.
        self.map_device_employee(device, str(decoy.pk), decoy)

        rows = by_row(run_preview(profile, path))

        self.assertEqual(
            next(iter(rows.values()))["employee_code"],
            decoy.employee_number,
        )

    def _file_with_machine_id(self, machine_id: str):
        import tempfile
        from pathlib import Path

        header = (
            "Departemen\tNama\tNo.ID\tTgl/Waktu\tLokasi ID\tNo.PIN"
            "\tKode Verifikasi\tNo.Kartu"
        )

        line = (
            f'"OUR COMPANY"\t"Decoy"\t"{machine_id}"'
            f'\t01/07/2026 07.05.19\t"1"\t""\t"Sidik Jari"\t""'
        )

        handle = tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".csv",
            delete=False,
        )

        handle.write((f"{header}\r\n{line}\r\n").encode("utf-8"))
        handle.close()

        self.addCleanup(
            lambda: Path(handle.name).unlink(missing_ok=True),
        )

        return Path(handle.name)

    def test_unknown_machine_id_is_invalid_and_creates_nobody(self):
        profile = self.site_profile("AIM-MAP-4")

        device = self.make_device("AIM-DEV-UNKNOWN")

        profile.options = {
            "attendance": {
                **profile.options["attendance"],
                "device_code": device.code,
            },
        }

        profile.save(update_fields=["options"])

        before = Employee.objects.count()

        result = run_execute(profile, SITE_FILE)

        self.assertEqual(Employee.objects.count(), before)
        self.assertEqual(result["created_rows"], 0)
        self.assertEqual(result["skipped_rows"], 7)

    def test_explicit_mapping_beats_the_configured_transform(self):
        """
        Transform boleh ada, tapi orang yang menulis pemetaan sudah
        menyatakan jawabannya. Kalau aturan menang, pemetaan manual
        tidak ada gunanya.
        """
        profile = self.site_profile(
            "AIM-MAP-5",
            identifier={
                "column": "No.ID",
                "transform": ["left_pad", "prefix"],
                "pad_length": 4,
                "prefix": "KW",
            },
        )

        rule_target = self.make_employee(
            number="KW0001",
            roster=True,
            shift=self.day_shift,
        )

        mapping_target = self.make_employee(
            roster=True,
            shift=self.day_shift,
        )

        for employee in (rule_target, mapping_target):
            self.make_roster_days(employee, start=JULY, days=30)

        device = self.make_device("AIM-DEV-OVERRIDE")

        self.map_device_employee(device, "0001", mapping_target)

        profile.options = {
            "attendance": {
                **profile.options["attendance"],
                "device_code": device.code,
            },
        }

        profile.save(update_fields=["options"])

        rows = by_row(run_preview(profile, SITE_FILE))

        self.assertEqual(
            rows[6]["employee_code"],
            mapping_target.employee_number,
        )

        # Baris yang **tidak** dipetakan tetap boleh jatuh ke transform:
        # `1` -> left pad -> `0001` -> prefix -> `KW0001`.
        self.assertEqual(rows[2]["employee_code"], "KW0001")
        self.assertEqual(rows[2]["match_source"], "employee_number")

    def test_transform_steps_run_in_the_configured_order(self):
        config = AttendanceImportConfig.from_options({
            "attendance": {
                "identifier": {
                    "transform": ["left_pad", "prefix"],
                    "pad_length": 4,
                    "prefix": "KW",
                },
            },
        })

        self.assertEqual(apply_transform("1", config.identifier), "KW0001")

        reversed_config = AttendanceImportConfig.from_options({
            "attendance": {
                "identifier": {
                    "transform": ["prefix", "left_pad"],
                    "pad_length": 6,
                    "prefix": "KW",
                },
            },
        })

        # `prefix` dulu menghasilkan `KW1`, baru di-pad ke enam karakter.
        # Panjang totalnya yang dijaga, bukan jumlah nolnya.
        self.assertEqual(
            apply_transform("1", reversed_config.identifier),
            "000KW1",
        )


# ======================================================================
# Satu pipeline untuk semua format
# ======================================================================


class SharedPipelineTests(AttendanceImportTestCase):
    def test_comma_profile_with_explicit_events_uses_the_same_engine(self):
        """
        File HO: pemisah koma, kolom `EmployeeCode`/`Timestamp`, dan
        kolom event bernilai `0`/`1`. Tidak ada importer terpisah —
        yang berbeda cuma barisnya di tabel ImportProfile.
        """
        profile = self.make_profile(
            "AIM-HO-1",
            delimiter=",",
            mapping={
                "employee_code": ["employeecode"],
                "log_time": ["timestamp"],
                "log_type": ["status"],
                "employee_name": ["name"],
                "device_code": ["devicecode"],
            },
            value_mapping={"log_type": {"0": "in", "1": "out"}},
            datetime_formats=["%Y-%m-%d %H:%M:%S"],
            options={
                "attendance": {
                    "timezone": "Asia/Jakarta",
                    "event_mode": "explicit",
                },
            },
        )

        employee = self.make_employee(
            number="HOX0001",
            shift=self.office_shift,
        )

        rows = by_row(run_preview(profile, HO_FILE))

        self.assertEqual(rows[2]["status"], statuses.VALID)
        self.assertEqual(rows[2]["employee_code"], "HOX0001")
        self.assertEqual(rows[2]["log_type"], "in")
        self.assertEqual(rows[3]["log_type"], "out")

        self.assertEqual(
            get_importer(MODULE).module,
            profile.module,
            "HO dan site harus memakai importer yang sama.",
        )

        del employee

    def test_explicit_mode_rejects_unmappable_event_values(self):
        profile = self.make_profile(
            "AIM-HO-2",
            mapping={
                "employee_code": ["employeecode"],
                "log_time": ["timestamp"],
                "log_type": ["status"],
            },
            value_mapping={},
            datetime_formats=["%Y-%m-%d %H:%M:%S"],
            options={"attendance": {"event_mode": "explicit"}},
        )

        self.make_employee(number="HOX0001", shift=self.office_shift)

        rows = by_row(run_preview(profile, HO_FILE))

        self.assertEqual(rows[2]["status"], statuses.INVALID_EVENT)

    def test_raw_tap_mode_ignores_any_event_column(self):
        profile = self.make_profile(
            "AIM-HO-3",
            mapping={
                "employee_code": ["employeecode"],
                "log_time": ["timestamp"],
                "log_type": ["status"],
            },
            datetime_formats=["%Y-%m-%d %H:%M:%S"],
            options={"attendance": {"event_mode": "raw_tap"}},
        )

        self.make_employee(number="HOX0001", shift=self.office_shift)

        rows = by_row(run_preview(profile, HO_FILE))

        self.assertEqual(rows[2]["log_type"], "unknown")
        self.assertEqual(rows[3]["log_type"], "unknown")

    def test_profile_without_new_options_still_works(self):
        """
        Backward compatibility. Profil lama tidak punya blok
        `options.attendance` sama sekali; ia harus tetap berjalan
        dengan pencocokan lewat Employee Number seperti sebelumnya.
        """
        profile = self.make_profile(
            "AIM-LEGACY",
            mapping={
                "employee_code": ["employeecode"],
                "log_time": ["timestamp"],
            },
            datetime_formats=["%Y-%m-%d %H:%M:%S"],
            options={},
        )

        self.make_employee(number="HOX0001", shift=self.office_shift)

        rows = by_row(run_preview(profile, HO_FILE))

        self.assertEqual(rows[2]["employee_code"], "HOX0001")
        self.assertEqual(rows[2]["match_source"], "employee_number")


# ======================================================================
# Jadwal dari HR, bukan dari profile
# ======================================================================


class ScheduleResolutionTests(AttendanceImportTestCase):
    def _ho_profile(self, code):
        return self.make_profile(
            code,
            mapping={
                "employee_code": ["employeecode"],
                "log_time": ["timestamp"],
            },
            datetime_formats=["%Y-%m-%d %H:%M:%S"],
            options={"attendance": {"event_mode": "raw_tap"}},
        )

    def test_office_schedule_comes_from_the_hr_resolver(self):
        profile = self._ho_profile("AIM-SCH-1")

        self.make_employee(number="HOX0001", shift=self.office_shift)

        rows = by_row(run_preview(profile, HO_FILE))

        # 1 Juli 2026 jatuh hari Rabu — hari kerja kantor.
        self.assertEqual(rows[2]["work_date"], "2026-07-01")
        self.assertEqual(rows[2]["schedule_label"], "10:00–18:00")
        self.assertEqual(rows[2]["status"], statuses.VALID)

    def test_site_schedule_comes_from_roster_and_shift(self):
        profile = self.site_profile("AIM-SCH-2")

        employee = self.make_employee(roster=True, shift=self.day_shift)

        self.make_roster_days(employee, start=JULY, days=30)

        device = self.make_device("AIM-SCH-DEV")

        self.map_device_employee(device, "1", employee)

        profile.options = {
            "attendance": {
                **profile.options["attendance"],
                "device_code": device.code,
            },
        }

        profile.save(update_fields=["options"])

        rows = by_row(run_preview(profile, SITE_FILE))

        self.assertEqual(rows[2]["work_date"], "2026-07-01")
        self.assertEqual(rows[2]["schedule_label"], "07:00–17:00")

    def test_tap_outside_any_roster_segment_is_flagged_but_imported(self):
        profile = self.site_profile("AIM-SCH-3")

        employee = self.make_employee(roster=True, shift=self.day_shift)

        # Rosternya ada, tapi bulan lain — tap Juli jatuh di luar blok.
        self.make_roster_days(employee, start=date(2026, 9, 1), days=30)

        device = self.make_device("AIM-SCH-DEV-2")

        self.map_device_employee(device, "1", employee)

        profile.options = {
            "attendance": {
                **profile.options["attendance"],
                "device_code": device.code,
            },
        }

        profile.save(update_fields=["options"])

        rows = by_row(run_preview(profile, SITE_FILE))

        self.assertEqual(rows[2]["status"], statuses.NO_ROSTER_SHIFT)
        self.assertTrue(rows[2]["valid"])

        # Tetap masuk: kehilangan tap sungguhan lebih buruk daripada
        # baris presensi yang kolom jadwalnya kosong.
        result = run_execute(profile, SITE_FILE)

        self.assertGreater(result["created_rows"], 0)

    def test_night_shift_tap_after_midnight_belongs_to_the_previous_day(self):
        """
        Shift 24 Agustus 19:00 -> 25 Agustus 07:00.

        Tap 18:54 pada tanggal 24 dan tap 07:11 pada tanggal 25 adalah
        **satu** hari kerja. Mengelompokkannya dengan `timestamp.date()`
        memecahnya jadi dua baris yang dua-duanya terlihat setengah.
        """
        profile = self.site_profile("AIM-NIGHT-1")

        employee = self.make_employee(roster=True, shift=self.night_shift)

        self.make_roster_days(employee, start=date(2026, 8, 20), days=14)

        device = self.make_device("AIM-NIGHT-DEV")

        self.map_device_employee(device, "7", employee)

        profile.options = {
            "attendance": {
                **profile.options["attendance"],
                "device_code": device.code,
            },
        }

        profile.save(update_fields=["options"])

        path = self._write_night_file()

        result = run_execute(profile, path)

        self.assertEqual(result["created_rows"], 1)
        self.assertEqual(result["updated_rows"], 1)

        attendance = EmployeeAttendance.objects.get(
            employee=employee,
            is_deleted=False,
        )

        self.assertEqual(attendance.work_date, date(2026, 8, 24))

        self.assertEqual(
            attendance.check_in.astimezone(WIB),
            datetime(2026, 8, 24, 18, 54, tzinfo=WIB),
        )

        self.assertEqual(
            attendance.check_out.astimezone(WIB),
            datetime(2026, 8, 25, 7, 11, tzinfo=WIB),
        )

        self.assertEqual(
            attendance.scheduled_check_in.astimezone(WIB),
            datetime(2026, 8, 24, 19, 0, tzinfo=WIB),
        )

        self.assertEqual(
            attendance.scheduled_check_out.astimezone(WIB),
            datetime(2026, 8, 25, 7, 0, tzinfo=WIB),
        )

    def _write_night_file(self):
        import tempfile
        from pathlib import Path

        header = (
            "Departemen\tNama\tNo.ID\tTgl/Waktu\tLokasi ID\tNo.PIN"
            "\tKode Verifikasi\tNo.Kartu"
        )

        lines = [header]

        for stamp in ("24/08/2026 18.54.00", "25/08/2026 07.11.00"):
            lines.append(
                f'"OUR COMPANY"\t"Night"\t"7"\t{stamp}\t"1"\t""'
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
# Cakupan organisasi & applicability
# ======================================================================


class AuthorizationTests(AttendanceImportTestCase):
    def _ho_profile(self, code):
        return self.make_profile(
            code,
            mapping={
                "employee_code": ["employeecode"],
                "log_time": ["timestamp"],
            },
            datetime_formats=["%Y-%m-%d %H:%M:%S"],
            options={"attendance": {"event_mode": "raw_tap"}},
        )

    def _scoped_user(self, location):
        User = get_user_model()

        AuthorizationTests._counter += 1

        user = User.objects.create_user(
            username=f"aim-scoped-{AuthorizationTests._counter}",
            email=f"aim-scoped-{AuthorizationTests._counter}@example.com",
            password="x",
        )

        role = Role.objects.create(
            code=f"AIM-SCOPE-{AuthorizationTests._counter}",
            name="Scoped",
        )

        # Resolver importer menanyakan cakupan **per izin** sejak Stage
        # 3B, sama dengan tabel Employee. Di produksi setiap role yang
        # diseed memegang `hr.view_employee` (`READ_GRANTS`), jadi role
        # tanpa izin menguji keadaan yang tidak pernah ada — dan
        # akibatnya justru menyesatkan: test negatifnya tetap hijau
        # karena semua baris ditolak, sementara test positifnya merah.
        grant_employee_read(role)

        # Cakupannya **dinyatakan pada penugasan** — satu-satunya
        # tempat WHERE disimpan. `.roles.add()` telanjang cuma memberi
        # keanggotaan: test positif akan merah sementara test
        # negatifnya tetap hijau, pola kegagalan yang paling mudah
        # disalahbaca sebagai "keamanannya bekerja".
        grant_role(
            user,
            role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("location", location.id)],
        )

        return user

    def test_csv_cannot_reach_employees_outside_the_scope(self):
        profile = self._ho_profile("AIM-SCOPE-1")

        self.make_employee(
            number="HOX0001",
            shift=self.office_shift,
            location=self.other_site,
        )

        user = self._scoped_user(self.site)

        rows = by_row(run_preview(profile, HO_FILE, user=user))

        self.assertEqual(
            rows[2]["status"],
            statuses.OUTSIDE_ORGANIZATION_SCOPE,
        )

        # Identitas pegawainya tidak ikut bocor ke layar review.
        self.assertEqual(rows[2]["employee_code"], "")
        self.assertEqual(rows[2]["employee_name"], "")

        result = run_execute(profile, HO_FILE, user=user)

        self.assertEqual(result["created_rows"], 0)

    def test_same_file_imports_for_a_user_whose_scope_covers_it(self):
        profile = self._ho_profile("AIM-SCOPE-2")

        self.make_employee(
            number="HOX0001",
            shift=self.office_shift,
            location=self.site,
        )

        user = self._scoped_user(self.site)

        rows = by_row(run_preview(profile, HO_FILE, user=user))

        self.assertEqual(rows[2]["status"], statuses.VALID)

    def test_attendance_not_applicable_cannot_be_bypassed(self):
        profile = self._ho_profile("AIM-APPLY-1")

        self.make_employee(
            number="HOX0001",
            shift=self.office_shift,
            group=self.no_attendance_group,
        )

        rows = by_row(run_preview(profile, HO_FILE))

        self.assertEqual(rows[2]["status"], statuses.NOT_APPLICABLE)

        result = run_execute(profile, HO_FILE)

        self.assertEqual(result["created_rows"], 0)


# ======================================================================
# Idempotensi
# ======================================================================


class IdempotencyTests(AttendanceImportTestCase):
    def _profile(self, code):
        return self.make_profile(
            code,
            mapping={
                "employee_code": ["employeecode"],
                "log_time": ["timestamp"],
            },
            datetime_formats=["%Y-%m-%d %H:%M:%S"],
            options={"attendance": {"event_mode": "raw_tap"}},
        )

    def test_re_importing_the_same_file_changes_nothing(self):
        profile = self._profile("AIM-DUP-1")

        employee = self.make_employee(
            number="HOX0001",
            shift=self.office_shift,
        )

        first = run_execute(profile, HO_FILE)

        self.assertEqual(first["created_rows"], 1)
        self.assertEqual(first["updated_rows"], 1)
        self.assertEqual(first["duplicate_rows"], 0)

        attendance = EmployeeAttendance.objects.get(employee=employee)

        snapshot = (
            attendance.check_in,
            attendance.check_out,
            attendance.work_date,
        )

        logs = AttendanceLog.objects.filter(employee=employee).count()

        second = run_execute(profile, HO_FILE)

        self.assertEqual(second["created_rows"], 0)
        self.assertEqual(second["updated_rows"], 0)
        self.assertEqual(second["duplicate_rows"], 2)

        self.assertEqual(
            AttendanceLog.objects.filter(employee=employee).count(),
            logs,
        )

        self.assertEqual(
            EmployeeAttendance.objects.filter(employee=employee).count(),
            1,
        )

        attendance.refresh_from_db()

        self.assertEqual(
            (
                attendance.check_in,
                attendance.check_out,
                attendance.work_date,
            ),
            snapshot,
        )

    def test_duplicate_rows_inside_one_file_are_written_once(self):
        profile = self._profile("AIM-DUP-2")

        employee = self.make_employee(
            number="HOX0001",
            shift=self.office_shift,
        )

        path = self._duplicated_file()

        result = run_execute(profile, path)

        self.assertEqual(result["duplicate_rows"], 1)

        self.assertEqual(
            AttendanceLog.objects.filter(employee=employee).count(),
            1,
        )

    def _duplicated_file(self):
        import tempfile
        from pathlib import Path

        lines = [
            "EmployeeCode,Name,Timestamp,Status,DeviceCode",
            "HOX0001,Office Person,2026-07-01 09:52:10,0,FP-HO-TEST",
            "HOX0001,Office Person,2026-07-01 09:52:10,0,FP-HO-TEST",
        ]

        handle = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".csv",
            delete=False,
            encoding="utf-8",
        )

        handle.write("\n".join(lines) + "\n")
        handle.close()

        self.addCleanup(
            lambda: Path(handle.name).unlink(missing_ok=True),
        )

        return Path(handle.name)


# ======================================================================
# Preview == Commit
# ======================================================================


class PreviewMatchesCommitTests(AttendanceImportTestCase):
    def test_preview_and_commit_agree_on_every_row(self):
        profile = self.site_profile("AIM-SAME-1")

        employee = self.make_employee(roster=True, shift=self.day_shift)

        self.make_roster_days(employee, start=JULY, days=30)

        device = self.make_device("AIM-SAME-DEV")

        self.map_device_employee(device, "1", employee)
        self.map_device_employee(device, "0001", employee)

        profile.options = {
            "attendance": {
                **profile.options["attendance"],
                "device_code": device.code,
            },
        }

        profile.save(update_fields=["options"])

        preview = run_preview(profile, SITE_FILE)

        expected_valid = sum(
            1
            for row in preview["rows"]
            if row["valid"] and not row["duplicate"]
        )

        result = run_execute(profile, SITE_FILE)

        self.assertEqual(preview["total_rows"], result["total_rows"])
        self.assertEqual(preview["valid_rows"], result["valid_rows"])

        self.assertEqual(
            result["created_rows"] + result["updated_rows"],
            expected_valid,
        )


# ======================================================================
# Metadata profile untuk layar import
# ======================================================================


class ProfileMetadataTests(AttendanceImportTestCase):
    def test_profile_describes_its_own_file_format(self):
        profile = self.site_profile("AIM-META-1")

        described = get_importer(MODULE).describe_profile(profile)

        summary = {
            item["label"]: item["value"]
            for item in described["summary"]
        }

        self.assertEqual(summary["Delimiter"], "TAB")
        self.assertEqual(summary["Employee ID Column"], "No.ID")
        self.assertEqual(summary["Timestamp Column"], "tgl/waktu")
        self.assertEqual(summary["Datetime Format"], "%d/%m/%Y %H.%M.%S")
        self.assertEqual(summary["Source Timezone"], "Asia/Jakarta")

        self.assertIn("Raw Tap", summary["Event Mode"])

        self.assertTrue(described["notes"])


# ======================================================================
# Invariant sumber
# ======================================================================


class NoHardcodedContextTests(AttendanceImportTestCase):
    """
    Penjaga terakhir, dan yang paling sering dibutuhkan enam bulan lagi.

    Seluruh gagasan task ini adalah bahwa lokasi, perusahaan, merek
    mesin, header file, awalan nomor pegawai, dan jam kerja tidak boleh
    hidup di dalam kode importer. Yang menahannya bukan niat baik —
    yang menahannya test ini.
    """

    FORBIDDEN = (
        # Konteks organisasi
        r"\bHO\b",
        r"\bSITE\b",
        r"\bHead Office\b",
        # Awalan nomor pegawai milik satu klien
        r"\bKW\d*\b",
        # Merek/vendor dan header file milik satu mesin
        r"Sidik Jari",
        r"No\.ID",
        r"Tgl/Waktu",
        # Header rekap harian milik satu mesin. Kolomnya dipetakan di
        # ImportProfile (`mapping.check_in = ["work1"]`), jadi nama ini
        # tidak boleh muncul di kode mana pun.
        r"\bwork1\b",
        r"\bwork2\b",
        r"\bymd\b",
        r"ZKTeco",
        r"Solution",
        r"FP-",
        # Jam kerja
        r"\b07:00\b",
        r"\b10:00\b",
        r"\b17:00\b",
        r"\b18:00\b",
    )

    SCANNED = (
        "apps/hr/imports/attendance/config.py",
        "apps/hr/imports/attendance/identity.py",
        "apps/hr/imports/attendance/importer.py",
        "apps/hr/imports/attendance/resolver.py",
        "apps/hr/imports/attendance/statuses.py",
        "apps/hr/imports/attendance/workdate.py",
        "apps/framework/imports/base.py",
        "apps/framework/imports/service.py",
    )

    @staticmethod
    def code_only(source: str) -> str:
        """
        Buang komentar dan docstring, sisakan **kode**.

        Prosa harus boleh menyebut "HO 10:00-18:00" — justru di situ
        alasan kenapa hal itu tidak boleh ada di kodenya dijelaskan.
        Yang dilarang adalah literalnya benar-benar dieksekusi. String
        biasa **tidak** dibuang: `if device.code == "FP-01"` harus tetap
        tertangkap.
        """
        import ast
        import io
        import tokenize

        tokens = [
            token
            for token in tokenize.generate_tokens(
                io.StringIO(source).readline,
            )
            if token.type != tokenize.COMMENT
        ]

        stripped = tokenize.untokenize(tokens)

        lines = stripped.splitlines()

        for node in ast.walk(ast.parse(stripped)):
            if not isinstance(node, ast.Expr):
                continue

            if not isinstance(node.value, ast.Constant):
                continue

            if not isinstance(node.value.value, str):
                continue

            for index in range(node.lineno - 1, node.end_lineno):
                lines[index] = ""

        return "\n".join(lines)

    def test_importer_source_has_no_client_specific_literals(self):
        import re
        from pathlib import Path

        root = Path(__file__).resolve().parents[4]

        for relative in self.SCANNED:
            source = self.code_only(
                (root / relative).read_text(encoding="utf-8"),
            )

            for pattern in self.FORBIDDEN:
                with self.subTest(file=relative, pattern=pattern):
                    self.assertIsNone(
                        re.search(pattern, source),
                        f"{relative} memuat '{pattern}'. Konteks klien "
                        f"harus tinggal di ImportProfile / "
                        f"AttendanceDevice, bukan di kode.",
                    )


