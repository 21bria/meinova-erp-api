"""
Mengunci aturan alokasi FIFO.

`SimpleTestCase` — **tidak menyentuh database sama sekali**. Itu properti
yang harus tetap dijaga: alokasi dipakai perhitungan ulang, pratinjau, dan
perintah penghangusan, dan ketiganya harus memakai jalan yang sama. Begitu
ada yang menambahkan query ke `allocation.py`, berkas ini yang pertama
gagal.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.test import SimpleTestCase

from apps.hr.api.leave.allocation import (
    POCKET_CARRIED_OVER,
    POCKET_ENTITLEMENT,
    POCKET_OPENING,
    Claim,
    Pocket,
    allocate,
)


def d(value: str) -> Decimal:
    return Decimal(value)


class AllocationTestCase(SimpleTestCase):
    def test_yang_paling_cepat_hangus_dipakai_lebih_dulu(self):
        """
        Inti seluruh aturannya. Kalau dibalik, orang kehilangan bawaannya
        walau cutinya banyak — dan tidak ada yang bisa menjelaskan kenapa.
        """
        result = allocate(
            pockets=[
                Pocket(POCKET_ENTITLEMENT, d("12"), None),
                Pocket(POCKET_CARRIED_OVER, d("5"), date(2027, 6, 30)),
            ],
            claims=[Claim(d("3"), date(2027, 2, 1))],
        )

        self.assertEqual(result.taken(POCKET_CARRIED_OVER), d("3"))
        self.assertEqual(result.taken(POCKET_ENTITLEMENT), d("0.0"))

    def test_kantong_habis_lalu_lanjut_ke_berikutnya(self):
        result = allocate(
            pockets=[
                Pocket(POCKET_ENTITLEMENT, d("12"), None),
                Pocket(POCKET_CARRIED_OVER, d("5"), date(2027, 6, 30)),
            ],
            claims=[Claim(d("8"), date(2027, 2, 1))],
        )

        self.assertEqual(result.taken(POCKET_CARRIED_OVER), d("5"))
        self.assertEqual(result.taken(POCKET_ENTITLEMENT), d("3"))
        self.assertEqual(result.advance, d("0.0"))

    def test_saldo_awal_lebih_dulu_saat_dua_duanya_hangus(self):
        """
        Saldo awal dan bawaan tahun lalu hangus di tanggal yang sama:
        yang lebih tua asal-usulnya yang dipakai duluan.
        """
        expiry = date(2027, 3, 31)

        result = allocate(
            pockets=[
                Pocket(POCKET_ENTITLEMENT, d("12"), None),
                Pocket(POCKET_CARRIED_OVER, d("4"), expiry),
                Pocket(POCKET_OPENING, d("7"), expiry),
            ],
            claims=[Claim(d("9"), date(2027, 1, 10))],
        )

        self.assertEqual(result.taken(POCKET_OPENING), d("7"))
        self.assertEqual(result.taken(POCKET_CARRIED_OVER), d("2"))
        self.assertEqual(result.taken(POCKET_ENTITLEMENT), d("0.0"))

    def test_tanggal_hangus_lebih_awal_menang_atas_asal_usul(self):
        result = allocate(
            pockets=[
                Pocket(POCKET_OPENING, d("7"), date(2027, 12, 31)),
                Pocket(POCKET_CARRIED_OVER, d("4"), date(2027, 3, 31)),
            ],
            claims=[Claim(d("2"), date(2027, 1, 10))],
        )

        self.assertEqual(result.taken(POCKET_CARRIED_OVER), d("2"))
        self.assertEqual(result.taken(POCKET_OPENING), d("0.0"))

    def test_kantong_yang_sudah_hangus_tidak_dipakai(self):
        """
        Cuti yang diambil setelah tanggal hangus tidak boleh menggerus
        kantong yang pada hari itu sudah tidak ada — kalau boleh,
        penghangusan tidak berarti apa-apa.
        """
        result = allocate(
            pockets=[
                Pocket(POCKET_CARRIED_OVER, d("5"), date(2027, 6, 30)),
                Pocket(POCKET_ENTITLEMENT, d("12"), None),
            ],
            claims=[Claim(d("3"), date(2027, 8, 1))],
        )

        self.assertEqual(result.taken(POCKET_CARRIED_OVER), d("0.0"))
        self.assertEqual(result.taken(POCKET_ENTITLEMENT), d("3"))

    def test_batas_hangus_eksklusif(self):
        """
        Cuti yang mulai **tepat** di tanggal hangus sudah tidak boleh
        memakainya — sejajar dengan syarat penghangusan
        (`expires_at <= today` berarti sudah hangus).
        """
        expiry = date(2027, 6, 30)

        result = allocate(
            pockets=[
                Pocket(POCKET_CARRIED_OVER, d("5"), expiry),
                Pocket(POCKET_ENTITLEMENT, d("12"), None),
            ],
            claims=[Claim(d("1"), expiry)],
        )

        self.assertEqual(result.taken(POCKET_CARRIED_OVER), d("0.0"))
        self.assertEqual(result.taken(POCKET_ENTITLEMENT), d("1"))

    def test_kelebihan_jadi_cuti_dibayar_di_muka(self):
        result = allocate(
            pockets=[Pocket(POCKET_ENTITLEMENT, d("12"), None)],
            claims=[Claim(d("20"), date(2027, 5, 1))],
        )

        self.assertEqual(result.taken(POCKET_ENTITLEMENT), d("12"))
        self.assertEqual(result.advance, d("8"))

    def test_kekurangan_karena_kantong_hangus_dicatat_terpisah(self):
        """
        Kekurangan yang lahir karena kantongnya **sudah hangus** punya
        sebab berbeda dari kekurangan karena jatahnya memang habis, dan
        itu yang ditanyakan orang.
        """
        result = allocate(
            pockets=[
                Pocket(POCKET_CARRIED_OVER, d("5"), date(2027, 6, 30)),
            ],
            claims=[Claim(d("3"), date(2027, 8, 1))],
        )

        self.assertEqual(result.advance, d("3"))
        self.assertEqual(result.expired_shortfall, d("3"))

    def test_urutan_cuti_menentukan_kantongnya(self):
        """
        Dua cuti, satu sebelum tanggal hangus dan satu sesudahnya. Yang
        duluan menggerus bawaan, yang belakangan tidak bisa lagi.
        """
        result = allocate(
            pockets=[
                Pocket(POCKET_CARRIED_OVER, d("5"), date(2027, 6, 30)),
                Pocket(POCKET_ENTITLEMENT, d("12"), None),
            ],
            claims=[
                Claim(d("2"), date(2027, 3, 1)),
                Claim(d("4"), date(2027, 9, 1)),
            ],
        )

        self.assertEqual(result.taken(POCKET_CARRIED_OVER), d("2"))
        self.assertEqual(result.taken(POCKET_ENTITLEMENT), d("4"))

    def test_cuti_nol_hari_tidak_menggerus_apa_pun(self):
        """
        Pegawai roster yang cuti saat blok off-nya memotong nol hari.
        Itu sah, dan sudah jadi keputusan desain di `LeaveDayCalculator`.
        """
        result = allocate(
            pockets=[Pocket(POCKET_ENTITLEMENT, d("12"), None)],
            claims=[Claim(d("0.0"), date(2027, 5, 1))],
        )

        self.assertEqual(result.consumed, {})
        self.assertEqual(result.advance, d("0.0"))

    def test_tanpa_cuti_tidak_ada_yang_tergerus(self):
        result = allocate(
            pockets=[
                Pocket(POCKET_OPENING, d("7"), date(2027, 3, 31)),
                Pocket(POCKET_ENTITLEMENT, d("12"), None),
            ],
            claims=[],
        )

        self.assertEqual(result.consumed, {})
        self.assertEqual(result.advance, d("0.0"))

    def test_kantong_kosong_dilewati(self):
        result = allocate(
            pockets=[
                Pocket(POCKET_OPENING, d("0.0"), date(2027, 3, 31)),
                Pocket(POCKET_ENTITLEMENT, d("12"), None),
            ],
            claims=[Claim(d("2"), date(2027, 1, 5))],
        )

        self.assertEqual(result.taken(POCKET_OPENING), d("0.0"))
        self.assertEqual(result.taken(POCKET_ENTITLEMENT), d("2"))
