"""
Mengunci penurunan keadaan kewajiban cuti di baris presensi.

`SimpleTestCase` — instance dibuat di memori, tidak disimpan, dan tidak
satu pun test di sini menyentuh database. Itu mungkin karena keduanya
memang properti murni; begitu ada yang menambahkan query ke
`leave_obligation_status`, berkas ini yang pertama gagal.

Yang dijaga di sini satu hal: **angka menurut aturan tidak boleh hilang
oleh keputusan orang.** `leave_required_days` tetap utuh di belakang
pembebasan maupun angka yang ditetapkan atasan — kalau tidak, pembebasan
tidak bisa dibedakan dari aturan yang memang tidak menyala, dan
pertanyaan "kenapa orang ini tidak dipotong" kehilangan jawabannya.
"""

from __future__ import annotations

from decimal import Decimal

from django.test import SimpleTestCase

from apps.hr.models import EmployeeAttendance


def row(**kwargs) -> EmployeeAttendance:
    return EmployeeAttendance(**kwargs)


class LeaveRequiredEffectiveTestCase(SimpleTestCase):
    def test_tanpa_penanda_nol(self):
        self.assertEqual(
            row().leave_required_effective,
            Decimal("0.00"),
        )

    def test_ikut_aturan_kalau_tidak_ada_keputusan(self):
        self.assertEqual(
            row(leave_required_days=Decimal("0.50"))
            .leave_required_effective,
            Decimal("0.50"),
        )

    def test_override_menang_atas_aturan(self):
        item = row(
            leave_required_days=Decimal("0.50"),
            leave_required_override=Decimal("1.00"),
        )

        self.assertEqual(item.leave_required_effective, Decimal("1.00"))

        # Angka menurut aturan tetap utuh di belakangnya.
        self.assertEqual(item.leave_required_days, Decimal("0.50"))

    def test_override_nol_sah(self):
        """
        Nol yang **diketik** berbeda artinya dari kolom yang kosong:
        yang pertama keputusan, yang kedua belum diputuskan. Kalau nol
        diperlakukan sebagai "tidak diisi", atasan tidak punya cara
        menurunkan potongan jadi nol tanpa membebaskan.
        """
        item = row(
            leave_required_days=Decimal("0.50"),
            leave_required_override=Decimal("0.00"),
        )

        self.assertEqual(item.leave_required_effective, Decimal("0.00"))

    def test_pembebasan_menang_atas_apa_pun(self):
        item = row(
            leave_required_days=Decimal("0.50"),
            leave_required_override=Decimal("1.00"),
            leave_required_waived=True,
        )

        self.assertEqual(item.leave_required_effective, Decimal("0.00"))
        self.assertEqual(item.leave_required_days, Decimal("0.50"))


class LeaveObligationStatusTestCase(SimpleTestCase):
    def test_tanpa_kewajiban(self):
        self.assertEqual(row().leave_obligation_status, "none")

    def test_belum_diselesaikan(self):
        self.assertEqual(
            row(leave_required_days=Decimal("0.50"))
            .leave_obligation_status,
            "outstanding",
        )

    def test_dibebaskan(self):
        self.assertEqual(
            row(
                leave_required_days=Decimal("0.50"),
                leave_required_waived=True,
                leave_required_waiver_reason="Ban bocor",
            ).leave_obligation_status,
            "waived",
        )

    def test_override_nol_bukan_pembebasan(self):
        """
        Keduanya menghasilkan potongan nol, tapi artinya berbeda: yang
        satu keputusan "hari ini tidak dipotong", yang satu "aturannya
        memang tidak menyala". Labelnya harus ikut berbeda.
        """
        item = row(
            leave_required_days=Decimal("0.50"),
            leave_required_override=Decimal("0.00"),
        )

        self.assertEqual(item.leave_obligation_status, "none")

    def test_label_terbaca(self):
        self.assertEqual(
            row(
                leave_required_days=Decimal("0.50"),
            ).leave_obligation_label,
            "Belum diselesaikan",
        )
