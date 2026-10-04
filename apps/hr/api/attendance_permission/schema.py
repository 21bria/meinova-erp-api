"""
Schema UI Attendance Permission.

Yang menentukan bentuk formulirnya `visible_when` pada kolom jam:
empat jenis izin memakai kolom yang berbeda, dan menampilkan keduanya
untuk semua jenis membuat separuh form selalu kosong.

**Satu kolom, satu label**, walau artinya berbeda per jenis — `end_time`
adalah "boleh datang paling lambat" untuk Late Arrival dan "jam kembali"
untuk Temporary Out. Sempat ditulis sebagai dua field tampilan
ber-`source` yang menunjuk kolom yang sama; itu dicabut, karena kunci
yang tidak dikenal serializer akan dikirim form lalu **diabaikan diam-
diam** — jam izinnya tidak pernah tersimpan dan tidak ada satu pesan pun
yang menyebutkannya. Perbedaan artinya karena itu tinggal di
`help_text`, tempat yang memang terbaca pengaju.
"""

from apps.framework.builders import action, field, tabs, ui


PERMISSION_TYPE_OPTIONS = [
    {"label": "Late Arrival", "value": "late_arrival"},
    {"label": "Early Leave", "value": "early_leave"},
    {"label": "Temporary Out", "value": "temporary_out"},
    {"label": "Full Day Permission", "value": "full_day"},
]


PERMISSION_STATUS_OPTIONS = [
    {"label": "Draft", "value": "draft"},
    {"label": "Submitted", "value": "submitted"},
    {"label": "In Review", "value": "in_review"},
    {"label": "Approved", "value": "approved"},
    {"label": "Rejected", "value": "rejected"},
    {"label": "Cancelled", "value": "cancelled"},
]


GENERAL_FIELDS = {
    "document_number": field.text(
        tab="general",
        label="Document No.",
        read_only=True,
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        help_text="Terbit otomatis saat izin disimpan.",
        order=10,
    ),

    "employee": field.lookup(
        tab="general",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="employee_name",
        # Autofill organisasi dibuang 21 Sep 2026: ketiga kolom itu
        # bukan isian lagi, dan yang mengisinya backend dari penempatan
        # pegawai. Autofill yang menulis ke kolom yang tidak dikirim
        # cuma kontrak mati yang menyesatkan pembacanya.
        required=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    "permission_type": field.select(
        tab="general",
        label="Permission Type",
        display_key="permission_type_label",
        options=PERMISSION_TYPE_OPTIONS,
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Menentukan kolom jam mana yang diisi. Izin kehadiran "
            "bukan cuti — saldo cuti tidak berkurang karenanya."
        ),
        order=30,
    ),

    "date": field.date(
        tab="general",
        label="Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Tanggal shift-nya. Shift malam yang izinnya lewat tengah "
            "malam tetap memakai tanggal shift dimulai."
        ),
        order=40,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        display_key="status_label",
        options=PERMISSION_STATUS_OPTIONS,
        read_only=True,
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text="Berpindah lewat tombol alur, bukan lewat form.",
        order=50,
    ),
}


TIME_FIELDS = {
    "start_time": field.time(
        tab="time",
        label="Start Time",
        required=False,
        # Bukan kolom tabel: `time_window` sudah menggabungkan keduanya
        # jadi satu kalimat yang artinya benar per jenis izin. Dua
        # kolom jam yang separuhnya selalu kosong tidak menjawab apa pun.
        table=False,
        filter=False,
        search=False,
        sortable=True,
        # Dipakai dua tipe dengan arti yang berbeda: jam keluar
        # (Temporary Out) dan jam paling awal boleh pulang (Early
        # Leave). Full Day dan Late Arrival tidak memakainya sama
        # sekali, dan service mengosongkannya sendiri.
        visible_when={
            "field": "permission_type",
            "op": "in",
            "value": ["early_leave", "temporary_out"],
        },
        help_text=(
            "Early Leave: boleh pulang mulai jam ini. "
            "Temporary Out: jam keluar."
        ),
        order=110,
    ),

    "end_time": field.time(
        tab="time",
        label="End Time",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        visible_when={
            "field": "permission_type",
            "op": "in",
            "value": ["late_arrival", "temporary_out"],
        },
        help_text=(
            "Late Arrival: boleh datang paling lambat jam ini — "
            "keterlambatan sampai batas ini jadi Excused Late, "
            "selebihnya tetap tanpa izin. Temporary Out: jam kembali; "
            "lebih kecil dari jam keluar dianggap lewat tengah malam."
        ),
        order=120,
    ),
}


