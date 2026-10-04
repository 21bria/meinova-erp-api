"""
Schema UI Visitor Management.

Tiga layar: master tamu luar, dokumen kunjungan, dan kartu tamu.

Yang menentukan bentuk dokumen kunjungan adalah `visible_when` pada
`travel_required` dan `accommodation_required` — itu yang membuat
satu form melayani tamu yang datang sebentar tanpa perjalanan sampai
tamu luar yang dijemput di bandara dan menginap tiga malam (dua puluh
sembilan kolom). Menampilkan semuanya sekaligus
berarti dua puluh kolom kosong yang tiap penggunanya harus memutuskan
sendiri mana yang berlaku.

Catatan yang gampang terlupa saat menambah field di sini: field
read-only yang memang mau tampil di form **wajib** `display=True` —
generator FE membuang seluruh field ber-`read_only` dari `form.ts`,
dan tanpa penanda itu field-nya hilang tanpa satu pun pesan.
"""

from apps.framework.builders import action, field, tabs, ui


# BT-2A — Visitor Request hanya untuk orang luar; pegawai yang
# berkunjung ke lokasi lain memakai Business Trip. `internal` tidak lagi
# ditawarkan. Dokumen lama tetap menampilkan jenisnya lewat
# `visitor_type_label`, dan backend menolak `internal` yang dikirim
# langsung (`VisitorRequestService.assert_external_only`).
VISITOR_TYPE_OPTIONS = [
    {"label": "External", "value": "external"},
]


IDENTITY_TYPE_OPTIONS = [
    {"label": "KTP", "value": "ktp"},
    {"label": "Passport", "value": "passport"},
    {"label": "SIM", "value": "sim"},
    {"label": "KITAS / KITAP", "value": "kitas"},
    {"label": "Other", "value": "other"},
]


VISITOR_REQUEST_STATUS_OPTIONS = [
    {"label": "Draft", "value": "draft"},
    {"label": "Submitted", "value": "submitted"},
    {"label": "Under Review", "value": "under_review"},
    {"label": "Approved", "value": "approved"},
    {"label": "Rejected", "value": "rejected"},
    {"label": "Cancelled", "value": "cancelled"},
    {"label": "Completed", "value": "completed"},
]


ARRIVAL_STATUS_OPTIONS = [
    {"label": "Expected", "value": "expected"},
    {"label": "Arrived", "value": "arrived"},
    {"label": "Checked In", "value": "checked_in"},
    {"label": "Checked Out", "value": "checked_out"},
    {"label": "No Show", "value": "no_show"},
]


PASS_STATUS_OPTIONS = [
    {"label": "Issued", "value": "issued"},
    {"label": "Returned", "value": "returned"},
    {"label": "Expired", "value": "expired"},
    {"label": "Lost", "value": "lost"},
]


IS_EXTERNAL = {"field": "visitor_type", "op": "eq", "value": "external"}


# =====================================================================
# External Visitor — master
# =====================================================================

EXTERNAL_VISITOR_IDENTITY_FIELDS = {
    "visitor_number": field.text(
        tab="identity",
        label="Visitor ID",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        disabled=True,
        display=True,
        help_text=(
            "Terisi otomatis dari pola penomoran hr/external_visitor. "
            "Kosong berarti pola itu belum diseed — jalankan "
            "seed_administration --only=numbering."
        ),
        order=10,
    ),

    "full_name": field.text(
        tab="identity",
        label="Full Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    "identity_type": field.select(
        tab="identity",
        label="Identity Type",
        display_key="identity_type_label",
        options=IDENTITY_TYPE_OPTIONS,
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=30,
    ),

    "identity_number": field.text(
        tab="identity",
        label="Identity Number",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        help_text=(
            "Dipakai memeriksa tamu ganda. Boleh dikosongkan kalau "
            "identitasnya belum sempat dicatat, tapi tamu tanpa nomor "
            "identitas tidak bisa dipakai di Visitor Request."
        ),
        order=40,
    ),

    "gender": field.lookup(
        tab="identity",
        label="Gender",
        lookup_endpoint="/api/administration/references/hr/lookup/genders/",
        display_key="gender_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=50,
    ),

    "date_of_birth": field.date(
        tab="identity",
        label="Date of Birth",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=60,
    ),

    "nationality": field.lookup(
        tab="identity",
        label="Nationality",
        lookup_endpoint="/api/administration/references/hr/lookup/nationalities/",
        display_key="nationality_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=70,
    ),
}


