from __future__ import annotations

from datetime import date, timedelta

from apps.hr.models import RotationPeriodType


# Pagar kewarasan. Satu siklus 6/2 minggu = 56 hari, jadi 24 siklus
# sudah lebih dari tiga tahun ke depan — di atas itu hampir pasti salah
# ketik, dan barisnya tidak akan pernah dipakai.
MAX_CYCLE_COUNT = 24


class RotationPeriodGenerator:
    """
    Menerjemahkan pola siklus + tanggal mulai jadi deret baris ON/OFF.

    Sengaja fungsi murni tanpa sentuhan database: bentuk barisnya bisa
    ditunjukkan ke pengguna sebelum disimpan (preview), dipakai ulang
    saat generate ulang, dan diperiksa tanpa menyiapkan tenant.

    Perhitungannya memakai tanggal aktual, bukan modulo seperti
    `LeaveDayCalculator` — di sini yang dihasilkan memang baris yang
    boleh disunting tangan, jadi rumusnya berhenti begitu barisnya jadi.

    Bentuk satu siklus
    ------------------
    ::

        [ WORK work_days ][ out ][ OFF off_days ][ in ][ WORK ...

    `travel_days` adalah **total pulang-pergi**, bukan sekali jalan —
    itu yang dimaksud kolom "Waktu Perjalanan" di dokumen klien. Angka 2
    berarti sehari keluar dan sehari kembali, bukan dua hari
    masing-masing.

    Angka ganjil dipecah tidak rata, dan **kelebihannya jatuh ke sisi
    keluar**: 3 → 2 keluar, 1 kembali. Alasannya aturan #4 dokumen
    "Substansi Roster" — perjalanan Sorong/Ternate ke site sudah
    dihitung On Site, jadi sisi kembali memang lebih pendek sebagai
    hari perjalanan murni.

    Hari travel adalah hari kalender tersendiri: tidak dihitung sebagai
    hari kerja, tidak pula sebagai hari off. Itu sebabnya blok berikutnya
    "meloncat" melewatinya, bukan menempel rapat ke blok sebelumnya.

    Jendela travel di antara dua blok **tidak** dibuatkan baris di
    sini. Tanggal penerbangan adalah hal yang diajukan dan disetujui,
    dan tempatnya `TravelArrangement` di dalam Travel Request.
    Generator cuma menyisakan hari kalendernya; `RotationPeriod`
    menghitung jendelanya sebagai properti untuk ditampilkan.
    """

    @staticmethod
    def build(
        *,
        start_date: date,
        work_days: int,
        off_days: int,
        cycle_count: int,
        travel_days: int = 0,
        start_with: str = RotationPeriodType.WORK,
        start_sequence: int = 1,
    ) -> list[dict]:
        """
        Deret baris ON/OFF mulai dari `start_date`.

        `start_with` dan `start_sequence` dipakai saat **menyambung**
        jadwal yang sudah ada: sambungan bisa jatuh di blok off (kalau
        baris terakhir blok kerja) dan nomor urutnya harus melanjutkan,
        bukan mengulang dari 1. Tanpa dua parameter itu, satu-satunya
        cara menambah siklus adalah membangun ulang seluruh dokumen —
        dan itu menghapus setiap penyesuaian lapangan yang sudah dibuat.
        """
        if not start_date or not work_days or not off_days:
            return []

        cycle_count = max(1, min(int(cycle_count or 1), MAX_CYCLE_COUNT))

        travel_days = max(0, int(travel_days or 0))

        # Total pulang-pergi dipecah jadi dua jendela. Ganjil condong
        # ke sisi keluar — lihat docstring.
        travel_out = -(-travel_days // 2)
        travel_in = travel_days // 2

        blocks = [
            (RotationPeriodType.WORK, work_days, travel_out),
            (RotationPeriodType.OFF, off_days, travel_in),
        ]

        # Menyambung dari blok kerja berarti giliran berikutnya blok
        # off, jadi urutan pasangannya dibalik.
        if start_with == RotationPeriodType.OFF:
            blocks.reverse()

        rows: list[dict] = []

        cursor = start_date
        sequence = max(1, int(start_sequence)) - 1

        for _ in range(cycle_count):
            for period_type, length, trailing_travel in blocks:
                sequence += 1

                end = cursor + timedelta(days=length - 1)

                rows.append(
                    {
                        "sequence": sequence,
                        "period_type": period_type,
                        "start_date": cursor,
                        "end_date": end,
                        # Hari travel tidak ikut dihitung — blok kerja
                        # 45 hari tetap 45 hari walau perjalanannya dua
                        # hari.
                        "total_days": length,
                    },
                )

                # Di sinilah loncatannya: kursor melewati blok yang baru
                # ditutup **dan** jendela travel yang mengekorinya.
                cursor = end + timedelta(days=1 + trailing_travel)

        return rows

    @staticmethod
    def cycles_until(
        *,
        start_date: date,
        until: date,
        cycle_length: int,
    ) -> int:
        """
        Berapa siklus dibutuhkan supaya jadwal menutupi sampai `until`.

        Dipakai supaya pengguna tidak perlu menghitung sendiri.
        "Sampai Desember 2027" jauh lebih bisa dijawab daripada
        "berapa siklus" — dan menebak angkanya adalah cara paling umum
        jadwal jadi terlalu pendek tanpa ada yang sadar.
        """
        if not start_date or not until or not cycle_length:
            return 1

        span = (until - start_date).days + 1

        if span <= 0:
            return 1

        # Pembulatan ke atas: separuh siklus tetap butuh satu siklus
        # penuh untuk menutupinya.
        return max(1, min(-(-span // cycle_length), MAX_CYCLE_COUNT))

    @staticmethod
    def summarize(rows: list[dict]) -> dict:
        """
        Rekap satu deret hasil `build()`.

        Dipakai untuk validasi dan laporan: jumlah hari kerja, hari off,
        hari travel, dan berapa siklus yang benar-benar terbentuk.
        """
        work_days = sum(
            row["total_days"]
            for row in rows
            if row["period_type"] == RotationPeriodType.WORK
        )

        off_days = sum(
            row["total_days"]
            for row in rows
            if row["period_type"] == RotationPeriodType.OFF
        )

        return {
            "cycles": len(
                [
                    row
                    for row in rows
                    if row["period_type"] == RotationPeriodType.WORK
                ],
            ),
            "work_days": work_days,
            "off_days": off_days,
            "start_date": rows[0]["start_date"] if rows else None,
            "end_date": rows[-1]["end_date"] if rows else None,
        }

    @staticmethod
    def next_cycle_start(
        *,
        anchor: date,
        cycle_length: int,
        on_or_after: date,
    ) -> date:
        """
        Menggeser jangkar milik crew maju ke awal siklus pertama yang
        jatuh pada atau setelah `on_or_after`.

        Dipakai sebagai nilai awal `start_date` dokumen baru. Tanpa ini,
        memilih crew akan mengisi tanggal mulai dengan jangkar aslinya —
        yang bisa jadi tahun lalu, dan seluruh roster yang digenerate
        jadi jadwal masa lampau.

        `cycle_length` harus sudah memasukkan hari travel dua arah.
        `SiteRotation.cycle_length` sudah menghitungnya begitu.
        """
        if not anchor or not cycle_length:
            return on_or_after

        delta = (on_or_after - anchor).days

        if delta <= 0:
            return anchor

        # Pembulatan ke atas: kalau `on_or_after` persis di awal siklus,
        # tanggal itu sendiri yang dipakai.
        cycles = -(-delta // cycle_length)

        return anchor + timedelta(days=cycles * cycle_length)