REASON_FIELDS = {
    "reason": field.textarea(
        tab="reason",
        label="Reason",
        rows=3,
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        order=210,
    ),

    "supporting_document": field.file(
        tab="reason",
        label="Attachment",
        accept=".pdf,.jpg,.jpeg,.png",
        max_size_mb=5,
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        help_text="Surat, undangan, atau dokumen pendukung lainnya.",
        order=220,
    ),

    "notes": field.textarea(
        tab="reason",
        label="Notes",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=230,
    ),
}


OVERRIDE_FIELDS = {
    "allow_outside_shift": field.switch(
        tab="override",
        label="Allow Outside Shift (HR Override)",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        help_text=(
            "Bawaannya izin harus jatuh di dalam jam kerja pegawai. "
            "Nyalakan hanya kalau jadwalnya memang belum tersusun atau "
            "baru berubah setelah izinnya diajukan."
        ),
        order=310,
    ),

    "outside_shift_reason": field.textarea(
        tab="override",
        label="Override Reason",
        rows=2,
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        # `not` + `is_false`, bukan `is_true`: di layar create nilainya
        # belum ada, dan `is_true` atas nilai yang belum ada berarti
        # sembunyi — kolomnya hilang dari form record baru.
        visible_when={
            "not": {"field": "allow_outside_shift", "op": "is_false"},
        },
        help_text="Wajib diisi saat override dinyalakan.",
        order=320,
    ),
}


# **Diturunkan server, bukan diisi client.** Sejak 21 Sep 2026
# serializer tidak lagi menerima ketiganya: nilainya selalu diambil dari
# penempatan pegawai (`apply_organization`), dan sebelum itu
# `disabled=True` di sini cuma pagar tampilan — satu request berisi
# `"location": <id>` tetap memindahkan dokumen ke unit lain.
#
# Tetap ditampilkan (bukan `read_only` pada schema) supaya tab ini
# memperlihatkan organisasi yang **berlaku** untuk dokumennya; yang
# dikirim balik dari sana diabaikan backend.
ORGANIZATION_FIELDS = {
    "company": field.lookup(
        tab="organization",
        label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        overview=True,
        overview_order=80,
        help_text="Diisi otomatis dari penempatan pegawai.",
        order=410,
    ),

    "branch": field.lookup(
        tab="organization",
        label="Branch",
        lookup_endpoint="/api/administration/organization/lookup/branches/",
        display_key="branch_name",
        depends_on="company",
        lookup_params={"company": "company"},
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        order=420,
    ),

    "location": field.lookup(
        tab="organization",
        label="Location",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="location_name",
        depends_on="company",
        lookup_params={"company": "company"},
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        overview=True,
        overview_order=90,
        order=430,
    ),
}


ATTENDANCE_PERMISSION_FIELDS = {
    **GENERAL_FIELDS,
    **TIME_FIELDS,
    **REASON_FIELDS,
    **OVERRIDE_FIELDS,
    **ORGANIZATION_FIELDS,
}


