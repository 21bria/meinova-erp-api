"""
Mengunci aturan "tahun ini milik siapa".

`LeaveGoLiveResolver.owns_year` adalah satu-satunya tempat pertanyaan
itu dijawab, dan jawabannya menentukan selisih dua belas hari per orang
di kartu cuti. Ditulis sebagai `SimpleTestCase` — **tidak menyentuh
database sama sekali**, karena aturannya memang murni perbandingan
tanggal. Begitu ada yang menambahkan query ke dalamnya, berkas ini yang
pertama gagal.
"""

from __future__ import annotations

from datetime import date

from django.test import SimpleTestCase

from apps.hr.api.leave.go_live import LeaveGoLiveResolver


class FakeGoLive:
    """Cukup dua atribut — resolver tidak membaca yang lain."""

    def __init__(self, go_live_date):
        self.go_live_date = go_live_date


GO_LIVE = FakeGoLive(date(2026, 9, 1))


class OwnsYearTestCase(SimpleTestCase):
    def test_tanpa_go_live_jatah_terbit_normal(self):
        # Ini yang membuat perubahan ini tidak menggeser satu angka pun
        # di tenant yang memang mulai dari nol.
        self.assertFalse(
            LeaveGoLiveResolver.owns_year(
                None,
                year=2026,
                join_date=date(2020, 1, 1),
            ),
        )

    def test_tahun_sebelum_go_live_dipegang_sistem_lama(self):
        self.assertTrue(
            LeaveGoLiveResolver.owns_year(
                GO_LIVE,
                year=2025,
                join_date=date(2020, 1, 1),
            ),
        )

    def test_tahun_go_live_pegawai_lama_dipegang_sistem_lama(self):
        # Kasus utamanya: Sarah sudah bekerja sejak 2020, jatah 2026-nya
        # sebagian sudah terpakai di sistem lama, dan yang tersisa
        # datang lewat saldo awal.
        self.assertTrue(
            LeaveGoLiveResolver.owns_year(
                GO_LIVE,
                year=2026,
                join_date=date(2020, 1, 1),
            ),
        )

    def test_masuk_tepat_di_hari_go_live_jatahnya_dihitung_di_sini(self):
        # Batasnya eksklusif ke bawah: yang masuk **pada** hari go-live
        # tidak pernah punya saldo di sistem lama.
        self.assertFalse(
            LeaveGoLiveResolver.owns_year(
                GO_LIVE,
                year=2026,
                join_date=date(2026, 9, 1),
            ),
        )

    def test_masuk_setelah_go_live_jatahnya_dihitung_di_sini(self):
        # Cabang yang paling gampang terlewat. Kalau ikut dimatikan,
        # pegawai yang direkrut bulan depan mendapat jatah nol tanpa
        # satu pun saldo awal yang menjelaskannya.
        self.assertFalse(
            LeaveGoLiveResolver.owns_year(
                GO_LIVE,
                year=2026,
                join_date=date(2026, 10, 1),
            ),
        )

    def test_tahun_sesudah_go_live_selalu_dihitung_di_sini(self):
        self.assertFalse(
            LeaveGoLiveResolver.owns_year(
                GO_LIVE,
                year=2027,
                join_date=date(2020, 1, 1),
            ),
        )

    def test_join_date_kosong_diperlakukan_sebagai_pegawai_lama(self):
        # Menerbitkan jatah penuh untuk orang yang tanggal masuknya saja
        # belum diketahui adalah tebakan, dan tebakan itu menempel di
        # kartu cutinya.
        self.assertTrue(
            LeaveGoLiveResolver.owns_year(
                GO_LIVE,
                year=2026,
                join_date=None,
            ),
        )

    def test_go_live_tanpa_tanggal_tidak_memegang_apa_pun(self):
        self.assertFalse(
            LeaveGoLiveResolver.owns_year(
                FakeGoLive(None),
                year=2026,
                join_date=date(2020, 1, 1),
            ),
        )