EXTERNAL_VISITOR_CONTACT_FIELDS = {
    "email": field.email(
        tab="contact",
        label="Email",
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=110,
    ),

    "phone": field.phone(
        tab="contact",
        label="Phone",
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=120,
    ),

    "mobile": field.phone(
        tab="contact",
        label="Mobile",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        order=130,
    ),
}


EXTERNAL_VISITOR_ORIGIN_FIELDS = {
    "organization_name": field.text(
        tab="origin",
        label="Company / Institution",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        order=210,
    ),

    "position": field.text(
        tab="origin",
        label="Position",
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=220,
    ),

    "city": field.lookup(
        tab="origin",
        label="City",
        lookup_endpoint="/api/administration/references/geography/lookup/cities/",
        display_key="city_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=False,
        order=230,
    ),

    "country": field.lookup(
        tab="origin",
        label="Country",
        lookup_endpoint="/api/administration/references/geography/lookup/countries/",
        display_key="country_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=240,
    ),

    "address": field.textarea(
        tab="origin",
        label="Address",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=250,
    ),
}


EXTERNAL_VISITOR_EXTRA_FIELDS = {
    "emergency_contact_name": field.text(
        tab="additional",
        label="Emergency Contact",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=310,
    ),

    "emergency_contact_phone": field.phone(
        tab="additional",
        label="Emergency Phone",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=320,
    ),

    "is_active": field.switch(
        tab="additional",
        label="Active",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        default=True,
        help_text="Dimatikan = tidak muncul lagi di pencarian tamu.",
        order=330,
    ),

    "is_blacklisted": field.switch(
        tab="additional",
        label="Blacklisted",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Tamu yang ditandai di sini ditolak saat dipakai di "
            "Visitor Request, dengan menyebut alasannya."
        ),
        order=340,
    ),

    "blacklist_reason": field.text(
        tab="additional",
        label="Blacklist Reason",
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        visible_when={"field": "is_blacklisted", "op": "is_true"},
        order=350,
    ),

    "notes": field.textarea(
        tab="additional",
        label="Notes",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=360,
    ),

    "visit_count": field.integer(
        tab="additional",
        label="Total Visits",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        help_text="Berapa kali tamu ini pernah diundang.",
        order=370,
    ),
}


EXTERNAL_VISITOR_FIELDS = {
    **EXTERNAL_VISITOR_IDENTITY_FIELDS,
    **EXTERNAL_VISITOR_CONTACT_FIELDS,
    **EXTERNAL_VISITOR_ORIGIN_FIELDS,
    **EXTERNAL_VISITOR_EXTRA_FIELDS,
}


# Kolom turunan introspeksi yang tidak dipakai di tabel. Tanpa ini
# setiap relasi muncul dua kali — `gender` (pk mentah) dan
# `gender_name` — dan tabelnya harus digulir ke samping untuk melihat
# kolom yang benar-benar dibaca orang.
EXTERNAL_VISITOR_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "identity_type_label",
        "gender_name",
        "nationality_name",
        "city_name",
        "country_name",
    )
}


EXTERNAL_VISITOR_SCHEMA = {
    "module": "hr/external-visitors",
    "name": "ExternalVisitor",
    "label": "External Visitor",
    "endpoint": "/api/hr/external-visitors/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="External Visitor",
            description=(
                "Data tamu dari luar perusahaan. Sekali diisi, tamunya "
                "bisa dipilih lagi di kunjungan berikutnya."
            ),
            size="xl",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=True,
            export=True,
        ),
    },
    "tabs": [
        tabs.form(
            key="identity",
            label="Identity",
            fields=list(EXTERNAL_VISITOR_IDENTITY_FIELDS.keys()),
            order=10,
            show_on_create=True,
        ),
        tabs.form(
            key="contact",
            label="Contact",
            fields=list(EXTERNAL_VISITOR_CONTACT_FIELDS.keys()),
            order=20,
            show_on_create=True,
        ),
        tabs.form(
            key="origin",
            label="Origin",
            fields=list(EXTERNAL_VISITOR_ORIGIN_FIELDS.keys()),
            order=30,
            show_on_create=True,
        ),
        tabs.form(
            key="additional",
            label="Additional",
            fields=list(EXTERNAL_VISITOR_EXTRA_FIELDS.keys()),
            order=40,
            show_on_create=True,
        ),
    ],
    "fields": {
        **EXTERNAL_VISITOR_FIELDS,
        **EXTERNAL_VISITOR_DISPLAY_FIELDS,
    },
}


