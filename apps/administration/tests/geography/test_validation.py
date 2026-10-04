"""
Validasi baris import wilayah.

`validate_rows` sengaja menerima daftar induk sebagai **parameter**,
bukan membacanya sendiri dari database. Itu yang membuat berkas ini bisa
menguji "induknya tidak ada" tanpa menyiapkan tenant — dan yang membuat
dry-run bisa memvalidasi anak di database yang masih kosong, memakai
induk yang baru saja lolos di berkas sebelumnya.
"""

from django.test import SimpleTestCase

from apps.administration.imports.geography.codes import (
    CITY,
    DISTRICT,
    LEVELS,
    PROVINCE,
    VILLAGE,
)
from apps.administration.imports.geography.service import (
    GeographyImportService,
    LevelResult,
)


class ValidateRowsTests(SimpleTestCase):
    def run_level(self, level_key, rows, parent_aids=None):
        """
        `rows` = [(nomor_baris, aid, name)].
        Mengembalikan `(baris_lolos, result)`.
        """
        level = LEVELS[level_key]

        result = LevelResult(level=level.key, label=level.label)

        valid = GeographyImportService.validate_rows(
            level=level,
            rows=rows,
            parent_aids=parent_aids,
            result=result,
        )

        return valid, result

    def messages(self, result):
        return " | ".join(item.error for item in result.errors)

    # ------------------------------------------------------------------
    # Kasus yang disebut eksplisit di spesifikasi
    # ------------------------------------------------------------------

    def test_city_under_missing_province_is_rejected(self):
        """
        Province = 11, City = 12.01 -> ditolak.

        Provinsi 12 tidak ada, jadi kabupatennya tidak punya tempat
        bergantung. Tanpa pemeriksaan ini barisnya tersimpan dengan
        induk yang salah — atau lebih buruk, tanpa induk sama sekali.
        """
        valid, result = self.run_level(
            CITY,
            [(2, "11.01", "Aceh Selatan"), (3, "12.01", "Orphan")],
            parent_aids={"11"},
        )

        self.assertEqual(len(valid), 1)
        self.assertEqual(result.valid, 1)
        self.assertEqual(result.invalid, 1)
        self.assertIn("12", self.messages(result))

    def test_district_under_missing_city_is_rejected(self):
        """City = 11.01, Kecamatan = 11.02.01 -> ditolak."""
        valid, result = self.run_level(
            DISTRICT,
            [(2, "11.01.01", "Bakongan"), (3, "11.02.01", "Salah Induk")],
            parent_aids={"11.01"},
        )

        self.assertEqual(len(valid), 1)
        self.assertEqual(result.invalid, 1)

    def test_wrong_level_shape_is_rejected(self):
        """Kode kelurahan di berkas kecamatan tidak boleh lolos."""
        _valid, result = self.run_level(
            DISTRICT,
            [(2, "11.01.01.2002", "Level Tertukar")],
            parent_aids={"11.01"},
        )

        self.assertEqual(result.invalid, 1)
        self.assertIn("Kelurahan/Desa", self.messages(result))

    def test_empty_id_and_empty_name_are_rejected(self):
        _valid, result = self.run_level(
            PROVINCE,
            [(2, "", "Tanpa Kode"), (3, "12", "")],
            parent_aids=None,
        )

        self.assertEqual(result.invalid, 2)
        self.assertIn("id kosong", self.messages(result))
        self.assertIn("name kosong", self.messages(result))

    def test_duplicate_aid_in_same_file_is_detected(self):
        """
        Duplikat di dalam berkas tidak bisa ditangkap constraint
        database: saat dry-run belum ada yang tertulis sama sekali.
        """
        valid, result = self.run_level(
            PROVINCE,
            [(2, "11", "Aceh"), (3, "11", "Aceh Lagi")],
            parent_aids=None,
        )

        self.assertEqual(len(valid), 1)
        self.assertEqual(result.invalid, 1)
        self.assertIn("duplikat", self.messages(result).lower())
        self.assertIn("baris 2", self.messages(result))

    def test_error_row_carries_full_context(self):
        """
        Laporan error wajib memuat level, baris, code, name, parent, dan
        sebabnya — laporan tanpa nomor baris tidak bisa ditindaklanjuti
        pada berkas berisi 83.762 baris.
        """
        _valid, result = self.run_level(
            VILLAGE,
            [(9, "11.99.01.2002", "Yatim")],
            parent_aids={"11.01.01"},
        )

        error = result.errors[0].as_dict()

        self.assertEqual(error["level"], "Kelurahan/Desa")
        self.assertEqual(error["row"], 9)
        self.assertEqual(error["code"], "11.99.01.2002")
        self.assertEqual(error["name"], "Yatim")
        self.assertEqual(error["parent_code"], "11.99.01")
        self.assertTrue(error["error"])

    # ------------------------------------------------------------------
    # Nama tidak pernah ikut menentukan
    # ------------------------------------------------------------------

    def test_identical_names_under_different_parents_both_pass(self):
        """
        Nama wilayah berulang di seluruh Indonesia. Kalau nama ikut
        menentukan, salah satunya akan dibuang sebagai duplikat.
        """
        valid, result = self.run_level(
            DISTRICT,
            [
                (2, "11.01.01", "Sukamaju"),
                (3, "12.01.01", "Sukamaju"),
            ],
            parent_aids={"11.01", "12.01"},
        )

        self.assertEqual(len(valid), 2)
        self.assertEqual(result.invalid, 0)

    def test_matching_name_does_not_rescue_a_wrong_code(self):
        """
        Nama yang persis sama dengan induknya tidak membuat kodenya
        sah. Yang menentukan cuma awalan kode.
        """
        _valid, result = self.run_level(
            CITY,
            [(2, "99.01", "Aceh")],
            parent_aids={"11"},
        )

        self.assertEqual(result.invalid, 1)

    # ------------------------------------------------------------------
    # Rantai dry-run
    # ------------------------------------------------------------------

    def test_parent_may_come_from_the_same_run(self):
        """
        Dry-run di database kosong: induk kabupaten adalah provinsi yang
        baru saja lolos di berkas sebelumnya, belum tertulis di
        database. Tanpa ini, dry-run pertama menolak seluruh berkas anak.
        """
        province_valid, province_result = self.run_level(
            PROVINCE,
            [(2, "11", "Aceh")],
            parent_aids=None,
        )

        self.assertEqual(len(province_valid), 1)

        _valid, city_result = self.run_level(
            CITY,
            [(2, "11.01", "Aceh Selatan")],
            parent_aids=province_result.valid_aids,
        )

        self.assertEqual(city_result.valid, 1)
        self.assertEqual(city_result.invalid, 0)

    def test_province_needs_no_area_parent(self):
        _valid, result = self.run_level(
            PROVINCE,
            [(2, "11", "Aceh"), (3, "96", "Papua Barat Daya")],
            parent_aids=None,
        )

        self.assertEqual(result.valid, 2)
        self.assertEqual(result.invalid, 0)
