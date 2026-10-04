from apps.framework.builders import field, tabs, ui


GENERAL_FIELDS = {
    "employee": field.lookup(
        tab="general",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="employee_name",
        required=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        order=10,
    ),

    "leave_type": field.lookup(
        tab="general",
        label="Leave Type",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/leave-types/"
        ),
        display_key="leave_type_name",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=20,
    ),

    "year": field.integer(
        tab="general",
        label="Year",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=30,
    ),
}


QUOTA_FIELDS = {
    "entitlement": field.decimal(
        tab="quota",
        label="Entitlement",
        decimal_places=1,
        max_digits=6,
        required=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        help_text="Jatah cuti tahun berjalan, dalam hari.",
        order=110,
    ),

    "carried_over": field.decimal(
        tab="quota",
        label="Carried Over",
        decimal_places=1,
        max_digits=6,
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        help_text="Sisa cuti tahun sebelumnya yang dibawa.",
        order=120,
    ),

    # Kantong saldo awal migrasi. Read-only karena dijumlah ulang dari
    # dokumen Leave Opening Balance — `display=True` supaya tetap
    # dirender di form: generator membuang field read-only dari
    # `form.ts`, dan tanpa penanda itu kolomnya hilang tanpa satu pun
    # pesan.
    "opening_balance": field.decimal(
        tab="quota",
        label="Opening Balance",
        decimal_places=1,
        max_digits=6,
        required=False,
        readonly=True,
        display=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        help_text=(
            "Saldo awal saat ERP mulai dipakai. Diubah lewat dokumen "
            "Leave Opening Balance, bukan dari layar ini."
        ),
        order=125,
    ),

    "opening_expires_at": field.date(
        tab="quota",
        label="Opening Expires",
        required=False,
        readonly=True,
        display=True,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        help_text="Tanggal saldo awal hangus. Kosong = tidak hangus.",
        order=126,
    ),

    "adjustment": field.decimal(
        tab="quota",
        label="Adjustment",
        decimal_places=1,
        max_digits=6,
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        help_text=(
            "Koreksi manual, boleh negatif. Tidak berasal dari "
            "record cuti."
        ),
        order=130,
    ),

    # Dihitung ulang dari record EmployeeLeave setiap kali cuti
    # berubah, jadi tidak bisa diisi lewat form.
    "used": field.decimal(
        tab="quota",
        label="Used",
        decimal_places=1,
        max_digits=6,
        required=False,
        readonly=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text="Terisi otomatis dari record cuti yang tercatat.",
        order=140,
    ),

    "notes": field.textarea(
        tab="quota",
        label="Notes",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=150,
    ),
}


LEAVE_BALANCE_FIELDS = {
    **GENERAL_FIELDS,
    **QUOTA_FIELDS,
}


LEAVE_BALANCE_DISPLAY_FIELDS = {
    "employee_name": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    # Nomor pegawai jadi kolom tersendiri, bukan ikut tenggelam di
    # kolom Employee: kartu cuti dibaca berdampingan dengan file dari
    # klien, dan yang dicocokkan orang di sana nomornya.
    "employee_number": field.text(
        # Duduk di sebelah kolom Employee, bukan terlempar ke ujung
        # kanan tabel — lihat `column_after` di columns.mjs.
        column_after="employee",
        label="Employee No.",
        read_only=True,
        table=True,
        search=True,
        sortable=True,
        order=5,
    ),
    "leave_type_name": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    # Properti model, bukan kolom database — bisa ditampilkan tapi
    # tidak bisa disortir di level query.
    "remaining": {
        "label": "Remaining",
        "table": True,
        "filter": False,
        "search": False,
        "sortable": False,
        "overview": True,
        "order": 160,
    },

    # ------------------------------------------------------------------
    # Rincian pemakaian per kantong
    # ------------------------------------------------------------------
    #
    # Sengaja **tidak** ikut di tabel: enam kolom angka berjejer membuat
    # kartu saldo harus digulir ke samping hanya untuk melihat sisanya,
    # dan yang dicari orang di daftar cuma Remaining. Yang butuh
    # rinciannya membuka barisnya.
    #
    # Yang hangus dua-duanya ikut, karena tanpa itu "empat hari saya ke
    # mana" tidak punya jawaban di layar mana pun — dan itu justru
    # pertanyaan yang paling sering sampai ke HR.
    "opening_used": {
        "label": "Opening Used",
        "table": False,
        "filter": False,
        "search": False,
        "sortable": True,
    },
    "opening_forfeited": {
        "label": "Opening Forfeited",
        "table": False,
        "filter": False,
        "search": False,
        "sortable": True,
    },
    "carried_over_used": {
        "label": "Carried Over Used",
        "table": False,
        "filter": False,
        "search": False,
        "sortable": True,
    },
    "carried_over_forfeited": {
        "label": "Carried Over Forfeited",
        "table": False,
        "filter": False,
        "search": False,
        "sortable": True,
    },
    "carried_over_expires_at": {
        "label": "Carried Over Expires",
        "table": False,
        "filter": False,
        "search": False,
        "sortable": True,
    },
    # Pemakaian yang melebihi seluruh kantong — cuti dibayar di muka.
    # Inilah yang membuat kartu bersaldo minus bisa dijelaskan.
    "advance_used": {
        "label": "Advance Used",
        "table": False,
        "filter": False,
        "search": False,
        "sortable": True,
    },
}


LEAVE_BALANCE_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="quota",
        label="Quota",
        fields=list(QUOTA_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
]


LEAVE_BALANCE_UI = {
    **ui.dialog(
        title="Leave Balance",
        description=(
            "Jatah dan pemakaian cuti per pegawai per tipe per tahun."
        ),
        size="lg",
        columns=2,
        create=True,
        edit=True,
        delete=True,
        bulk_delete=True,
        export=True,
    ),
}


LEAVE_BALANCE_SCHEMA = {
    "module": "hr/leave-balances",
    "name": "LeaveBalance",
    "label": "Leave Balance",
    "endpoint": "/api/hr/leave-balances/",
    "schema_type": "crud",

    "ui": LEAVE_BALANCE_UI,
    "tabs": LEAVE_BALANCE_TABS,
    "fields": {
        **LEAVE_BALANCE_FIELDS,
        **LEAVE_BALANCE_DISPLAY_FIELDS,
    },
}
