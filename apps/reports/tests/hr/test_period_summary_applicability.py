"""
Feature Applicability pada HR Period Summary.

Yang dijaga di sini satu kontrak: **populasi laporan ditentukan resolver
applicability, bukan kode Employee Group.** Tidak satu pun test di
berkas ini menyebut "BOARD" sebagai penentu — group-nya dibuat dengan
nama apa saja lalu penandanya dimatikan, dan yang diperiksa adalah
akibat dari penanda itu. Kalau suatu saat ada yang menambahkan
`if code == "BOARD"` di service, test di sini tetap hijau — yang akan
jatuh adalah `test_kode_group_tidak_menentukan_apa_pun`.

Dua populasi yang sengaja tidak dicampur:

* **populasi organisasi** — siapa yang boleh dilihat pengguna
  (Organization Scope + filter dropdown);
* **populasi proses** — dari situ, siapa yang diproses metrik yang
  sedang dihitung.

Yang pertama selalu lebih dulu. Applicability hanya boleh mempersempit,
dan `test_applicability_tidak_pernah_menambah_di_luar_scope` yang
menguncinya.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from apps.hr.models import RosterSegmentType
from apps.administration.models.references.hr import (
    EmployeeGroup,
    HRFeature,
    applicability_field,
)
from apps.reports.api.hr.period_summary.drilldown import (
    HRPeriodSummaryDrilldown,
)
from apps.reports.api.hr.period_summary.metrics import (
    METRIC_FEATURES,
    Metric,
    REPORT_FEATURES,
)
from apps.reports.api.hr.period_summary.services import (
    HRPeriodSummaryPresenter,
    HRPeriodSummaryService,
)

from .base import PERIOD_END, PERIOD_START, PeriodSummaryTestCase


def workdays(start: date, end: date, *, skip: set[date] | None = None) -> list[date]:
    """
    Senin–Jumat pada rentang, di luar tanggal yang dikecualikan.

    Sengaja disalin dari `test_period_summary.py` alih-alih diimpor dari
    sana: mengimpor antar berkas test membuat urutan pemuatan jadi bagian
    dari kontrak, dan fungsinya tiga baris.
    """
    skip = skip or set()

    days = []
    current = start

    while current <= end:
        if current.weekday() < 5 and current not in skip:
            days.append(current)

        current += timedelta(days=1)

    return days


def group(code: str, **flags) -> EmployeeGroup:
    """
    Employee Group dengan penanda yang disebut dimatikan, sisanya nyala.

    `code` sengaja bebas dan tidak pernah dibaca logika mana pun — ia ada
    cuma supaya barisnya bisa dibedakan saat test gagal.
    """
    values = {
        applicability_field(feature): flags.get(feature.value, True)
        for feature in HRFeature
    }

    return EmployeeGroup.objects.create(
        code=code,
        name=code.title(),
        **values,
    )


def all_off(code: str) -> EmployeeGroup:
    return group(code, **{feature.value: False for feature in HRFeature})


class RosterFixtureMixin:
    """
    Pegawai site di `base.py` cuma membawa `roster_crew` — segmen
    rosternya tidak ikut terbit, jadi tanpa ini Scheduled dan Field Break
    dua-duanya nol dan test apa pun tentang keduanya lulus karena alasan
    yang salah.
    """

    WORK_START = date(2026, 6, 1)
    WORK_END = date(2026, 6, 14)
    BREAK_START = date(2026, 6, 15)
    BREAK_END = date(2026, 6, 21)

    def make_rostered_employee(self, **kwargs):
        employee = self.make_site_employee(**kwargs)

        rotation = self.make_rotation(employee)

        self.make_segment(
            employee,
            segment_type=RosterSegmentType.WORK,
            start=self.WORK_START,
            end=self.WORK_END,
            rotation=rotation,
        )

        self.make_segment(
            employee,
            segment_type=RosterSegmentType.FIELD_BREAK,
            start=self.BREAK_START,
            end=self.BREAK_END,
            rotation=rotation,
        )

        return employee


class PopulationTests(RosterFixtureMixin, PeriodSummaryTestCase):
    """Siapa yang menghasilkan baris, dan siapa yang tidak."""

    def test_seluruh_feature_mati_hilang_dari_tabel_dan_headcount(self):
        """
        Pegawai yang keenam prosesnya dimatikan tidak punya satu pun
        angka untuk disumbangkan. Baris nol di tengah tabel terbaca
        sebagai "orang ini tidak masuk sebulan penuh" — bukan sebagai
        "proses ini memang tidak berlaku untuknya", dan tidak ada apa pun
        di layar yang membedakan keduanya.
        """
        excluded = self.make_office_employee(
            employee_group=all_off("NO-PROCESS"),
        )

        summary = HRPeriodSummaryService.build(
            self.context(excluded),
            PERIOD_START,
            PERIOD_END,
        )

        self.assertEqual(summary.rows, [])
        self.assertEqual(summary.headcount, 0)

    def test_seluruh_feature_nyala_tetap_dihitung(self):
        employee = self.make_office_employee(
            employee_group=group("FULL-PROCESS"),
        )

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        for day in days[:5]:
            self.make_attendance(employee, day)

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        self.assertEqual(summary.headcount, 1)
        self.assertEqual(self.row(summary, employee).present, 5)

    def test_tanpa_employee_group_tetap_dihitung(self):
        """
        Backward compatibility. Hanya nilai **eksplisit False** yang
        mengecualikan; tenant yang belum mengisi masternya tidak boleh
        kehilangan seluruh isi laporannya tanpa satu pun pesan.
        """
        employee = self.make_office_employee(employee_group=None)

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        self.make_attendance(employee, days[0])

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        self.assertEqual(summary.headcount, 1)
        self.assertEqual(self.row(summary, employee).present, 1)

    def test_satu_feature_nyala_sudah_cukup_untuk_masuk(self):
        """
        Semantik populasi laporan **ANY**, bukan ALL: satu proses yang
        masih berlaku sudah membuat pegawainya punya sesuatu untuk
        dilaporkan.
        """
        employee = self.make_rostered_employee(
            employee_group=group(
                "FIELD-ONLY",
                attendance=False,
                leave=False,
                overtime=False,
            ),
        )

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        self.assertEqual(summary.headcount, 1)

        row = self.row(summary, employee)

        # Field Break masih berlaku, jadi angkanya tetap terbit.
        self.assertGreater(row.field_break, 0)

        # Yang dimatikan tidak menyumbang apa pun.
        self.assertEqual(row.scheduled, 0)
        self.assertEqual(row.present, 0)
        self.assertEqual(row.absent, 0)

    def test_kode_group_tidak_menentukan_apa_pun(self):
        """
        Pagar anti-hardcode. Dua pegawai, group bernama `BOARD` dan
        `BOD` — dua kode yang paling mungkin ditulis sebagai cabang `if`
        — tapi penandanya menyala semua. Keduanya harus tetap dihitung.

        Kalau suatu saat ada yang "memperbaiki" laporan dengan
        mencocokkan kode, test inilah yang jatuh.
        """
        for code in ("BOARD", "BOD"):
            with self.subTest(code=code):
                employee = self.make_office_employee(
                    employee_group=group(code),
                )

                summary = HRPeriodSummaryService.build(
                    self.context(employee),
                    PERIOD_START,
                    PERIOD_END,
                )

                self.assertEqual(
                    summary.headcount,
                    1,
                    f"group berkode {code} dengan seluruh penanda menyala "
                    "harus tetap masuk laporan",
                )


class MetricFeatureTests(RosterFixtureMixin, PeriodSummaryTestCase):
    """Tiap metrik membaca penandanya sendiri, bukan satu flag bersama."""

    def test_setiap_metrik_punya_pemetaan(self):
        """
        Metrik baru tanpa pemetaan akan diam-diam dihitung untuk siapa
        pun. Dijaga di sini supaya ketahuan saat test, bukan saat ada
        yang bertanya kenapa angkanya tidak turun.
        """
        known = {
            value
            for name, value in vars(Metric).items()
            if not name.startswith("_") and isinstance(value, str)
        }

        self.assertEqual(known - set(METRIC_FEATURES), set())

    def test_leave_mati_tidak_menghitung_cuti(self):
        """
        Attendance menyala, Leave dimatikan. Hari yang tertutup dokumen
        cuti karena itu **tidak** jadi Leave — dan karena hari itu tetap
        terjadwal, ia jatuh ke Absent. Itu memang yang benar: tanpa
        proses cuti, ketidakhadirannya tidak punya dokumen yang
        membenarkannya.
        """
        employee = self.make_office_employee(
            employee_group=group("NO-LEAVE", leave=False),
        )

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        self.make_leave(
            employee,
            leave_type=self.annual,
            start=days[0],
            end=days[1],
        )

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        self.assertEqual(row.leave(Metric.ANNUAL), Decimal("0"))
        self.assertEqual(summary.total(Metric.ANNUAL), Decimal("0"))

        # Invariant tetap utuh untuk populasi Attendance-nya.
        self.assertEqual(
            row.scheduled,
            row.present + row.absent + int(row.leave_total),
        )

    def test_overtime_mati_tidak_menghitung_lembur(self):
        employee = self.make_office_employee(
            employee_group=group("NO-OT", overtime=False),
        )

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        self.make_overtime(employee, days[0], minutes=180)

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        self.assertEqual(row.ot_total_minutes, 0)
        self.assertEqual(summary.total(Metric.OT_TOTAL), 0)

    def test_overtime_nyala_tetap_menghitung_walau_leave_mati(self):
        """
        Penanda dibaca satu per satu. Mematikan Leave tidak boleh ikut
        mematikan Lembur — itu yang terjadi kalau seluruh laporan
        memakai satu flag bersama.
        """
        employee = self.make_office_employee(
            employee_group=group("OT-ONLY", leave=False),
        )

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        self.make_overtime(employee, days[0], minutes=120)

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        self.assertEqual(self.row(summary, employee).ot_total_minutes, 120)

    def test_field_break_mati_tidak_menghitung_blok_off(self):
        employee = self.make_rostered_employee(
            employee_group=group("NO-FB", field_break=False),
        )

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        self.assertEqual(row.field_break, 0)
        self.assertEqual(summary.total(Metric.FIELD_BREAK), 0)

        # Attendance-nya masih berlaku, jadi barisnya tetap berisi.
        self.assertGreater(row.scheduled, 0)

    def test_attendance_mati_tidak_menghitung_kehadiran(self):
        employee = self.make_office_employee(
            employee_group=group("NO-ATT", attendance=False),
        )

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        for day in days[:3]:
            self.make_attendance(employee, day)

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        for metric in (
            Metric.SCHEDULED,
            Metric.PRESENT,
            Metric.ABSENT,
            Metric.OFF_WORKED,
            Metric.HOLIDAY_WORKED,
            Metric.LATE,
            Metric.EARLY,
        ):
            with self.subTest(metric=metric):
                self.assertEqual(row.metric(metric), 0)
                self.assertEqual(summary.total(metric), 0)


class DenominatorTests(PeriodSummaryTestCase):
    """Penyebut rasio tidak boleh diencerkan oleh yang tidak diproses."""

    def test_attendance_rate_tidak_memasukkan_yang_tidak_diabsen(self):
        """
        Dua pegawai. Yang pertama diabsen dan pernah mangkir; yang kedua
        tidak diabsen sama sekali tapi tetap masuk laporan karena
        Lembur-nya menyala.

        Angka rasionya harus persis sama dengan kalau yang kedua tidak
        ada — nol yang ikut penyebut adalah cara paling sunyi sebuah
        rasio berubah tanpa ada yang mengubah datanya.
        """
        counted = self.make_office_employee(
            employee_group=group("COUNTED"),
        )

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        for day in days[:8]:
            self.make_attendance(counted, day)

        context = self.context()

        alone = HRPeriodSummaryPresenter._attendance_rate(
            HRPeriodSummaryService.build(context, PERIOD_START, PERIOD_END),
        )

        self.make_office_employee(
            employee_group=group("NO-ATT-2", attendance=False),
        )

        together = HRPeriodSummaryPresenter._attendance_rate(
            HRPeriodSummaryService.build(
                self.context(),
                PERIOD_START,
                PERIOD_END,
            ),
        )

        self.assertEqual(alone, together)

    def test_feature_headcount_memisahkan_populasi_proses(self):
        """
        `headcount` = berapa pegawai di laporan.
        `feature_headcount` = berapa yang diproses fitur itu.

        Keduanya sama selama semua applicable, dan **harus** berbeda
        begitu ada yang dimatikan — kalau tidak, penyebut rasio yang
        memakainya diam-diam salah.
        """
        self.make_office_employee(employee_group=group("A"))
        self.make_office_employee(
            employee_group=group("B", attendance=False),
        )

        summary = HRPeriodSummaryService.build(
            self.context(),
            PERIOD_START,
            PERIOD_END,
        )

        self.assertEqual(summary.headcount, 2)
        self.assertEqual(
            summary.feature_headcount(HRFeature.ATTENDANCE),
            1,
        )
        self.assertEqual(
            summary.feature_headcount(HRFeature.OVERTIME),
            2,
        )


class ScopeIntersectionTests(PeriodSummaryTestCase):
    """Applicability mempersempit, tidak pernah memperluas."""

    def test_applicability_tidak_pernah_menambah_di_luar_scope(self):
        """
        Pegawai yang dibuang filter organisasi tidak boleh kembali muncul
        gara-gara penandanya menyala. Diuji lewat filter `location`, yang
        jalurnya sama dengan cakupan data: dua-duanya menyaring queryset
        pegawai sebelum applicability dipasang.
        """
        inside = self.make_office_employee(employee_group=group("IN"))
        outside = self.make_site_employee(employee_group=group("OUT"))

        context = self.context()
        context["location"] = self.ho.id

        summary = HRPeriodSummaryService.build(
            context,
            PERIOD_START,
            PERIOD_END,
        )

        ids = {row.employee_id for row in summary.rows}

        self.assertIn(inside.id, ids)
        self.assertNotIn(outside.id, ids)

    def test_urutan_penyaringan_scope_lebih_dulu(self):
        """
        Pegawai di luar filter **dan** seluruh penandanya mati tetap
        hilang — dan yang membuangnya harus filter organisasinya, bukan
        applicability. Diperiksa dari sisi hasil: menyalakan kembali
        penandanya tidak mengubah apa pun.
        """
        outside_off = self.make_site_employee(
            employee_group=all_off("OUT-OFF"),
        )
        outside_on = self.make_site_employee(employee_group=group("OUT-ON"))

        context = self.context()
        context["location"] = self.ho.id

        summary = HRPeriodSummaryService.build(
            context,
            PERIOD_START,
            PERIOD_END,
        )

        ids = {row.employee_id for row in summary.rows}

        self.assertNotIn(outside_off.id, ids)
        self.assertNotIn(outside_on.id, ids)


class ConsistencyTests(PeriodSummaryTestCase):
    """KPI = chart = tabel = kaki tabel = drill-down, tetap."""

    def test_kpi_tabel_dan_kaki_tabel_sepakat(self):
        applicable = self.make_office_employee(employee_group=group("C1"))
        self.make_office_employee(employee_group=all_off("C2"))

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        for day in days[:6]:
            self.make_attendance(applicable, day)

        context = self.context()

        summary = HRPeriodSummaryService.summary(context)
        table = HRPeriodSummaryPresenter.employee_table(context)

        self.assertEqual(summary.headcount, 1)
        self.assertEqual(table["total"], 1)
        self.assertEqual(len(table["items"]), 1)

        self.assertEqual(
            table["totals"][Metric.PRESENT],
            float(summary.total(Metric.PRESENT)),
        )

        self.assertEqual(
            sum(item[Metric.PRESENT] for item in table["items"]),
            summary.total(Metric.PRESENT),
        )

    def test_drilldown_sepakat_dengan_angkanya(self):
        """
        Baris yang prosesnya tidak berlaku tidak boleh menyumbang
        rincian. "Present 6" yang membuka 8 baris adalah kegagalan yang
        membuat pembacanya menyimpulkan salah satunya salah.
        """
        counted = self.make_office_employee(employee_group=group("D1"))
        muted = self.make_office_employee(
            employee_group=group("D2", attendance=False),
        )

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        for day in days[:4]:
            self.make_attendance(counted, day)
            self.make_attendance(muted, day)

        context = self.context()

        summary = HRPeriodSummaryService.summary(context)

        result = HRPeriodSummaryDrilldown.resolve(
            context,
            metric=Metric.PRESENT,
            employee_id=None,
        )

        self.assertEqual(summary.total(Metric.PRESENT), 4)
        self.assertEqual(len(result["items"]), 4)

    def test_report_features_hanya_yang_punya_metrik(self):
        """
        `REPORT_FEATURES` harus benar-benar terwakili kolom. Proses yang
        tidak punya metrik apa pun di laporan ini (Roster, Shift) tidak
        boleh ikut menentukan populasinya — kalau ikut, pegawai yang cuma
        punya Roster tetap terbit sebagai baris nol.
        """
        represented = set(METRIC_FEATURES.values())

        self.assertEqual(set(REPORT_FEATURES), represented)