# Kolom turunan serializer. Boleh tampil, tidak boleh jadi dasar
# pengurutan di level query.
DISPLAY_FIELDS = {
    "employee_number": field.text(
        column_after="employee",
        label="Employee No.",
        read_only=True,
        table=True,
        search=True,
        sortable=True,
        order=15,
    ),

    # Jendela izin sebagai satu kalimat pendek. Satu kolom "Time" yang
    # bisa dibaca tanpa membuka dokumennya — `start_time` dan
    # `end_time` berdiri sendiri artinya berbeda per jenis izin, dan
    # dua kolom yang separuhnya selalu kosong tidak menjawab apa pun.
    "time_window": {
        "label": "Time",
        "table": True,
        "filter": False,
        "search": False,
        "sortable": False,
        "read_only": True,
        "column_after": "date",
        "order": 45,
    },

    # Meja yang sedang menahan dokumen ini. Disiapkan viewset sekali
    # per halaman, bukan ditanyakan per baris.
    "current_approver": {
        "label": "Current Approver",
        "table": True,
        "filter": False,
        "search": False,
        "sortable": False,
        "read_only": True,
        "order": 55,
    },

    "duration_minutes": {
        "label": "Duration (min)",
        "table": True,
        "filter": False,
        "search": False,
        "sortable": False,
        "order": 150,
    },

    # ------------------------------------------------------------------
    # Stempel waktu keputusan: **bukan** kolom tabel
    # ------------------------------------------------------------------
    #
    # Keempatnya terisi otomatis dari introspeksi model dengan
    # `table=True`, dan hasilnya empat kolom datetime yang tiga di
    # antaranya selalu kosong untuk baris mana pun — satu dokumen cuma
    # bisa berakhir di satu keadaan. Yang menjawab "sudah sampai mana"
    # kolom Status di sebelahnya; kapan persisnya dibaca di detail.
    # `display` sengaja **tidak** dinyalakan: yang menyalakannya akan
    # menyeret keempatnya masuk ke form — termasuk form create, tempat
    # semuanya pasti kosong. Yang membacanya panel Overview dan riwayat
    # persetujuan.
    #
    # Hanya dua yang masuk Overview. Satu dokumen cuma bisa berakhir di
    # satu keadaan, jadi empat baris yang tiga di antaranya selalu
    # kosong adalah kebisingan yang sama dengan empat kolom tabel tadi;
    # kapan ditolak atau dibatalkan terbaca di riwayat persetujuan,
    # lengkap dengan siapa dan alasannya.
    "submitted_at": {
        "label": "Submitted At",
        "table": False,
        "filter": False,
        "search": False,
        "read_only": True,
        "overview": True,
        "overview_order": 60,
        "overview_format": "datetime",
        "order": 610,
    },

    "approved_at": {
        "label": "Approved At",
        "table": False,
        "filter": False,
        "search": False,
        "read_only": True,
        "overview": True,
        "overview_order": 70,
        "overview_format": "datetime",
        "order": 620,
    },

    "rejected_at": {
        "label": "Rejected At",
        "table": False,
        "filter": False,
        "search": False,
        "read_only": True,
        "order": 630,
    },

    "cancelled_at": {
        "label": "Cancelled At",
        "table": False,
        "filter": False,
        "search": False,
        "read_only": True,
        "order": 640,
    },

    # Tiga blok yang membuat layar approval bisa dinilai tanpa membuka
    # layar lain: jadwal yang dimintakan kelonggarannya, presensi
    # sesungguhnya, dan peringatan tabrakan.
    "shift": {
        "label": "Scheduled Shift",
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
        "order": 500,
    },

    "attendance": {
        "label": "Actual Attendance",
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
        "order": 510,
    },

    "conflicts": {
        "label": "Conflicts",
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
        "order": 520,
    },

    "approval": {
        "label": "Approval",
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
        "order": 530,
    },
}


ATTENDANCE_PERMISSION_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="time",
        label="Time",
        fields=list(TIME_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
    tabs.form(
        key="reason",
        label="Reason & Attachment",
        fields=list(REASON_FIELDS.keys()),
        order=30,
        show_on_create=True,
    ),
    # Hanya untuk pemegang `hr.override_attendancepermission`. FE
    # menyaringnya lewat `useAccess().can()`; yang menegakkan tetap
    # serializer di backend.
    tabs.form(
        key="override",
        label="HR Override",
        fields=list(OVERRIDE_FIELDS.keys()),
        order=40,
        show_on_create=True,
        permission="hr.override_attendancepermission",
    ),
    # Tab "Organization" dibuang 21 Sep 2026. Isinya tiga kolom yang
    # sekarang diturunkan server, jadi sebagai formulir ia kosong;
    # nilainya muncul di panel ringkasan lewat `overview=True`.

    # Tab peninjauan: jadwal, presensi sesungguhnya, peringatan
    # tabrakan, dan jejak persetujuan — empat hal yang harus dilihat
    # bersamaan saat approver memutuskan.
    #
    # **`custom`, bukan `form`**, karena isinya bukan field yang bisa
    # disunting melainkan blok konteks yang dikirim serializer sebagai
    # objek (`shift`, `attendance`, `conflicts`, `approval`). Frontend
    # mengisinya lewat slot bernama sama dengan `key` ini.
    #
    # `requires_record=True`: tidak ada satu pun isinya yang punya arti
    # sebelum dokumennya tersimpan — presensi hari itu belum bisa
    # dicari, dan alurnya belum berjalan.
    tabs.custom(
        key="review",
        label="Review & Attendance",
        component="AttendancePermissionReview",
        requires_record=True,
        order=60,
    ),
]


