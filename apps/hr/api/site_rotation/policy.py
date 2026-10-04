"""
Membaca `RosterPolicy` untuk satu pegawai.

Dipisah dari service karena yang dijawabnya — policy mana yang berlaku,
berapa hari perjalanannya, berapa rasio konversinya — dipakai di banyak
tempat: generator jadwal, pengisi awal Travel Request, penyesuaian hari
akibat mundur cuti, dan konversi rotation credit.

Fungsinya murni: masukkan pegawai, keluar angka plus alasannya. Alasan
selalu ikut karena angka hari perjalanan yang salah baru ketahuan saat
tiketnya sudah dipesan, dan saat itu orang perlu tahu dari mana angkanya
datang.

Dua peran policy, dan hanya satu yang boleh menghasilkan jadwal
------------------------------------------------------------------
**Pola roster pegawai** selalu dari `EmploymentAssignment.roster_policy`
yang ditunjuk eksplisit. Tidak ada fallback: pegawai tanpa policy adalah
pegawai non-roster (HO), dan generator tidak menyentuhnya sama sekali.

**Aturan site** dicocokkan berjenjang lewat `specificity` di antara
policy ber-`is_default`. Itu yang menjawab hari perjalanan pegawai yang
belum punya policy, dan yang mengisi nilai awal di form.

Memisahkan keduanya bukan kerapian: satu site kini boleh punya beberapa
policy, jadi "policy yang paling cocok" tidak lagi punya jawaban
tunggal — dan jadwal seseorang tidak boleh ditentukan oleh policy yang
kebetulan terpilih.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apps.administration.models import RosterPolicy


# Dipakai kalau tidak ada aturan sama sekali. Nol berarti travel
# dianggap sudah termasuk blok kerja — perilaku lama sebelum ada
# master ini, dan tetap benar untuk site yang bisa ditempuh sehari.
FALLBACK_TRAVEL_DAYS = 0


@dataclass(frozen=True)
class ResolvedPolicy:
    """
    Policy yang berlaku plus dari mana ia didapat.

    `source` menentukan apa yang boleh dilakukan dengannya:

    * ``"assignment"``   — ditunjuk pegawai, boleh dipakai generator
    * ``"site_default"`` — bawaan site, **hanya** untuk hari perjalanan
      dan pengisian awal form
    * ``None``           — pegawai non-roster
    """

    policy: RosterPolicy | None
    source: str | None
    reason: str

    @property
    def can_generate(self) -> bool:
        return (
            self.source == "assignment"
            and self.policy is not None
            and self.policy.has_cycle_pattern
        )


@dataclass(frozen=True)
class TravelDays:
    """Hari perjalanan dua arah beserta asal angkanya."""

    out_days: int
    in_days: int
    reason: str

    @property
    def total(self) -> int:
        return self.out_days + self.in_days

    # Nama lama, dipertahankan supaya pemanggil yang masih memakai total
    # pulang-pergi (`SiteRotation.cycle_travel_days`) tidak perlu diubah
    # serentak.
    @property
    def days(self) -> int:
        return self.total


@dataclass(frozen=True)
class ConversionRatio:
    """
    Perbandingan hari kerja : hari off.

    Dipakai dua arah, dan arahnya berlawanan:

    * mundur cuti atas persetujuan KTT → tambahan off = hari ÷ rasio
    * terlambat kembali karena kesalahan pegawai → tambahan on-site =
      hari × rasio
    """

    value: Decimal
    reason: str

    def off_from_deferred(self, days: int) -> int:
        """Tambahan hari off dari sekian hari mundur cuti."""
        if self.value <= 0:
            return 0

        return int(Decimal(days) / self.value)

    def onsite_from_late(self, days: int) -> int:
        """Tambahan hari on-site dari sekian hari keterlambatan."""
        return int(Decimal(days) * self.value)


class RosterPolicyResolver:
    # ------------------------------------------------------------------
    # Pencocokan
    # ------------------------------------------------------------------

    @staticmethod
    def base_queryset():
        return (
            RosterPolicy.objects
            .filter(is_deleted=False, is_active=True)
            .prefetch_related("travel_days__point_of_hire")
        )

    @classmethod
    def site_default(cls, *, company=None, location=None) -> RosterPolicy | None:
        """
        Aturan bawaan paling khusus yang cocok dengan satu penempatan.

        Dipilih lewat skor `specificity`, bukan urutan baris — hari
        perjalanan seseorang tidak boleh bergantung pada nomor id di
        database. Yang ikut dipertimbangkan **hanya** policy bawaan;
        `uniq_active_rosterpolicy_default` menjamin tidak ada dua yang
        setara.
        """
        company_id = getattr(company, "pk", company)
        location_id = getattr(location, "pk", location)

        matched = [
            policy
            for policy in cls.base_queryset().filter(is_default=True)
            # Aturan yang menyebut sasaran tertentu hanya berlaku untuk
            # sasaran itu; yang mengosongkannya berlaku untuk semua.
            if (not policy.company_id or policy.company_id == company_id)
            and (not policy.location_id or policy.location_id == location_id)
        ]

        if not matched:
            return None

        matched.sort(
            key=lambda policy: (policy.specificity, policy.pk),
            reverse=True,
        )

        return matched[0]

    @classmethod
    def policy_for(cls, employee) -> ResolvedPolicy:
        """
        Policy yang berlaku untuk satu pegawai, plus asal-usulnya.

        Urutannya sengaja tidak berjenjang untuk pola: yang ditunjuk
        penempatan **adalah** jawabannya. Bawaan site hanya melayani
        pegawai yang belum ditugaskan, dan hasilnya ditandai supaya
        tidak sampai dipakai generator.
        """
        employment = getattr(employee, "employment", None)

        assigned = getattr(employment, "roster_policy", None)

        if assigned is not None:
            return ResolvedPolicy(
                policy=assigned,
                source="assignment",
                reason=(
                    f"Ditugaskan pada data kepegawaian: {assigned.code}."
                ),
            )

        organization = getattr(employee, "organization", None)

        fallback = cls.site_default(
            company=getattr(organization, "company_id", None),
            location=getattr(organization, "location_id", None),
        )

        if fallback is None:
            return ResolvedPolicy(
                policy=None,
                source=None,
                reason=(
                    "Pegawai ini belum ditugaskan Roster Policy dan "
                    "site-nya belum punya aturan bawaan — bukan pegawai "
                    "roster."
                ),
            )

        return ResolvedPolicy(
            policy=fallback,
            source="site_default",
            reason=(
                f"Aturan bawaan site ({fallback.code}). Pegawai ini belum "
                "ditugaskan Roster Policy, jadi jadwalnya tidak digenerate."
            ),
        )

    @classmethod
    def for_employee(cls, employee) -> RosterPolicy | None:
        """
        Bentuk ringkas `policy_for()` untuk pemanggil yang cuma butuh
        angkanya (hari perjalanan, tenggat pengajuan).
        """
        return cls.policy_for(employee).policy

    # ------------------------------------------------------------------
    # Hari perjalanan
    # ------------------------------------------------------------------

    @classmethod
    def travel_days_for(cls, employee, *, policy=None) -> TravelDays:
        """
        Berjenjang: override pegawai → tabel (site, POH) → bawaan
        policy → nol.

        `policy` boleh disebut pemanggil, dan **harus** disebut kalau ia
        sudah memegang policy-nya sendiri. Tanpa itu fungsi ini
        me-resolve ulang dari penempatan pegawai dan bisa mendarat di
        policy yang berbeda — atau tidak menemukan satu pun, sehingga
        hari perjalanan jatuh ke nol untuk rencana yang policy-nya
        justru menetapkannya. Gagalnya diam: jadwalnya tetap terbit,
        cuma tanpa satu pun segmen travel.

        Yang menentukan **jarak**, bukan gelombang. Dua orang satu
        policy bisa berbeda hari perjalanannya kalau POH-nya berbeda,
        dan itu memang yang terjadi di lapangan.

        `travel_days_override` pada penempatan adalah **total
        pulang-pergi** — kolom itu sudah ada sebelum arahnya dipisah,
        dan mengubah artinya diam-diam akan menggeser jadwal pegawai
        yang sudah memakainya. Dipecah dengan pembulatan condong ke sisi
        keluar, persis seperti generator lama.
        """
        employment = getattr(employee, "employment", None)

        override = getattr(employment, "travel_days_override", None)

        if override is not None:
            return TravelDays(
                out_days=-(-override // 2),
                in_days=override // 2,
                reason=(
                    f"Diisi khusus pada data kepegawaian ({override} hari "
                    "pulang-pergi)."
                ),
            )

        if policy is None:
            policy = cls.policy_for(employee).policy

        if policy is None:
            return TravelDays(
                out_days=FALLBACK_TRAVEL_DAYS,
                in_days=FALLBACK_TRAVEL_DAYS,
                reason=(
                    "Belum ada Roster Policy untuk site ini — travel "
                    "dianggap termasuk blok kerja."
                ),
            )

        point_of_hire_id = getattr(employment, "point_of_hire_id", None)

        if point_of_hire_id:
            row = next(
                (
                    entry
                    for entry in policy.travel_days.all()
                    if not entry.is_deleted
                    and entry.point_of_hire_id == point_of_hire_id
                ),
                None,
            )

            if row is not None:
                return TravelDays(
                    out_days=row.travel_out_days,
                    in_days=row.travel_in_days,
                    reason=(
                        f"{policy.code}: {row.point_of_hire.name} → "
                        f"{row.travel_out_days} keluar / "
                        f"{row.travel_in_days} kembali."
                    ),
                )

        missing_poh = (
            " Point of Hire pegawai belum diisi."
            if not point_of_hire_id
            else f" POH-nya belum terdaftar di {policy.code}."
        )

        return TravelDays(
            out_days=policy.default_travel_out_days,
            in_days=policy.default_travel_in_days,
            reason=(
                f"Bawaan site menurut {policy.code} "
                f"({policy.default_travel_out_days} keluar / "
                f"{policy.default_travel_in_days} kembali)."
                + missing_poh
            ),
        )

    # ------------------------------------------------------------------
    # Rasio konversi
    # ------------------------------------------------------------------

    @staticmethod
    def ratio_from_pattern(
        *,
        work_days: int | None,
        off_days: int | None,
        policy: RosterPolicy | None = None,
    ) -> ConversionRatio:
        """
        Rasio kerja:off dari sepasang angka pola.

        Dihitung, bukan didaftar per pola: perusahaan yang besok memakai
        9:3 tidak perlu menunggu ada yang menambahkan barisnya di
        master. Angka yang ditetapkan policy tetap menang.
        """
        if policy is not None and policy.conversion_ratio:
            return ConversionRatio(
                value=Decimal(policy.conversion_ratio),
                reason=f"Rasio ditetapkan {policy.code}.",
            )

        work = work_days or 0
        off = off_days or 0

        if not off:
            return ConversionRatio(
                value=Decimal(0),
                reason="Pola roster belum punya hari off.",
            )

        value = (Decimal(work) / Decimal(off)).quantize(Decimal("0.01"))

        return ConversionRatio(
            value=value,
            reason=f"Dihitung dari pola {work}:{off} = {value}.",
        )

    @classmethod
    def ratio_for(cls, *, rotation, policy=None) -> ConversionRatio:
        """
        Rasio dokumen roster. Bentuk lama, dipertahankan untuk
        `SiteRotationService.adjust_by_ratio`.
        """
        return cls.ratio_from_pattern(
            work_days=rotation.cycle_work_days,
            off_days=rotation.cycle_off_days,
            policy=policy,
        )

    @classmethod
    def ratio_for_employee(cls, employee) -> ConversionRatio:
        """
        Rasio pegawai, dibaca dari policy yang ditugaskan kepadanya.

        Dipakai konversi rotation credit, yang berangkat dari pegawai —
        bukan dari dokumen roster tertentu.
        """
        resolved = cls.policy_for(employee)
        policy = resolved.policy

        if policy is None:
            return ConversionRatio(
                value=Decimal(0),
                reason="Pegawai ini belum punya Roster Policy.",
            )

        return cls.ratio_from_pattern(
            work_days=policy.cycle_work_days,
            off_days=policy.cycle_off_days,
            policy=policy,
        )
