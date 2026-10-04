"""
`RosterCalculationService` — rumus jadwal roster.

`SimpleTestCase`, dan itu **bukan kebetulan**: kalkulator ini fungsi
murni tanpa satu pun query, dan test yang tidak menyentuh database
adalah cara paling langsung menjaganya tetap begitu. Begitu ada yang
menambahkan lookup ke dalamnya, berkas ini yang pertama gagal.

Menutup kasus uji A (jadwal normal), B (policy sama, jangkar berbeda),
dan L (pegawai lokal tanpa travel).
"""

from __future__ import annotations

from datetime import date

from django.test import SimpleTestCase

from apps.hr.api.roster.calculation import (
    DEFAULT_HORIZON_MONTHS,
    MAX_HORIZON_MONTHS,
    MAX_SEGMENTS_PER_PLAN,
    CyclePattern,
    RosterCalculationService,
    add_months,
)
from apps.hr.models import RosterSegmentType


SIX_TWO = CyclePattern(work_days=42, off_days=14)

SIX_TWO_TRAVEL = CyclePattern(
    work_days=42,
    off_days=14,
    travel_out_days=1,
    travel_in_days=1,
)


class CyclePatternTests(SimpleTestCase):
    def test_cycle_length_includes_both_travel_legs(self):
        self.assertEqual(SIX_TWO.cycle_length, 56)
        self.assertEqual(SIX_TWO_TRAVEL.cycle_length, 58)

    def test_asymmetric_travel_is_not_doubled(self):
        """
        Tiga hari perjalanan pulang-pergi berarti panjang siklus
        `work + off + 3`, bukan `+ 6`. Ini kesalahan yang pernah
        terjadi di generator lama dan melesetnya menumpuk sepanjang
        tahun.
        """
        pattern = CyclePattern(
            work_days=42,
            off_days=14,
            travel_out_days=2,
            travel_in_days=1,
        )

        self.assertEqual(pattern.cycle_length, 59)

    def test_pattern_without_off_days_is_invalid(self):
        self.assertFalse(
            CyclePattern(work_days=42, off_days=0).is_valid,
        )

        self.assertEqual(
            CyclePattern(work_days=42, off_days=0).cycle_length, 0,
        )


class WorkBlockStartTests(SimpleTestCase):
    """
    Tiga basis, tiga jawaban berbeda dari satu tanggal yang sama —
    justru itu alasannya jadi kolom.
    """

    def test_work_start_uses_the_date_as_typed(self):
        self.assertEqual(
            RosterCalculationService.work_block_start(
                cycle_start=date(2026, 8, 1),
                pattern=SIX_TWO_TRAVEL,
            ),
            # Basis bawaan: tanggal yang diketik adalah hari pertama
            # kerja, apa pun hari perjalanannya.
            date(2026, 8, 1),
        )

    def test_site_arrival_starts_the_next_day(self):
        pattern = CyclePattern(
            work_days=42,
            off_days=14,
            travel_in_days=1,
            roster_start_basis="site_arrival",
        )

        self.assertEqual(
            RosterCalculationService.work_block_start(
                cycle_start=date(2026, 8, 1),
                pattern=pattern,
            ),
            date(2026, 8, 2),
        )

    def test_site_arrival_without_travel_starts_the_same_day(self):
        """Tanpa perjalanan tidak ada yang bisa 'tiba'."""
        pattern = CyclePattern(
            work_days=42,
            off_days=14,
            roster_start_basis="site_arrival",
        )

        self.assertEqual(
            RosterCalculationService.work_block_start(
                cycle_start=date(2026, 8, 1),
                pattern=pattern,
            ),
            date(2026, 8, 1),
        )

    def test_travel_departure_skips_the_whole_inbound_leg(self):
        pattern = CyclePattern(
            work_days=42,
            off_days=14,
            travel_in_days=3,
            roster_start_basis="travel_departure",
        )

        self.assertEqual(
            RosterCalculationService.work_block_start(
                cycle_start=date(2026, 8, 1),
                pattern=pattern,
            ),
            date(2026, 8, 4),
        )


