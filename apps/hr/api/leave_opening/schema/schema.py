from apps.framework.builders import action, field, tabs, ui

from .importer import LEAVE_OPENING_IMPORT_SCHEMA


GENERAL_FIELDS = {
    # Paling depan, dan itu disengaja: selama sebuah baris masih Draft,
    # angka di sebelahnya belum berarti apa-apa bagi kartu cuti
    # pegawainya. Ditaruh di belakang, daftarnya terbaca seperti saldo
    # yang sudah berlaku — dan itu persis salah paham yang paling mahal
    # di layar ini.
    "status": field.select(
        tab="general",
        label="Status",
        options=[
            {"label": "Draft", "value": "draft"},
            {"label": "Posted", "value": "posted"},
        ],
        display_key="status_label",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Draft belum memengaruhi kartu saldo. Tekan Post kalau "
            "angkanya sudah benar."
        ),
        order=1,
    ),

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

    "opening_date": field.date(
        tab="general",
        label="Opening Date",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Tanggal saldo ini berlaku. Dikosongkan = ikut tanggal "
            "Leave Go-Live perusahaan pegawainya. Bukan tanggal "
            "pengetikan."
        ),
        order=30,
    ),

    "days": field.decimal(
        tab="general",
        label="Opening Balance",
        decimal_places=1,
        max_digits=6,
        required=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text="Sisa saldo dari sistem lama, dalam hari.",
        order=40,
    ),
}


DETAIL_FIELDS = {
    # Diisi service dari tahun `opening_date` kalau dikosongkan. Tetap
    # bisa diketik: tenant yang policy-nya berbasis tanggal masuk
    # kadang perlu menaruhnya di kartu tahun berikutnya.
    "year": field.integer(
        tab="detail",
        label="Balance Year",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Kartu saldo tahun berapa yang menerima angka ini. "
            "Dikosongkan = ikut tahun Opening Date."
        ),
        order=110,
    ),

    # Dibekukan saat dokumen dibuat, tidak pernah dihitung ulang.
    "expires_at": field.date(
        tab="detail",
        label="Expires At",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        help_text=(
            "Terisi dari Leave Policy kalau cuti bawaan memang punya "
            "masa berlaku. Dikosongkan = tidak hangus."
        ),
        order=120,
    ),

    "remark": field.textarea(
        tab="detail",
        label="Remark",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        help_text=(
            "Dari mana angkanya. Saldo awal tanpa keterangan tidak bisa "
            "dipertanggungjawabkan setahun kemudian."
        ),
        order=130,
    ),

    "posted_at": field.date(
        tab="detail",
        label="Posted At",
        required=False,
        read_only=True,
        display=True,
        modes=["edit"],
        table=False,
        filter=False,
        search=False,
        sortable=True,
        help_text="Kapan angkanya mulai berlaku di kartu cuti.",
        order=135,
    ),

    # Ditentukan sistem: manual atau hasil import. Ditampilkan supaya
    # baris hasil migrasi massal bisa dibedakan dari yang diketik
    # satu per satu, tapi tidak bisa dipilih di form.
    "source": field.select(
        tab="detail",
        label="Source",
        options=[
            {"label": "Manual", "value": "manual"},
            {"label": "Import", "value": "import"},
        ],
        display_key="source_label",
        required=False,
        readonly=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=140,
    ),
}


LEAVE_OPENING_FIELDS = {
    **GENERAL_FIELDS,
    **DETAIL_FIELDS,
}


LEAVE_OPENING_DISPLAY_FIELDS = {
    "employee_name": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    # Nomor pegawai jadi kolom tersendiri: daftar ini dibaca
    # berdampingan dengan file dari sistem lama, dan yang dicocokkan
    # orang di sana nomornya.
    "employee_number": field.text(
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

    # Tiga kolom kelayakan, diturunkan serializer dari Join Date +
    # Leave Policy. Ada di daftar ini — bukan cuma di layar preview —
    # karena langkah Review terjadi **di sini**, sesudah filenya
    # di-confirm: tombol Post ada di baris ini, jadi bahan untuk
    # memutuskannya harus ada di baris ini juga. Preview yang sudah
    # ditinggalkan tidak bisa dibuka lagi.
    # **`export=False` wajib pada keempatnya**, dan bukan kerapian.
    # `resolve_export_value` membaca **instance**, bukan hasil
    # serializer; `SerializerMethodField` bernilai `source="*"` sehingga
    # `get_export_sources` melewatinya, dan `getattr(row, "join_date")`
    # tidak pernah ada. Tanpa penanda ini CSV-nya memuat kolom Join
    # Date, Eligible Date, dan Validation yang **kosong di semua baris**
    # — persis kegagalan diam yang paling menyesatkan: kolomnya ada di
    # tabel, ada di header CSV, isinya saja yang tidak pernah ada, jadi
    # terbaca seperti data yang memang belum diisi. Terverifikasi
    # sebelum ditambahkan.
    "join_date": field.date(
        column_after="employee_number",
        export=False,
        label="Join Date",
        read_only=True,
        display=True,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        overview=True,
        help_text="Dari kartu pegawai. Tidak disunting di sini.",
        order=43,
    ),

    "eligible_date": field.date(
        column_after="join_date",
        export=False,
        label="Eligible Date",
        read_only=True,
        display=True,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        overview=True,
        help_text=(
            "Join Date + masa tunggu di Leave Policy. Kosong berarti "
            "belum bisa dihitung — lihat kolom Reason."
        ),
        order=44,
    ),

    # `filter=False` disengaja: statusnya diturunkan saat dibaca dari
    # policy yang berlaku, jadi tidak ada kolom database yang bisa
    # disaring. Filter yang tampil lalu diabaikan diam-diam adalah
    # kegagalan yang paling sulit dilaporkan — yang memakainya
    # menyimpulkan datanya yang salah, bukan filternya.
    "validation_label": field.text(
        column_after="days",
        export=False,
        label="Validation",
        read_only=True,
        display=True,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        overview=True,
        help_text=(
            "VALID, VALID - NOT YET ELIGIBLE, atau REVIEW. REVIEW tidak "
            "menghalangi Post — ia menandai baris yang perlu dibaca "
            "orang lebih dulu."
        ),
        order=45,
    ),

    "validation_reason": field.textarea(
        label="Reason",
        export=False,
        rows=2,
        read_only=True,
        display=True,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        overview=True,
        help_text="Kenapa barisnya ditandai begitu.",
        order=46,
    ),
    "source_label": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    "status_label": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    },
    # Kode mentah di balik `validation_label`. Dibawa serializer supaya
    # frontend bisa mewarnai badge-nya tanpa mencocokkan teks, tapi tidak
    # jadi kolom sendiri — dua kolom berjudul "Validation" di satu CSV
    # tidak bisa dibedakan siapa pun.
    "validation": {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
        "export": False,
    },
}


