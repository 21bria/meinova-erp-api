"""
Menghitung ulang jadwal dari satu titik ke depan.

Satu operasi, dan seluruh Adjustment memakainya
-----------------------------------------------
Perpanjangan blok kerja, kepulangan lebih awal, penggeseran jadwal,
pemakaian rotation credit — keempatnya berujung pada hal yang sama:
*"mulai tanggal X, jadwalnya jadi begini; sebelum X jangan disentuh"*.
Menulis empat jalur berbeda untuk itu berarti empat kesempatan berbeda
untuk menghitungnya salah.

Tiga jaminan yang ditegakkan di sini, bukan diserahkan ke pemanggil
-------------------------------------------------------------------
1. **Masa lalu tidak pernah disentuh.** Baris yang berakhir sebelum
   `effective_date` tidak di-UPDATE, tidak ditutup, tidak disalin. Ia
   dimiliki bersama oleh versi lama dan versi baru — dan itulah yang
   membuat `TravelRequest.rotation_period` yang menunjuknya tetap sah
   setelah lima kali penyesuaian.
2. **Tidak ada silent edit.** Baris yang berubah **ditutup**
   (`version_to` diisi) lalu diganti baris baru milik versi berikutnya.
   Tanggal sebuah `RotationPeriod` tidak pernah di-UPDATE di berkas ini.
3. **Baris terkunci menolak.** Blok yang sudah dijalani tidak bisa
   dihitung ulang, dan penolakannya menyebut baris mana.

Nomor urut tidak pernah dipakai ulang
-------------------------------------
`uniq_active_hr_rotation_period_sequence` berlaku untuk seluruh baris
sebuah rencana, termasuk yang sudah ditutup. Jadi baris pengganti
mendapat nomor **berikutnya** dari yang tertinggi, bukan nomor yang
sama dengan yang digantikannya. Konsekuensinya nomor urut berlubang di
versi berjalan — dan itu benar: urutan tampilan ditentukan tanggal
(`Meta.ordering`), sedangkan nomor urut cuma identitas baris.
"""

from __future__ import annotations

import logging

from dataclasses import replace
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.hr.api.roster.calculation import (
    RosterCalculationService,
    SegmentRow,
)
from apps.hr.api.roster.services import RosterGenerationService
from apps.hr.models import (
    RosterSegmentType,
    RosterVersionSource,
    RotationPeriod,
    SiteRotation,
)


logger = logging.getLogger(__name__)


