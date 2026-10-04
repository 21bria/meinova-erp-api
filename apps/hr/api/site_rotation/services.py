from __future__ import annotations

import logging

from datetime import date, timedelta
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.administration.api.numbering.services.numbering_service import (
    DocumentNumberService,
)
from apps.core.services.master import BaseMasterService

from apps.hr.api.mixins import OrganizationDenormalizationMixin
from apps.hr.applicability import HRFeature, is_applicable
from apps.hr.api.site_rotation.policy import RosterPolicyResolver
from apps.hr.api.site_rotation.generator import (
    MAX_CYCLE_COUNT,
    RotationPeriodGenerator,
)
from apps.hr.models import (
    RosterSegmentType,
    RotationPeriod,
    RotationPeriodType,
    SiteRotation,
)


logger = logging.getLogger(__name__)


# Kolom yang membentuk jadwal. Berubahnya salah satu berarti seluruh
# baris ON/OFF yang tersimpan sudah tidak lagi menggambarkan polanya.
CYCLE_PATTERN_FIELDS = (
    "start_date",
    "cycle_work_days",
    "cycle_off_days",
    "cycle_travel_days",
    "cycle_count",
)


def period_span_end(period) -> date:
    """
    Hari terakhir yang dipakai satu periode, termasuk jendela travel
    yang mengekor di ujungnya.

    Jendelanya dihitung dari pola siklus (`RotationPeriod.travel_window_end`),
    bukan dibaca dari baris travel — sejak tanggal penerbangan pindah ke
    Travel Request, jadwal tidak lagi menyimpan barisnya. Tanpa
    memperhitungkan jendela ini, setiap hari perjalanan akan dilaporkan
    sebagai jadwal bolong padahal justru itu bentuk yang benar.
    """
    return period.travel_window_end or period.end_date


def _adjacent_period(period, *, before: bool):
    """
    Baris jadwal tetangga pada versi yang sedang berlaku.

    Kronologis, bukan lewat `sequence`: nomor urut tidak pernah dipakai
    ulang dan berlubang setelah ada penyesuaian, jadi "baris sebelum
    ini" tidak bisa disimpulkan dari nomornya.
    """
    queryset = (
        RotationPeriod.objects
        .filter(
            rotation_id=period.rotation_id,
            is_deleted=False,
            version_to__isnull=True,
        )
        .exclude(pk=period.pk)
    )

    if before:
        return (
            queryset
            .filter(end_date__lt=period.start_date)
            .order_by("-end_date", "-sequence")
            .first()
        )

    return (
        queryset
        .filter(start_date__gt=period.end_date)
        .order_by("start_date", "sequence")
        .first()
    )


def outbound_travel_window(period) -> tuple[date, date] | None:
    """
    Jendela travel **keluar** yang mendahului satu blok off.

    Jadwal yang memegang angkanya, bukan pemanggilnya. Travel Request
    sempat menurunkannya sendiri dari `cycle_travel_days` dan memakai
    angka itu utuh untuk kedua arah — padahal kolom itu total
    pulang-pergi, dipecah `ceil(t/2)` keluar + `floor(t/2)` kembali.
    Akibatnya etape keluar mundur satu hari terlalu jauh dan menabrak
    hari kerja terakhir, dan etape pulang jadi dua kali lebih panjang
    dari jendela yang sama di layar roster.

    Dua jalur roster dilayani satu fungsi:

    * jalur baru menulis segmen `TRAVEL_OUT` sebagai baris tersendiri —
      itu yang dipakai, karena tanggalnya sudah tercatat;
    * jalur lama tidak punya barisnya, jadi jendelanya dibaca dari
      properti turunan blok kerja yang mendahuluinya.

    ``None`` = jadwalnya memang tidak menyediakan hari perjalanan
    (pegawai lokal, atau pola tanpa travel). Itu keadaan yang sah dan
    bukan alasan menebak tanggal.
    """
    previous = _adjacent_period(period, before=True)

    if previous is None:
        return None

    if previous.segment_type == RosterSegmentType.TRAVEL_OUT:
        return previous.start_date, previous.end_date

    start = previous.travel_window_start
    end = previous.travel_window_end

    if start and end:
        return start, end

    return None


def inbound_travel_window(period) -> tuple[date, date] | None:
    """
    Jendela travel **kembali** yang mengekor di ujung blok off.

    Pasangan `outbound_travel_window`; bedanya jendela ini milik blok
    off itu sendiri, jadi jalur lama tidak perlu menengok baris
    tetangga sama sekali.
    """
    following = _adjacent_period(period, before=False)

    if (
        following is not None
        and following.segment_type == RosterSegmentType.TRAVEL_IN
    ):
        return following.start_date, following.end_date

    start = period.travel_window_start
    end = period.travel_window_end

    if start and end:
        return start, end

    return None


def build_schedule_warnings(periods) -> list[dict]:
    """
    Memeriksa periode satu dokumen bersambung dan tidak saling tindih.

    **Peringatan, bukan penolakan.** Alasannya bentuk penyuntingannya:
    tabel inline menyimpan baris satu per satu, jadi menggeser satu blok
    dua hari selalu melewati keadaan "tumpang tindih dengan blok
    berikutnya" sebelum blok itu ikut digeser. Menolak simpan di keadaan
    itu membuat jadwal yang bersambung mustahil disunting. Polanya sama
    dengan verifikasi nama pada sinkronisasi absensi: alarm, bukan
    gerbang.

    Yang dijaga tetap nyata — roster bolong enam bulan atau dua blok yang
    bertindihan akan membuat akumulasi hari kerja salah, dan tanpa daftar
    ini tidak ada yang tahu kenapa.

    `periods` boleh queryset maupun daftar objek. Jendela travel dibaca
    dari `rotation`, jadi queryset-nya sebaiknya `select_related`
    supaya tidak menembak satu query per baris.
    """
    ordered = sorted(
        (
            period
            for period in periods
            if not period.is_deleted
        ),
        key=lambda period: (period.start_date, period.sequence),
    )

    warnings: list[dict] = []

    for previous, current in zip(ordered, ordered[1:]):
        expected = period_span_end(previous) + timedelta(days=1)

        if current.start_date == expected:
            continue

        gap = (current.start_date - expected).days

        warnings.append(
            {
                "kind": "gap" if gap > 0 else "overlap",
                "from_sequence": previous.sequence,
                "to_sequence": current.sequence,
                "days": abs(gap),
                "message": (
                    f"Periode #{previous.sequence} berakhir "
                    f"{previous.end_date}, periode "
                    f"#{current.sequence} mulai "
                    f"{current.start_date} — "
                    + (
                        f"bolong {gap} hari."
                        if gap > 0
                        else f"bertindihan {abs(gap)} hari."
                    )
                ),
            },
        )

    return warnings


