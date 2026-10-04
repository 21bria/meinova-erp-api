"""
Tabel Employee Period Summary — paginasi, pencarian, dan baris Total.

Yang diuji di sini bukan aritmetika metriknya (itu ada di
`test_period_summary.py` dan tidak boleh berubah), melainkan satu janji
yang gampang sekali dilanggar diam-diam:

    **Pindah halaman tidak mengubah satu angka pun di luar tabel.**

Kalau `total`/`totals` ikut diiris bersama `items`, kartu KPI yang
menghitung 500 orang berdiri di atas baris Total yang menjumlahkan 25 —
dan yang membacanya akan menyimpulkan salah satunya salah, tanpa ada
satu pun error yang menunjukkan yang mana.

Jumlah pegawai tenant test **tidak** diasumsikan: `TenantTestCase`
django-tenants tidak me-rollback antar test, jadi pegawai dari berkas
test lain ikut terbaca. Tiap assertion karena itu membandingkan hasil
berhalaman dengan hasil tanpa halaman **di test yang sama**, bukan
dengan angka yang ditulis di kode.
"""

from __future__ import annotations

from apps.framework.tables import TablePage
from apps.reports.api.hr.period_summary.metrics import Metric
from apps.reports.api.hr.period_summary.schema import TABLE_WIDGET
from apps.reports.api.hr.period_summary.services import (
    HRPeriodSummaryPresenter,
)

from .base import PeriodSummaryTestCase


class EmployeeIdentityColumnTests(PeriodSummaryTestCase):
    """
    Nomor pegawai berdiri sebagai kolomnya sendiri, di depan nama.

    Sebelumnya `employee_number` **sudah** ikut di setiap baris —
    `table_row()` mengirimnya, dan kotak cari sudah mencocokkannya — tapi
    tidak ada satu kolom pun yang menampilkannya. Data yang terkirim
    tanpa kolom adalah cara paling sunyi sebuah field terlihat "tidak
    ada": yang membuka layar menyimpulkan backend tidak mengirimnya, dan
    mencarinya di tempat yang salah.
    """

    def test_kolomnya_ada_dan_mendahului_nama(self):
        keys = [column["key"] for column in TABLE_WIDGET["columns"]]

        self.assertIn("employee_number", keys)
        self.assertIn("employee", keys)

        self.assertLess(
            keys.index("employee_number"),
            keys.index("employee"),
            "Employee ID harus berdiri sebelum Employee Name",
        )

    def test_labelnya_employee_id(self):
        label = next(
            column["label"]
            for column in TABLE_WIDGET["columns"]
            if column["key"] == "employee_number"
        )

        self.assertEqual(label, "Employee ID")

    def test_nomor_dan_nama_terkirim_bersama_di_baris_yang_sama(self):
        """
        Keduanya harus datang dari baris yang sama. Nomor yang benar di
        sebelah nama orang lain adalah kesalahan yang tidak terlihat
        seperti kesalahan.
        """
        employee = self.make_office_employee()

        table = HRPeriodSummaryPresenter.employee_table(
            self.context(employee),
        )

        item = next(
            row for row in table["items"] if row["id"] == employee.id
        )

        self.assertEqual(item["employee_number"], employee.employee_number)
        self.assertEqual(item["employee"], employee.full_name)

        # Nomornya benar-benar terisi, bukan string kosong yang kebetulan
        # sama dengan nilai bawaan `EmployeeSummary`.
        self.assertTrue(item["employee_number"])

    def test_drilldown_tetap_memakai_id_internal(self):
        """
        Nomor pegawai boleh diketik ulang HR dan boleh kosong, jadi ia
        bukan kunci. Yang dipakai menelusuri tetap `id`.
        """
        employee = self.make_office_employee()

        table = HRPeriodSummaryPresenter.employee_table(
            self.context(employee),
        )

        item = next(
            row for row in table["items"] if row["id"] == employee.id
        )

        self.assertEqual(item["id"], employee.id)
        self.assertNotEqual(item["id"], item["employee_number"])

    def test_lebarnya_disebut_supaya_tidak_menyisakan_jarak(self):
        """
        Kolom terkunci memakai lebar bawaan 224px kalau schema diam, dan
        "HO001" di kotak selebar itu meninggalkan jarak kosong sampai
        kolom nama — terbaca seperti kolomnya salah pasang.
        """
        column = next(
            item
            for item in TABLE_WIDGET["columns"]
            if item["key"] == "employee_number"
        )

        self.assertIn("width", column)
        self.assertLess(column["width"], 224)

    def test_nama_ikut_terkunci_bersama_nomor(self):
        """
        Dua kolom terkunci, bukan satu. Sebelum Employee ID ada, satu
        kolom terkunci berarti **nama** yang tinggal saat tabel digeser;
        membiarkannya satu sekarang membuat yang tinggal cuma nomor, dan
        sembilan belas kolom angka di sebelahnya jadi tidak bisa dibaca
        milik siapa.
        """
        keys = [column["key"] for column in TABLE_WIDGET["columns"]]

        sticky = keys[: TABLE_WIDGET["sticky_columns"]]

        self.assertEqual(sticky, ["employee_number", "employee"])

    def test_baris_total_tidak_menjumlahkan_identitas(self):
        """
        Kolom identitas tidak punya nilai di kaki tabel. Menjumlahkan
        nomor pegawai menghasilkan angka yang tidak salah hitung, cuma
        tidak berarti apa pun.
        """
        self.make_office_employee()

        table = HRPeriodSummaryPresenter.employee_table(self.context())

        self.assertNotIn("employee_number", table["totals"])
        self.assertNotIn("employee", table["totals"])


