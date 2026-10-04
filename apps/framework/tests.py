"""
Framework — pembacaan parameter yang tidak boleh dipercaya begitu saja.

`SimpleTestCase`: tidak satu pun test di sini menyentuh database, dan itu
properti yang harus tetap dijaga. `TablePage` memang cuma membaca query
string; begitu ada yang menambahkan query ke dalamnya, berkas ini yang
pertama gagal.
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.framework.tables import DEFAULT_PAGE_SIZE, TablePage


class FakeParams(dict):
    """Sekadar `query_params`; yang dipakai `TablePage` hanya `.get()`."""


class FakeRequest:
    def __init__(self, **params):
        self.query_params = FakeParams(params)


class TablePageTests(SimpleTestCase):
    WIDGET = {
        "key": "employee_period_summary",
        "page_size": 25,
        "page_size_options": [25, 50, 100],
    }

    # ------------------------------------------------------------------
    # Batas ukuran
    # ------------------------------------------------------------------

    def test_page_size_outside_options_falls_back_to_default(self):
        """
        `?page_size=99999` **tidak** dilayani.

        Ini bukan kerapian: laporan ini merakit satu baris per pegawai
        beserta seluruh metriknya, dan satu tenant tiga ribu pegawai yang
        diminta dalam satu halaman berarti seluruh agregasi dirakit jadi
        satu respons. Yang jatuh bukan cuma laporannya.
        """
        page = TablePage.from_request(
            FakeRequest(page_size="99999"),
            self.WIDGET,
        )

        self.assertEqual(page.page_size, 25)

    def test_page_size_within_options_is_honoured(self):
        page = TablePage.from_request(
            FakeRequest(page_size="100"),
            self.WIDGET,
        )

        self.assertEqual(page.page_size, 100)

    def test_widget_without_options_uses_framework_defaults(self):
        page = TablePage.from_request(FakeRequest(page_size="50"), {})

        self.assertEqual(page.page_size, 50)

        fallback = TablePage.from_request(FakeRequest(page_size="7"), {})

        self.assertEqual(fallback.page_size, DEFAULT_PAGE_SIZE)

    # ------------------------------------------------------------------
    # Halaman
    # ------------------------------------------------------------------

    def test_nonsense_page_falls_back_instead_of_erroring(self):
        """
        Satu parameter salah ketik tidak boleh mematikan halaman —
        aturan yang sama dengan `BaseDashboardAPIView.get_period`.
        """
        for raw in ("", "abc", "-3", None):
            with self.subTest(page=raw):
                page = TablePage.from_request(
                    FakeRequest(page=raw),
                    self.WIDGET,
                )

                self.assertEqual(page.page, 1)

    def test_page_zero_lands_on_the_first_page(self):
        """
        `?page=0` bukan offset negatif.

        `rows[-25:]` tidak melempar apa pun — ia mengembalikan 25 baris
        **terakhir** dengan tenang, dan halaman yang terbuka berisi orang
        yang sama sekali bukan yang dicari.
        """
        page = TablePage.from_request(FakeRequest(page="0"), self.WIDGET)

        self.assertEqual(page.page, 1)
        self.assertEqual(page.offset, 0)

    def test_offset_follows_page_and_size(self):
        page = TablePage(page=3, page_size=25)

        self.assertEqual(page.offset, 50)
        self.assertEqual(page.slice(list(range(100))), list(range(50, 75)))

    # ------------------------------------------------------------------
    # Pencarian
    # ------------------------------------------------------------------

    def test_search_is_case_insensitive_and_trimmed(self):
        page = TablePage.from_request(
            FakeRequest(search="  BIMO  "),
            self.WIDGET,
        )

        self.assertEqual(page.search, "BIMO")
        self.assertEqual(page.matching(["bimo nugroho", "sari"], text=str), ["bimo nugroho"])

    def test_empty_search_keeps_every_row(self):
        rows = ["a", "b", "c"]

        page = TablePage.from_request(FakeRequest(), self.WIDGET)

        self.assertEqual(page.matching(rows, text=str), rows)

    # ------------------------------------------------------------------
    # Amplop
    # ------------------------------------------------------------------

    def test_envelope_counts_pages_from_matched_not_total(self):
        """
        Jumlah halaman mengikuti yang **lolos kotak cari**.

        Kalau ia mengikuti `total`, mencari satu nama di tenant berisi
        500 orang menyisakan satu baris tapi tetap menawarkan 20 halaman
        — sembilan belas di antaranya kosong.
        """
        page = TablePage(page=1, page_size=25, search="bimo")

        envelope = page.envelope(items=[{}], matched=1, total=500)

        self.assertEqual(envelope["page_count"], 1)
        self.assertEqual(envelope["matched"], 1)
        self.assertEqual(envelope["total"], 500)

    def test_envelope_never_reports_zero_pages(self):
        """Hasil kosong tetap "1 / 1", bukan "1 / 0"."""
        envelope = TablePage().envelope(items=[], matched=0, total=0)

        self.assertEqual(envelope["page_count"], 1)