class SiteRotationService(
    OrganizationDenormalizationMixin,
    BaseMasterService,
):
    model = SiteRotation

    # ------------------------------------------------------------------
    # Penyiapan data
    # ------------------------------------------------------------------

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_roster_applicable(data.get("employee"))

        data = cls.apply_organization(data)
        data = cls.apply_roster_crew(data)
        data = cls.apply_cycle_pattern(data)
        data = cls.apply_travel_days(data)

        return cls.apply_document_number(data)

    @staticmethod
    def assert_roster_applicable(employee) -> None:
        """
        Roster Assignment hanya untuk pegawai yang Roster-nya memang
        berlaku (Employee Group → Feature Applicability).

        **Hanya di jalur pembuatan.** Sengaja tidak ditaruh di
        `SiteRotation.clean()`: `full_clean()` di sana ikut jalan saat
        dokumen lama dihitung ulang dan saat periodenya digeser, jadi
        admin yang mematikan Roster untuk sebuah group akan sekaligus
        mengunci seluruh dokumen yang sudah terbit sebelumnya — data
        yang sah jadi tidak bisa disentuh, dan pesannya menunjuk kolom
        yang tidak diubah siapa pun. Yang dicegah di sini pembuatan
        dokumen baru; yang sudah ada tetap bisa dirawat sampai
        ditutup.
        """
        if employee is None:
            return

        if is_applicable(employee, HRFeature.ROSTER):
            return

        group = getattr(
            getattr(employee, "employment", None),
            "employee_group",
            None,
        )

        raise ValidationError(
            {
                "employee": (
                    f"Employee Group "
                    f"\"{getattr(group, 'name', '-')}\" tidak "
                    "memakai Roster. Nyalakan Roster pada master "
                    "Employee Group kalau kebijakannya berubah."
                ),
            },
        )

    @staticmethod
    def apply_travel_days(
        data: dict[str, Any],
        *,
        instance: SiteRotation | None = None,
    ) -> dict[str, Any]:
        """
        Mengambil hari perjalanan dari aturan (site, Point of Hire).

        Yang menentukan jarak, bukan gelombang: dua orang satu crew
        dengan POH Makassar dan Yogyakarta berbeda satu hari, dan itu
        memang yang tertulis di dokumen Substansi Roster.

        Hanya mengisi yang belum disebutkan. Angka yang diketik di form
        menang — ada perjalanan yang memang menyimpang dari pola dan
        tidak bisa disimpulkan dari POH.
        """
        if data.get("cycle_travel_days") is not None:
            return data

        employee = data.get(
            "employee",
            getattr(instance, "employee", None),
        )

        if employee is None:
            return data

        resolved = RosterPolicyResolver.travel_days_for(employee)

        data["cycle_travel_days"] = resolved.days

        return data

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = cls.apply_organization(
            data,
            fallback_employee=instance.employee,
        )

        data = cls.apply_roster_crew(
            data,
            instance=instance,
        )

        data = cls.apply_cycle_pattern(
            data,
            instance=instance,
        )

        # Ditandai di sini, bukan di `after_update`: begitu `update()`
        # meng-`setattr` nilai barunya ke instance, nilai lamanya sudah
        # tidak bisa dibandingkan lagi. Atribut sementara, tidak
        # tersimpan ke tabel.
        instance._cycle_pattern_changed = any(
            field in data
            and data[field] != getattr(instance, field)
            for field in CYCLE_PATTERN_FIELDS
        )

        return data

    @staticmethod
    def apply_document_number(data: dict[str, Any]) -> dict[str, Any]:
        """
        Mengambil nomor TR dari pola penomoran, kecuali sudah diisi.

        Hanya untuk dokumen baru. Nomor tidak boleh berubah setelah
        terbit: yang tercetak di TR dan yang dipegang bagian travel harus
        tetap menunjuk dokumen yang sama walau perusahaan atau tanggalnya
        dikoreksi belakangan.
        """
        if data.get("document_number"):
            return data

        data["document_number"] = DocumentNumberService.next(
            module="hr",
            document_type="site_rotation",
            company=data.get("company"),
        )

        return data

    @staticmethod
    def apply_roster_crew(
        data: dict[str, Any],
        *,
        instance: SiteRotation | None = None,
    ) -> dict[str, Any]:
        """
        Mengambil gelombang dari penempatan pegawai kalau form tidak
        menyebutkannya.

        `EmploymentAssignment.roster_crew` sudah jadi sumber kebenaran
        untuk perhitungan hari cuti pegawai site, jadi menanyakannya lagi
        di form roster hanya membuka peluang dua jawaban berbeda untuk
        orang yang sama.
        """
        if data.get("roster_crew") is not None:
            return data

        # `None` yang dikirim eksplisit berarti "tanpa crew, pola diisi
        # manual" — itu pilihan sah dan tidak boleh ditimpa.
        if "roster_crew" in data:
            return data

        # Crew yang diisikan di sini adalah **turunan**, bukan pilihan
        # pengguna. `apply_cycle_pattern` membedakan keduanya lewat
        # penanda ini: tanpa itu, menyimpan dokumen yang mana pun akan
        # terbaca sebagai "pindah gelombang" dan Work Days yang sudah
        # dikoreksi tangan dikembalikan diam-diam ke bawaan crew.
        data["_roster_crew_derived"] = True

        employee = data.get(
            "employee",
            getattr(instance, "employee", None),
        )

        if employee is None:
            return data

        employment = getattr(employee, "employment", None)

        if employment is not None and employment.roster_crew_id:
            data["roster_crew"] = employment.roster_crew

        return data

    @classmethod
    def apply_cycle_pattern(
        cls,
        data: dict[str, Any],
        *,
        instance: SiteRotation | None = None,
    ) -> dict[str, Any]:
        """
        Menyalin pola siklus dan jangkar dari crew ke dokumen.

        Disalin, bukan dibaca lewat relasi setiap kali: jadwal yang sudah
        digenerate dan sudah dibelikan tiket tidak boleh berubah gara-gara
        master WorkSchedule disunting bulan depan.
        """
        # Penanda internal dari `apply_roster_crew`, bukan kolom model —
        # wajib dibuang di sini sebelum dict-nya jadi kwargs `Model(**...)`.
        crew_derived = data.pop("_roster_crew_derived", False)

        crew = data.get(
            "roster_crew",
            getattr(instance, "roster_crew", None),
        )

        schedule = (
            getattr(crew, "work_schedule", None)
            if crew is not None
            else None
        )

        if schedule is not None:
            # Disalin ulang kalau crew-nya memang baru **dipilih** di
            # request ini — pindah gelombang berarti pindah pola. Crew
            # yang cuma diturunkan dari penempatan pegawai tidak dihitung
            # sebagai perpindahan; kalau dihitung, setiap penyimpanan
            # dokumen akan mengembalikan Work Days ke bawaan crew.
            crew_changed = (
                "roster_crew" in data
                and not crew_derived
            )

            for field_name, value in (
                ("cycle_work_days", schedule.cycle_work_days),
                ("cycle_off_days", schedule.cycle_off_days),
            ):
                if data.get(field_name):
                    continue

                if crew_changed or not getattr(instance, field_name, None):
                    data[field_name] = value

        # Tanggal mulai hanya diisikan untuk dokumen baru. Menyentuhnya
        # saat update akan menggeser seluruh periode yang sudah ada.
        if instance is None and not data.get("start_date") and crew is not None:
            employee = data.get("employee")
            employment = getattr(employee, "employment", None)

            anchor = (
                getattr(employment, "roster_start_override", None)
                or crew.cycle_start_date
            )

            work = data.get("cycle_work_days") or 0
            off = data.get("cycle_off_days") or 0
            travel = data.get("cycle_travel_days") or 0

            # Hari travel ikut dihitung **sekali**, bukan dua kali:
            # `cycle_travel_days` sudah berarti total pulang-pergi, dan
            # generator memecahnya jadi `ceil(t/2)` keluar + `floor(t/2)`
            # kembali. Satu putaran karena itu maju `work + off + travel`.
            #
            # Sempat ditulis `travel * 2` di sini, dan akibatnya tanggal
            # mulai yang terisi otomatis mendarat di tanggal yang bukan
            # awal siklus crew mana pun — meleset `travel` hari tiap
            # putaran, dan melesetnya menumpuk sepanjang tahun. Angka
            # yang sama sudah dihitung `SiteRotation.cycle_length`; yang
            # dipakai di sini nilai dari `data` karena dokumennya belum
            # ada.
            cycle_length = work + off + travel

            if anchor and cycle_length:
                data["start_date"] = RotationPeriodGenerator.next_cycle_start(
                    anchor=anchor,
                    cycle_length=cycle_length,
                    on_or_after=timezone.localdate(),
                )

        return data

    # ------------------------------------------------------------------
    # Generate periode
    # ------------------------------------------------------------------

    @classmethod
    def after_create(cls, *, instance, user=None, **kwargs):
        instance = super().after_create(
            instance=instance,
            user=user,
            **kwargs,
        )

        # Digenerate langsung supaya dokumen yang baru dibuat tidak
        # tampil dengan tabel periode kosong. Tombol "Generate Periods"
        # tetap ada untuk generate ulang saat polanya diubah.
        cls.generate_periods(
            rotation=instance,
            user=user,
        )

        return instance

    @classmethod
    def after_update(cls, *, instance, user=None, **kwargs):
        instance = super().after_update(
            instance=instance,
            user=user,
            **kwargs,
        )

        # Mengubah pola di tab Cycle tanpa membuat ulang barisnya
        # menghasilkan dokumen yang menyatakan dua jadwal berbeda:
        # kepalanya bilang 42/14, tabelnya masih 45/14. Tidak ada
        # peringatan apa pun untuk keadaan itu — makanya dibuat ulang
        # sendiri.
        if not getattr(instance, "_cycle_pattern_changed", False):
            return instance

        protected = cls.protected_periods(instance)

        if protected:
            # Sengaja tidak melempar: yang barusan disimpan boleh jadi
            # cuma catatan, dan menolak simpan karena ada baris tangan
            # membuat dokumen mustahil dikoreksi. Regenerate paksa
            # tersedia sebagai tombol tersendiri.
            logger.warning(
                "Pola siklus SiteRotation %s berubah tapi %s periode "
                "sudah disunting tangan atau punya travel manual — "
                "baris tidak dibuat ulang.",
                instance.pk,
                protected,
            )

            return instance

        cls.generate_periods(
            rotation=instance,
            user=user,
        )

        return instance

    @classmethod
    def protected_periods(cls, rotation: SiteRotation) -> int:
        """
        Jumlah periode yang tidak boleh ditimpa generate ulang.

        Yang dilindungi baris yang tanggalnya digeser tangan. Tiket dan
        akomodasi tidak lagi ikut dipertimbangkan di sini — sejak
        keduanya pindah ke Travel Request, menghapus baris jadwal tidak
        menghapus bookingan apa pun.
        """
        return (
            RotationPeriod.objects
            .filter(
                rotation=rotation,
                is_deleted=False,
                is_manual_override=True,
            )
            .count()
        )

    @classmethod
    @transaction.atomic
    def generate_periods(
        cls,
        *,
        rotation: SiteRotation,
        cycle_count: int | None = None,
        force: bool = False,
        user=None,
    ) -> list[RotationPeriod]:
        """
        Membuat ulang seluruh baris ON/OFF milik satu dokumen.

        Generate ulang selalu **mengganti** semua baris, bukan menambal
        yang kurang — menambal berarti nomor urut dan tanggalnya bisa
        berbeda dari pola, dan hasilnya tidak lagi bisa dijelaskan.

        Karena itu baris yang sudah disunting tangan atau yang sudah
        punya travel dilindungi: kalau ada, generate ditolak sampai
        pemanggil mengirim `force=True`. Menghapusnya diam-diam berarti
        membuang tanggal penerbangan dan bookingan hotel yang sudah
        terlanjur dipesan.
        """
        if cycle_count:
            cycle_count = max(1, min(int(cycle_count), MAX_CYCLE_COUNT))

            if cycle_count != rotation.cycle_count:
                rotation.cycle_count = cycle_count
                rotation.save(update_fields=["cycle_count", "updated_at"])

        existing = RotationPeriod.objects.filter(
            rotation=rotation,
            is_deleted=False,
        )

        if not force:
            protected = cls.protected_periods(rotation)

            if protected:
                raise ValidationError(
                    {
                        "periods": (
                            f"{protected} periode sudah disunting tangan "
                            "atau punya baris travel yang diisi tangan. "
                            "Generate ulang akan menghapusnya — pakai "
                            "Regenerate (Overwrite) kalau memang itu "
                            "yang diinginkan."
                        ),
                    },
                )

        # Soft delete, bukan hard: baris lama tetap bisa ditelusuri
        # kalau ternyata generate ulangnya keliru. Sengaja lewat
        # queryset, bukan satu per satu lewat service — generate ulang
        # mengganti seluruh isi dokumen, jadi menyinkronkan `end_date`
        # di setiap baris yang dihapus hanya menghasilkan puluhan
        # penyimpanan yang langsung ditimpa di akhir.
        deleted_at = timezone.now()

        existing.update(
            is_deleted=True,
            deleted_at=deleted_at,
            deleted_by=user,
        )

        rows = RotationPeriodGenerator.build(
            start_date=rotation.start_date,
            work_days=rotation.cycle_work_days,
            off_days=rotation.cycle_off_days,
            cycle_count=rotation.cycle_count,
            travel_days=rotation.cycle_travel_days,
        )

        periods = [
            RotationPeriodService.create(
                data={
                    "rotation": rotation,
                    "employee": rotation.employee,
                    **row,
                },
                user=user,
            )
            for row in rows
        ]

        cls.sync_end_date(rotation)
        cls.sync_shift_baseline(rotation, user=user)

        return periods

    # ------------------------------------------------------------------
    # Menyambung & membangun ulang sebagian
    # ------------------------------------------------------------------
    #
    # `generate_periods` selalu mengganti **seluruh** isi dokumen. Itu
    # benar untuk dokumen yang baru dibuat, tapi merusak untuk dokumen
    # yang sudah berjalan: satu penyesuaian lapangan saja sudah membuat
    # hampir semua baris tertandai tangan, dan sejak itu jadwalnya tidak
    # bisa diperpanjang tanpa membuang penyesuaian itu.
    #
    # Dua operasi di bawah bekerja **dari satu titik ke depan**. Baris
    # sebelum titik itu tidak disentuh sama sekali — termasuk yang sudah
    # digeser, diperpanjang, atau dikoreksi tangan.

    @classmethod
    def last_period(cls, rotation: SiteRotation) -> RotationPeriod | None:
        return (
            RotationPeriod.objects
            .filter(rotation=rotation, is_deleted=False)
            .order_by("-start_date", "-sequence")
            .first()
        )

    @classmethod
    @transaction.atomic
    def extend_periods(
        cls,
        *,
        rotation: SiteRotation,
        cycles: int | None = None,
        until: date | None = None,
        user=None,
    ) -> list[RotationPeriod]:
        """
        Menyambung siklus baru di ujung jadwal.

        Tidak menyentuh satu pun baris yang sudah ada — ini menempel
        halaman baru di bawah kalender, bukan mencetak ulang
        kalendernya.

        Sambungan berangkat dari hari setelah blok terakhir beserta
        hari travel-nya, dan dimulai dengan jenis blok yang berlawanan:
        jadwal yang berakhir di blok kerja disambung dengan blok off.

        `until` boleh dipakai sebagai ganti `cycles` — "sampai Desember
        2027" jauh lebih bisa dijawab daripada "berapa siklus".
        """
        last = cls.last_period(rotation)

        if last is None:
            raise ValidationError(
                {
                    "periods": (
                        "Dokumen ini belum punya baris jadwal. Pakai "
                        "Generate Periods dulu."
                    ),
                },
            )

        travel_days = rotation.cycle_travel_days or 0

        # Hari pertama sambungan: setelah blok terakhir **dan** hari
        # travel yang mengekorinya.
        cursor = last.end_date + timedelta(days=1 + travel_days)

        if cycles is None:
            if until is None:
                raise ValidationError(
                    {
                        "cycles": (
                            "Sebutkan jumlah siklus, atau tanggal "
                            "sampai kapan jadwalnya diperpanjang."
                        ),
                    },
                )

            cycles = RotationPeriodGenerator.cycles_until(
                start_date=cursor,
                until=until,
                cycle_length=rotation.cycle_length or 0,
            )

        cycles = max(1, min(int(cycles), MAX_CYCLE_COUNT))

        rows = RotationPeriodGenerator.build(
            start_date=cursor,
            work_days=rotation.cycle_work_days,
            off_days=rotation.cycle_off_days,
            cycle_count=cycles,
            travel_days=travel_days,
            start_with=(
                RotationPeriodType.OFF
                if last.period_type == RotationPeriodType.WORK
                else RotationPeriodType.WORK
            ),
            start_sequence=last.sequence + 1,
        )

        periods = [
            RotationPeriodService.create(
                data={
                    "rotation": rotation,
                    "employee": rotation.employee,
                    **row,
                },
                user=user,
            )
            for row in rows
        ]

        # `cycle_count` ikut naik supaya angka di form tetap
        # menggambarkan panjang dokumen yang sebenarnya.
        rotation.cycle_count = min(
            MAX_CYCLE_COUNT,
            (rotation.cycle_count or 0) + cycles,
        )

        rotation.save(update_fields=["cycle_count", "updated_at"])

        cls.sync_end_date(rotation)
        cls.sync_shift_baseline(rotation, user=user)

        return periods

    @classmethod
    @transaction.atomic
    def regenerate_from(
        cls,
        *,
        rotation: SiteRotation,
        from_sequence: int,
        cycles: int | None = None,
        user=None,
    ) -> list[RotationPeriod]:
        """
        Membuat ulang jadwal **mulai dari satu blok**, dengan pola yang
        berlaku sekarang.

        Untuk perubahan yang berlaku ke depan saja: pegawai pindah dari
        42:14 ke 56:14 mulai Oktober. Baris sebelum titik itu adalah
        sejarah — sudah dijalani, sudah dibelikan tiket — dan tidak
        boleh ikut berubah hanya karena polanya diganti.

        Titik sambungnya tanggal mulai blok yang ditunjuk, jadi
        jadwalnya tetap rapat dengan baris sebelumnya.
        """
        anchor = (
            RotationPeriod.objects
            .filter(
                rotation=rotation,
                sequence=from_sequence,
                is_deleted=False,
            )
            .first()
        )

        if anchor is None:
            raise ValidationError(
                {
                    "from_sequence": (
                        f"Periode #{from_sequence} tidak ada di dokumen "
                        "ini."
                    ),
                },
            )

        cursor = anchor.start_date

        obsolete = RotationPeriod.objects.filter(
            rotation=rotation,
            is_deleted=False,
            start_date__gte=cursor,
        )

        kept = (
            RotationPeriod.objects
            .filter(rotation=rotation, is_deleted=False)
            .exclude(pk__in=obsolete.values("pk"))
            .count()
        )

        if cycles is None:
            # Sebanyak yang dibuang, dibulatkan ke atas — panjang
            # dokumen tidak berubah tanpa diminta.
            cycles = max(1, -(-obsolete.count() // 2))

        # Soft delete, bukan hard: kalau ternyata polanya salah, baris
        # lamanya masih bisa ditelusuri.
        obsolete.update(
            is_deleted=True,
            deleted_at=timezone.now(),
            deleted_by=user,
        )

        rows = RotationPeriodGenerator.build(
            start_date=cursor,
            work_days=rotation.cycle_work_days,
            off_days=rotation.cycle_off_days,
            cycle_count=max(1, min(int(cycles), MAX_CYCLE_COUNT)),
            travel_days=rotation.cycle_travel_days or 0,
            start_with=anchor.period_type,
            start_sequence=anchor.sequence,
        )

        periods = [
            RotationPeriodService.create(
                data={
                    "rotation": rotation,
                    "employee": rotation.employee,
                    **row,
                },
                user=user,
            )
            for row in rows
        ]

        rotation.cycle_count = min(
            MAX_CYCLE_COUNT,
            -(-(kept + len(periods)) // 2),
        )

        rotation.save(update_fields=["cycle_count", "updated_at"])

        cls.sync_end_date(rotation)
        cls.sync_shift_baseline(rotation, user=user)

        return periods

    # ------------------------------------------------------------------
    # Penyesuaian hari lewat rasio kerja:off
    # ------------------------------------------------------------------
    #
    # Aturan #13, #17, dan #18 dokumen "Substansi Roster". Ketiganya
    # menyangkut hari yang bergeser dari rencana, tapi akibatnya
    # berlawanan — dan yang membedakan **siapa yang menyebabkannya**,
    # bukan berapa harinya:
    #
    #   #13 mundur cuti ATAS persetujuan KTT   → dapat tambahan off
    #   #14 mundur cuti TANPA persetujuan      → "loyalitas", nihil
    #   #17 pesawat cancel (bukan salah orang) → jadwal tidak berubah
    #   #18 terlambat karena salah pegawai     → tambah on-site
    #
    # Karena itu jenisnya harus disebut pemanggil, tidak boleh
    # disimpulkan sistem dari selisih tanggal.

    ADJUSTMENT_KINDS = {
        "deferred_leave": "Mundur cuti (disetujui KTT)",
        "loyalty": "Mundur cuti tanpa persetujuan (loyalitas)",
        "late_return": "Terlambat kembali (kesalahan pegawai)",
        "no_impact": "Di luar kendali pegawai (mis. pesawat cancel)",
    }

    @classmethod
    @transaction.atomic
    def adjust_by_ratio(
        cls,
        *,
        rotation: SiteRotation,
        kind: str,
        days: int,
        sequence: int | None = None,
        user=None,
    ) -> dict:
        """
        Menghitung dampak hari yang bergeser, lalu menerapkannya ke
        jadwal.

        `sequence` menunjuk blok yang diperpanjang. Dikosongkan =
        blok pertama yang jenisnya cocok — off untuk mundur cuti,
        kerja untuk keterlambatan.

        Blok yang diperpanjang bertambah panjang, dan **seluruh blok
        sesudahnya bergeser** sebanyak itu. Gelombang crew tidak ikut
        digeser; ini penyesuaian satu orang.
        """
        if kind not in cls.ADJUSTMENT_KINDS:
            raise ValidationError(
                {
                    "kind": (
                        f"Jenis penyesuaian {kind!r} tidak dikenal. "
                        f"Pilihan: {', '.join(cls.ADJUSTMENT_KINDS)}."
                    ),
                },
            )

        if days <= 0:
            raise ValidationError(
                {"days": "Jumlah hari harus lebih besar dari nol."},
            )

        policy = RosterPolicyResolver.for_employee(rotation.employee)
        ratio = RosterPolicyResolver.ratio_for(
            rotation=rotation,
            policy=policy,
        )

        # Dua jenis ini sengaja tidak mengubah apa pun. Tetap dihitung
        # dan dilaporkan supaya ada jawaban tertulis untuk "kenapa
        # jadwal saya tidak berubah" — diam adalah jawaban terburuk.
        if kind in {"loyalty", "no_impact"}:
            return {
                "kind": kind,
                "label": cls.ADJUSTMENT_KINDS[kind],
                "ratio": str(ratio.value),
                "ratio_reason": ratio.reason,
                "days_input": days,
                "days_applied": 0,
                "applied": False,
                "message": (
                    "Tidak mengubah jadwal — "
                    + (
                        "mundur cuti tanpa persetujuan KTT dihitung "
                        "sebagai loyalitas."
                        if kind == "loyalty"
                        else "penyebabnya di luar kendali pegawai."
                    )
                ),
            }

        if kind == "deferred_leave":
            applied = ratio.off_from_deferred(days)
            wanted = RotationPeriodType.OFF
            formula = f"{days} ÷ {ratio.value}"
        else:
            applied = ratio.onsite_from_late(days)
            wanted = RotationPeriodType.WORK
            formula = f"{days} × {ratio.value}"

        if applied <= 0:
            return {
                "kind": kind,
                "label": cls.ADJUSTMENT_KINDS[kind],
                "ratio": str(ratio.value),
                "ratio_reason": ratio.reason,
                "days_input": days,
                "days_applied": 0,
                "applied": False,
                "message": (
                    f"{formula} = 0 hari — belum cukup untuk menambah "
                    "satu hari penuh."
                ),
            }

        period = cls._adjustment_target(
            rotation=rotation,
            sequence=sequence,
            period_type=wanted,
        )

        cls.extend_period(
            rotation=rotation,
            period=period,
            days=applied,
            user=user,
        )

        return {
            "kind": kind,
            "label": cls.ADJUSTMENT_KINDS[kind],
            "ratio": str(ratio.value),
            "ratio_reason": ratio.reason,
            "days_input": days,
            "days_applied": applied,
            "applied": True,
            "sequence": period.sequence,
            "message": (
                f"{formula} = {applied} hari ditambahkan ke periode "
                f"#{period.sequence} ({period.get_period_type_display()}); "
                "periode sesudahnya ikut bergeser."
            ),
        }

    @staticmethod
    def _adjustment_target(*, rotation, sequence, period_type):
        periods = (
            RotationPeriod.objects
            .filter(rotation=rotation, is_deleted=False)
            .order_by("start_date", "sequence")
        )

        if sequence is not None:
            period = periods.filter(sequence=sequence).first()

            if period is None:
                raise ValidationError(
                    {
                        "sequence": (
                            f"Periode #{sequence} tidak ada di dokumen "
                            "ini."
                        ),
                    },
                )

            return period

        period = periods.filter(period_type=period_type).first()

        if period is None:
            raise ValidationError(
                {
                    "sequence": (
                        "Dokumen ini belum punya periode bertipe "
                        f"{period_type}. Generate periodenya dulu."
                    ),
                },
            )

        return period

    @classmethod
    @transaction.atomic
    def extend_period(
        cls,
        *,
        rotation: SiteRotation,
        period: RotationPeriod,
        days: int,
        user=None,
    ) -> RotationPeriod:
        """
        Memperpanjang satu blok dan menggeser seluruh blok sesudahnya.

        Memperpanjang tanpa menggeser sisanya akan membuat blok ini
        bertindihan dengan yang berikutnya — dan jadwal yang tumpang
        tindih membuat akumulasi hari kerja salah tanpa ada yang tahu
        kenapa.
        """
        following = (
            RotationPeriod.objects
            .filter(
                rotation=rotation,
                is_deleted=False,
                start_date__gt=period.start_date,
            )
            .order_by("start_date", "sequence")
            .first()
        )

        # Sisanya digeser lebih dulu, dari belakang ke depan lewat
        # `shift_from` — kalau blok ini diperpanjang duluan, geseran
        # berikutnya berangkat dari keadaan yang sudah tumpang tindih.
        if following is not None:
            cls.shift_from(
                rotation=rotation,
                from_sequence=following.sequence,
                days=days,
                user=user,
            )

        return RotationPeriodService.update(
            instance=period,
            data={"end_date": period.end_date + timedelta(days=days)},
            user=user,
        )

    @classmethod
    @transaction.atomic
    def shift_from(
        cls,
        *,
        rotation: SiteRotation,
        from_sequence: int,
        days: int,
        user=None,
    ) -> list[RotationPeriod]:
        """
        Menggeser satu periode **beserta seluruh sisa jadwalnya**.

        Kapal ditunda tiga hari bukan cuma memundurkan satu blok: blok
        itu mundur, blok berikutnya ikut mundur, dan seterusnya sampai
        ujung dokumen — kalau tidak, jadwalnya jadi tumpang tindih.
        Menggesernya satu per satu lewat grid bisa saja, tapi untuk
        dokumen dua belas baris itu dua belas penyimpanan yang setiap
        kalinya melewati keadaan tumpang tindih, dan satu baris terlewat
        sudah cukup membuat akumulasi hari kerjanya salah.

        `days` positif memundurkan, negatif memajukan. Yang digeser
        hanya baris jadwal; tanggal penerbangan ada di Travel Request
        dan tidak ikut, sebab tiket yang sudah dipesan tidak boleh
        ditulis ulang oleh perubahan jadwal.

        Seluruh baris yang tergeser ditandai `is_manual_override`.
        Jadwal hasil geseran memang tidak lagi sama dengan polanya, dan
        generate ulang tanpa `force` tidak boleh menghapusnya diam-diam.

        Titik awalnya ditentukan dari nomor urut, tapi penyaringannya
        kronologis: baris sisipan mendapat nomor urut terakhir yang
        bebas walau tanggalnya di tengah, jadi menyaring dari `sequence`
        saja akan melewatkan justru baris yang duduk di antara blok yang
        digeser.
        """
        if not days:
            raise ValidationError(
                {
                    "days": (
                        "Jumlah hari geseran tidak boleh 0 — tidak ada "
                        "yang berubah."
                    ),
                },
            )

        periods = list(
            RotationPeriod.objects
            .filter(rotation=rotation, is_deleted=False)
            .order_by("start_date", "sequence")
            .select_related("rotation"),
        )

        anchor = next(
            (
                period
                for period in periods
                if period.sequence == from_sequence
            ),
            None,
        )

        if anchor is None:
            raise ValidationError(
                {
                    "from_sequence": (
                        f"Periode #{from_sequence} tidak ada di dokumen "
                        "ini."
                    ),
                },
            )

        origin = (anchor.start_date, anchor.sequence)

        offset = timedelta(days=days)

        shifted: list[RotationPeriod] = []

        for period in periods:
            if (period.start_date, period.sequence) < origin:
                continue

            shifted.append(
                RotationPeriodService.update(
                    instance=period,
                    data={
                        "start_date": period.start_date + offset,
                        "end_date": period.end_date + offset,
                    },
                    user=user,
                ),
            )

        cls.sync_end_date(rotation)
        cls.sync_shift_baseline(rotation, user=user)

        return shifted

    @staticmethod
    def schedule_warnings(rotation: SiteRotation) -> list[dict]:
        """
        Versi berbasis query dari `build_schedule_warnings`, untuk
        pemanggil yang cuma memegang dokumennya.
        """
        periods = (
            RotationPeriod.objects
            .filter(rotation=rotation, is_deleted=False)
            .order_by("start_date", "sequence")
            .select_related("rotation")
        )

        return build_schedule_warnings(periods)

    @classmethod
    def sync_end_date(cls, rotation: SiteRotation) -> SiteRotation:
        """
        Menyalin tanggal akhir periode terakhir ke dokumen.

        Dihitung ulang dari baris, bukan dari pola: setelah ada
        penyesuaian manual, tanggal akhir menurut rumus tidak lagi sama
        dengan tanggal akhir yang sebenarnya dijadwalkan.
        """
        last: date | None = (
            RotationPeriod.objects
            .filter(rotation=rotation, is_deleted=False)
            .order_by("-end_date")
            .values_list("end_date", flat=True)
            .first()
        )

        if rotation.end_date == last:
            return rotation

        rotation.end_date = last
        rotation.save(update_fields=["end_date", "updated_at"])

        return rotation

    @staticmethod
    def sync_shift_baseline(rotation: SiteRotation, *, user=None) -> dict:
        """
        Menerbitkan ulang rencana shift `BASELINE` dari roster + policy.

        **Kenapa dipanggil dari keempat mutasi roster, dan bukan dari
        `sync_end_date`:** yang di atas ikut jalan sekali per baris saat
        `generate_periods` menulis dua puluh enam periode, jadi
        menaruhnya di sana berarti dua puluh enam kali menghitung ulang
        rencana yang sama. Yang di sini dipanggil sekali per operasi,
        sesudah seluruh barisnya tersimpan.

        Bukan signal: `bulk_create` di jalur dokumen Setup tidak
        menerbitkan `post_save` sama sekali, jadi separuh jalur roster
        akan diam-diam terlewat.

        Bukan saat kalender dibaca: sebuah `GET` tidak boleh menulis, dan
        jadwal yang lahir saat seseorang kebetulan membuka layar tidak
        bisa dijelaskan ke orang yang tidak membukanya.

        Kegagalannya **tidak** membatalkan perubahan rosternya. Roster
        adalah keputusan pengguna; rencana shift turunannya, dan
        turunan yang gagal tidak boleh menghapus yang asli — tinggal
        disusun ulang lewat tombol Generate Shift Baseline.
        """
        from apps.hr.api.shift_calendar.pattern import (
            RosterShiftPatternService,
        )

        employee = getattr(rotation, "employee", None)

        if employee is None:
            return {"skipped": "no_employee"}

        try:
            return RosterShiftPatternService.sync(
                employee=employee,
                user=user,
            )
        except Exception as error:  # noqa: BLE001
            logger.warning(
                "Sinkronisasi baseline shift gagal untuk %s: %s",
                getattr(employee, "employee_number", employee.pk),
                error,
            )

            return {"skipped": "error", "error": str(error)}


    @classmethod
    @transaction.atomic
    def soft_delete(cls, *, instance, user=None, **kwargs):
        """
        Menghapus dokumen roster **beserta jejaknya di dua tabel lain**.

        Soft delete tidak meng-cascade. Tanpa baris di bawah ini,
        menghapus satu rencana meninggalkan dua sisa yang sama-sama
        gagal diam:

        * `RotationPeriod`-nya tetap `is_deleted=False`, jadi seluruh
          pembaca roster — termasuk `schedule_bounds()` — masih
          menganggap jadwalnya ada
        * `EmployeeShiftAssignment` lapis `BASELINE` **tidak punya FK ke
          roster sama sekali**, jadi Shift Calendar tetap menampilkan
          shift di tanggal yang rosternya sudah dihapus

        Urutannya penting: periodenya dulu, baru sinkronisasi — kalau
        terbalik, `sync()` masih melihat blok kerja yang sebentar lagi
        hilang dan menerbitkan ulang rencana yang justru mau dibuang.
        Kegagalan sinkronisasi tidak membatalkan penghapusan; polanya
        sama dengan keempat mutasi roster lainnya.
        """
        periods = RotationPeriod.objects.filter(
            rotation=instance,
            is_deleted=False,
        )

        for period in periods:
            RotationPeriodService.soft_delete(instance=period, user=user)

        instance = super().soft_delete(
            instance=instance,
            user=user,
            **kwargs,
        )

        cls.sync_shift_baseline(instance, user=user)

        return instance


class RotationPeriodService(BaseMasterService):
    model = RotationPeriod

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = cls.apply_employee(data)
        data = cls.apply_sequence(data)

        return cls.apply_total_days(data)

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        data = cls.apply_employee(data, instance=instance)
        data = cls.apply_sequence(data, instance=instance)
        data = cls.apply_total_days(data, instance=instance)

        return cls.apply_manual_override(data, instance=instance)

    @staticmethod
    def apply_employee(
        data: dict[str, Any],
        *,
        instance: RotationPeriod | None = None,
    ) -> dict[str, Any]:
        if data.get("employee") is not None:
            return data

        rotation = data.get(
            "rotation",
            getattr(instance, "rotation", None),
        )

        if rotation is not None:
            data["employee"] = rotation.employee

        return data

    @staticmethod
    def apply_sequence(
        data: dict[str, Any],
        *,
        instance: RotationPeriod | None = None,
    ) -> dict[str, Any]:
        """
        Memberi nomor urut bebas untuk baris yang disisipkan tangan.

        Baris hasil generate selalu membawa nomornya sendiri, jadi ini
        hanya kena pada penyisipan manual — memecah satu blok off jadi
        field break + cuti tahunan, misalnya. Tanpa ini form harus
        menanyakan nomor urut yang belum terpakai, dan salah tebak
        berujung IntegrityError, bukan pesan yang bisa dibaca.
        """
        if data.get("sequence") is not None:
            return data

        # Serializer menaruh `None` sebagai bawaan untuk melewati
        # UniqueTogetherValidator, jadi nilai kosong pada baris yang sudah
        # ada berarti "jangan diubah", bukan "kosongkan".
        if instance is not None and instance.sequence:
            data["sequence"] = instance.sequence

            return data

        rotation = data.get(
            "rotation",
            getattr(instance, "rotation", None),
        )

        if rotation is None:
            return data

        last = (
            RotationPeriod.objects
            .filter(rotation=rotation, is_deleted=False)
            .order_by("-sequence")
            .values_list("sequence", flat=True)
            .first()
        )

        data["sequence"] = (last or 0) + 1

        return data

    @staticmethod
    def apply_total_days(
        data: dict[str, Any],
        *,
        instance: RotationPeriod | None = None,
    ) -> dict[str, Any]:
        # Isian manual dihormati: blok kerja yang dipotong hari travel
        # tidak selalu sama dengan selisih tanggalnya.
        if data.get("total_days") is not None:
            return data

        def resolved(field_name):
            if field_name in data:
                return data[field_name]

            return getattr(instance, field_name, None)

        start = resolved("start_date")
        end = resolved("end_date")

        if start and end and end >= start:
            data["total_days"] = (end - start).days + 1

        return data

    @staticmethod
    def apply_manual_override(
        data: dict[str, Any],
        *,
        instance: RotationPeriod,
    ) -> dict[str, Any]:
        """
        Menandai baris yang tanggalnya digeser tangan.

        Hanya perubahan tanggal yang dihitung sebagai penyesuaian.
        Mengubah status atau menambah catatan tidak boleh membuat baris
        itu kebal terhadap generate ulang — kalau iya, satu baris
        bercatatan akan memblokir seluruh dokumen.
        """
        shifted = any(
            field in data and data[field] != getattr(instance, field)
            for field in ("start_date", "end_date")
        )

        # Diperiksa lebih dulu, sebelum nilai yang dikirim form.
        # Grid inline mengirim balik seluruh isi baris — termasuk
        # `is_manual_override: false` yang barusan dibacanya dari API —
        # jadi menghormati nilai kiriman lebih dulu berarti penanda ini
        # tidak pernah bisa menyala dari satu-satunya layar yang dipakai
        # untuk menggeser tanggal.
        if shifted:
            data["is_manual_override"] = True

        return data

    # ------------------------------------------------------------------
    # Sinkronisasi ke dokumen induk
    # ------------------------------------------------------------------

    @classmethod
    def after_create(cls, *, instance, user=None, **kwargs):
        instance = super().after_create(
            instance=instance,
            user=user,
            **kwargs,
        )

        SiteRotationService.sync_end_date(instance.rotation)

        return instance

    @classmethod
    def after_update(cls, *, instance, user=None, **kwargs):
        instance = super().after_update(
            instance=instance,
            user=user,
            **kwargs,
        )

        SiteRotationService.sync_end_date(instance.rotation)

        return instance

    @classmethod
    @transaction.atomic
    def soft_delete(cls, *, instance, user=None, **kwargs):
        instance = super().soft_delete(
            instance=instance,
            user=user,
            **kwargs,
        )

        SiteRotationService.sync_end_date(instance.rotation)

        return instance
