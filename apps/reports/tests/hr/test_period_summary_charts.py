"""
Legenda chart HR Period Summary: kode kanonik, bukan teks yang
diterjemahkan frontend dengan menebak.

Yang dijaga di sini cuma **bentuk respons**. Angkanya sudah diuji
`test_period_summary.py`, dan tidak satu pun assertion di berkas ini
boleh berubah kalau aturan kehadiran berubah.
"""

from __future__ import annotations

from datetime import date

from apps.reports.api.hr.period_summary.metrics import Metric
from apps.reports.api.hr.period_summary.services import (
    HRPeriodSummaryPresenter,
)

from .base import PeriodSummaryTestCase


MON = date(2026, 6, 1)
TUE = date(2026, 6, 2)

# Hari terjadwal yang **tidak** dipakai baris presensi mana pun. Hari
# terjadwal yang sudah berstatus hadir dihitung sebagai hadir dan
# berhenti di situ; dokumen cuti di tanggal yang sama tidak pernah
# ikut terhitung. Jadi cuti contoh harus punya harinya sendiri, kalau
# tidak donutnya kosong dan test ini menguji tabel kosong.
WED = date(2026, 6, 3)


class ChartSeriesCodeTests(PeriodSummaryTestCase):
    def setUp(self):
        super().setUp()

        self.employee = self.make_office_employee()

        self.make_attendance(self.employee, MON)
        self.make_attendance(self.employee, TUE, late_minutes=10)
        self.make_leave(
            self.employee, leave_type=self.annual, start=WED, end=WED,
        )
        self.make_overtime(self.employee, TUE, minutes=120)

        self.context = self.context()

    def codes(self, chart):
        return [item["code"] for item in chart["datasets"]]

    def test_tren_kehadiran_menyebut_kode_metrik(self):
        chart = HRPeriodSummaryPresenter.attendance_trend(self.context)

        self.assertEqual(
            self.codes(chart),
            [Metric.PRESENT, Metric.LATE, Metric.ABSENT],
        )

        # Label lama tetap dikirim — klien tanpa katalog membacanya.
        self.assertEqual(
            [item["label"] for item in chart["datasets"]],
            ["Hadir", "Telat", "Tidak Hadir"],
        )

    def test_tren_lembur_menyebut_kode_metrik(self):
        chart = HRPeriodSummaryPresenter.overtime_trend(self.context)

        self.assertEqual(
            self.codes(chart),
            [Metric.OT_REGULAR, Metric.OT_OFF, Metric.OT_HOLIDAY],
        )

    def test_perbandingan_department_menyebut_kode_metrik(self):
        chart = HRPeriodSummaryPresenter.department_comparison(self.context)

        self.assertEqual(self.codes(chart), [Metric.PRESENT, Metric.ABSENT])

        # Nama department **tidak** berkode: itu data tenant, dan kode
        # untuknya berarti frontend boleh menerjemahkannya.
        self.assertTrue(chart["categories"])

    def test_irisan_cuti_berkode_kelompok_laporannya(self):
        chart = HRPeriodSummaryPresenter.leave_breakdown(self.context)

        codes = [item["code"] for item in chart["series"]]

        self.assertIn(Metric.ANNUAL, codes)
        self.assertTrue(all(code for code in codes))

        # Irisannya benar-benar berisi. Tanpa ini, donut kosong lolos
        # semua assertion di atas secara hampa.
        annual = next(
            item for item in chart["series"] if item["code"] == Metric.ANNUAL
        )

        self.assertEqual(annual["value"], 1.0)

        # Nilainya tidak bergeser karena kodenya ditambahkan.
        self.assertEqual(
            sum(item["value"] for item in chart["series"]),
            chart["total"],
        )

    def test_kode_selalu_kode_metrik_yang_sudah_ada(self):
        """
        Kosakata baru di sisi chart berarti katalog frontend harus
        menebak nama kedua untuk hal yang sama.
        """
        known = {
            value
            for key, value in vars(Metric).items()
            if not key.startswith("_") and isinstance(value, str)
        }

        charts = [
            HRPeriodSummaryPresenter.attendance_trend(self.context),
            HRPeriodSummaryPresenter.overtime_trend(self.context),
            HRPeriodSummaryPresenter.department_comparison(self.context),
        ]

        for chart in charts:
            for item in chart["datasets"]:
                self.assertIn(item["code"], known)

        leave = HRPeriodSummaryPresenter.leave_breakdown(
            self.context,
        )["series"]

        self.assertTrue(leave)

        for item in leave:
            self.assertIn(item["code"], known)