class BuildSegmentsTests(SimpleTestCase):
    def rows(self, pattern=SIX_TWO_TRAVEL, **kwargs):
        kwargs.setdefault("cycle_start", date(2026, 8, 1))
        kwargs.setdefault("horizon_end", date(2027, 8, 1))

        return RosterCalculationService.build_segments(
            pattern=pattern, **kwargs,
        )

    # -- Kasus A ------------------------------------------------------

    def test_cycle_shape_is_work_out_break_in(self):
        rows = self.rows()

        self.assertEqual(
            [row.segment_type for row in rows[:5]],
            [
                RosterSegmentType.WORK,
                RosterSegmentType.TRAVEL_OUT,
                RosterSegmentType.FIELD_BREAK,
                RosterSegmentType.TRAVEL_IN,
                RosterSegmentType.WORK,
            ],
        )

    def test_segments_are_contiguous_with_no_gap_or_overlap(self):
        rows = self.rows()

        for previous, current in zip(rows, rows[1:]):
            self.assertEqual(
                (current.start_date - previous.end_date).days,
                1,
                f"{previous.segment_type} → {current.segment_type}",
            )

    def test_work_blocks_advance_by_one_full_cycle(self):
        rows = self.rows()

        starts = [
            row.start_date
            for row in rows
            if row.segment_type == RosterSegmentType.WORK
        ]

        for previous, current in zip(starts, starts[1:]):
            self.assertEqual((current - previous).days, 58)

    def test_travel_never_shortens_the_work_block(self):
        """
        Pegawai 42/14 yang dua hari di kapal tetap menjalani 42 hari di
        site. Memotongnya dari Work Days membuat angka di kontrak tidak
        cocok dengan angka mana pun di sistem.
        """
        for out_days, in_days in ((0, 0), (1, 1), (2, 1), (3, 3)):
            pattern = CyclePattern(
                work_days=42,
                off_days=14,
                travel_out_days=out_days,
                travel_in_days=in_days,
            )

            rows = self.rows(pattern=pattern)

            work = [
                row for row in rows
                if row.segment_type == RosterSegmentType.WORK
            ]

            self.assertTrue(work)

            for row in work:
                self.assertEqual(row.total_days, 42)

    # -- Kasus L ------------------------------------------------------

    def test_local_employee_has_no_travel_segment(self):
        rows = self.rows(pattern=SIX_TWO)

        self.assertEqual(
            {row.segment_type for row in rows},
            {RosterSegmentType.WORK, RosterSegmentType.FIELD_BREAK},
        )

        # Dan jadwalnya tetap bersambung — tidak ada lubang di tempat
        # segmen travel yang tidak dibuat.
        for previous, current in zip(rows, rows[1:]):
            self.assertEqual(
                (current.start_date - previous.end_date).days, 1,
            )

    def test_travel_creates_segment_false_suppresses_the_rows(self):
        pattern = CyclePattern(
            work_days=42,
            off_days=14,
            travel_out_days=2,
            travel_in_days=2,
            travel_creates_segment=False,
        )

        rows = self.rows(pattern=pattern)

        self.assertNotIn(
            RosterSegmentType.TRAVEL_OUT,
            {row.segment_type for row in rows},
        )

        # Tanpa baris travel, panjang putarannya kembali `work + off`.
        starts = [
            row.start_date
            for row in rows
            if row.segment_type == RosterSegmentType.WORK
        ]

        self.assertEqual((starts[1] - starts[0]).days, 56)

    # -- Nomor putaran ------------------------------------------------

    def test_cycle_number_increments_at_each_work_block(self):
        rows = self.rows()

        for row in rows[:4]:
            self.assertEqual(row.cycle_number, 1)

        self.assertEqual(rows[4].cycle_number, 2)
        self.assertEqual(rows[5].cycle_number, 2)

    def test_cycle_number_still_lands_on_work_when_joining_mid_cycle(self):
        """
        Menyambung dari field break: nomor putaran harus naik saat blok
        **kerja** berikutnya dibuka, bukan saat daftar bloknya habis.
        Kalau salah, blok kerja pembuka putaran kedua masih bernomor 1
        dan travel sesudahnya yang bernomor 2.
        """
        rows = self.rows(
            start_with=RosterSegmentType.FIELD_BREAK,
            cycle_number_start=3,
            horizon_end=date(2026, 12, 31),
        )

        self.assertEqual(rows[0].segment_type, RosterSegmentType.FIELD_BREAK)
        self.assertEqual(rows[0].cycle_number, 3)

        first_work = next(
            row for row in rows
            if row.segment_type == RosterSegmentType.WORK
        )

        self.assertEqual(first_work.cycle_number, 4)

    # -- Penyambungan -------------------------------------------------

    def test_start_sequence_continues_instead_of_restarting(self):
        rows = self.rows(start_sequence=27)

        self.assertEqual(rows[0].sequence, 27)
        self.assertEqual(rows[1].sequence, 28)

    def test_start_with_rotates_the_block_list(self):
        rows = self.rows(start_with=RosterSegmentType.TRAVEL_IN)

        self.assertEqual(
            [row.segment_type for row in rows[:3]],
            [
                RosterSegmentType.TRAVEL_IN,
                RosterSegmentType.WORK,
                RosterSegmentType.TRAVEL_OUT,
            ],
        )

    # -- Go-live ------------------------------------------------------

    def test_skip_before_drops_only_fully_past_segments(self):
        """
        Kasus D: pegawai yang sedang di tengah blok kerja saat sistem
        dipasang mendapat **sisa** blok itu, bukan kehilangan seluruhnya.
        """
        rows = self.rows(
            cycle_start=date(2026, 6, 1),
            skip_before=date(2026, 7, 1),
        )

        self.assertTrue(rows)

        first = rows[0]

        self.assertLess(first.start_date, date(2026, 7, 1))
        self.assertGreaterEqual(first.end_date, date(2026, 7, 1))

    def test_skip_before_keeps_sequence_numbering_dense(self):
        rows = self.rows(
            cycle_start=date(2025, 1, 1),
            skip_before=date(2026, 7, 1),
        )

        self.assertEqual(
            [row.sequence for row in rows],
            list(range(1, len(rows) + 1)),
        )

    # -- Pagar --------------------------------------------------------

    def test_invalid_pattern_yields_nothing(self):
        self.assertEqual(
            self.rows(pattern=CyclePattern(work_days=0, off_days=14)),
            [],
        )

    def test_segment_cap_is_enforced(self):
        rows = RosterCalculationService.build_segments(
            cycle_start=date(2026, 1, 1),
            pattern=CyclePattern(work_days=1, off_days=1),
            horizon_end=date(2036, 1, 1),
        )

        self.assertEqual(len(rows), MAX_SEGMENTS_PER_PLAN)