# =====================================================================
# Visitor Request — dokumen kunjungan
# =====================================================================

REQUEST_GENERAL_FIELDS = {
    "document_number": field.text(
        tab="general",
        label="Request No.",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        disabled=True,
        display=True,
        modes=["edit"],
        help_text=(
            "Terisi otomatis dari pola penomoran hr/visitor_request."
        ),
        order=10,
    ),

    "request_date": field.date(
        tab="general",
        label="Request Date",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text="Dikosongkan = hari ini.",
        order=20,
    ),

    "requester": field.lookup(
        tab="general",
        label="Requester",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="requester_name",
        # Penempatan pemohon yang menentukan cakupan dokumen dan meja
        # approver-nya, jadi company/branch/location ikut terisi dari
        # sini. `EmployeeLookup` memang sudah mengirim ketiganya.
        autofill={
            "company": "company",
            "branch": "branch",
            "location": "location",
        },
        required=False,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        help_text=(
            "Pegawai yang mengajukan. Dikosongkan = akun yang sedang "
            "login."
        ),
        order=30,
    ),

    "company": field.lookup(
        tab="general",
        label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        default="$me.placement.company",
        readonly_when={
            "field": "$me.data_scope.values.company",
            "op": "is_not_null",
        },
        order=40,
    ),

    "location": field.lookup(
        tab="general",
        label="Visit Location / Site",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="location_name",
        # Seluruh induk yang mungkin terisi, bukan cuma induk
        # terdekat: level perantara boleh dilompati di struktur ini,
        # dan penyaringan satu level akan gugur diam-diam kalau
        # branch-nya kosong.
        lookup_params={
            "company_id": "$company",
            "branch_id": "$branch",
        },
        depends_on="company",
        required=False,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        order=50,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        display_key="status_label",
        options=VISITOR_REQUEST_STATUS_OPTIONS,
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        disabled=True,
        display=True,
        modes=["edit"],
        help_text=(
            "Berpindah lewat tombol Submit/Approve/Check-out, bukan "
            "diketik."
        ),
        order=60,
    ),
}


REQUEST_VISITOR_FIELDS = {
    "visitor_type": field.select(
        tab="visitor",
        label="Visitor Type",
        display_key="visitor_type_label",
        options=VISITOR_TYPE_OPTIONS,
        required=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        default="external",
        help_text=(
            "Tamu dari luar perusahaan, datanya diambil dari Visitor "
            "Master. Pegawai yang berkunjung ke lokasi lain memakai "
            "Business Trip."
        ),
        order=110,
    ),

    # `employee` (tamu internal) dimatikan di form, tabel, dan filter
    # sejak BT-2A. Ditulis eksplisit karena introspeksi menambahkan
    # kembali kolom serializer yang tidak disebut. Kolomnya tetap di
    # model untuk dokumen lama; namanya tetap tampil lewat
    # `visitor_name`.
    "employee": field.lookup(
        tab="visitor",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="employee_name",
        required=False,
        form=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=120,
    ),

    # ---- External -------------------------------------------------
    "external_visitor": field.lookup(
        tab="visitor",
        label="Visitor",
        lookup_endpoint="/api/hr/lookup/external-visitors/",
        display_key="external_visitor_name",
        required=False,
        table=False,
        filter=True,
        search=True,
        sortable=False,
        visible_when=IS_EXTERNAL,
        help_text=(
            "Cari tamu yang sudah terdaftar. Kalau belum ada, buat "
            "dulu di HR → Visitor Master."
        ),
        order=130,
    ),

    # ---- Turunan, satu pasang untuk dua sumber --------------------
    #
    # Tabel daftar tidak boleh punya dua kolom nama tamu yang salah
    # satunya selalu kosong, jadi keduanya diturunkan serializer dari
    # sumber yang sesuai jenis kunjungannya.
    "visitor_name": field.text(
        tab="visitor",
        label="Visitor Name",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        overview=True,
        order=140,
    ),

    "visitor_organization": field.text(
        tab="visitor",
        label="Company",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=150,
    ),

    "visitor_identity": field.text(
        tab="visitor",
        label="Identity",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=160,
    ),

    "visitor_contact": field.text(
        tab="visitor",
        label="Contact",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=170,
    ),

    "number_of_visitors": field.integer(
        tab="visitor",
        label="Number of Visitors",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        default=1,
        min=1,
        help_text="Termasuk tamu utama di atas.",
        order=180,
    ),
}


