"""
Kode kanonik deret chart + kunci placeholder pencarian.

`SimpleTestCase`: tidak satu pun test di sini menyentuh database —
keduanya murni bentuk data, dan biaya schema tenant tidak dibayar untuk
memeriksa sebuah dict.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.framework.builders import dashboard as builder
from apps.framework.charts import dataset, point


class ChartSeriesTests(SimpleTestCase):
    def test_kode_dikirim_di_samping_label_bukan_menggantikannya(self):
        """
        Aditif. Klien lama membaca `label`; yang baru membaca `code` dan
        menerjemahkannya. Menghapus `label` berarti dashboard yang belum
        punya katalog kehilangan legendanya sama sekali.
        """
        result = dataset(
            code="present", label="Hadir", data=[1, 2], color="success",
        )

        self.assertEqual(
            result,
            {
                "label": "Hadir",
                "data": [1, 2],
                "code": "present",
                "color": "success",
            },
        )

    def test_warna_tidak_dikirim_kalau_tidak_disebut(self):
        # Apex memakai `colors` sebagai rotasi berurutan; daftar yang
        # bolong menggeser warna seluruh deret sesudahnya.
        self.assertNotIn("color", dataset(code="late", label="Telat", data=[]))

    def test_titik_donut_membawa_kode_dan_nilai(self):
        self.assertEqual(
            point(code="annual", label="Annual", value=2.5),
            {"label": "Annual", "value": 2.5, "code": "annual"},
        )

    def test_data_disalin_bukan_dirujuk(self):
        values = [1, 2]
        result = dataset(code="absent", label="Tidak Hadir", data=values)

        values.append(3)

        self.assertEqual(result["data"], [1, 2])


class SearchPlaceholderKeyTests(SimpleTestCase):
    def test_kunci_konteks_diteruskan_ke_schema(self):
        widget = builder.table(
            "employee_period_summary",
            label="Employee Period Summary",
            searchable=True,
            search_placeholder="Cari nama atau nomor pegawai",
            search_placeholder_key="employee",
        )

        self.assertEqual(widget["search_placeholder_key"], "employee")
        # Teks cadangan tetap dikirim: schema yang belum punya katalog
        # frontend tidak boleh kehilangan placeholder-nya.
        self.assertEqual(
            widget["search_placeholder"], "Cari nama atau nomor pegawai",
        )

    def test_tabel_lama_tidak_mendadak_membawa_kunci_kosong(self):
        widget = builder.table("x", label="X", searchable=True)

        self.assertNotIn("search_placeholder_key", widget)

    def test_period_summary_menyebut_konteks_pencariannya(self):
        from apps.reports.api.hr.period_summary.schema import (
            HR_PERIOD_SUMMARY_SCHEMA,
        )

        table = next(
            widget
            for widget in HR_PERIOD_SUMMARY_SCHEMA["widgets"]
            if widget["key"] == "employee_period_summary"
        )

        self.assertEqual(table["search_placeholder_key"], "employee")