class HorizonTests(SimpleTestCase):
    def test_default_horizon(self):
        self.assertEqual(
            RosterCalculationService.resolve_horizon(
                start=date(2026, 1, 15),
            ),
            add_months(date(2026, 1, 15), DEFAULT_HORIZON_MONTHS),
        )

    def test_months_are_capped(self):
        self.assertEqual(
            RosterCalculationService.resolve_horizon(
                start=date(2026, 1, 1),
                months=120,
            ),
            add_months(date(2026, 1, 1), MAX_HORIZON_MONTHS),
        )

    def test_explicit_until_is_capped_too(self):
        """
        Batas dipagari **di kalkulator**, bukan di pemanggil: generator
        tidak boleh bisa diminta membuat roster tak hingga dari mana
        pun, termasuk dari query param yang salah ketik.
        """
        self.assertEqual(
            RosterCalculationService.resolve_horizon(
                start=date(2026, 1, 1),
                until=date(2050, 1, 1),
            ),
            add_months(date(2026, 1, 1), MAX_HORIZON_MONTHS),
        )

    def test_zero_months_falls_back_to_one(self):
        self.assertEqual(
            RosterCalculationService.resolve_horizon(
                start=date(2026, 1, 1),
                months=0,
            ),
            add_months(date(2026, 1, 1), DEFAULT_HORIZON_MONTHS),
        )