REQUEST_VISIT_FIELDS = {
    "visit_purpose": field.lookup(
        tab="visit",
        label="Visit Purpose",
        lookup_endpoint="/api/administration/references/hr/lookup/visit-purposes/",
        display_key="visit_purpose_name",
        required=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        order=210,
    ),

    "visit_type": field.lookup(
        tab="visit",
        label="Visit Type",
        lookup_endpoint="/api/administration/references/hr/lookup/visit-types/",
        display_key="visit_type_name",
        required=False,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        order=220,
    ),

    "visit_start_date": field.date(
        tab="visit",
        label="Visit Start Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=230,
    ),

    "visit_start_time": field.time(
        tab="visit",
        label="Visit Start Time",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=240,
    ),

    "visit_end_date": field.date(
        tab="visit",
        label="Visit End Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=250,
    ),

    "visit_end_time": field.time(
        tab="visit",
        label="Visit End Time",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=260,
    ),

    "expected_duration_days": field.integer(
        tab="visit",
        label="Expected Duration (days)",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        # Dihitung ulang di grid supaya angkanya ikut berubah begitu
        # tanggalnya digeser, bukan menunggu simpan.
        compute={
            "kind": "date_diff",
            "from": "visit_start_date",
            "to": "visit_end_date",
            "inclusive": True,
        },
        order=270,
    ),

    "remarks": field.textarea(
        tab="visit",
        label="Remarks",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=280,
    ),
}


REQUEST_HOST_FIELDS = {
    "host_employee": field.lookup(
        tab="host",
        label="Host Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="host_name",
        required=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        help_text=(
            "Pegawai yang bertanggung jawab menerima tamu. Departemen "
            "dan jabatannya dibaca dari kartu pegawainya, tidak "
            "disalin ke dokumen ini."
        ),
        order=310,
    ),

    "host_department": field.text(
        tab="host",
        label="Host Department",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=320,
    ),

    "host_position": field.text(
        tab="host",
        label="Host Position",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=330,
    ),

    "host_contact": field.text(
        tab="host",
        label="Host Contact",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=340,
    ),

    "requester_department": field.text(
        tab="host",
        label="Requester Department",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=350,
    ),
}


TRAVEL_ON = {"field": "travel_required", "op": "is_true"}
ACCOMMODATION_ON = {"field": "accommodation_required", "op": "is_true"}


