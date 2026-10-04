"""
Kolom klasifikasi izin pada layar Attendance.

Seluruhnya **read-only**, dan itu inti keputusannya: pembebasan lahir
dari dokumen Attendance Permission yang disetujui, bukan dari kolom yang
bisa diketik di tengah baris lain. Kolom yang bisa disunting di sini
berarti keterlambatan bisa dimaafkan tanpa satu pun tanda tangan, dan
jejaknya cuma "diubah oleh" tanpa alasan tertulis maupun approver.

Yang tampil di tabel sengaja dibatasi tiga: penanda keadaannya, menit
telat yang dimaafkan, dan menit telat yang tidak. Menampilkan kesembilan
kolom membuat tabel presensi tidak bisa dibaca di layar mana pun.
"""

from apps.framework.builders import field


PERMISSION_FIELDS = {
    "permission_state": field.select(
        tab="time",
        label="Permission",
        options=[
            {"label": "Menunggu izin", "value": "pending"},
            {"label": "Permitted", "value": "excused"},
            {"label": "Partially permitted", "value": "partial"},
            {"label": "Unauthorised", "value": "unauthorized"},
        ],
        display_key="permission_state_label",
        table=True,
        filter=True,
        search=False,
        sortable=True,
        read_only=True,
        display=True,
        help_text=(
            "Kosong = tidak ada pengecualian yang perlu dijelaskan. "
            "Diisi dari dokumen Attendance Permission, bukan diketik."
        ),
        order=140,
    ),

    "excused_late_minutes": field.integer(
        tab="time",
        label="Excused Late (min)",
        table=True,
        filter=False,
        search=False,
        sortable=True,
        read_only=True,
        display=True,
        help_text=(
            "Bagian dari keterlambatan yang tertutup izin yang "
            "disetujui. Jam tap-nya tidak berubah."
        ),
        order=141,
    ),

    "excused_early_leave_minutes": field.integer(
        tab="time",
        label="Excused Early Leave (min)",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        read_only=True,
        display=True,
        order=142,
    ),

    "permission_minutes": field.integer(
        tab="time",
        label="Temporary Out (min)",
        table=False,
        filter=False,
        search=False,
        sortable=True,
        read_only=True,
        display=True,
        help_text="Menit izin keluar sementara yang disetujui.",
        order=143,
    ),

    "is_excused_absence": field.switch(
        tab="time",
        label="Excused Absence",
        table=False,
        filter=True,
        search=False,
        sortable=False,
        read_only=True,
        display=True,
        help_text=(
            "Tidak masuk dengan izin yang disetujui — bukan mangkir. "
            "Dibayar atau tidak mengikuti Payroll Permission Rule."
        ),
        order=144,
    ),
}


# Properti model, bukan kolom database — boleh tampil, tidak boleh jadi
# dasar pengurutan di level query. Disimpan sebagai selisih yang
# diturunkan justru supaya ia tidak bisa menyimpang dari kedua kolom
# yang membentuknya.
PERMISSION_DISPLAY_FIELDS = {
    "unauthorized_late_minutes": {
        "label": "Unauthorized Late (min)",
        "table": True,
        "filter": False,
        "search": False,
        "sortable": False,
        "read_only": True,
        "order": 145,
    },

    "unauthorized_early_leave_minutes": {
        "label": "Unauthorized Early Leave (min)",
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
        "read_only": True,
        "order": 146,
    },
}
