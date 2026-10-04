"""
Mengunci perilaku `RotationPeriodGenerator` yang berlaku sekarang.

Ini test **regresi fase 0**, ditulis sebelum roster disentuh sama sekali.
Tujuannya bukan menyatakan bahwa perilaku di bawah sudah benar, melainkan
membuat setiap perubahannya terlihat sebagai test yang sengaja diperbarui
— bukan sebagai angka yang diam-diam berbeda.

Seluruhnya `SimpleTestCase`: generatornya memang fungsi murni tanpa
sentuhan database, dan itu properti yang harus tetap dijaga.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.test import SimpleTestCase

from apps.hr.api.site_rotation.generator import (
    MAX_CYCLE_COUNT,
    RotationPeriodGenerator,
)
from apps.hr.models import RotationPeriodType, SiteRotation


class RotationPeriodGeneratorBuildTests(SimpleTestCase):
    """Bentuk deret ON/OFF yang dihasilkan `build()`."""

    def test_simple_cycle_without_travel(self):
        """Pola 42/14 tanpa travel: dua blok rapat, tanpa celah."""
        rows = RotationPeriodGenerator.build(
            start_date=date(2026, 8, 1),
            work_days=42,
            off_days=14,
            cycle_count=2,
        )

        self.assertEqual(len(rows), 4)

        self.assertEqual(
            rows[0],
            {
                "sequence": 1,
                "period_type": RotationPeriodType.WORK,
                "start_date": date(2026, 8, 1),
                "end_date": date(2026, 9, 11),
                "total_days": 42,
            },
        )

        self.assertEqual(
            rows[1],
            {
                "sequence": 2,
                "period_type": RotationPeriodType.OFF,
                "start_date": date(2026, 9, 12),
                "end_date": date(2026, 9, 25),
                "total_days": 14,
            },
        )

        # Tanpa travel, blok berikutnya menempel persis di hari
        # berikutnya.
        self.assertEqual(rows[2]["start_date"], date(2026, 9, 26))
        self.assertEqual(rows[2]["period_type"], RotationPeriodType.WORK)

    def test_odd_travel_days_lean_to_outbound(self):
        """
        Travel total ganjil dipecah tidak rata dan kelebihannya jatuh ke
        sisi keluar: 3 → 2 keluar, 1 kembali (aturan #4 dokumen
        "Substansi Roster").
        """
        rows = RotationPeriodGenerator.build(
            start_date=date(2026, 1, 1),
            work_days=5,
            off_days=3,
            cycle_count=2,
            travel_days=3,
        )

        # WORK 1–5, lalu 2 hari travel keluar (6–7)
        self.assertEqual(rows[0]["end_date"], date(2026, 1, 5))
        self.assertEqual(rows[1]["start_date"], date(2026, 1, 8))

        # OFF 8–10, lalu 1 hari travel kembali (11)
        self.assertEqual(rows[1]["end_date"], date(2026, 1, 10))
        self.assertEqual(rows[2]["start_date"], date(2026, 1, 12))

    def test_travel_days_do_not_shrink_the_work_block(self):
        """
        Blok kerja 45 hari tetap 45 hari walau perjalanannya dua hari.

        Keputusan lama yang tetap berlaku: memotong travel dari Work Days
        membuat angka di kontrak tidak cocok dengan angka mana pun di
        sistem.
        """
        rows = RotationPeriodGenerator.build(
            start_date=date(2026, 3, 1),
            work_days=45,
            off_days=14,
            cycle_count=1,
            travel_days=2,
        )

        self.assertEqual(rows[0]["total_days"], 45)
        self.assertEqual(rows[1]["total_days"], 14)

    def test_cycle_advance_counts_travel_once(self):
        """
        Jarak antara dua awal blok kerja = work + off + travel.

        `travel_days` adalah total pulang-pergi, dan generator
        memecahnya jadi `ceil(t/2)` keluar + `floor(t/2)` kembali —
        sehingga per putaran travel terpakai **sekali**, bukan dua kali.

        Ini invarian yang paling gampang salah dipahami, dan sudah ada
        satu tempat di codebase yang menghitungnya berbeda. Test ini yang
        menentukan mana yang benar.
        """
        for work, off, travel in (
            (42, 14, 0),
            (42, 14, 2),
            (42, 14, 3),
            (56, 14, 2),
            (5, 3, 7),
        ):
            with self.subTest(work=work, off=off, travel=travel):
                rows = RotationPeriodGenerator.build(
                    start_date=date(2026, 1, 1),
                    work_days=work,
                    off_days=off,
                    cycle_count=3,
                    travel_days=travel,
                )

                work_starts = [
                    row["start_date"]
                    for row in rows
                    if row["period_type"] == RotationPeriodType.WORK
                ]

                for previous, current in zip(work_starts, work_starts[1:]):
                    self.assertEqual(
                        (current - previous).days,
                        work + off + travel,
                    )

    def test_start_with_off_reverses_the_block_order(self):
        """
        Menyambung jadwal yang berakhir di blok kerja dimulai dengan blok
        off, dan nomor urutnya melanjutkan — bukan mengulang dari 1.
        """
        rows = RotationPeriodGenerator.build(
            start_date=date(2026, 5, 1),
            work_days=10,
            off_days=4,
            cycle_count=1,
            travel_days=2,
            start_with=RotationPeriodType.OFF,
            start_sequence=7,
        )

        self.assertEqual(rows[0]["period_type"], RotationPeriodType.OFF)
        self.assertEqual(rows[0]["sequence"], 7)
        self.assertEqual(rows[1]["period_type"], RotationPeriodType.WORK)
        self.assertEqual(rows[1]["sequence"], 8)

        # Blok off diikuti porsi travel kembali (floor(2/2) = 1).
        self.assertEqual(rows[0]["end_date"], date(2026, 5, 4))
        self.assertEqual(rows[1]["start_date"], date(2026, 5, 6))

    def test_incomplete_pattern_returns_no_rows(self):
        """
        Tanpa tanggal mulai atau tanpa salah satu sisi siklus, generator
        diam — bukan melempar. Yang memberi pesan `Model.clean()`.
        """
        self.assertEqual(
            RotationPeriodGenerator.build(
                start_date=None,
                work_days=42,
                off_days=14,
                cycle_count=2,
            ),
            [],
        )

        self.assertEqual(
            RotationPeriodGenerator.build(
                start_date=date(2026, 1, 1),
                work_days=0,
                off_days=14,
                cycle_count=2,
            ),
            [],
        )

        self.assertEqual(
            RotationPeriodGenerator.build(
                start_date=date(2026, 1, 1),
                work_days=42,
                off_days=0,
                cycle_count=2,
            ),
            [],
        )

    def test_cycle_count_is_clamped(self):
        """Nol dinaikkan jadi 1, angka kebesaran dipotong ke pagar."""
        rows = RotationPeriodGenerator.build(
            start_date=date(2026, 1, 1),
            work_days=10,
            off_days=4,
            cycle_count=0,
        )

        self.assertEqual(len(rows), 2)

        rows = RotationPeriodGenerator.build(
            start_date=date(2026, 1, 1),
            work_days=10,
            off_days=4,
            cycle_count=999,
        )

        self.assertEqual(len(rows), MAX_CYCLE_COUNT * 2)

    def test_negative_travel_days_treated_as_zero(self):
        rows = RotationPeriodGenerator.build(
            start_date=date(2026, 1, 1),
            work_days=10,
            off_days=4,
            cycle_count=1,
            travel_days=-5,
        )

        self.assertEqual(rows[1]["start_date"], date(2026, 1, 11))

    def test_crosses_leap_day(self):
        """29 Februari 2028 ikut terhitung sebagai hari biasa."""
        rows = RotationPeriodGenerator.build(
            start_date=date(2028, 2, 20),
            work_days=14,
            off_days=7,
            cycle_count=1,
        )

        self.assertEqual(rows[0]["end_date"], date(2028, 3, 4))
        self.assertEqual(rows[0]["total_days"], 14)


class RotationPeriodGeneratorHelperTests(SimpleTestCase):
    """`cycles_until`, `summarize`, `next_cycle_start`."""

    def test_cycles_until_rounds_up(self):
        # 100 hari dengan siklus 56 → 2 siklus, karena separuh siklus
        # tetap butuh siklus penuh untuk menutupinya.
        self.assertEqual(
            RotationPeriodGenerator.cycles_until(
                start_date=date(2026, 1, 1),
                until=date(2026, 4, 10),
                cycle_length=56,
            ),
            2,
        )

    def test_cycles_until_guards(self):
        # `until` sebelum `start_date`, dan argumen kosong, sama-sama
        # jatuh ke 1 — bukan 0, yang akan menghasilkan jadwal kosong.
        self.assertEqual(
            RotationPeriodGenerator.cycles_until(
                start_date=date(2026, 6, 1),
                until=date(2026, 1, 1),
                cycle_length=56,
            ),
            1,
        )

        self.assertEqual(
            RotationPeriodGenerator.cycles_until(
                start_date=date(2026, 1, 1),
                until=date(2026, 6, 1),
                cycle_length=0,
            ),
            1,
        )

    def test_cycles_until_is_capped(self):
        self.assertEqual(
            RotationPeriodGenerator.cycles_until(
                start_date=date(2026, 1, 1),
                until=date(2099, 1, 1),
                cycle_length=56,
            ),
            MAX_CYCLE_COUNT,
        )

    def test_summarize(self):
        rows = RotationPeriodGenerator.build(
            start_date=date(2026, 8, 1),
            work_days=42,
            off_days=14,
            cycle_count=3,
            travel_days=2,
        )

        summary = RotationPeriodGenerator.summarize(rows)

        self.assertEqual(summary["cycles"], 3)
        self.assertEqual(summary["work_days"], 126)
        self.assertEqual(summary["off_days"], 42)
        self.assertEqual(summary["start_date"], date(2026, 8, 1))
        self.assertEqual(summary["end_date"], rows[-1]["end_date"])

    def test_summarize_empty(self):
        summary = RotationPeriodGenerator.summarize([])

        self.assertEqual(summary["cycles"], 0)
        self.assertEqual(summary["work_days"], 0)
        self.assertEqual(summary["off_days"], 0)
        self.assertIsNone(summary["start_date"])
        self.assertIsNone(summary["end_date"])

    def test_next_cycle_start_moves_anchor_forward(self):
        # Jangkar lama digeser maju ke awal siklus pertama yang jatuh
        # pada atau setelah tanggal acuan — bukan ke siklus terdekat.
        #
        # 1 Jan + 56 = 26 Feb sudah lewat saat acuannya 1 Mar (selisih 59
        # hari), jadi yang dipakai siklus berikutnya: 1 Jan + 112.
        self.assertEqual(
            RotationPeriodGenerator.next_cycle_start(
                anchor=date(2026, 1, 1),
                cycle_length=56,
                on_or_after=date(2026, 3, 1),
            ),
            date(2026, 4, 23),
        )

    def test_next_cycle_start_keeps_anchor_when_already_ahead(self):
        self.assertEqual(
            RotationPeriodGenerator.next_cycle_start(
                anchor=date(2026, 6, 1),
                cycle_length=56,
                on_or_after=date(2026, 1, 1),
            ),
            date(2026, 6, 1),
        )

    def test_next_cycle_start_lands_exactly_on_boundary(self):
        # `on_or_after` persis di awal siklus: tanggal itu sendiri yang
        # dipakai, bukan siklus berikutnya.
        anchor = date(2026, 1, 1)

        self.assertEqual(
            RotationPeriodGenerator.next_cycle_start(
                anchor=anchor,
                cycle_length=56,
                on_or_after=anchor + timedelta(days=56),
            ),
            anchor + timedelta(days=56),
        )

    def test_next_cycle_start_without_anchor_or_length(self):
        self.assertEqual(
            RotationPeriodGenerator.next_cycle_start(
                anchor=None,
                cycle_length=56,
                on_or_after=date(2026, 5, 5),
            ),
            date(2026, 5, 5),
        )

        self.assertEqual(
            RotationPeriodGenerator.next_cycle_start(
                anchor=date(2026, 1, 1),
                cycle_length=0,
                on_or_after=date(2026, 5, 5),
            ),
            date(2026, 5, 5),
        )


class SiteRotationCycleLengthTests(SimpleTestCase):
    """
    `SiteRotation.cycle_length` — properti murni, tidak menyentuh
    database, jadi cukup instance yang belum disimpan.
    """

    def test_cycle_length_counts_travel_once(self):
        """
        Sepakat dengan `test_cycle_advance_counts_travel_once`: panjang
        satu putaran = work + off + travel, travel dihitung sekali.
        """
        rotation = SiteRotation(
            cycle_work_days=42,
            cycle_off_days=14,
            cycle_travel_days=2,
        )

        self.assertEqual(rotation.cycle_length, 58)

    def test_cycle_length_without_pattern(self):
        self.assertIsNone(SiteRotation().cycle_length)