REQUEST_TRAVEL_FIELDS = {
    "travel_required": field.switch(
        tab="travel",
        label="Travel Required",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Dimatikan = seluruh isian perjalanan disembunyikan. Yang "
            "sudah terisi tidak dihapus — menyalakannya lagi "
            "mengembalikan isinya."
        ),
        order=410,
    ),

    "travel_from": field.text(
        tab="travel",
        label="Travel From",
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        visible_when=TRAVEL_ON,
        order=420,
    ),

    "travel_to": field.text(
        tab="travel",
        label="Travel To",
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        visible_when=TRAVEL_ON,
        order=430,
    ),

    "departure_date": field.date(
        tab="travel",
        label="Departure Date",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        visible_when=TRAVEL_ON,
        order=440,
    ),

    "departure_time": field.time(
        tab="travel",
        label="Departure Time",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        visible_when=TRAVEL_ON,
        order=450,
    ),

    "return_date": field.date(
        tab="travel",
        label="Return Date",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        visible_when=TRAVEL_ON,
        order=460,
    ),

    "return_time": field.time(
        tab="travel",
        label="Return Time",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        visible_when=TRAVEL_ON,
        order=470,
    ),

    "transport_mode": field.lookup(
        tab="travel",
        label="Transportation",
        lookup_endpoint="/api/administration/references/hr/lookup/transport-modes/",
        display_key="transport_mode_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        visible_when=TRAVEL_ON,
        order=480,
    ),

    "ticket_required": field.switch(
        tab="travel",
        label="Ticket Required",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        visible_when=TRAVEL_ON,
        order=490,
    ),

    "ticket_number": field.text(
        tab="travel",
        label="Ticket Number",
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        visible_when={
            "all": [TRAVEL_ON, {"field": "ticket_required", "op": "is_true"}],
        },
        order=500,
    ),
}


REQUEST_ACCOMMODATION_FIELDS = {
    "accommodation_required": field.switch(
        tab="travel",
        label="Accommodation Required",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=510,
    ),

    "accommodation_type": field.lookup(
        tab="travel",
        label="Accommodation Type",
        lookup_endpoint="/api/administration/references/hr/lookup/accommodation-types/",
        display_key="accommodation_type_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        visible_when=ACCOMMODATION_ON,
        order=520,
    ),

    "accommodation_name": field.text(
        tab="travel",
        label="Hotel / Accommodation",
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        visible_when=ACCOMMODATION_ON,
        order=530,
    ),

    "accommodation_checkin": field.date(
        tab="travel",
        label="Check-in Date",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        visible_when=ACCOMMODATION_ON,
        order=540,
    ),

    "accommodation_checkout": field.date(
        tab="travel",
        label="Check-out Date",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        visible_when=ACCOMMODATION_ON,
        order=550,
    ),
}


REQUEST_PICKUP_FIELDS = {
    "pickup_required": field.switch(
        tab="travel",
        label="Airport / Station Pickup",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=610,
    ),

    "pickup_point": field.text(
        tab="travel",
        label="Pickup Point",
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        visible_when={"field": "pickup_required", "op": "is_true"},
        order=620,
    ),

    "dropoff_point": field.text(
        tab="travel",
        label="Drop-off Point",
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        visible_when={"field": "pickup_required", "op": "is_true"},
        order=630,
    ),

    "vehicle_required": field.switch(
        tab="travel",
        label="Vehicle Required",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        order=640,
    ),

    "driver_required": field.switch(
        tab="travel",
        label="Driver Required",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        visible_when={"field": "vehicle_required", "op": "is_true"},
        order=650,
    ),

    "travel_remarks": field.textarea(
        tab="travel",
        label="Travel Remarks",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=660,
    ),
}


REQUEST_ARRIVAL_FIELDS = {
    "arrival_status": field.select(
        tab="arrival",
        label="Arrival Status",
        display_key="arrival_status_label",
        options=ARRIVAL_STATUS_OPTIONS,
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        disabled=True,
        display=True,
        modes=["edit"],
        help_text=(
            "Berpindah lewat tombol Check In / Check Out di layar ini "
            "atau di pos jaga."
        ),
        order=710,
    ),

    "expected_arrival": field.datetime(
        tab="arrival",
        label="Expected Arrival",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=720,
    ),

    "checked_in_at": field.datetime(
        tab="arrival",
        label="Check-in Time",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        disabled=True,
        display=True,
        modes=["edit"],
        order=730,
    ),

    "checked_in_by_name": field.text(
        tab="arrival",
        label="Check-in By",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        modes=["edit"],
        order=740,
    ),

    "check_in_gate": field.text(
        tab="arrival",
        label="Gate / Security Post",
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        disabled=True,
        display=True,
        modes=["edit"],
        order=750,
    ),

    "check_in_remarks": field.textarea(
        tab="arrival",
        label="Check-in Remarks",
        rows=2,
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        modes=["edit"],
        order=760,
    ),

    "checked_out_at": field.datetime(
        tab="arrival",
        label="Check-out Time",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        disabled=True,
        display=True,
        modes=["edit"],
        order=770,
    ),

    "checked_out_by_name": field.text(
        tab="arrival",
        label="Check-out By",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        modes=["edit"],
        order=780,
    ),

    "check_out_remarks": field.textarea(
        tab="arrival",
        label="Check-out Remarks",
        rows=2,
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        modes=["edit"],
        order=790,
    ),
}


