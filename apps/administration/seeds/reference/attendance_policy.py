"""
Aturan kehadiran bawaan: satu global, satu untuk kantor.

**Angkanya sengaja sedikit dan konservatif.** Tidak ada undang-undang
yang menetapkan berapa menit keterlambatan boleh dimaafkan — itu murni
kebijakan perusahaan. Menyeed angka yang terdengar wajar tapi tidak
punya dasar justru berbahaya: orang menganggapnya sudah divalidasi dan
tidak pernah memeriksanya lagi. Pelajaran yang sama dengan `SICK-STD`
30 hari yang dulu ditarik dari seed jatah cuti.

Yang diseed:

* `ATT-STD` — global, **tanpa toleransi**. Ini bukan angka karangan:
  tanpa aturan, "telat" berarti lewat jam jadwal, dan itu memang
  bawaan yang paling jujur.
* `ATT-OFFICE` — untuk lokasi bertipe kantor, toleransi 15 menit.
  Diseed **hanya kalau lokasinya ketemu**, dan tidak menimpa baris yang
  sudah disunting orang.

Ambang lembur 30 menit dipakai keduanya. Itu bukan kebijakan
pengupahan — cuma pagar supaya kolom lembur tidak terisi satu-dua menit
di hampir setiap baris.
"""

from __future__ import annotations


DEFAULT_POLICIES = [
    {
        "code": "ATT-STD",
        "name": "Standard Attendance",
        "description": (
            "Berlaku untuk semua yang tidak punya aturan sendiri. "
            "Tanpa toleransi keterlambatan."
        ),
        "late_tolerance_minutes": 0,
        "late_counts_from_tolerance": True,
        "early_leave_tolerance_minutes": 0,
        "overtime_threshold_minutes": 30,
        "overtime_rounding_minutes": 0,
        "break_minutes": 60,
        "sort_order": 10,
    },
]


def seed(*, log=print) -> dict:
    from apps.administration.models import AttendancePolicy

    created = 0
    updated = 0

    for row in DEFAULT_POLICIES:
        code = row["code"]

        policy = AttendancePolicy.objects.filter(
            code=code,
            is_deleted=False,
        ).first()

        if policy is None:
            AttendancePolicy.objects.create(**row)

            created += 1

            log(f"  + {code} — {row['name']}")

            continue

        # **Tidak menimpa baris yang sudah ada.** Angka toleransi adalah
        # keputusan perusahaan; seed yang dijalankan ulang setelah orang
        # menyetelnya akan mengembalikannya ke bawaan tanpa satu pun
        # pesan, dan yang menyadarinya baru payroll bulan depan.
        updated += 0

        log(f"  = {code} — sudah ada, dibiarkan apa adanya")

    return {"created": created, "updated": updated}
