"""
Kapan seorang pegawai mulai berhak atas sebuah jenis cuti.

Sepotong kecil dari apa yang nanti jadi Eligibility Engine, dan sengaja
sebatas yang dibutuhkan langkah import saldo awal: **tanggal berhaknya**
dan **penilaian satu baris file** terhadap tanggal itu. Perhitungan
jatahnya sendiri tetap milik `LeaveEntitlementCalculator` — dua penghitung
untuk angka yang sama adalah cara paling pasti membuat keduanya berbeda.

Kenapa ini perlu ada saat import, bukan nanti
---------------------------------------------
Angka yang datang dari sistem lama tidak bisa diperiksa sistem ini: ia
tidak punya histori pemakaiannya. Satu-satunya hal yang **bisa**
diperiksa adalah kelayakannya — Sultan masuk 10 November 2025 dan baru
berhak 10 November 2026, jadi saldo 2 hari per go-live 19 Agustus 2026
itu mustahil menurut aturan yang berlaku di sini.

Yang tidak boleh dilakukan terhadap temuan itu: menolaknya, atau
mengubahnya jadi nol. Dua-duanya membuang informasi yang cuma dipegang
klien — bisa jadi perusahaan lamanya memang memberi cuti lebih awal, dan
itu keputusan yang sudah diambil sebelum sistem ini ada. Yang benar
menandainya REVIEW dan menyerahkannya ke orang, karena satu-satunya yang
tahu jawabannya adalah HR yang memegang berkas migrasinya.

Nol **bukan** temuan. Pegawai yang belum berhak memang saldonya nol, dan
barisnya tetap perlu ada di file: ia yang membuktikan orangnya tidak
terlewat, bukan terlewat lalu kebetulan nol.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from apps.administration.models import LeavePolicy

from .entitlement import LeavePolicyResolver, add_months


class OpeningValidation:
    """
    Empat keadaan sebuah baris saldo awal, dan hanya satu yang menahan.

    Labelnya ikut di sini — bukan diturunkan frontend dari kodenya —
    supaya kalimat yang sama muncul di layar preview, di daftar Review,
    dan di laporan error. Tiga penerjemah untuk satu kode adalah cara
    "VALID - NOT YET ELIGIBLE" berbunyi tiga macam di tiga layar.
    """

    VALID = "valid"
    NOT_YET_ELIGIBLE = "not_yet_eligible"
    REVIEW = "review"

    # Barisnya ditolak pipeline — pegawainya tidak ada, tanggalnya tidak
    # terbaca, saldonya negatif. Ini satu-satunya yang tidak bisa
    # di-confirm; tiga di atas semuanya boleh masuk sebagai draft.
    ERROR = "error"

    LABELS = {
        VALID: "VALID",
        NOT_YET_ELIGIBLE: "VALID - NOT YET ELIGIBLE",
        REVIEW: "REVIEW",
        ERROR: "ERROR",
    }

    @classmethod
    def label(cls, status: str) -> str:
        return cls.LABELS.get(status, status)


@dataclass(frozen=True)
class LeaveEligibility:
    """Hasil untuk satu pegawai, satu jenis cuti."""

    join_date: date | None
    eligible_date: date | None
    policy: LeavePolicy | None

    # Kenapa `eligible_date` kosong, kalau memang kosong. Tanpa ini
    # kolom Eligible Date yang kosong di layar preview tidak bisa
    # dibedakan dari kolom yang gagal dihitung.
    reason: str = ""

    @property
    def is_known(self) -> bool:
        return self.eligible_date is not None

    def is_eligible_on(self, when: date | None) -> bool | None:
        """
        True / False / None — dan `None` bukan sinonim False.

        `None` berarti **tidak bisa dinilai** (Join Date belum diisi,
        atau jenis cutinya belum punya policy). Memperlakukannya sebagai
        "belum berhak" akan menandai NOT YET ELIGIBLE untuk orang yang
        sudah bekerja sepuluh tahun, dan penilaian yang salah lebih
        merugikan daripada penilaian yang mengaku tidak tahu.
        """
        if self.eligible_date is None or when is None:
            return None

        return self.eligible_date <= when


class LeaveEligibilityResolver:
    """
    Instansiabel, dan itu yang membuatnya boleh dipakai per baris.

    Satu instance = satu file import atau satu halaman daftar, dengan
    memo di dalamnya. `LeavePolicyResolver.resolve` menembak satu query
    tiap dipanggil; tanpa memo, preview 300 baris berarti 300 query
    untuk aturan yang lazimnya cuma satu baris di seluruh tenant.

    Kuncinya empat nilai yang sama dengan yang dibaca `resolve` —
    company, employee group, employment type, jenis cuti. Memakai
    `employee.pk` sebagai kunci juga benar tapi tidak pernah kena:
    tiap pegawai muncul sekali per file.
    """

    def __init__(self) -> None:
        self._policies: dict[tuple, LeavePolicy | None] = {}

    def policy_for(self, employee, leave_type) -> LeavePolicy | None:
        organization = getattr(employee, "organization", None)
        employment = getattr(employee, "employment", None)

        key = (
            getattr(organization, "company_id", None),
            getattr(employment, "employee_group_id", None),
            getattr(employment, "employment_type_id", None),
            getattr(leave_type, "pk", None),
        )

        if key not in self._policies:
            self._policies[key] = LeavePolicyResolver.resolve(
                employee=employee,
                leave_type=leave_type,
            )

        return self._policies[key]

    def for_employee(self, employee, leave_type) -> LeaveEligibility:
        employment = getattr(employee, "employment", None)
        join_date = getattr(employment, "join_date", None)

        policy = (
            self.policy_for(employee, leave_type)
            if employee is not None and leave_type is not None
            else None
        )

        if join_date is None:
            return LeaveEligibility(
                join_date=None,
                eligible_date=None,
                policy=policy,
                reason=(
                    "Join Date pegawai belum diisi, jadi tanggal "
                    "berhaknya tidak bisa dihitung."
                ),
            )

        if policy is None:
            code = getattr(leave_type, "code", "-")

            return LeaveEligibility(
                join_date=join_date,
                eligible_date=None,
                policy=None,
                reason=(
                    f"Belum ada Leave Policy untuk {code}, jadi masa "
                    f"tunggunya tidak diketahui."
                ),
            )

        # Masa tunggu nol = berhak sejak hari pertama, dan `add_months`
        # dengan 0 memang mengembalikan tanggal masuknya sendiri. Tidak
        # perlu cabang khusus.
        months = int(policy.eligible_after_months or 0)

        return LeaveEligibility(
            join_date=join_date,
            eligible_date=add_months(join_date, months),
            policy=policy,
            reason="",
        )

    # ------------------------------------------------------------------
    # Penilaian satu baris
    # ------------------------------------------------------------------

    @staticmethod
    def classify(
        *,
        days: Decimal | None,
        eligibility: LeaveEligibility,
        opening_date: date | None,
    ) -> tuple[str, str]:
        """
        Status + alasannya untuk satu baris saldo awal.

        Alasannya selalu terisi kecuali untuk VALID: status yang tidak
        bisa dijelaskan akan diperdebatkan tiap kali muncul, dan yang
        memperdebatkannya tidak punya bahan selain menebak.
        """
        eligible = eligibility.is_eligible_on(opening_date)

        if eligible is None:
            # Tidak bisa dinilai. REVIEW, bukan VALID: kalau dilewatkan
            # sebagai sah, satu tenant yang policy-nya belum diisi akan
            # memposting seluruh filenya tanpa satu baris pun pernah
            # diperiksa — dan langkah Review kehilangan gunanya persis
            # di tenant yang paling membutuhkannya.
            return OpeningValidation.REVIEW, eligibility.reason

        if eligible:
            return OpeningValidation.VALID, ""

        amount = days if days is not None else Decimal("0")

        if amount > 0:
            return (
                OpeningValidation.REVIEW,
                (
                    f"Saldo {amount} hari padahal baru berhak "
                    f"{eligibility.eligible_date} (masuk "
                    f"{eligibility.join_date}). Periksa data migrasinya "
                    f"— angkanya tidak diubah dan tidak ditolak."
                ),
            )

        # Nol dan belum berhak: benar, dan barisnya tetap perlu ada.
        return (
            OpeningValidation.NOT_YET_ELIGIBLE,
            (
                f"Belum berhak sampai {eligibility.eligible_date} "
                f"(masuk {eligibility.join_date})."
            ),
        )
