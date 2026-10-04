"""
Menerjemahkan Roster Policy + Current Cycle Start jadi deret segmen.

**Fungsi murni, tanpa satu pun query.** Itu bukan kerapian: bentuk
jadwal harus bisa ditunjukkan ke pengguna sebelum ada yang disimpan
(preview), dipakai ulang saat generate ulang dan saat menyambung
horizon, dan diperiksa lewat test tanpa menyiapkan tenant. Begitu
kalkulator ini menyentuh database, ketiganya hilang sekaligus.

Bentuk satu siklus
------------------
::

    [ WORK ][ TRAVEL_OUT ][ FIELD_BREAK ][ TRAVEL_IN ][ WORK ...

Empat segmen, dan urutannya mengikuti kenyataan: orang menyelesaikan
blok kerjanya, pulang, menjalani field break, lalu berangkat lagi.

Segmen travel **tidak dibuat** kalau harinya nol atau policy
mematikannya — pegawai lokal yang tidak perlu terbang menjalani
`WORK → FIELD_BREAK → WORK` tanpa satu pun cabang khusus di sini. Nol
hari menghasilkan nol baris; itu saja.

Hari travel bukan potongan blok kerja
-------------------------------------
Panjang satu putaran `work + off + travel_out + travel_in`, dan blok
kerja tetap sepanjang yang tertulis di policy. Pegawai 45/14 yang
menghabiskan dua hari di kapal tetap menjalani 45 hari di site;
memotongnya dari Work Days membuat angka di kontrak tidak cocok dengan
angka mana pun di sistem.

`counts_as_roster_day` karena itu hanya memengaruhi **rekap** hari
on-site — bukan panjang blok. Dua hal yang sangat mudah tertukar.

Batasnya tanggal, bukan jumlah siklus
-------------------------------------
`horizon_end` yang menghentikan deret, bukan `cycle_count`. Itu yang
membuat rolling horizon jadi satu parameter alih-alih hitungan manual
yang harus ditebak ulang setiap kali polanya berubah.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta

from apps.hr.models.rotation import RosterSegmentType


# Pagar kewarasan, dua-duanya. Horizon 24 bulan sudah jauh melewati
# perencanaan yang masuk akal, dan 400 segmen kira-kira 8 tahun untuk
# pola terpendek — di atas itu hampir pasti salah ketik, dan barisnya
# tidak akan pernah dibaca siapa pun.
MAX_HORIZON_MONTHS = 24
MAX_SEGMENTS_PER_PLAN = 400

DEFAULT_HORIZON_MONTHS = 12


TRAVEL_SEGMENTS = frozenset(
    {RosterSegmentType.TRAVEL_OUT, RosterSegmentType.TRAVEL_IN},
)


@dataclass(frozen=True)
class SegmentRow:
    """Satu baris jadwal, belum tersimpan."""

    sequence: int
    segment_type: str
    start_date: date
    end_date: date
    total_days: int
    counts_as_roster_day: bool
    cycle_number: int

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CyclePattern:
    """
    Pola yang membentuk jadwal, dibekukan dari policy.

    Dipisah dari model supaya kalkulator tidak pernah menyentuh
    database — preview memakai angka yang belum tersimpan, generate
    ulang memakai angka yang sudah dibekukan ke dokumen, dan keduanya
    lewat jalan yang sama.
    """

    work_days: int
    off_days: int
    travel_out_days: int = 0
    travel_in_days: int = 0
    travel_creates_segment: bool = True
    travel_out_counts_as_roster_day: bool = False
    travel_in_counts_as_roster_day: bool = False
    roster_start_basis: str = "work_start"

    @property
    def is_valid(self) -> bool:
        return bool(self.work_days and self.off_days)

    @property
    def cycle_length(self) -> int:
        """Panjang satu putaran penuh dalam hari kalender."""
        if not self.is_valid:
            return 0

        return (
            self.work_days
            + self.off_days
            + (self.travel_out_days or 0)
            + (self.travel_in_days or 0)
        )

    @classmethod
    def from_policy(cls, policy, *, travel_days=None) -> "CyclePattern":
        """
        Pola dari master, dengan hari perjalanan yang boleh ditimpa.

        `travel_days` adalah hasil `RosterPolicyResolver.travel_days_for()`
        — hari perjalanan ditentukan **jarak** (site, Point of Hire),
        bukan pola, jadi dua pegawai dengan policy yang sama bisa
        berbeda di sini. Dikosongkan = pakai bawaan policy.
        """
        return cls(
            work_days=policy.cycle_work_days or 0,
            off_days=policy.cycle_off_days or 0,
            travel_out_days=(
                travel_days.out_days
                if travel_days is not None
                else policy.default_travel_out_days
            ),
            travel_in_days=(
                travel_days.in_days
                if travel_days is not None
                else policy.default_travel_in_days
            ),
            travel_creates_segment=policy.travel_creates_segment,
            travel_out_counts_as_roster_day=(
                policy.travel_out_counts_as_roster_day
            ),
            travel_in_counts_as_roster_day=(
                policy.travel_in_counts_as_roster_day
            ),
            roster_start_basis=policy.roster_start_basis,
        )


def add_months(anchor: date, months: int) -> date:
    """
    Geser tanggal sekian bulan, tanpa dateutil.

    31 Januari + 1 bulan = 28/29 Februari — dipotong ke hari terakhir
    bulan tujuan, bukan melimpah ke Maret.
    """
    if not months:
        return anchor

    total = anchor.month - 1 + months

    year = anchor.year + total // 12
    month = total % 12 + 1

    # Hari terakhir bulan tujuan: hari pertama bulan berikutnya, mundur
    # satu hari.
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)

    return date(year, month, min(anchor.day, last_day.day))


class RosterCalculationService:
    """
    Seluruh rumus jadwal roster, dan tidak ada satu pun di tempat lain.

    Aturannya keras: kalau sebuah angka bisa dihitung dari pola dan
    tanggal, ia dihitung di sini. Service yang menyimpan, view yang
    menyajikan, frontend yang menampilkan — tidak satu pun boleh
    menghitung ulang, karena dua tempat yang menghitung hal yang sama
    cepat atau lambat menjawab berbeda.
    """

    # ------------------------------------------------------------------
    # Normalisasi jangkar
    # ------------------------------------------------------------------

    @staticmethod
    def work_block_start(
        *,
        cycle_start: date,
        pattern: CyclePattern,
    ) -> date:
        """
        Tanggal yang diketik HR → hari pertama blok kerja.

        Ketiga basis menghasilkan tanggal yang berbeda dari input yang
        sama, dan itu justru alasannya jadi kolom: tanpa disebut, satu
        angka "1 Agustus" bisa berarti tiga jadwal berbeda.

        * ``work_start``       — 1 Agustus adalah hari pertama kerja
        * ``site_arrival``     — 1 Agustus adalah hari tiba di site;
          hari itu masih hari terakhir perjalanan, jadi blok kerjanya
          mulai 2 Agustus. Kalau perjalanannya nol hari, tidak ada yang
          bisa "tiba", dan tanggal itu langsung jadi hari kerja
        * ``travel_departure`` — 1 Agustus adalah hari berangkat dari
          Point of Hire; blok kerja mulai setelah perjalanannya habis
        """
        basis = pattern.roster_start_basis
        travel_in = pattern.travel_in_days or 0

        if basis == "travel_departure":
            return cycle_start + timedelta(days=travel_in)

        if basis == "site_arrival" and travel_in:
            return cycle_start + timedelta(days=1)

        return cycle_start

    @staticmethod
    def resolve_horizon(
        *,
        start: date,
        months: int | None = None,
        until: date | None = None,
    ) -> date:
        """
        Sampai kapan jadwal digenerate.

        Dipagari `MAX_HORIZON_MONTHS` di sini, bukan di pemanggil:
        generator tidak boleh bisa diminta membuat roster tak hingga
        dari mana pun, termasuk dari query param yang salah ketik.
        """
        if until is not None:
            ceiling = add_months(start, MAX_HORIZON_MONTHS)

            return min(until, ceiling)

        months = months or DEFAULT_HORIZON_MONTHS
        months = max(1, min(int(months), MAX_HORIZON_MONTHS))

        return add_months(start, months)

    # ------------------------------------------------------------------
    # Deret segmen
    # ------------------------------------------------------------------

    @classmethod
    def build_segments(
        cls,
        *,
        cycle_start: date,
        pattern: CyclePattern,
        horizon_end: date,
        start_sequence: int = 1,
        start_with: str = RosterSegmentType.WORK,
        cycle_number_start: int = 1,
        skip_before: date | None = None,
    ) -> list[SegmentRow]:
        """
        Deret segmen dari jangkar sampai `horizon_end`.

        `start_with` dan `start_sequence` dipakai saat **menyambung**
        jadwal yang sudah ada: sambungan bisa jatuh di field break, dan
        nomor urutnya harus melanjutkan, bukan mengulang dari 1. Tanpa
        keduanya, satu-satunya cara memperpanjang jadwal adalah
        membangun ulang seluruhnya — dan itu menghapus setiap
        penyesuaian lapangan yang sudah dibuat.

        `skip_before` membuang segmen yang seluruhnya jatuh sebelum
        tanggal itu. Dipakai saat go-live: jadwal berangkat dari blok
        yang sedang dijalani orangnya, dan sistem tidak berpura-pura
        tahu apa yang terjadi tahun lalu.
        """
        if not pattern.is_valid or not cycle_start or not horizon_end:
            return []

        blocks = cls._cycle_blocks(pattern)

        if not blocks:
            return []

        # Jangkar diartikan menurut basisnya, lalu seluruh perhitungan
        # di bawah memakai satu angka yang sudah pasti.
        cursor = (
            cls.work_block_start(cycle_start=cycle_start, pattern=pattern)
            if start_with == RosterSegmentType.WORK
            else cycle_start
        )

        # Menyambung dari tengah siklus: putar daftar bloknya supaya
        # dimulai dari jenis yang diminta.
        offset = next(
            (
                index
                for index, (segment_type, _, _) in enumerate(blocks)
                if segment_type == start_with
            ),
            0,
        )

        ordered = blocks[offset:] + blocks[:offset]

        rows: list[SegmentRow] = []

        sequence = max(1, int(start_sequence)) - 1
        cycle_number = max(1, int(cycle_number_start))

        index = 0

        while cursor <= horizon_end and len(rows) < MAX_SEGMENTS_PER_PLAN:
            segment_type, length, counts = ordered[index % len(ordered)]

            # Putaran baru dimulai saat blok **kerja** dibuka, bukan
            # saat daftar blok habis. Bedanya kelihatan begitu jadwal
            # disambung dari tengah siklus: kalau dihitung dari
            # habisnya daftar, blok kerja yang membuka putaran kedua
            # masih bernomor 1 dan travel sesudahnya yang bernomor 2 —
            # nomor putaran jadi menempel di baris yang salah.
            if segment_type == RosterSegmentType.WORK and index:
                cycle_number += 1

            end = cursor + timedelta(days=length - 1)

            if skip_before is None or end >= skip_before:
                sequence += 1

                rows.append(
                    SegmentRow(
                        sequence=sequence,
                        segment_type=segment_type,
                        start_date=cursor,
                        end_date=end,
                        total_days=length,
                        counts_as_roster_day=counts,
                        cycle_number=cycle_number,
                    ),
                )

            cursor = end + timedelta(days=1)

            index += 1

        return rows

    @staticmethod
    def _cycle_blocks(pattern: CyclePattern) -> list[tuple[str, int, bool]]:
        """
        Satu putaran sebagai daftar `(jenis, hari, hitung_on_site)`.

        Segmen travel dilewati kalau harinya nol atau policy
        mematikannya — itu satu-satunya perlakuan khusus untuk pegawai
        lokal, dan bentuknya "tidak ada baris", bukan cabang `if` di
        sepanjang generator.
        """
        blocks: list[tuple[str, int, bool]] = [
            (RosterSegmentType.WORK, pattern.work_days, True),
        ]

        emit_travel = pattern.travel_creates_segment

        if emit_travel and pattern.travel_out_days:
            blocks.append(
                (
                    RosterSegmentType.TRAVEL_OUT,
                    pattern.travel_out_days,
                    pattern.travel_out_counts_as_roster_day,
                ),
            )

        blocks.append(
            (RosterSegmentType.FIELD_BREAK, pattern.off_days, False),
        )

        if emit_travel and pattern.travel_in_days:
            blocks.append(
                (
                    RosterSegmentType.TRAVEL_IN,
                    pattern.travel_in_days,
                    pattern.travel_in_counts_as_roster_day,
                ),
            )

        return blocks

    # ------------------------------------------------------------------
    # Rekap
    # ------------------------------------------------------------------

    @staticmethod
    def summarize(rows: list[SegmentRow]) -> dict:
        """
        Rekap satu deret. Dipakai layar preview dan laporan.

        `on_site_days` sengaja berbeda dari `work_days`: yang pertama
        ikut menghitung hari travel yang policy-nya menyatakan on-site,
        yang kedua murni blok kerja. Menyatukan keduanya membuat aturan
        #4 dokumen klien tidak bisa dilaporkan sama sekali.

        Tanggalnya dikembalikan sebagai **string ISO**, bukan `date`.
        Rekap ini dibekukan ke `RosterPlanVersion.summary` yang sebuah
        JSONField, dan `date` tidak bisa diserialisasi ke sana — dulu
        kegagalannya baru muncul saat commit, jauh dari layar preview
        yang memakai rekap yang sama.
        """
        def total(*types) -> int:
            return sum(
                row.total_days
                for row in rows
                if row.segment_type in types
            )

        return {
            "cycles": len(
                {row.cycle_number for row in rows},
            ),
            "segments": len(rows),
            "work_days": total(RosterSegmentType.WORK),
            "field_break_days": total(RosterSegmentType.FIELD_BREAK),
            "travel_days": total(
                RosterSegmentType.TRAVEL_OUT,
                RosterSegmentType.TRAVEL_IN,
            ),
            "on_site_days": sum(
                row.total_days
                for row in rows
                if row.counts_as_roster_day
            ),
            "start_date": (
                rows[0].start_date.isoformat() if rows else None
            ),
            "end_date": (
                max(row.end_date for row in rows).isoformat()
                if rows
                else None
            ),
        }

    # ------------------------------------------------------------------
    # Bantuan
    # ------------------------------------------------------------------

    @staticmethod
    def cycles_until(
        *,
        start_date: date,
        until: date,
        cycle_length: int,
    ) -> int:
        """
        Berapa putaran dibutuhkan supaya jadwal menutupi sampai `until`.

        Dipakai supaya pengguna tidak perlu menghitung sendiri: "sampai
        Desember 2027" jauh lebih bisa dijawab daripada "berapa siklus",
        dan menebak angkanya adalah cara paling umum jadwal jadi terlalu
        pendek tanpa ada yang sadar.
        """
        if not start_date or not until or not cycle_length:
            return 1

        span = (until - start_date).days + 1

        if span <= 0:
            return 1

        # Pembulatan ke atas: separuh putaran tetap butuh satu putaran
        # penuh untuk menutupinya.
        return max(1, -(-span // cycle_length))

    @staticmethod
    def next_cycle_start(
        *,
        anchor: date,
        cycle_length: int,
        on_or_after: date,
    ) -> date:
        """
        Menggeser jangkar maju ke awal putaran pertama yang jatuh pada
        atau setelah `on_or_after`.

        `cycle_length` **wajib** sudah memuat hari travel dua arah —
        diberi `work + off` saja, jangkarnya meleset sebanyak hari
        travel setiap putaran, dan melesetnya menumpuk sepanjang tahun.
        """
        if not anchor or not cycle_length:
            return on_or_after

        delta = (on_or_after - anchor).days

        if delta <= 0:
            return anchor

        # Pembulatan ke atas: kalau `on_or_after` persis di awal
        # putaran, tanggal itu sendiri yang dipakai.
        cycles = -(-delta // cycle_length)

        return anchor + timedelta(days=cycles * cycle_length)

    @staticmethod
    def current_block_start(
        *,
        anchor: date,
        cycle_length: int,
        as_of: date,
    ) -> date:
        """
        Awal putaran yang sedang **dijalani** pada `as_of`.

        Kebalikan `next_cycle_start`, dan ini yang dipakai saat go-live:
        pegawai yang sudah di tengah blok kerja saat sistem dipasang
        harus mendapat jadwal yang berangkat dari blok itu, bukan dari
        blok berikutnya. Menggesernya ke depan akan menghilangkan sisa
        hari yang justru sedang dijalaninya.
        """
        if not anchor or not cycle_length:
            return as_of

        delta = (as_of - anchor).days

        if delta <= 0:
            return anchor

        return anchor + timedelta(
            days=(delta // cycle_length) * cycle_length,
        )