# `visible_when` di sini **bukan** penjagaan. Yang menolak tetap
# `AttendancePermissionService` di backend — ini cuma supaya tombol yang
# pasti ditolak tidak ditawarkan, dan penolakannya tidak datang setelah
# orangnya mengetik alasan.
ATTENDANCE_PERMISSION_ACTIONS = [
    action.custom(
        "submit",
        label="Submit for Approval",
        icon="Send",
        variant="default",
        placement="primary",
        modes=["edit"],
        endpoint="/api/hr/attendance-permissions/{id}/submit/",
        method="post",
        refresh=True,
        visible_when={"status": ["draft", "rejected"]},
        confirm={
            "title": "Ajukan izin kehadiran?",
            "description": (
                "Dokumen dikirim ke alur persetujuan dan tidak bisa "
                "disunting sampai keputusannya keluar."
            ),
        },
    ),

    action.custom(
        "approve",
        label="Approve",
        icon="CheckCircle2",
        variant="default",
        placement="primary",
        modes=["edit"],
        endpoint="/api/hr/attendance-permissions/{id}/approve/",
        method="post",
        refresh=True,
        visible_when={"approval.can_act": True},
        confirm={
            "title": "Setujui izin ini?",
            "description": (
                "Presensi pada tanggal tersebut langsung dihitung "
                "ulang. Jam tap-nya tidak berubah — yang berubah "
                "klasifikasinya."
            ),
        },
    ),

    action.custom(
        "reject",
        label="Reject",
        icon="XCircle",
        variant="destructive",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/attendance-permissions/{id}/reject/",
        method="post",
        refresh=True,
        visible_when={"approval.can_act": True},
        fields=[
            {
                "key": "notes",
                "type": "textarea",
                "label": "Alasan Penolakan",
                "required": True,
            },
        ],
    ),

    action.custom(
        "cancel",
        label="Cancel",
        icon="RotateCcw",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/attendance-permissions/{id}/cancel/",
        method="post",
        refresh=True,
        visible_when={
            "status": ["submitted", "in_review", "approved"],
        },
        fields=[
            {
                "key": "notes",
                "type": "textarea",
                "label": "Alasan Pembatalan",
                "required": False,
            },
        ],
        confirm={
            "title": "Batalkan izin ini?",
            "description": (
                "Izin yang sudah disetujui berhenti berlaku dan "
                "presensinya dihitung ulang tanpa pembebasan. Yang "
                "belum disetujui kembali ke Draft."
            ),
        },
    ),
]


ATTENDANCE_PERMISSION_UI = {
    **ui.workspace(
        title="Attendance Permission",
        description=(
            "Izin kehadiran di luar cuti: datang terlambat, pulang "
            "lebih awal, keluar sementara, atau tidak masuk satu hari."
        ),
        size="full",
        columns=2,
        create=True,
        edit=True,
        delete=True,
        bulk_delete=False,
        export=True,
    ),
}


ATTENDANCE_PERMISSION_SCHEMA = {
    "module": "hr/attendance-permissions",
    "name": "Attendance Permission",
    "label": "Attendance Permission",
    "endpoint": "/api/hr/attendance-permissions/",
    "schema_type": "crud",

    "ui": ATTENDANCE_PERMISSION_UI,
    "tabs": ATTENDANCE_PERMISSION_TABS,
    "actions": ATTENDANCE_PERMISSION_ACTIONS,
    "fields": {
        **ATTENDANCE_PERMISSION_FIELDS,
        **DISPLAY_FIELDS,
    },
}