# Dua tombol, dan yang membedakannya cuma keadaan barisnya — jadi
# `visible_when` yang memilih mana yang tampil. Menampilkan keduanya
# sekaligus berarti separuh penekanannya selalu dibalas 400.
LEAVE_OPENING_ACTIONS = [
    action.record(
        "post",
        endpoint="/api/hr/leave-opening-balances/{id}/post/",
        label="Post",
        icon="CheckCircle2",
        variant="default",
        placement="primary",
        confirm={
            "title": "Post saldo awal?",
            "description": (
                "Angka ini akan jadi saldo cuti pegawainya dan bisa "
                "langsung dipakai mengajukan cuti."
            ),
        },
        visible_when={"status": ["draft"]},
        permission="hr.change_leaveopeningbalance",
    ),

    action.record(
        "unpost",
        endpoint="/api/hr/leave-opening-balances/{id}/unpost/",
        label="Unpost",
        icon="Undo2",
        variant="outline",
        placement="secondary",
        confirm={
            "title": "Tarik saldo awal?",
            "description": (
                "Angkanya keluar dari kartu cuti pegawainya. Cuti yang "
                "sudah diambil tetap tercatat, jadi saldonya bisa jadi "
                "minus sampai angka penggantinya di-post."
            ),
        },
        visible_when={"status": ["posted"]},
        permission="hr.change_leaveopeningbalance",
    ),

    # Tombol massal, dan ini yang sebenarnya dipakai saat go-live.
    #
    # Tanpa ia, satu batch migrasi berisi tiga ratus baris berarti tiga
    # ratus kali membuka baris, menekan Post, menutupnya lagi — dan
    # pekerjaan itulah yang membuat orang berhenti memakai layarnya lalu
    # meminta seseorang menjalankan perintah di server. Endpoint-nya
    # sudah jalan sejak awal; yang tidak ada cuma tombolnya, dan
    # endpoint tanpa tombol tidak bisa dibedakan dari fitur yang tidak
    # ada.
    #
    # `selection="optional"` yang membuatnya melayani dua kebiasaan
    # sekaligus: yang mencentang beberapa baris memposting yang itu
    # saja, yang tidak mencentang apa pun memposting **seluruh draft
    # yang sedang terlihat** — lewat `filter_queryset`, jadi penyaring
    # toolbar ikut berlaku dan cakupan data tidak bisa dilewati.
    action.collection(
        "post_all",
        endpoint="/api/hr/leave-opening-balances/post-all/",
        label="Post Saldo Awal",
        icon="CheckCircle2",
        variant="default",
        selection="optional",
        confirm={
            "title": "Post saldo awal?",
            "description": (
                "Angkanya jadi saldo cuti pegawainya dan bisa langsung "
                "dipakai mengajukan cuti. Baris yang gagal dilaporkan "
                "satu per satu dan tidak membatalkan yang berhasil. "
                "Periksa dulu kolom Validation — yang bertanda REVIEW "
                "sebaiknya dibereskan sebelum di-post."
            ),
        },
        permission="hr.change_leaveopeningbalance",
    ),
]


LEAVE_OPENING_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="detail",
        label="Detail",
        fields=list(DETAIL_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
]


LEAVE_OPENING_UI = {
    **ui.dialog(
        title="Leave Opening Balance",
        description=(
            "Titik awal saldo cuti saat sistem ini mulai dipakai. "
            "Import lalu periksa angkanya, tekan Post agar jadi saldo "
            "pegawai. Sesudah itu saldo berubah lewat Leave Request, "
            "bukan lewat layar ini."
        ),
        size="lg",
        columns=2,
        create=True,
        edit=True,
        delete=True,
        bulk_delete=True,
        export=True,
    ),
    "import": True,
}


LEAVE_OPENING_SCHEMA = {
    "module": "hr/leave-opening-balances",
    "name": "LeaveOpeningBalance",
    "label": "Leave Opening Balance",
    "endpoint": "/api/hr/leave-opening-balances/",
    "schema_type": "crud",

    "ui": LEAVE_OPENING_UI,
    "tabs": LEAVE_OPENING_TABS,
    "fields": {
        **LEAVE_OPENING_FIELDS,
        **LEAVE_OPENING_DISPLAY_FIELDS,
    },

    "actions": LEAVE_OPENING_ACTIONS,

    "import": LEAVE_OPENING_IMPORT_SCHEMA,
}