class AddMonthsTests(SimpleTestCase):
    def test_end_of_month_is_clamped_not_overflowed(self):
        self.assertEqual(
            add_months(date(2026, 1, 31), 1),
            date(2026, 2, 28),
        )

    def test_leap_year(self):
        self.assertEqual(
            add_months(date(2028, 1, 31), 1),
            date(2028, 2, 29),
        )

    def test_crossing_december(self):
        self.assertEqual(
            add_months(date(2026, 12, 15), 1),
            date(2027, 1, 15),
        )


class AnchorHelperTests(SimpleTestCase):
    """
    Kasus B: satu policy, jangkar berbeda per pegawai. Dua helper ini
    yang menerjemahkan jangkar itu jadi titik mulai jadwal.
    """

    def test_current_block_start_walks_backwards(self):
        self.assertEqual(
            RosterCalculationService.current_block_start(
                anchor=date(2026, 1, 1),
                cycle_length=58,
                as_of=date(2026, 4, 1),
            ),
            # 90 hari berlalu → satu putaran penuh (58) sudah lewat.
            date(2026, 2, 28),
        )

    def test_current_block_start_before_anchor_returns_anchor(self):
        self.assertEqual(
            RosterCalculationService.current_block_start(
                anchor=date(2026, 8, 1),
                cycle_length=58,
                as_of=date(2026, 1, 1),
            ),
            date(2026, 8, 1),
        )

    def test_next_cycle_start_rounds_up(self):
        self.assertEqual(
            RosterCalculationService.next_cycle_start(
                anchor=date(2026, 1, 1),
                cycle_length=58,
                on_or_after=date(2026, 2, 1),
            ),
            date(2026, 2, 28),
        )

    def test_next_cycle_start_on_exact_boundary_stays(self):
        self.assertEqual(
            RosterCalculationService.next_cycle_start(
                anchor=date(2026, 1, 1),
                cycle_length=58,
                on_or_after=date(2026, 2, 28),
            ),
            date(2026, 2, 28),
        )

    def test_cycles_until_rounds_up(self):
        self.assertEqual(
            RosterCalculationService.cycles_until(
                start_date=date(2026, 1, 1),
                until=date(2026, 12, 31),
                cycle_length=58,
            ),
            7,
        )


class SummarizeTests(SimpleTestCase):
    def test_on_site_days_counts_travel_the_policy_calls_on_site(self):
        """
        `on_site_days` sengaja berbeda dari `work_days` — aturan #4
        dokumen klien menyebut perjalanan menuju site sudah dihitung On
        Site, dan menyatukan keduanya membuat aturan itu tidak bisa
        dilaporkan sama sekali.
        """
        pattern = CyclePattern(
            work_days=42,
            off_days=14,
            travel_out_days=1,
            travel_in_days=1,
            travel_in_counts_as_roster_day=True,
        )

        rows = RosterCalculationService.build_segments(
            cycle_start=date(2026, 1, 1),
            pattern=pattern,
            horizon_end=date(2026, 4, 30),
        )

        summary = RosterCalculationService.summarize(rows)

        self.assertGreater(summary["on_site_days"], summary["work_days"])

        travel_in = [
            row for row in rows
            if row.segment_type == RosterSegmentType.TRAVEL_IN
        ]

        self.assertEqual(
            summary["on_site_days"] - summary["work_days"],
            sum(row.total_days for row in travel_in),
        )

    def test_dates_are_iso_strings_so_the_summary_is_jsonable(self):
        """
        Rekapnya dibekukan ke `RosterPlanVersion.summary`, sebuah
        JSONField. `date` tidak bisa diserialisasi ke sana, dan dulu
        kegagalannya baru muncul saat commit — jauh dari layar preview
        yang memakai rekap yang sama.
        """
        import json

        rows = RosterCalculationService.build_segments(
            cycle_start=date(2026, 1, 1),
            pattern=SIX_TWO_TRAVEL,
            horizon_end=date(2026, 6, 30),
        )

        summary = RosterCalculationService.summarize(rows)

        self.assertEqual(summary["start_date"], "2026-01-01")

        json.dumps(summary)

    def test_empty_summary(self):
        summary = RosterCalculationService.summarize([])

        self.assertEqual(summary["segments"], 0)
        self.assertIsNone(summary["start_date"])
        self.assertIsNone(summary["end_date"])
