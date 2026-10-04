from apps.framework.builders import field, tabs, ui


GENERAL_FIELDS = {
    "company": field.lookup(
        tab="general",
        label="Company",
        lookup_endpoint=(
            "/api/administration/organization/lookup/companies/"
        ),
        display_key="company_name",
        required=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        help_text=(
            "Perusahaan yang cutinya mulai dikelola di sistem ini. "
            "Satu baris per perusahaan."
        ),
        order=10,
    ),

    "go_live_date": field.date(
        tab="general",
        label="Go-Live Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Hari pertama cuti dikelola di sini. Jatah tahun ini TIDAK "
            "diterbitkan untuk pegawai yang sudah bekerja sebelum "
            "tanggal ini — saldonya datang dari Leave Opening Balance."
        ),
        order=20,
    ),

    # Read-only, diturunkan dari tanggal di atasnya. Ditampilkan karena
    # inilah tanggal yang disebut HR saat meminta datanya ke sistem
    # lama — "saldo per tanggal berapa" adalah pertanyaan pertama, dan
    # menyuruh orang menghitung mundur satu hari sendiri adalah cara
    # paling mudah menghasilkan file yang tanggalnya meleset sehari.
    "cutoff_date": field.date(
        tab="general",
        label="Cut-Off Date",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        overview=True,
        help_text=(
            "Hari terakhir yang masih dipegang sistem lama. Angka saldo "
            "awal harus menyatakan keadaan per tanggal ini."
        ),
        order=30,
    ),

    "is_active": field.switch(
        tab="general",
        label="Active",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Matikan untuk mengembalikan perhitungan jatah ke aturan "
            "biasa. Saldo awal yang sudah di-post tidak ikut hilang."
        ),
        order=40,
    ),
}


PROGRESS_FIELDS = {
    # Dua penghitung, dan yang pertama yang paling perlu terbaca:
    # baris draft sudah terlihat di layar dengan angka yang benar,
    # tapi kartu cutinya masih nol. Tanpa angka ini, "kenapa saldo
    # pegawai saya masih kosong padahal sudah diimport" tidak punya
    # jawaban di layar mana pun.
    "draft_count": field.integer(
        tab="progress",
        label="Opening Balance — Draft",
        read_only=True,
        display=True,
        modes=["edit"],
        table=True,
        filter=False,
        search=False,
        sortable=False,
        help_text=(
            "Baris saldo awal yang belum di-post. Belum memengaruhi "
            "kartu cuti siapa pun."
        ),
        order=110,
    ),

    "posted_count": field.integer(
        tab="progress",
        label="Opening Balance — Posted",
        read_only=True,
        display=True,
        modes=["edit"],
        table=True,
        filter=False,
        search=False,
        sortable=False,
        help_text="Baris yang angkanya sudah berlaku di kartu cuti.",
        order=120,
    ),

    "notes": field.textarea(
        tab="progress",
        label="Notes",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        help_text=(
            "Dari sistem apa datanya dipindah, dan siapa yang "
            "menyerahkan angkanya."
        ),
        order=130,
    ),
}


LEAVE_GO_LIVE_FIELDS = {
    **GENERAL_FIELDS,
    **PROGRESS_FIELDS,
}


LEAVE_GO_LIVE_DISPLAY_FIELDS = {
    "company_name": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
}


LEAVE_GO_LIVE_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="progress",
        label="Migration",
        fields=list(PROGRESS_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
]


LEAVE_GO_LIVE_UI = {
    **ui.dialog(
        title="Leave Go-Live",
        description=(
            "Tanggal sebuah perusahaan menyerahkan pencatatan cutinya "
            "ke sistem ini. Terisi, jatah tahun go-live tidak "
            "diterbitkan lagi — yang berlaku saldo dari Leave Opening "
            "Balance."
        ),
        size="lg",
        columns=2,
        create=True,
        edit=True,
        delete=True,
        bulk_delete=False,
        export=True,
    ),
}


LEAVE_GO_LIVE_SCHEMA = {
    "module": "hr/leave-go-live",
    "name": "LeaveGoLive",
    "label": "Leave Go-Live",
    "endpoint": "/api/hr/leave-go-live/",
    "schema_type": "crud",

    "ui": LEAVE_GO_LIVE_UI,
    "tabs": LEAVE_GO_LIVE_TABS,
    "fields": {
        **LEAVE_GO_LIVE_FIELDS,
        **LEAVE_GO_LIVE_DISPLAY_FIELDS,
    },
}
