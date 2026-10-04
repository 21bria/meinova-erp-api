"""
Tombol keputusan atas kewajiban cuti yang lahir dari presensi.

Tiga, dan urutannya mengikuti cara orang memutuskannya: **bebaskan**
kalau alasannya sah, **minta ajukan cuti** kalau tidak, dan
**terbitkan cutinya** untuk HR yang memang mencatatkannya sendiri.

`visible_when` dinilai terhadap `leave_obligation_status` yang
diturunkan serializer — bukan terhadap `leave_required_days` mentah.
Bedanya: baris yang sudah dibebaskan atau yang cutinya sudah terbit
tidak boleh lagi menawarkan tombol yang sama, dan angka mentahnya tetap
terisi di keduanya.

Ini **bukan penjagaan**. Yang menolak tetap
`AttendanceObligationService.assert_can_review()` di backend —
`visible_when` cuma menyembunyikan tombol yang pasti ditolak, supaya
penolakannya tidak datang setelah orangnya mengetik alasan.
"""

from apps.framework.builders import action


ATTENDANCE_ACTIONS = [
    action.record(
        "waive",
        label="Waive",
        icon="ShieldCheck",
        endpoint="/api/hr/attendance/{id}/waive/",
        placement="primary",
        # Hanya untuk baris yang memang menandai kewajiban dan belum
        # diselesaikan. `settled` sengaja tidak ikut: membebaskan hari
        # yang cutinya sudah disetujui berarti saldonya sudah terpotong
        # dan pembebasannya tidak mengembalikan apa pun.
        visible_when={"leave_obligation_status": ["outstanding"]},
        fields=[
            {
                "key": "reason",
                "type": "textarea",
                "label": "Alasan Pembebasan",
                "required": True,
                "help_text": (
                    "Wajib. Pembebasan tanpa alasan tertulis membuat "
                    "aturan ini kehilangan wibawanya dalam tiga bulan."
                ),
            },
        ],
    ),

    action.record(
        "require_leave",
        label="Require Leave",
        icon="CalendarClock",
        endpoint="/api/hr/attendance/{id}/require-leave/",
        placement="primary",
        # `waived` ikut: atasan boleh meninjau ulang pembebasan yang
        # ternyata salah. Service yang mencabut penanda pembebasannya,
        # supaya tidak ada baris yang dua-duanya benar sekaligus.
        visible_when={
            "leave_obligation_status": ["outstanding", "waived"],
        },
        fields=[
            {
                "key": "notes",
                "type": "textarea",
                "label": "Catatan Peninjauan",
                "required": False,
                "help_text": (
                    "Ikut terkirim ke pegawainya bersama permintaan "
                    "mengajukan cuti."
                ),
            },
            {
                "key": "days",
                "type": "decimal",
                "label": "Hari Cuti (opsional)",
                "required": False,
                "help_text": (
                    "Kosongkan untuk memakai angka menurut aturan."
                ),
            },
        ],
    ),

    action.record(
        "issue_leave",
        label="Issue Leave",
        icon="FilePlus2",
        endpoint="/api/hr/attendance/{id}/issue-leave/",
        # Dokumennya lahir sebagai **draft**, bukan langsung disetujui:
        # yang menerbitkan bukan yang berhak menyetujui, dan di seluruh
        # sistem ini saldo tidak pernah berkurang tanpa persetujuan.
        confirm={
            "title": "Terbitkan dokumen cuti?",
            "description": (
                "Dokumen cuti dibuat sebagai draft untuk tanggal ini. "
                "Saldo baru berkurang setelah cutinya disetujui."
            ),
        },
        visible_when={
            "leave_obligation_status": ["outstanding"],
        },
    ),
]
