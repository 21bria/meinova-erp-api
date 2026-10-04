"""
Service roster: preview, commit baseline, perpanjangan horizon.

Pembagian tugasnya sengaja tegas, karena tiga hal ini paling sering
tercampur dan begitu tercampur tidak bisa dipisah lagi:

* ``RosterCalculationService``   — rumus, tanpa database (``calculation.py``)
* ``RosterGenerationService``    — preview & menulis segmen
* ``RosterRecalculationService`` — menghitung ulang dari satu titik ke
  depan (``recalculation.py``)

Aturan yang berlaku di seluruh berkas ini: **segmen tidak pernah
di-UPDATE tanggalnya.** Yang ada tutup-dan-ganti lewat interval versi.
Kalau suatu saat ada yang perlu menggeser satu baris, yang benar adalah
membuat versi baru, bukan menyentuh barisnya.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass
from datetime import date
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.administration.api.numbering.services.numbering_service import (
    DocumentNumberService,
)
from apps.core.services.master import BaseMasterService

from apps.hr.api.roster.calculation import (
    CyclePattern,
    RosterCalculationService,
    SegmentRow,
)
from apps.hr.api.site_rotation.policy import RosterPolicyResolver
from apps.hr.models import (
    ROSTER_LIVE_STATUSES,
    RosterPlanVersion,
    RosterSegmentType,
    RosterVersionSource,
    RotationPeriod,
    RotationPeriodType,
    SiteRotation,
    SiteRotationStatus,
)


logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Validasi
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class Validation:
    """
    Satu temuan pada calon jadwal.

    `level` membedakan dua hal yang sangat berbeda nasibnya:
    **blocking** menghentikan commit, **warning** cuma memberi tahu.
    Menyamakan keduanya berarti salah satu dari dua kesalahan: jadwal
    yang jelas salah tetap terbit, atau pegawai yang cuma belum punya
    pasangan back-to-back tidak bisa dibuatkan jadwal sama sekali.
    """

    level: str
    code: str
    message: str

    def as_dict(self) -> dict:
        return {
            "level": self.level,
            "code": self.code,
            "message": self.message,
        }


def blocking(code: str, message: str) -> Validation:
    return Validation(level="blocking", code=code, message=message)


def warning(code: str, message: str) -> Validation:
    return Validation(level="warning", code=code, message=message)


class RosterValidator:
    """
    Pemeriksaan calon jadwal satu pegawai.

    Dipakai tiga layar sekaligus — setup satuan, baris di dokumen bulk,
    dan review sebelum submit. Satu implementasi, karena begitu ada dua,
    salah satunya akan menampilkan temuan yang berbeda dari yang
    akhirnya menghentikan penyimpanan.
    """

    @classmethod
    def check(
        cls,
        *,
        employee,
        policy,
        cycle_start: date | None,
        as_of_date: date | None = None,
        exclude_plan=None,
    ) -> list[Validation]:
        findings: list[Validation] = []

        findings += cls._check_policy(policy)
        findings += cls._check_anchor(
            employee=employee,
            cycle_start=cycle_start,
            policy=policy,
            as_of_date=as_of_date,
        )
        findings += cls._check_employment(employee)
        findings += cls._check_overlap(
            employee=employee,
            exclude_plan=exclude_plan,
        )
        findings += cls._check_partner(employee)

        return findings

    @staticmethod
    def _check_policy(policy) -> list[Validation]:
        if policy is None:
            return [
                blocking(
                    "no_policy",
                    "Pegawai ini belum ditugaskan Roster Policy, jadi "
                    "jadwalnya tidak bisa dihitung. Pegawai non-roster "
                    "(HO) memang tidak diproses generator.",
                ),
            ]

        if not policy.has_cycle_pattern:
            return [
                blocking(
                    "policy_without_pattern",
                    f"{policy.code} belum mengisi pola siklus (Work Days "
                    "/ Field Break Days). Isi polanya di master Roster "
                    "Policy, atau pilih policy lain.",
                ),
            ]

        return []

    @staticmethod
    def _check_anchor(
        *,
        employee,
        cycle_start,
        policy,
        as_of_date,
    ) -> list[Validation]:
        if cycle_start is None:
            return [
                blocking(
                    "no_cycle_start",
                    "Current Cycle Start belum diisi. Tanpa titik "
                    "jangkar, sistem tidak tahu pegawai ini sedang di "
                    "hari ke berapa siklusnya.",
                ),
            ]

        findings: list[Validation] = []

        employment = getattr(employee, "employment", None)

        termination = getattr(employment, "termination_date", None)

        if termination and cycle_start > termination:
            findings.append(
                blocking(
                    "after_termination",
                    f"Current Cycle Start ({cycle_start}) jatuh setelah "
                    f"tanggal berhenti ({termination}).",
                ),
            )

        join_date = getattr(employment, "join_date", None)

        if join_date and cycle_start < join_date:
            findings.append(
                warning(
                    "before_join_date",
                    f"Current Cycle Start ({cycle_start}) lebih awal "
                    f"dari tanggal bergabung ({join_date}).",
                ),
            )

        reference = as_of_date or timezone.localdate()

        if policy is not None and policy.cycle_length:
            elapsed = (reference - cycle_start).days

            if elapsed > policy.cycle_length:
                findings.append(
                    warning(
                        "stale_anchor",
                        f"Current Cycle Start sudah {elapsed} hari lalu, "
                        f"lebih dari satu putaran ({policy.cycle_length} "
                        "hari). Jadwal akan berangkat dari blok yang "
                        "sedang dijalani — pastikan tanggalnya memang "
                        "blok yang sekarang, bukan blok pertama dulu.",
                    ),
                )

        return findings

    @staticmethod
    def _check_employment(employee) -> list[Validation]:
        findings: list[Validation] = []

        organization = getattr(employee, "organization", None)

        if organization is None or not organization.company_id:
            findings.append(
                blocking(
                    "no_company",
                    "Pegawai ini belum punya penempatan organisasi.",
                ),
            )

        employment = getattr(employee, "employment", None)

        if employment is None:
            findings.append(
                blocking(
                    "no_employment",
                    "Pegawai ini belum punya data kepegawaian.",
                ),
            )

            return findings

        if not employment.point_of_hire_id:
            findings.append(
                warning(
                    "no_point_of_hire",
                    "Point of Hire belum diisi, jadi hari perjalanan "
                    "jatuh ke angka bawaan site — bukan ke jarak "
                    "sebenarnya.",
                ),
            )

        return findings

    @staticmethod
    def _check_overlap(*, employee, exclude_plan=None) -> list[Validation]:
        """
        Dua rencana aktif untuk satu pegawai di periode yang sama berarti
        dua jadwal yang sama-sama mengaku benar.

        Pesannya menyebut **nomor dokumen** yang menabrak. "Pegawai ini
        sudah punya roster aktif" tidak bisa ditindaklanjuti siapa pun.
        """
        queryset = (
            SiteRotation.objects
            .filter(
                employee=employee,
                is_deleted=False,
                effective_to__isnull=True,
                status__in=ROSTER_LIVE_STATUSES,
            )
        )

        if exclude_plan is not None:
            queryset = queryset.exclude(pk=exclude_plan.pk)

        existing = queryset.first()

        if existing is None:
            return []

        return [
            blocking(
                "active_plan_exists",
                f"Pegawai ini sudah punya rencana roster berjalan "
                f"({existing.document_number or f'#{existing.pk}'}, "
                f"mulai {existing.start_date}). Tutup dulu eranya, atau "
                "pakai dokumen Adjustment untuk mengubah jadwal yang "
                "sudah ada.",
            ),
        ]

    @staticmethod
    def _check_partner(employee) -> list[Validation]:
        """
        Back-to-back adalah **referensi**, jadi temuannya selalu
        warning. Pegawai tanpa pasangan tetap valid — dan tidak boleh
        ada satu jalur pun yang memblokir karena kolom ini kosong.
        """
        employment = getattr(employee, "employment", None)

        if employment is None or employment.back_to_back_partner_id:
            return []

        return [
            warning(
                "no_b2b_partner",
                "Pasangan back-to-back belum diisi. Tidak menghalangi "
                "jadwal disetujui — cuma tidak ada pembanding di layar "
                "detail.",
            ),
        ]


# ----------------------------------------------------------------------
# Generasi
# ----------------------------------------------------------------------


class RosterGenerationService:
    """Preview dan penulisan segmen."""

    @staticmethod
    def pattern_for(*, employee, policy) -> CyclePattern:
        """
        Pola pegawai: policy plus hari perjalanan menurut Point of
        Hire-nya.

        Dua pegawai dengan policy yang sama bisa berbeda di sini, dan
        itu memang yang terjadi di lapangan — yang menentukan jarak,
        bukan pola.
        """
        return CyclePattern.from_policy(
            policy,
            # Policy dioper eksplisit: kalau dibiarkan diresolve ulang
            # dari penempatan pegawai, rencana yang dibuat sebelum
            # policy-nya menempel akan mendapat nol hari perjalanan —
            # tanpa satu pun pesan.
            travel_days=RosterPolicyResolver.travel_days_for(
                employee, policy=policy,
            ),
        )

    @classmethod
    def preview(
        cls,
        *,
        employee,
        policy=None,
        cycle_start: date | None = None,
        horizon_months: int | None = None,
        as_of_date: date | None = None,
        exclude_plan=None,
    ) -> dict:
        """
        Bentuk jadwal **tanpa menulis apa pun**.

        Dipakai tiga layar: setup satuan, tiap baris dokumen bulk, dan
        review sebelum submit. Yang dikembalikan sama persis dengan yang
        akan disimpan — kalau berbeda, orang menyetujui satu jadwal dan
        mendapat jadwal yang lain.
        """
        employment = getattr(employee, "employment", None)

        if policy is None:
            resolved = RosterPolicyResolver.policy_for(employee)

            policy = (
                resolved.policy
                if resolved.source == "assignment"
                else None
            )

        if cycle_start is None:
            cycle_start = getattr(employment, "roster_cycle_start", None)

        as_of = as_of_date or timezone.localdate()

        findings = RosterValidator.check(
            employee=employee,
            policy=policy,
            cycle_start=cycle_start,
            as_of_date=as_of,
            exclude_plan=exclude_plan,
        )

        travel = RosterPolicyResolver.travel_days_for(employee)

        blocked = any(
            item.level == "blocking"
            for item in findings
        )

        if blocked:
            return {
                "segments": [],
                "summary": None,
                "travel_days_reason": travel.reason,
                "validations": [item.as_dict() for item in findings],
                "can_commit": False,
            }

        segments = cls.build(
            employee=employee,
            policy=policy,
            cycle_start=cycle_start,
            horizon_months=horizon_months,
            as_of_date=as_of,
        )

        return {
            "segments": [row.as_dict() for row in segments],
            "summary": RosterCalculationService.summarize(segments),
            "travel_days_reason": travel.reason,
            "cycle_start": cycle_start,
            "roster_start_basis": policy.roster_start_basis,
            "work_block_start": RosterCalculationService.work_block_start(
                cycle_start=cycle_start,
                pattern=cls.pattern_for(employee=employee, policy=policy),
            ),
            "validations": [item.as_dict() for item in findings],
            "can_commit": True,
        }

    @classmethod
    def build(
        cls,
        *,
        employee,
        policy,
        cycle_start: date,
        horizon_months: int | None = None,
        as_of_date: date | None = None,
    ) -> list[SegmentRow]:
        """
        Deret segmen untuk satu pegawai, berangkat dari blok yang sedang
        dijalani.

        Jangkarnya digeser maju ke awal putaran yang **sedang berjalan**
        pada `as_of_date`, bukan ke putaran berikutnya. Itu yang membuat
        pegawai yang sudah di tengah blok kerja saat sistem dipasang
        mendapat sisa harinya, bukan kehilangan seluruh blok itu.
        """
        pattern = cls.pattern_for(employee=employee, policy=policy)

        if not pattern.is_valid:
            return []

        as_of = as_of_date or timezone.localdate()

        anchor = RosterCalculationService.current_block_start(
            anchor=cycle_start,
            cycle_length=pattern.cycle_length,
            as_of=as_of,
        )

        horizon_end = RosterCalculationService.resolve_horizon(
            start=as_of,
            months=horizon_months or policy.rolling_horizon_months,
        )

        return RosterCalculationService.build_segments(
            cycle_start=anchor,
            pattern=pattern,
            horizon_end=horizon_end,
            skip_before=as_of,
        )

    # ------------------------------------------------------------------
    # Menulis
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def commit(
        cls,
        *,
        employee,
        policy,
        cycle_start: date,
        horizon_months: int | None = None,
        as_of_date: date | None = None,
        setup_line=None,
        user=None,
        status: str = SiteRotationStatus.DRAFT,
    ) -> SiteRotation:
        """
        Membuat rencana beserta versi pertamanya.

        Versi 1 belum jadi baseline di sini — baseline dikunci saat
        alurnya disetujui (`approve`). Yang dibuat sekarang cuma isi
        yang akan ditinjau.
        """
        as_of = as_of_date or timezone.localdate()

        findings = RosterValidator.check(
            employee=employee,
            policy=policy,
            cycle_start=cycle_start,
            as_of_date=as_of,
        )

        blocked = [
            item for item in findings if item.level == "blocking"
        ]

        if blocked:
            raise ValidationError(
                {
                    "roster": [item.message for item in blocked],
                },
            )

        pattern = cls.pattern_for(employee=employee, policy=policy)

        organization = getattr(employee, "organization", None)

        plan = SiteRotation(
            employee=employee,
            # Nomor dialokasikan sekali saat rencana lahir dan tidak
            # pernah dihitung ulang — dokumen penyesuaian merujuknya,
            # dan nomor yang berubah membuat rujukan itu menunjuk
            # dokumen yang berbeda dari yang dimaksud.
            document_number=DocumentNumberService.next(
                module="hr",
                document_type="site_rotation",
                company=getattr(organization, "company", None),
            ),
            company=getattr(organization, "company", None),
            branch=getattr(organization, "branch", None),
            location=getattr(organization, "location", None),
            roster_policy=policy,
            cycle_start=cycle_start,
            roster_start_basis=pattern.roster_start_basis,
            cycle_work_days=pattern.work_days,
            cycle_off_days=pattern.off_days,
            travel_out_days=pattern.travel_out_days,
            travel_in_days=pattern.travel_in_days,
            cycle_travel_days=(
                pattern.travel_out_days + pattern.travel_in_days
            ),
            travel_day_mode=policy.travel_day_mode,
            travel_creates_segment=pattern.travel_creates_segment,
            travel_out_counts_as_roster_day=(
                pattern.travel_out_counts_as_roster_day
            ),
            travel_in_counts_as_roster_day=(
                pattern.travel_in_counts_as_roster_day
            ),
            effective_from=as_of,
            status=status,
            setup_line=setup_line,
            created_by=user,
            updated_by=user,
        )

        segments = cls.build(
            employee=employee,
            policy=policy,
            cycle_start=cycle_start,
            horizon_months=horizon_months,
            as_of_date=as_of,
        )

        if not segments:
            raise ValidationError(
                {
                    "roster": (
                        "Pola ini tidak menghasilkan satu pun segmen. "
                        "Periksa Work Days / Field Break Days pada "
                        "policy."
                    ),
                },
            )

        plan.start_date = segments[0].start_date
        plan.end_date = max(row.end_date for row in segments)
        plan.horizon_end = plan.end_date
        plan.cycle_count = max(row.cycle_number for row in segments)

        plan.full_clean(exclude=["setup_line"])
        plan.save()

        version = RosterPlanVersion.objects.create(
            plan=plan,
            version_no=1,
            source=RosterVersionSource.INITIAL,
            effective_from=as_of,
            reason="Baseline awal.",
            summary=RosterCalculationService.summarize(segments),
            created_by=user,
            updated_by=user,
        )

        cls.write_segments(
            plan=plan,
            version=version,
            segments=segments,
            user=user,
        )

        plan.current_version = version
        plan.save(update_fields=["current_version", "updated_at"])

        cls.sync_assignment(
            employee=employee,
            policy=policy,
            cycle_start=cycle_start,
        )

        # Rencana shift menyusul rosternya, dan **sesudah**
        # `sync_assignment`: policy pegawai baru tersimpan di baris itu,
        # dan itulah yang dibaca sinkronisasi untuk menemukan urutan
        # perputaran shift-nya. Dibalik urutannya, rencana pertama
        # sebuah pegawai terbit tanpa shift sama sekali.
        from apps.hr.api.site_rotation.services import SiteRotationService

        SiteRotationService.sync_shift_baseline(plan, user=user)

        return plan

    @staticmethod
    def sync_assignment(*, employee, policy, cycle_start) -> None:
        """
        Menyalin policy dan jangkar ke penempatan pegawainya.

        Rencana yang terbit tanpa menyentuh assignment membuat form
        pegawai menampilkan keadaan yang berbeda dari jadwalnya sendiri —
        dan yang lebih halus: `RosterPolicyResolver` membaca policy dari
        assignment, jadi konversi rotation credit tidak menemukan
        rasionya dan diam-diam menghasilkan nol kredit.
        """
        employment = getattr(employee, "employment", None)

        if employment is None:
            return

        employment.roster_policy = policy
        employment.roster_cycle_start = cycle_start

        employment.save(
            update_fields=[
                "roster_policy",
                "roster_cycle_start",
                "updated_at",
            ],
        )

    @staticmethod
    def write_segments(
        *,
        plan: SiteRotation,
        version: RosterPlanVersion,
        segments: list[SegmentRow],
        user=None,
        lock: bool = False,
    ) -> list[RotationPeriod]:
        """
        Menulis segmen sebagai baris baru milik satu versi.

        `bulk_create` disengaja: satu rencana setahun bisa 26 baris, dan
        satu dokumen setup 30 pegawai berarti 780 penyimpanan kalau
        lewat service satu per satu. Konsekuensinya `full_clean()` tidak
        jalan — dan itu aman di sini karena seluruh nilainya berasal
        dari kalkulator, bukan dari input pengguna.
        """
        rows = [
            RotationPeriod(
                rotation=plan,
                employee=plan.employee,
                sequence=row.sequence,
                segment_type=row.segment_type,
                period_type=(
                    RotationPeriodType.WORK
                    if row.counts_as_roster_day
                    else RotationPeriodType.OFF
                ),
                counts_as_roster_day=row.counts_as_roster_day,
                cycle_number=row.cycle_number,
                start_date=row.start_date,
                end_date=row.end_date,
                planned_start_date=row.start_date,
                planned_end_date=row.end_date,
                total_days=row.total_days,
                version_from=version,
                is_locked=lock,
                created_by=user,
                updated_by=user,
            )
            for row in segments
        ]

        return RotationPeriod.objects.bulk_create(rows)

    # ------------------------------------------------------------------
    # Approval → baseline
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def lock_baseline(cls, *, plan: SiteRotation, user=None) -> SiteRotation:
        """
        Mengunci versi berjalan sebagai baseline permanen.

        Idempoten: rencana yang sudah punya baseline dibiarkan apa
        adanya. Approval yang kebetulan jalan dua kali tidak boleh
        memindahkan baseline ke versi yang lebih baru — kalau iya,
        "jadwal yang disepakati" berubah tanpa ada yang memutuskannya.
        """
        if plan.baseline_version_id:
            return plan

        version = plan.current_version

        if version is None:
            raise ValidationError(
                {
                    "roster": (
                        "Rencana ini belum punya versi apa pun — tidak "
                        "ada yang bisa dijadikan baseline."
                    ),
                },
            )

        now = timezone.now()

        version.approved_at = now
        version.approved_by = user
        version.committed_at = now

        version.save(
            update_fields=[
                "approved_at",
                "approved_by",
                "committed_at",
                "updated_at",
            ],
        )

        plan.baseline_version = version
        plan.status = SiteRotationStatus.ACTIVE
        plan.approved_at = now
        plan.approved_by = user
        plan.locked_at = now

        plan.save(
            update_fields=[
                "baseline_version",
                "status",
                "approved_at",
                "approved_by",
                "locked_at",
                "updated_at",
            ],
        )

        # Segmen yang sudah lewat dikunci; yang masih di depan tetap
        # boleh dihitung ulang lewat Adjustment.
        RotationPeriod.objects.filter(
            rotation=plan,
            is_deleted=False,
            version_to__isnull=True,
            end_date__lt=timezone.localdate(),
        ).update(is_locked=True)

        return plan

    # ------------------------------------------------------------------
    # Rolling horizon
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def extend_horizon(
        cls,
        *,
        plan: SiteRotation,
        months: int | None = None,
        until: date | None = None,
        user=None,
    ) -> list[RotationPeriod]:
        """
        Menyambung segmen baru di ujung jadwal.

        **Tidak menyentuh satu pun baris yang sudah ada** — ini menempel
        halaman baru di bawah kalender, bukan mencetak ulang
        kalendernya. Karena itu ia tidak butuh approval: tidak ada
        keputusan yang dibatalkannya.
        """
        last = (
            RotationPeriod.objects
            .filter(rotation=plan, is_deleted=False, version_to__isnull=True)
            .order_by("-end_date", "-sequence")
            .first()
        )

        if last is None:
            raise ValidationError(
                {
                    "roster": (
                        "Rencana ini belum punya satu pun segmen."
                    ),
                },
            )

        target = RosterCalculationService.resolve_horizon(
            start=timezone.localdate(),
            months=months or (
                plan.roster_policy.rolling_horizon_months
                if plan.roster_policy_id
                else None
            ),
            until=until,
        )

        if target <= last.end_date:
            return []

        pattern = cls.pattern_from_plan(plan)

        # Jenis segmen berikutnya = yang mengekor jenis terakhir di
        # dalam satu putaran. Tanpa ini sambungan selalu mulai dari blok
        # kerja, dan jadwal yang berhenti di field break jadi punya dua
        # blok kerja berturut-turut.
        blocks = RosterCalculationService._cycle_blocks(pattern)

        types = [segment_type for segment_type, _, _ in blocks]

        try:
            index = types.index(last.segment_type)
        except ValueError:
            index = len(types) - 1

        start_with = types[(index + 1) % len(types)]

        from datetime import timedelta

        segments = RosterCalculationService.build_segments(
            cycle_start=last.end_date + timedelta(days=1),
            pattern=pattern,
            horizon_end=target,
            start_sequence=last.sequence + 1,
            start_with=start_with,
            cycle_number_start=(
                last.cycle_number + 1
                if start_with == RosterSegmentType.WORK
                else last.cycle_number
            ),
        )

        if not segments:
            return []

        version = cls.new_version(
            plan=plan,
            source=RosterVersionSource.HORIZON_EXTENSION,
            effective_from=segments[0].start_date,
            reason=f"Horizon diperpanjang sampai {target}.",
            summary=RosterCalculationService.summarize(segments),
            user=user,
        )

        rows = cls.write_segments(
            plan=plan,
            version=version,
            segments=segments,
            user=user,
        )

        plan.end_date = max(row.end_date for row in segments)
        plan.horizon_end = plan.end_date
        plan.cycle_count = max(row.cycle_number for row in segments)
        plan.current_version = version

        plan.save(
            update_fields=[
                "end_date",
                "horizon_end",
                "cycle_count",
                "current_version",
                "updated_at",
            ],
        )

        return rows

    # ------------------------------------------------------------------
    # Bantuan
    # ------------------------------------------------------------------

    @staticmethod
    def pattern_from_plan(plan: SiteRotation) -> CyclePattern:
        """
        Pola yang **dibekukan** ke rencana, bukan yang berlaku di master
        sekarang.

        Ini yang membuat mengoreksi policy bulan depan tidak diam-diam
        menggeser jadwal yang sudah disetujui dan sudah dibelikan tiket.
        """
        return CyclePattern(
            work_days=plan.cycle_work_days or 0,
            off_days=plan.cycle_off_days or 0,
            travel_out_days=plan.travel_out_days or 0,
            travel_in_days=plan.travel_in_days or 0,
            travel_creates_segment=plan.travel_creates_segment,
            travel_out_counts_as_roster_day=(
                plan.travel_out_counts_as_roster_day
            ),
            travel_in_counts_as_roster_day=(
                plan.travel_in_counts_as_roster_day
            ),
            roster_start_basis=plan.roster_start_basis or "work_start",
        )

    @staticmethod
    def new_version(
        *,
        plan: SiteRotation,
        source: str,
        effective_from: date,
        reason: str,
        summary: dict | None = None,
        reference_type: str = "",
        reference_id: str = "",
        user=None,
    ) -> RosterPlanVersion:
        last = (
            RosterPlanVersion.objects
            .filter(plan=plan, is_deleted=False)
            .order_by("-version_no")
            .values_list("version_no", flat=True)
            .first()
        )

        return RosterPlanVersion.objects.create(
            plan=plan,
            version_no=(last or 0) + 1,
            source=source,
            effective_from=effective_from,
            reason=reason,
            summary=summary,
            reference_type=reference_type,
            reference_id=str(reference_id or ""),
            created_by=user,
            updated_by=user,
        )

    @staticmethod
    def segments_of(plan: SiteRotation, *, version=None):
        """
        Segmen milik satu versi, atau versi berjalan kalau tidak
        disebut.

        Baseline dibaca dengan `version=plan.baseline_version` — dan
        karena segmen masa lalu dimiliki bersama semua versi, hasilnya
        tetap utuh setelah berapa pun penyesuaian.
        """
        queryset = RotationPeriod.objects.filter(
            rotation=plan,
            is_deleted=False,
        )

        if version is None:
            return queryset.filter(version_to__isnull=True)

        from django.db.models import Q

        return queryset.filter(
            Q(version_from__version_no__lte=version.version_no),
        ).filter(
            Q(version_to__isnull=True)
            | Q(version_to__version_no__gte=version.version_no),
        )


class RosterPlanService(BaseMasterService):
    """
    CRUD tipis untuk header rencana.

    Yang berat — membangun segmen, mengunci baseline, menghitung ulang —
    ada di service di atas dan di `recalculation.py`. Di sini cuma
    penomoran dan penyalinan organisasi.
    """

    model = SiteRotation

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        if not data.get("document_number"):
            data["document_number"] = DocumentNumberService.next(
                module="hr",
                document_type="site_rotation",
                company=data.get("company"),
            )

        return data