VISITOR_REQUEST_FIELDS = {
    **REQUEST_GENERAL_FIELDS,
    **REQUEST_VISITOR_FIELDS,
    **REQUEST_VISIT_FIELDS,
    **REQUEST_HOST_FIELDS,
    **REQUEST_TRAVEL_FIELDS,
    **REQUEST_ACCOMMODATION_FIELDS,
    **REQUEST_PICKUP_FIELDS,
    **REQUEST_ARRIVAL_FIELDS,
}


# Kolom hasil introspeksi yang tidak dipakai di tabel. `branch` dan
# `company` adalah salinan cakupan untuk penyaringan data; kolomnya
# mencari `<field>_name` yang memang dikirim serializer, tapi tiga
# kolom organisasi berjejer di daftar kunjungan cuma memakan lebar
# tanpa menjawab apa pun — Location yang dicari orang.
VISITOR_REQUEST_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "branch",
        "company_name",
        "branch_name",
        "location_name",
        "status_label",
        "visitor_type_label",
        "arrival_status_label",
        "requester_name",
        "host_name",
        "employee_name",
        "employee_number",
        "employee_department",
        "employee_position",
        "employee_location",
        "external_visitor_name",
        "external_visitor_number",
        "external_visitor_organization",
        "visit_purpose_name",
        "visit_type_name",
        "transport_mode_name",
        "accommodation_type_name",
        "current_pass",
        "pass_count",
        "approval",
    )
}


