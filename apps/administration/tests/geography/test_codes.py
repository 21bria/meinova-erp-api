"""
Kode wilayah: bentuk, induk, dan hal-hal yang tidak boleh terjadi
padanya.

`SimpleTestCase` — berkas ini **tidak menyentuh database sama sekali**,
dan itu properti yang harus tetap dijaga. Seluruh penentuan induk di
modul import memang murni operasi string; begitu ada yang menambahkan
query ke dalamnya, berkas ini yang pertama gagal.
"""

from django.test import SimpleTestCase

from apps.administration.imports.geography.codes import (
    CITY,
    DISTRICT,
    LEVEL_ORDER,
    LEVELS,
    PROVINCE,
    VILLAGE,
    clean_aid,
    get_level,
    is_child_of,
    level_for_aid,
    parent_aid,
)


class ParentAidTests(SimpleTestCase):
    def test_parent_is_one_segment_shorter(self):
        self.assertEqual(parent_aid("11.01.01.2002"), "11.01.01")
        self.assertEqual(parent_aid("11.01.01"), "11.01")
        self.assertEqual(parent_aid("11.01"), "11")

    def test_province_has_no_parent_area(self):
        """Induk provinsi adalah Country, bukan wilayah."""
        self.assertEqual(parent_aid("11"), "")

    def test_is_child_of_rejects_prefix_lookalike(self):
        """
        `startswith` menerima '11.011' sebagai anak '11.01'. Pemenggalan
        segmen tidak — dan itu sebabnya pemeriksaannya lewat sini, bukan
        lewat `startswith`.
        """
        self.assertTrue(is_child_of("11.01", "11"))
        self.assertFalse(is_child_of("11.011", "11.01"))
        self.assertFalse(is_child_of("12.01", "11"))

    def test_is_child_of_rejects_grandchild(self):
        self.assertFalse(is_child_of("11.01.01", "11"))


class CleanAidTests(SimpleTestCase):
    def test_leading_zero_is_preserved(self):
        """
        Yang paling mudah rusak dan paling sulit terlihat: begitu kode
        diubah jadi angka, '01.01' tidak bisa dibedakan dari '1.1'.
        """
        self.assertEqual(clean_aid(" 11.01.01.2002 "), "11.01.01.2002")
        self.assertEqual(clean_aid("01"), "01")
        self.assertEqual(clean_aid('"11.01"'), "11.01")
        self.assertEqual(clean_aid('="11.01"'), "11.01")

    def test_result_is_always_string(self):
        self.assertIsInstance(clean_aid(11), str)
        self.assertEqual(clean_aid(None), "")


class LevelPatternTests(SimpleTestCase):
    def test_each_level_accepts_only_its_own_shape(self):
        samples = {
            PROVINCE: "11",
            CITY: "11.01",
            DISTRICT: "11.01.01",
            VILLAGE: "11.01.01.2002",
        }

        for key, own in samples.items():
            level = LEVELS[key]

            self.assertTrue(
                level.matches(own),
                f"{key} harus menerima {own}",
            )

            for other_key, other in samples.items():
                if other_key == key:
                    continue

                self.assertFalse(
                    level.matches(other),
                    f"{key} tidak boleh menerima {other}",
                )

    def test_village_requires_four_digit_last_segment(self):
        village = LEVELS[VILLAGE]

        self.assertTrue(village.matches("11.01.01.2002"))
        self.assertFalse(village.matches("11.01.01.202"))
        self.assertFalse(village.matches("11.01.01.20020"))

    def test_non_numeric_is_rejected(self):
        self.assertFalse(LEVELS[PROVINCE].matches("DKI"))
        self.assertFalse(LEVELS[CITY].matches("11.AB"))

    def test_level_for_aid_identifies_shape(self):
        self.assertEqual(level_for_aid("11").key, PROVINCE)
        self.assertEqual(level_for_aid("11.01.01.2002").key, VILLAGE)
        self.assertIsNone(level_for_aid("JKT"))


class LevelOrderTests(SimpleTestCase):
    def test_order_goes_parent_to_child(self):
        self.assertEqual(
            LEVEL_ORDER,
            (PROVINCE, CITY, DISTRICT, VILLAGE),
        )

    def test_each_level_points_at_the_previous_one(self):
        self.assertIsNone(LEVELS[PROVINCE].parent_key)
        self.assertEqual(LEVELS[CITY].parent_key, PROVINCE)
        self.assertEqual(LEVELS[DISTRICT].parent_key, CITY)
        self.assertEqual(LEVELS[VILLAGE].parent_key, DISTRICT)

    def test_unknown_level_raises(self):
        with self.assertRaises(ValueError):
            get_level("kabupaten")