class RosterRecalculationService:
    """Perhitungan ulang berversi. Satu pintu untuk seluruh Adjustment."""

    # ------------------------------------------------------------------
    # Operasi inti
    # ------------------------------------------------------------------

    @classmethod
    def compute(
        cls,
        *,
        plan: SiteRotation,
        effective_date: date,
        head_segments: list[SegmentRow] | None = None,
        tail_anchor: date | None = None,
        tail_start_with: str | None = None,
        tail_cycle_number: int | None = None,
        horizon_end: date | None = None,
    ) -> dict:
        """
        Menghitung jadwal pengganti **tanpa menulis apa pun**.

        Dipakai dua kali: sekali oleh layar preview, sekali oleh
        `recalculate()` yang menyimpannya. Satu perhitungan, bukan dua —
        kalau berbeda, orang menyetujui satu jadwal dan mendapat jadwal
        yang lain.
        """
        current = list(
            RotationPeriod.objects
            .filter(
                rotation=plan,
                is_deleted=False,
                version_to__isnull=True,
            )
            .order_by("start_date", "sequence")
        )

        cls.assert_recalculable(
            segments=current,
            effective_date=effective_date,
        )

        kept = [
            row for row in current
            if row.end_date < effective_date
        ]

        superseded = [
            row for row in current
            if row.end_date >= effective_date
        ]

        pattern = RosterGenerationService.pattern_from_plan(plan)

        if not pattern.is_valid:
            raise ValidationError(
                {
                    "roster": (
                        "Pola siklus yang dibekukan ke rencana ini tidak "
                        "lengkap (Work Days / Field Break Days kosong)."
                    ),
                },
            )

        head = list(head_segments or [])

        if not head:
            head = cls.truncate_straddling(
                superseded=superseded,
                effective_date=effective_date,
            )

        anchor, start_with, cycle_number = cls.resolve_tail_start(
            kept=kept,
            head=head,
            effective_date=effective_date,
            pattern=pattern,
            tail_anchor=tail_anchor,
            tail_start_with=tail_start_with,
            tail_cycle_number=tail_cycle_number,
        )

        horizon = horizon_end or plan.horizon_end or (
            RosterCalculationService.resolve_horizon(
                start=effective_date,
                months=(
                    plan.roster_policy.rolling_horizon_months
                    if plan.roster_policy_id
                    else None
                ),
            )
        )

        # Jangkar di sini adalah tanggal blok kerja yang **sebenarnya**,
        # sudah diturunkan dari jadwal yang bertahan — bukan tanggal yang
        # diketik HR. Karena itu basisnya dinetralkan: menafsirkannya
        # ulang akan menggeser jadwal sebanyak hari travel setiap kali
        # ada penyesuaian.
        literal = replace(pattern, roster_start_basis="work_start")

        next_sequence = cls.next_sequence(plan)

        tail = RosterCalculationService.build_segments(
            cycle_start=anchor,
            pattern=literal,
            horizon_end=horizon,
            start_sequence=next_sequence + len(head),
            start_with=start_with,
            cycle_number_start=cycle_number,
        )

        segments = cls.renumber(head, start=next_sequence) + tail

        if not segments and not kept:
            raise ValidationError(
                {
                    "roster": (
                        "Perhitungan ulang tidak menghasilkan satu pun "
                        "segmen. Periksa Effective Date terhadap horizon "
                        "rencana."
                    ),
                },
            )

        return {
            "kept": kept,
            "superseded": superseded,
            "segments": segments,
            "pattern": pattern,
            "horizon_end": horizon,
        }

    @classmethod
    def simulate(cls, **kwargs) -> dict:
        """
        Bentuk `compute()` yang siap dikirim ke layar: jadwal sekarang,
        jadwal sesudahnya, dan selisih per baris.
        """
        result = cls.compute(**kwargs)

        before = {
            (row.cycle_number, row.segment_type): row
            for row in result["superseded"]
        }

        rows = []

        for row in result["segments"]:
            origin = before.get((row.cycle_number, row.segment_type))

            rows.append(
                {
                    **row.as_dict(),
                    "previous_start_date": (
                        origin.start_date if origin else None
                    ),
                    "previous_end_date": (
                        origin.end_date if origin else None
                    ),
                    "shift_days": (
                        (row.start_date - origin.start_date).days
                        if origin
                        else None
                    ),
                },
            )

        return {
            "replaced_segments": len(result["superseded"]),
            "kept_segments": len(result["kept"]),
            "horizon_end": result["horizon_end"],
            "segments": rows,
            "summary": RosterCalculationService.summarize(
                result["segments"],
            ),
        }

    @classmethod
    @transaction.atomic
    def recalculate(
        cls,
        *,
        plan: SiteRotation,
        effective_date: date,
        source: str = RosterVersionSource.ADJUSTMENT,
        reason: str,
        head_segments: list[SegmentRow] | None = None,
        tail_anchor: date | None = None,
        tail_start_with: str | None = None,
        tail_cycle_number: int | None = None,
        horizon_end: date | None = None,
        reference_type: str = "",
        reference_id="",
        user=None,
    ):
        """
        Menutup jadwal mulai `effective_date`, lalu menyusun ulang ke
        depan.

        `head_segments` adalah baris yang **ditulis apa adanya** sebelum
        deret pola dilanjutkan — di situlah perpanjangan blok atau
        kepulangan lebih awal diletakkan. Dikosongkan berarti blok yang
        sedang berjalan cukup dipotong di `effective_date - 1`, dan
        deretnya dimulai kembali dari blok berikutnya.

        Mengembalikan `(version, rows)`.
        """
        plan = (
            SiteRotation.objects
            # `of=("self",)` wajib: `roster_policy` dan `current_version`
            # nullable, jadi `select_related` merakit LEFT JOIN dan
            # PostgreSQL menolak FOR UPDATE di sisi nullable-nya. Yang
            # perlu dikunci memang cuma baris rencananya.
            .select_for_update(of=("self",))
            .select_related("roster_policy", "current_version")
            .get(pk=plan.pk)
        )

        previous = plan.current_version

        if previous is None:
            raise ValidationError(
                {
                    "roster": (
                        "Rencana ini belum punya versi apa pun, jadi "
                        "tidak ada yang bisa dihitung ulang."
                    ),
                },
            )

        result = cls.compute(
            plan=plan,
            effective_date=effective_date,
            head_segments=head_segments,
            tail_anchor=tail_anchor,
            tail_start_with=tail_start_with,
            tail_cycle_number=tail_cycle_number,
            horizon_end=horizon_end,
        )

        superseded = result["superseded"]
        segments = result["segments"]

        version = RosterGenerationService.new_version(
            plan=plan,
            source=source,
            effective_from=effective_date,
            reason=reason,
            summary=RosterCalculationService.summarize(segments),
            reference_type=reference_type,
            reference_id=reference_id,
            user=user,
        )

        # Menutup, bukan menghapus: baris yang digantikan tetap terbaca
        # dari versi lama, dan itu yang membuat "jadwal yang disetujui"
        # masih bisa ditunjukkan setelah penyesuaian.
        if superseded:
            RotationPeriod.objects.filter(
                pk__in=[row.pk for row in superseded],
            ).update(
                version_to=previous,
                updated_at=timezone.now(),
            )

        rows = RosterGenerationService.write_segments(
            plan=plan,
            version=version,
            segments=segments,
            user=user,
        )

        cls.carry_planned_dates(
            new_rows=rows,
            replaced=superseded,
        )

        cls.repoint_travel_requests(
            plan=plan,
            replaced=superseded,
            new_rows=rows,
        )

        # Roster yang dihitung ulang menggeser tanggal blok kerjanya,
        # jadi rencana shift ikut disusun ulang dari policy — bukan
        # dibiarkan menunjuk tanggal yang sudah tidak ada. Penyesuaian
        # manual tidak tersentuh; itu dijaga di dalam service-nya.
        from apps.hr.api.site_rotation.services import SiteRotationService

        SiteRotationService.sync_shift_baseline(plan, user=user)

        cls.sync_header(plan=plan, version=version)

        logger.info(
            "Roster %s dihitung ulang dari %s: %s baris ditutup, "
            "%s baris baru (versi %s).",
            plan.pk,
            effective_date,
            len(superseded),
            len(rows),
            version.version_no,
        )

        return version, rows

    # ------------------------------------------------------------------
    # Penjagaan
    # ------------------------------------------------------------------

    @staticmethod
    def assert_recalculable(*, segments, effective_date: date) -> None:
        """
        Menolak perhitungan ulang yang menyentuh baris terkunci.

        Pesannya menyebut baris mana yang menghalangi. "Ada segmen
        terkunci" tidak bisa ditindaklanjuti siapa pun — yang perlu
        diketahui adalah tanggal berapa batas amannya.
        """
        blocking = [
            row for row in segments
            if row.is_locked and row.end_date >= effective_date
        ]

        if not blocking:
            return

        earliest = min(row.start_date for row in blocking)

        raise ValidationError(
            {
                "effective_date": (
                    f"Tanggal berlaku {effective_date} jatuh di jadwal "
                    f"yang sudah dikunci ({len(blocking)} segmen, mulai "
                    f"{earliest}). Jadwal yang sudah dijalani tidak "
                    "dihitung ulang — pilih tanggal setelah "
                    f"{max(row.end_date for row in blocking)}."
                ),
            },
        )

    # ------------------------------------------------------------------
    # Menyusun potongan
    # ------------------------------------------------------------------

    @staticmethod
    def truncate_straddling(
        *,
        superseded: list[RotationPeriod],
        effective_date: date,
    ) -> list[SegmentRow]:
        """
        Blok yang sedang berjalan dipotong di `effective_date - 1`.

        Tanpa ini, penyesuaian yang jatuh di tengah blok kerja akan
        membuang seluruh blok itu — termasuk hari-hari yang sudah
        dijalani orangnya minggu lalu.
        """
        straddling = next(
            (
                row for row in superseded
                if row.start_date < effective_date <= row.end_date
            ),
            None,
        )

        if straddling is None:
            return []

        end = effective_date - timedelta(days=1)

        return [
            SegmentRow(
                sequence=0,  # diberi nomor oleh `renumber`
                segment_type=straddling.segment_type,
                start_date=straddling.start_date,
                end_date=end,
                total_days=(end - straddling.start_date).days + 1,
                counts_as_roster_day=straddling.counts_as_roster_day,
                cycle_number=straddling.cycle_number,
            ),
        ]

    @classmethod
    def resolve_tail_start(
        cls,
        *,
        kept,
        head,
        effective_date: date,
        pattern,
        tail_anchor=None,
        tail_start_with=None,
        tail_cycle_number=None,
    ) -> tuple[date, str, int]:
        """
        Dari mana deret pola dilanjutkan, dan dengan blok jenis apa.

        Jenisnya **wajib** yang mengekor blok terakhir yang bertahan.
        Kalau selalu dimulai dari blok kerja, jadwal yang dipotong di
        tengah field break akan punya dua blok kerja berturut-turut, dan
        pegawainya kehilangan sisa istirahatnya tanpa satu pun pesan.
        """
        last = None

        if head:
            last = head[-1]
        elif kept:
            last = kept[-1]

        anchor = tail_anchor

        if anchor is None:
            anchor = (
                last.end_date + timedelta(days=1)
                if last is not None
                else effective_date
            )

        start_with = tail_start_with

        if start_with is None:
            start_with = (
                cls.next_block_type(
                    after=last.segment_type,
                    pattern=pattern,
                )
                if last is not None
                else RosterSegmentType.WORK
            )

        cycle_number = tail_cycle_number

        if cycle_number is None:
            base = last.cycle_number if last is not None else 0

            # Putaran baru dimulai saat blok kerja berikutnya dibuka.
            cycle_number = (
                base + 1
                if start_with == RosterSegmentType.WORK
                else max(1, base)
            )

        return anchor, start_with, cycle_number

    @staticmethod
    def next_block_type(*, after: str, pattern) -> str:
        blocks = RosterCalculationService._cycle_blocks(pattern)

        types = [segment_type for segment_type, _, _ in blocks]

        try:
            index = types.index(after)
        except ValueError:
            # Jenis yang tidak ada di pola sekarang — mis. travel yang
            # dimatikan setelah barisnya telanjur dibuat. Lanjutkan dari
            # blok kerja; itu satu-satunya jenis yang pasti ada.
            return RosterSegmentType.WORK

        return types[(index + 1) % len(types)]

    @staticmethod
    def renumber(rows: list[SegmentRow], *, start: int) -> list[SegmentRow]:
        return [
            replace(row, sequence=start + offset)
            for offset, row in enumerate(rows)
        ]

    @staticmethod
    def next_sequence(plan: SiteRotation) -> int:
        """
        Nomor urut berikutnya, dihitung dari **seluruh** baris rencana —
        termasuk yang sudah ditutup.

        Menghitungnya hanya dari baris berjalan akan menabrak
        `uniq_active_hr_rotation_period_sequence`, karena baris yang
        ditutup tetap memegang nomornya.
        """
        highest = (
            RotationPeriod.objects
            .filter(rotation=plan, is_deleted=False)
            .aggregate(value=Max("sequence"))["value"]
        )

        return (highest or 0) + 1

    # ------------------------------------------------------------------
    # Sesudah menulis
    # ------------------------------------------------------------------

    @staticmethod
    def carry_planned_dates(*, new_rows, replaced) -> None:
        """
        Baris pengganti membawa tanggal rencana **asli**, bukan
        tanggalnya sendiri.

        Itu yang membuat layar "rencana vs sekarang" bisa menunjukkan
        pergeserannya. Kalau tanggal rencananya ikut ditulis ulang,
        selisihnya selalu nol dan penyesuaiannya jadi tak terlihat.
        """
        if not replaced:
            return

        by_cycle_type = {}

        for row in replaced:
            by_cycle_type.setdefault(
                (row.cycle_number, row.segment_type), row,
            )

        updated = []

        for row in new_rows:
            origin = by_cycle_type.get(
                (row.cycle_number, row.segment_type),
            )

            if origin is None:
                continue

            row.planned_start_date = (
                origin.planned_start_date or origin.start_date
            )
            row.planned_end_date = (
                origin.planned_end_date or origin.end_date
            )

            updated.append(row)

        if updated:
            RotationPeriod.objects.bulk_update(
                updated,
                ["planned_start_date", "planned_end_date"],
            )

    @staticmethod
    def repoint_travel_requests(*, plan, replaced, new_rows) -> None:
        """
        Travel Request yang menunjuk blok yang digantikan diarahkan ke
        blok penggantinya.

        Tanpa ini, dokumen perjalanan yang sudah diajukan menunjuk baris
        yang tidak lagi ada di versi berjalan — dan layarnya menampilkan
        blok jadwal yang tidak cocok dengan jadwal pegawainya sendiri,
        tanpa satu pun pesan.

        Yang dicocokkan pasangan (putaran, jenis segmen), bukan tanggal:
        justru tanggalnya yang berubah, dan itu memang yang dimaksud
        penyesuaian.
        """
        if not replaced:
            return

        from apps.hr.models import TravelRequest

        mapping = {}

        for row in new_rows:
            mapping.setdefault((row.cycle_number, row.segment_type), row)

        for old in replaced:
            target = mapping.get((old.cycle_number, old.segment_type))

            if target is None:
                continue

            TravelRequest.objects.filter(
                rotation_period=old,
                is_deleted=False,
            ).update(
                rotation_period=target,
                updated_at=timezone.now(),
            )

    @staticmethod
    def sync_header(*, plan: SiteRotation, version) -> None:
        rows = (
            RotationPeriod.objects
            .filter(
                rotation=plan,
                is_deleted=False,
                version_to__isnull=True,
            )
            .order_by("start_date")
        )

        first = rows.first()
        last = rows.order_by("-end_date").first()

        plan.current_version = version

        if first is not None:
            plan.start_date = first.start_date

        if last is not None:
            plan.end_date = last.end_date
            plan.horizon_end = last.end_date

        plan.cycle_count = (
            rows.aggregate(value=Max("cycle_number"))["value"]
            or plan.cycle_count
        )

        plan.save(
            update_fields=[
                "current_version",
                "start_date",
                "end_date",
                "horizon_end",
                "cycle_count",
                "updated_at",
            ],
        )

    # ------------------------------------------------------------------
    # Bentuk penyesuaian yang bernama
    # ------------------------------------------------------------------

    @classmethod
    def extend_block(
        cls,
        *,
        plan: SiteRotation,
        effective_date: date,
        days: int,
        reason: str,
        source: str = RosterVersionSource.ADJUSTMENT,
        reference_type: str = "",
        reference_id="",
        user=None,
    ):
        """
        Blok yang sedang berjalan diperpanjang `days` hari; sisanya
        bergeser mengikutinya.

        Dipakai perpanjangan kerja (rencana 6 minggu, nyatanya 7) dan
        kepulangan tertunda. Blok berikutnya **tidak** dipendekkan:
        yang tertahan di site seminggu tetap berhak atas field break
        penuh, dan memotongnya berarti perusahaan mengambil dua kali.
        """
        block = cls.block_at(plan=plan, on=effective_date)

        if block is None:
            raise ValidationError(
                {
                    "effective_date": (
                        f"Tidak ada segmen jadwal yang memuat "
                        f"{effective_date}."
                    ),
                },
            )

        end = block.end_date + timedelta(days=int(days))

        head = [
            SegmentRow(
                sequence=0,
                segment_type=block.segment_type,
                start_date=block.start_date,
                end_date=end,
                total_days=(end - block.start_date).days + 1,
                counts_as_roster_day=block.counts_as_roster_day,
                cycle_number=block.cycle_number,
            ),
        ]

        return cls.recalculate(
            plan=plan,
            # Yang ditutup dimulai dari awal blok itu sendiri — bloknya
            # memang ditulis ulang, bukan dipotong.
            effective_date=block.start_date,
            source=source,
            reason=reason,
            head_segments=head,
            reference_type=reference_type,
            reference_id=reference_id,
            user=user,
        )

    @classmethod
    def shorten_block(
        cls,
        *,
        plan: SiteRotation,
        effective_date: date,
        days: int,
        reason: str,
        source: str = RosterVersionSource.ADJUSTMENT,
        reference_type: str = "",
        reference_id="",
        user=None,
    ):
        """
        Kebalikan `extend_block` — kepulangan lebih awal, atau field
        break yang dimajukan dengan rotation credit.
        """
        block = cls.block_at(plan=plan, on=effective_date)

        if block is None:
            raise ValidationError(
                {
                    "effective_date": (
                        f"Tidak ada segmen jadwal yang memuat "
                        f"{effective_date}."
                    ),
                },
            )

        end = block.end_date - timedelta(days=int(days))

        if end < block.start_date:
            raise ValidationError(
                {
                    "days": (
                        f"Blok {block.start_date}–{block.end_date} cuma "
                        f"{block.day_count} hari, tidak bisa dipendekkan "
                        f"{days} hari."
                    ),
                },
            )

        head = [
            SegmentRow(
                sequence=0,
                segment_type=block.segment_type,
                start_date=block.start_date,
                end_date=end,
                total_days=(end - block.start_date).days + 1,
                counts_as_roster_day=block.counts_as_roster_day,
                cycle_number=block.cycle_number,
            ),
        ]

        return cls.recalculate(
            plan=plan,
            effective_date=block.start_date,
            source=source,
            reason=reason,
            head_segments=head,
            reference_type=reference_type,
            reference_id=reference_id,
            user=user,
        )

    @classmethod
    def shift_from(
        cls,
        *,
        plan: SiteRotation,
        effective_date: date,
        days: int,
        reason: str,
        source: str = RosterVersionSource.ADJUSTMENT,
        reference_type: str = "",
        reference_id="",
        user=None,
    ):
        """
        Menggeser seluruh jadwal mulai `effective_date` sebanyak `days`
        hari (positif = memundurkan).

        Beda dengan `extend_block`: polanya tidak berubah dan tidak ada
        blok yang jadi lebih panjang — seluruh deret bergerak utuh.
        Dipakai saat kapal bergeser sehari dan semua blok sesudahnya
        ikut, bukan cuma yang sedang dijalani.
        """
        block = cls.block_at(plan=plan, on=effective_date)

        head: list[SegmentRow] = []

        if block is not None and block.start_date < effective_date:
            end = effective_date - timedelta(days=1)

            head = [
                SegmentRow(
                    sequence=0,
                    segment_type=block.segment_type,
                    start_date=block.start_date,
                    end_date=end,
                    total_days=(end - block.start_date).days + 1,
                    counts_as_roster_day=block.counts_as_roster_day,
                    cycle_number=block.cycle_number,
                ),
            ]

            anchor = effective_date + timedelta(days=int(days))
            start_with = block.segment_type
            cycle_number = block.cycle_number
        else:
            anchor = effective_date + timedelta(days=int(days))
            start_with = block.segment_type if block is not None else None
            cycle_number = block.cycle_number if block is not None else None

        return cls.recalculate(
            plan=plan,
            effective_date=effective_date,
            source=source,
            reason=reason,
            head_segments=head,
            tail_anchor=anchor,
            tail_start_with=start_with,
            tail_cycle_number=cycle_number,
            reference_type=reference_type,
            reference_id=reference_id,
            user=user,
        )

    @classmethod
    def reanchor(
        cls,
        *,
        plan: SiteRotation,
        effective_date: date,
        new_cycle_start: date,
        reason: str,
        source: str = RosterVersionSource.ADJUSTMENT,
        reference_type: str = "",
        reference_id="",
        user=None,
    ):
        """
        Jangkar diganti: deret dimulai ulang dari blok kerja pada
        tanggal baru.

        Dipakai saat pegawai pindah gelombang — bukan saat jadwalnya
        cuma bergeser beberapa hari.
        """
        return cls.recalculate(
            plan=plan,
            effective_date=effective_date,
            source=source,
            reason=reason,
            tail_anchor=new_cycle_start,
            tail_start_with=RosterSegmentType.WORK,
            reference_type=reference_type,
            reference_id=reference_id,
            user=user,
        )

    # ------------------------------------------------------------------
    # Bantuan
    # ------------------------------------------------------------------

    @staticmethod
    def block_at(*, plan: SiteRotation, on: date):
        """Segmen berjalan yang memuat sebuah tanggal."""
        return (
            RotationPeriod.objects
            .filter(
                rotation=plan,
                is_deleted=False,
                version_to__isnull=True,
                start_date__lte=on,
                end_date__gte=on,
            )
            .order_by("start_date", "sequence")
            .first()
        )
