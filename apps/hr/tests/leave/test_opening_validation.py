"""
Penilaian satu baris saldo awal terhadap tanggal berhaknya.

`SimpleTestCase` — **tidak menyentuh database sama sekali**. Penilaiannya
memang murni: tiga tanggal dan satu angka masuk, satu status dan satu
kalimat keluar. Begitu ada yang menambahkan query ke dalamnya, berkas ini
yang pertama gagal, dan itu memang gunanya.

Yang dikunci di sini justru keputusan yang paling mudah "dirapikan" orang
lain nanti: baris yang saldonya mendahului tanggal berhaknya **tidak**
ditolak dan **tidak** diubah jadi nol. Angka itu cuma dipegang klien —
bisa jadi perusahaan lamanya memang memberi cuti lebih awal — dan
satu-satunya yang bisa menjawabnya adalah HR yang memegang berkas
migrasinya. Menolaknya menghentikan migrasi; memaksanya jadi nol
menghapus data tanpa jejak.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.hr.api.leave.eligibility import (
    LeaveEligibility,
    LeaveEligibilityResolver,
    OpeningValidation,
)


GO_LIVE = date(2026, 8, 19)


def eligibility(
    *,
    join_date: date | None = date(2019, 1, 7),
    eligible_date: date | None = date(2020, 1, 7),
    reason: str = "",
) -> LeaveEligibility:
    return LeaveEligibility(
        join_date=join_date,
        eligible_date=eligible_date,
        policy=None,
        reason=reason,
    )


def classify(days, **kwargs) -> tuple[str, str]:
    return LeaveEligibilityResolver.classify(
        days=Decimal(str(days)) if days is not None else None,
        eligibility=eligibility(**kwargs),
        opening_date=GO_LIVE,
    )


class OpeningValidationTestCase(SimpleTestCase):
    # ------------------------------------------------------------------
    # Sudah berhak
    # ------------------------------------------------------------------

    def test_sudah_berhak_dengan_saldo_valid(self):
        status, reason = classify(7)

        self.assertEqual(status, OpeningValidation.VALID)

        # VALID satu-satunya status tanpa alasan: tidak ada yang perlu
        # dijelaskan tentang baris yang memang wajar.
        self.assertEqual(reason, "")

    def test_berhak_tepat_di_tanggal_go_live_ikut_valid(self):
        """
        Batasnya inklusif, dan HO003 di data peragaan persis kena ini —
        masuk 15 Agustus 2025, berhak 15 Agustus 2026, go-live 19
        Agustus 2026. Eksklusif, dan orang yang baru berhak empat hari
        sebelum migrasi ikut ditandai REVIEW tanpa sebab.
        """
        status, _ = classify(5, eligible_date=GO_LIVE)

        self.assertEqual(status, OpeningValidation.VALID)

    def test_sudah_berhak_dengan_saldo_nol_tetap_valid(self):
        """Jatahnya habis terpakai di sistem lama — itu keadaan wajar."""
        status, _ = classify(0)

        self.assertEqual(status, OpeningValidation.VALID)

    # ------------------------------------------------------------------
    # Belum berhak
    # ------------------------------------------------------------------

    def test_belum_berhak_dengan_saldo_nol_valid_dengan_catatan(self):
        """
        Barisnya tetap perlu ada di file: ia yang membuktikan orangnya
        tidak terlewat, bukan terlewat lalu kebetulan nol.
        """
        status, reason = classify(
            0,
            join_date=date(2026, 3, 2),
            eligible_date=date(2027, 3, 2),
        )

        self.assertEqual(status, OpeningValidation.NOT_YET_ELIGIBLE)
        self.assertEqual(
            OpeningValidation.label(status),
            "VALID - NOT YET ELIGIBLE",
        )
        self.assertIn("2027-03-02", reason)

    def test_belum_berhak_dengan_saldo_lebih_dari_nol_jadi_review(self):
        status, reason = classify(
            2,
            join_date=date(2025, 11, 10),
            eligible_date=date(2026, 11, 10),
        )

        self.assertEqual(status, OpeningValidation.REVIEW)

        # Alasannya menyebut **ketiga** angka yang dibutuhkan orang untuk
        # memutuskan: saldonya, tanggal berhaknya, dan tanggal masuknya.
        # Tanpa itu ia harus membuka kartu pegawai satu per satu.
        self.assertIn("2", reason)
        self.assertIn("2026-11-10", reason)
        self.assertIn("2025-11-10", reason)

    def test_pecahan_di_bawah_satu_hari_ikut_review(self):
        """
        `> 0`, bukan `>= 1`. Setengah hari yang muncul sebelum tanggal
        berhaknya sama mustahilnya dengan tujuh hari, dan pembulatan ke
        bawah akan melewatkannya diam-diam.
        """
        status, _ = classify(
            "0.5",
            join_date=date(2025, 11, 10),
            eligible_date=date(2026, 11, 10),
        )

        self.assertEqual(status, OpeningValidation.REVIEW)

    # ------------------------------------------------------------------
    # Tidak bisa dinilai
    # ------------------------------------------------------------------

    def test_tanpa_tanggal_berhak_jadi_review_bukan_valid(self):
        """
        Join Date belum diisi atau policy-nya belum ada. REVIEW, bukan
        VALID: kalau dilewatkan sebagai sah, tenant yang policy-nya
        belum diisi memposting seluruh filenya tanpa satu baris pun
        pernah diperiksa — dan langkah Review kehilangan gunanya persis
        di tenant yang paling membutuhkannya.
        """
        status, reason = classify(
            7,
            join_date=None,
            eligible_date=None,
            reason="Join Date pegawai belum diisi.",
        )

        self.assertEqual(status, OpeningValidation.REVIEW)
        self.assertEqual(reason, "Join Date pegawai belum diisi.")

    def test_tidak_bisa_dinilai_bukan_sinonim_belum_berhak(self):
        """
        `is_eligible_on` mengembalikan tiga nilai, dan `None` yang paling
        mudah ikut terbaca sebagai False. Kalau tertukar, pegawai yang
        sudah sepuluh tahun bekerja ditandai NOT YET ELIGIBLE hanya
        karena jenis cutinya belum punya policy.
        """
        unknown = eligibility(eligible_date=None)

        self.assertIsNone(unknown.is_eligible_on(GO_LIVE))
        self.assertFalse(unknown.is_known)

        known = eligibility()

        self.assertTrue(known.is_eligible_on(GO_LIVE))
        self.assertFalse(known.is_eligible_on(date(2019, 6, 1)))

    def test_tanpa_tanggal_berlaku_tidak_bisa_dinilai(self):
        """
        Tanggal berlakunya sendiri boleh kosong di file — diisi service
        dari go-live perusahaannya. Yang tidak boleh: menilainya seolah
        kosong berarti "hari ini".
        """
        status, _ = LeaveEligibilityResolver.classify(
            days=Decimal("7"),
            eligibility=eligibility(),
            opening_date=None,
        )

        self.assertEqual(status, OpeningValidation.REVIEW)

    # ------------------------------------------------------------------
    # Label
    # ------------------------------------------------------------------

    def test_label_persis_seperti_yang_dibaca_orang(self):
        self.assertEqual(
            OpeningValidation.label(OpeningValidation.VALID),
            "VALID",
        )
        self.assertEqual(
            OpeningValidation.label(OpeningValidation.REVIEW),
            "REVIEW",
        )
        self.assertEqual(
            OpeningValidation.label(OpeningValidation.ERROR),
            "ERROR",
        )

        # Kode yang tidak dikenal dikembalikan apa adanya, bukan jadi
        # string kosong: label kosong di kolom Validation terbaca seperti
        # baris yang belum dinilai.
        self.assertEqual(OpeningValidation.label("apa-saja"), "apa-saja")