VISITOR_REQUEST_TABS = [
    tabs.form(
        key="general",
        label="Overview",
        fields=list(REQUEST_GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="visitor",
        label="Visitor Information",
        fields=list(REQUEST_VISITOR_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
    tabs.form(
        key="visit",
        label="Visit Information",
        fields=list(REQUEST_VISIT_FIELDS.keys()),
        order=30,
        show_on_create=True,
    ),
    tabs.form(
        key="host",
        label="Host Information",
        fields=list(REQUEST_HOST_FIELDS.keys()),
        order=40,
        show_on_create=True,
    ),
    tabs.form(
        key="travel",
        label="Travel & Accommodation",
        fields=(
            list(REQUEST_TRAVEL_FIELDS.keys())
            + list(REQUEST_ACCOMMODATION_FIELDS.keys())
            + list(REQUEST_PICKUP_FIELDS.keys())
        ),
        order=50,
        show_on_create=True,
    ),

    # Kedatangan baru ada isinya setelah dokumennya tersimpan dan
    # tamunya datang — menampilkannya di layar create menghasilkan
    # delapan kotak kosong yang akan dicoba diisi orang.
    tabs.form(
        key="arrival",
        label="Arrival / Check-in",
        fields=list(REQUEST_ARRIVAL_FIELDS.keys()),
        order=60,
        show_on_create=False,
    ),

    tabs.resource(
        key="passes",
        label="Visitor Pass",
        endpoint="/api/hr/visitor-passes/",
        module="hr/visitor-passes",
        foreign_key="request",
        fields={},  # diisi di bawah, setelah PASS_FIELDS dideklarasikan
        requires_record=True,
        readonly=True,
        order=70,
    ),
]


VISITOR_REQUEST_ACTIONS = [
    action.save(),
    action.save_and_close(),
    action.delete(),
    action.export(),

    action.custom(
        "submit",
        label="Submit for Approval",
        icon="Send",
        variant="default",
        placement="primary",
        modes=["edit"],
        endpoint="/api/hr/visitor-requests/{id}/submit/",
        method="post",
        refresh=True,
        visible_when={"status": ["draft", "rejected"]},
        confirm={
            "title": "Ajukan Visitor Request?",
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
        endpoint="/api/hr/visitor-requests/{id}/approve/",
        method="post",
        refresh=True,
        visible_when={"approval.can_act": True},
    ),

    action.custom(
        "reject",
        label="Reject",
        icon="XCircle",
        variant="destructive",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/visitor-requests/{id}/reject/",
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
        "withdraw",
        label="Withdraw",
        icon="RotateCcw",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/visitor-requests/{id}/withdraw/",
        method="post",
        refresh=True,
        visible_when={"status": ["submitted", "under_review"]},
        confirm={
            "title": "Tarik kembali pengajuan?",
            "description": (
                "Dokumen kembali ke Draft dan bisa disunting lagi. "
                "Jejak pengajuannya tetap tersimpan."
            ),
        },
    ),

    # ---- Pos jaga -------------------------------------------------
    #
    # `visible_when` di sini **bukan** penjagaan — yang menolak tetap
    # service di backend (BR-08/BR-09). Ini cuma supaya tombol yang
    # pasti ditolak tidak ditawarkan.
    action.custom(
        "check_in",
        label="Check In",
        icon="LogIn",
        variant="default",
        placement="primary",
        modes=["edit"],
        endpoint="/api/hr/visitor-requests/{id}/check-in/",
        method="post",
        refresh=True,
        visible_when={
            "all": [
                {"field": "status", "op": "eq", "value": "approved"},
                {"field": "checked_in_at", "op": "is_null"},
            ],
        },
        fields=[
            {
                "key": "gate",
                "type": "text",
                "label": "Gate / Security Post",
                "required": False,
            },
            {
                "key": "remarks",
                "type": "textarea",
                "label": "Remarks",
                "required": False,
            },
        ],
    ),

    action.custom(
        "check_out",
        label="Check Out",
        icon="LogOut",
        variant="default",
        placement="primary",
        modes=["edit"],
        endpoint="/api/hr/visitor-requests/{id}/check-out/",
        method="post",
        refresh=True,
        visible_when={
            "all": [
                {"field": "checked_in_at", "op": "is_not_null"},
                {"field": "checked_out_at", "op": "is_null"},
            ],
        },
        fields=[
            {
                "key": "remarks",
                "type": "textarea",
                "label": "Remarks",
                "required": False,
            },
        ],
    ),

    action.custom(
        "issue_pass",
        label="Issue Visitor Pass",
        icon="IdCard",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/visitor-requests/{id}/issue-pass/",
        method="post",
        refresh=True,
        visible_when={"status": ["approved", "completed"]},
    ),

    action.custom(
        "no_show",
        label="Mark No Show",
        icon="UserX",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/visitor-requests/{id}/no-show/",
        method="post",
        refresh=True,
        visible_when={
            "all": [
                {"field": "status", "op": "eq", "value": "approved"},
                {"field": "checked_in_at", "op": "is_null"},
            ],
        },
        fields=[
            {
                "key": "remarks",
                "type": "textarea",
                "label": "Keterangan",
                "required": False,
            },
        ],
    ),
]


VISITOR_REQUEST_SCHEMA = {
    "module": "hr/visitor-requests",
    "name": "VisitorRequest",
    "label": "Visitor Request",
    "endpoint": "/api/hr/visitor-requests/",
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Visitor Request",
            description=(
                "Kunjungan tamu dari luar perusahaan: keperluan, "
                "tuan rumah, perjalanan, dan kedatangannya."
            ),
            size="full",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=True,
            export=True,
        ),
    },
    "tabs": VISITOR_REQUEST_TABS,
    "actions": VISITOR_REQUEST_ACTIONS,
    "fields": {
        **VISITOR_REQUEST_FIELDS,
        **VISITOR_REQUEST_DISPLAY_FIELDS,
    },
}


# =====================================================================
# Visitor Pass
# =====================================================================

VISITOR_PASS_FIELDS = {
    "pass_number": field.text(
        tab="general",
        label="Pass No.",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        disabled=True,
        display=True,
        order=10,
    ),

    "request": field.lookup(
        tab="general",
        label="Visitor Request",
        lookup_endpoint="/api/hr/lookup/visitor-requests/",
        display_key="request_number",
        required=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        order=20,
    ),

    "visitor_name": field.text(
        tab="general",
        label="Visitor Name",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        overview=True,
        order=30,
    ),

    "visitor_type_label": field.text(
        tab="general",
        label="Visitor Type",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=40,
    ),

    "host_name": field.text(
        tab="general",
        label="Host",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=50,
    ),

    "location_name": field.text(
        tab="general",
        label="Location",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=60,
    ),

    "visit_date": field.date(
        tab="general",
        label="Visit Date",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=70,
    ),

    "valid_from": field.date(
        tab="general",
        label="Valid From",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text="Dikosongkan = ikut tanggal mulai kunjungannya.",
        order=80,
    ),

    "valid_until": field.date(
        tab="general",
        label="Valid Until",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text="Dikosongkan = ikut tanggal selesai kunjungannya.",
        order=90,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        display_key="status_label",
        options=PASS_STATUS_OPTIONS,
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        disabled=True,
        display=True,
        order=100,
    ),

    "issued_at": field.datetime(
        tab="general",
        label="Issued At",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        disabled=True,
        display=True,
        order=110,
    ),

    "returned_at": field.datetime(
        tab="general",
        label="Returned At",
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        disabled=True,
        display=True,
        order=120,
    ),

    "notes": field.textarea(
        tab="general",
        label="Notes",
        rows=2,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=130,
    ),
}


VISITOR_PASS_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "status_label",
        "request_number",
        "issued_by",
        "returned_by",
    )
}