class EmployeeTablePaginationTests(PeriodSummaryTestCase):
    def full_table(self, context) -> dict:
        """Tabel tanpa paginasi — pembanding untuk seluruh test di sini."""
        return HRPeriodSummaryPresenter.employee_table(context)

    # ------------------------------------------------------------------
    # Potongan halaman
    # ------------------------------------------------------------------

    def test_first_page_holds_the_first_rows_in_the_same_order(self):
        for _ in range(3):
            self.make_office_employee()

        context = self.context()

        full = self.full_table(context)

        paged = HRPeriodSummaryPresenter.employee_table(
            context,
            page=TablePage(page=1, page_size=2),
        )

        self.assertEqual(len(paged["items"]), 2)
        self.assertEqual(paged["items"], full["items"][:2])

    def test_second_page_continues_where_the_first_stopped(self):
        """
        Halaman kedua menyambung, bukan mengulang.

        Urutan barisnya ditetapkan `employee_queryset` (`location__code`,
        lalu `employee_number`) dan **harus tetap** — irisan halaman di
        atas urutan yang tidak pasti membuat satu pegawai muncul di dua
        halaman sementara yang lain tidak muncul sama sekali.
        """
        for _ in range(3):
            self.make_office_employee()

        context = self.context()

        full = self.full_table(context)

        page_one = HRPeriodSummaryPresenter.employee_table(
            context,
            page=TablePage(page=1, page_size=2),
        )
        page_two = HRPeriodSummaryPresenter.employee_table(
            context,
            page=TablePage(page=2, page_size=2),
        )

        self.assertEqual(page_two["items"], full["items"][2:4])

        ids_one = {row["id"] for row in page_one["items"]}
        ids_two = {row["id"] for row in page_two["items"]}

        self.assertFalse(ids_one & ids_two)

    def test_page_beyond_the_end_is_empty_but_still_reports_the_totals(self):
        """
        Halaman di luar jangkauan mengembalikan nol baris — **bukan**
        baris terakhir. `rows[offset:]` dengan offset terlalu besar
        memang kosong; yang berbahaya adalah offset negatif, dan itu
        dicegah `TablePage` (lihat `apps/framework/tests.py`).
        """
        self.make_office_employee()

        context = self.context()

        full = self.full_table(context)

        paged = HRPeriodSummaryPresenter.employee_table(
            context,
            page=TablePage(page=9_999, page_size=25),
        )

        self.assertEqual(paged["items"], [])
        self.assertEqual(paged["total"], full["total"])
        self.assertEqual(paged["totals"], full["totals"])

    # ------------------------------------------------------------------
    # Yang tidak boleh ikut berubah
    # ------------------------------------------------------------------

    def test_totals_and_headcount_ignore_the_page(self):
        """
        Inti seluruh berkas ini. `total` dan `totals` sama persis di
        halaman mana pun, dan sama dengan yang dihitung tanpa halaman —
        yaitu angka yang juga dipakai kartu KPI.
        """
        for _ in range(3):
            self.make_office_employee()

        context = self.context()

        full = self.full_table(context)

        for number in (1, 2, 3):
            with self.subTest(page=number):
                paged = HRPeriodSummaryPresenter.employee_table(
                    context,
                    page=TablePage(page=number, page_size=1),
                )

                self.assertEqual(paged["total"], full["total"])
                self.assertEqual(paged["totals"], full["totals"])

    def test_totals_ignore_the_search_box(self):
        """
        Kotak cari menyaring **tabelnya**, bukan laporannya.

        Baris Total tetap menjawab "berapa seluruhnya pada filter ini".
        Yang berubah cuma `matched`, dan itu memang dipakai memberi tahu
        pembacanya bahwa yang terlihat lebih sedikit dari yang dihitung.
        """
        employee = self.make_office_employee()

        self.make_office_employee()

        context = self.context()

        full = self.full_table(context)

        found = HRPeriodSummaryPresenter.employee_table(
            context,
            page=TablePage(page=1, page_size=25, search=employee.employee_number),
        )

        self.assertEqual(len(found["items"]), 1)
        self.assertEqual(found["items"][0]["id"], employee.id)
        self.assertEqual(found["matched"], 1)

        self.assertEqual(found["total"], full["total"])
        self.assertEqual(found["totals"], full["totals"])

    # ------------------------------------------------------------------
    # Pencarian
    # ------------------------------------------------------------------

    def test_search_matches_name_as_well_as_number(self):
        employee = self.make_office_employee()

        context = self.context()

        by_name = HRPeriodSummaryPresenter.employee_table(
            context,
            page=TablePage(search=employee.first_name.lower()),
        )

        self.assertIn(
            employee.id,
            {row["id"] for row in by_name["items"]},
        )

    def test_search_without_a_match_is_empty_not_everything(self):
        """
        Kata yang tidak cocok menghasilkan nol baris.

        Kegagalan yang ditakuti adalah kebalikannya: pencarian yang salah
        dipasang mengembalikan seluruh tabel, dan itu terbaca seperti
        "tidak ada yang tersaring" alih-alih "tidak ada yang cocok".
        """
        self.make_office_employee()

        result = HRPeriodSummaryPresenter.employee_table(
            self.context(),
            page=TablePage(search="tidak-ada-pegawai-bernama-begini"),
        )

        self.assertEqual(result["items"], [])
        self.assertEqual(result["matched"], 0)
        self.assertEqual(result["page_count"], 1)

    # ------------------------------------------------------------------
    # Bentuk lama
    # ------------------------------------------------------------------

    def test_unpaginated_call_keeps_its_original_shape(self):
        """
        Tanpa `page`, balasannya tetap `{items, total, totals}` seperti
        sebelum paginasi ada — pemanggil lain (dan test metrik di berkas
        sebelah) tidak ikut berubah.
        """
        self.make_office_employee()

        result = self.full_table(self.context())

        self.assertEqual(set(result), {"items", "total", "totals"})
        self.assertIn(Metric.OT_TOTAL, result["totals"])