VISITOR_PASS_ACTIONS = [
    action.save(),
    action.delete(),
    action.export(),

    action.custom(
        "return_pass",
        label="Mark Returned",
        icon="Undo2",
        variant="default",
        placement="primary",
        modes=["edit"],
        endpoint="/api/hr/visitor-passes/{id}/return/",
        method="post",
        refresh=True,
        visible_when={"status": ["issued"]},
        confirm={
            "title": "Tandai kartu sudah kembali?",
            "description": "Kartu tidak lagi terhitung sedang dipegang tamu.",
        },
    ),

    action.custom(
        "mark_lost",
        label="Report Lost",
        icon="TriangleAlert",
        variant="destructive",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/visitor-passes/{id}/lost/",
        method="post",
        refresh=True,
        visible_when={"status": ["issued"]},
        fields=[
            {
                "key": "notes",
                "type": "textarea",
                "label": "Keterangan",
                "required": True,
            },
        ],
    ),
]


VISITOR_PASS_SCHEMA = {
    "module": "hr/visitor-passes",
    "name": "VisitorPass",
    "label": "Visitor Pass",
    "endpoint": "/api/hr/visitor-passes/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Visitor Pass",
            description="Kartu tamu yang diterbitkan di pos jaga.",
            size="lg",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=False,
            export=True,
        ),
    },
    "tabs": [
        tabs.form(
            key="general",
            label="General",
            fields=list(VISITOR_PASS_FIELDS.keys()),
            order=10,
            show_on_create=True,
        ),
    ],
    "actions": VISITOR_PASS_ACTIONS,
    "fields": {
        **VISITOR_PASS_FIELDS,
        **VISITOR_PASS_DISPLAY_FIELDS,
    },
}


def _grid(source: dict, keys: tuple[str, ...]) -> dict:
    """
    Salinan config kolom untuk satu tabel di dalam dokumen.

    Grid memilih kolomnya dari flag `table`, jadi tabel yang membaca
    endpoint milik resource lain wajib membawa salinannya sendiri —
    mengubah flag di tempat akan ikut mengubah tabel resource itu.
    """
    grid = {}

    for key in keys:
        config = dict(source[key])
        config["table"] = True
        grid[key] = config

    return grid


PASS_GRID_FIELDS = _grid(
    VISITOR_PASS_FIELDS,
    (
        "pass_number",
        "valid_from",
        "valid_until",
        "status",
        "issued_at",
        "returned_at",
        "notes",
    ),
)


# Tab kartu di dalam dokumen kunjungan. Diisi di sini, setelah
# PASS_FIELDS ada — kalau ditulis langsung di atas, dict-nya belum
# terdefinisi dan modulnya gagal di-import.
for _tab in VISITOR_REQUEST_TABS:
    if _tab.get("key") == "passes":
        _tab["fields"] = PASS_GRID_FIELDS
