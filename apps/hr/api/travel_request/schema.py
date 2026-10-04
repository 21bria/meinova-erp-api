"""
Schema UI Travel Request.

Bentuknya mengikuti formulir kertas: kepala dokumen, lalu tiga tabel —
Travel Purpose, Travel Arrangement, Accommodation. Dua tabel terakhir
membaca baris yang sama dengan kolom berbeda; akomodasi dipisah karena
satu tabel delapan belas kolom memaksa orang menggulir ke samping hanya
untuk melihat kolom yang sedang diisinya.
"""

from apps.framework.builders import action, field, tabs, ui


TRAVEL_REQUEST_STATUS_OPTIONS = [
    {"label": "Draft", "value": "draft"},
    {"label": "Pending Approval", "value": "submitted"},
    {"label": "Approved", "value": "approved"},
    {"label": "Rejected", "value": "rejected"},
    {"label": "Cancelled", "value": "cancelled"},
]


TRAVEL_DIRECTION_OPTIONS = [
    {"label": "Outbound", "value": "out"},
    {"label": "Inbound", "value": "in"},
]


GENERAL_FIELDS = {
    "document_number": field.text(
        tab="general",
        label="TR No.",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        disabled=True,
        help_text=(
            "Terisi otomatis dari pola penomoran hr/travel_request. "
            "Kosong berarti pola itu belum diseed — jalankan "
            "seed_administration --only=numbering."
        ),
        order=10,
    ),

    "employee": field.lookup(
        tab="general",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        # Travel Request adalah dokumen kepulangan site, jadi yang
        # disaring `field_break` — bukan `leave`. Yang tidak punya blok
        # off site tidak punya kepulangan untuk diajukan, walau cutinya
        # tetap berlaku lewat modul Cuti.
        lookup_params={"feature": "field_break"},
        display_key="employee_name",
        autofill={
            "company": "company",
            "branch": "branch",
            "location": "location",
        },
        required=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    # Blok off pada jadwal roster yang direalisasikan. Opsional:
    # pegawai yang jadwalnya belum disusun tetap harus bisa mengajukan.
    "rotation_period": field.lookup(
        tab="general",
        label="Roster Block",
        lookup_endpoint="/api/hr/lookup/rotation-periods/",
        display_key="rotation_period_label",
        lookup_params={"employee_id": "$employee"},
        depends_on="employee",
        # Memilih blok jadwal langsung mengisi tanggal off-nya.
        # `RotationPeriodLookup` ikut mengirim start_date/end_date
        # supaya autofill ini ada isinya.
        autofill={
            "start_date": "start_date",
            "end_date": "end_date",
        },
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        help_text=(
            "Blok Off pada jadwal roster yang diambil. Dikosongkan = "
            "pengajuan berdiri sendiri; tanggalnya diisi manual."
        ),
        order=30,
    ),

    # Sengaja **tidak** dikunci. Sempat ditandai `disabled` dengan
    # niat diisi service dari blok jadwal, dan hasilnya form yang
    # mustahil disimpan: tidak bisa diketik, tapi tetap wajib, dan
    # pengisian otomatisnya baru jalan di server — jauh setelah
    # validasi form menolak. Kombinasi required + disabled + diisi
    # server adalah kunci mati.
    #
    # Sekarang: terisi sendiri lewat `autofill` begitu blok jadwal
    # dipilih, dan tetap bisa dikoreksi tangan — kepulangan yang
    # dimajukan tiga hari harus bisa diajukan tanpa mengubah jadwal
    # tahunannya lebih dulu. Pengaju tanpa blok jadwal mengetiknya
    # sendiri.
    "start_date": field.date(
        tab="general",
        label="Off Start",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Terisi otomatis dari Blok Jadwal. Dirapatkan ulang ke "
            "baris Travel Purpose setelah disimpan."
        ),
        order=40,
    ),

    "end_date": field.date(
        tab="general",
        label="Off End",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Terisi otomatis dari Blok Jadwal. Dirapatkan ulang ke "
            "baris Travel Purpose setelah disimpan."
        ),
        order=50,
    ),

    "total_days": field.integer(
        tab="general",
        label="Total Days",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        disabled=True,
        display=True,
        help_text="Dijumlahkan dari baris Travel Purpose.",
        order=60,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        display_key="status_label",
        options=TRAVEL_REQUEST_STATUS_OPTIONS,
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        disabled=True,
        display=True,
        help_text=(
            "Berpindah lewat tombol Submit/Approve/Reject, bukan "
            "diketik."
        ),
        order=70,
    ),
}


# Kepala formulir — semuanya turunan dari relasi pegawai, ditampilkan
# read-only. `display=True` wajib: generator FE membuang field
# read_only dari form, dan tanpa penanda ini tab-nya tampil kosong.
EMPLOYEE_FIELDS = {
    name: field.text(
        tab="employee",
        label=label,
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        display=True,
        order=order,
    )
    for name, label, order in (
        ("department_name", "Department", 120),
        ("section_name", "Section", 130),
        ("position_name", "Job Title", 140),
        ("work_email", "Email Address", 150),
        ("phone_number", "Phone Number", 160),
        ("location_name", "Site / Location", 180),
    )
}

# Nomor pegawai ikut jadi kolom tabel, bukan cuma isian read-only di
# tab Employee. Satu orang punya banyak TR setahun dan daftarnya dibaca
# berdampingan dengan pemesanan tiket — nama kembar di satu site tidak
# bisa dibedakan tanpa nomornya. Labelnya disamakan dengan tabel lain
# ("Employee No.", bukan "NIK"): satu kolom berjudul berbeda dari kolom
# yang sama di layar sebelah adalah hal pertama yang dikeluhkan.
EMPLOYEE_FIELDS["employee_number"] = field.text(
    # Duduk di sebelah kolom Employee, bukan terlempar ke ujung
    # kanan tabel — lihat `column_after` di columns.mjs.
    column_after="employee",
    tab="employee",
    label="Employee No.",
    required=False,
    table=True,
    filter=False,
    search=True,
    sortable=True,
    disabled=True,
    display=True,
    order=110,
)

EMPLOYEE_FIELDS["join_date"] = field.date(
    tab="employee",
    label="Date Of Hire",
    required=False,
    table=False,
    filter=False,
    search=False,
    sortable=False,
    disabled=True,
    display=True,
    order=170,
)

EMPLOYEE_FIELDS["point_of_hire_name"] = field.text(
    tab="employee",
    label="Point Of Hire",
    required=False,
    table=False,
    filter=False,
    search=False,
    sortable=False,
    disabled=True,
    display=True,
    help_text=(
        "Kota rekrut — tujuan tiket pulang. Diubah dari master "
        "Employee, bukan dari sini."
    ),
    order=190,
)


NOTE_FIELDS = {
    "notes": field.textarea(
        tab="notes",
        label="Notes",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=210,
    ),
}


TRAVEL_REQUEST_FIELDS = {
    **GENERAL_FIELDS,
    **EMPLOYEE_FIELDS,
    **NOTE_FIELDS,
}


TRAVEL_REQUEST_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "employee_name",
        "company_name",
        "status_label",
        "rotation_period_label",
        "purpose_count",
        "leave_balances",
        "approval",
        "is_editable",
        "company",
        "branch",
        "location",
    )
}


# ----------------------------------------------------------------------
# Tabel "Travel Purpose"
# ----------------------------------------------------------------------

PURPOSE_FIELDS = {
    "purpose": field.lookup(
        tab="general",
        label="Travel Purpose",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/rotation-purposes/"
        ),
        display_key="purpose_name",
        # Dinas Luar/Training tidak ditawarkan — tugas perusahaan
        # diajukan lewat Business Trip (TR-CLEANUP-1). Penjagaannya
        # tetap `TravelRequestPurposeService.assert_purpose_allowed`.
        lookup_params={"document": "travel_request"},
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Field Break, Cuti Tahunan, dan cuti lain yang menumpang "
            "kepulangan site. Satu pengajuan boleh memuat beberapa "
            "baris beralasan berbeda. Dinas Luar/Training diajukan "
            "lewat Business Trip."
        ),
        order=10,
    ),

    "start_date": field.date(
        tab="general",
        label="From",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=20,
    ),

    "end_date": field.date(
        tab="general",
        label="Sampai",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=30,
    ),

    "total_days": field.integer(
        tab="general",
        label="Days",
        # Dihitung ulang di grid begitu tanggalnya diubah. Wajib:
        # baris membawa nilai lamanya, dan service menghormati
        # `total_days` yang dikirim sebagai isian manual.
        compute={
            "kind": "date_diff",
            "from": "start_date",
            "to": "end_date",
            "inclusive": True,
        },
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=40,
    ),

    "deducts_leave": field.switch(
        tab="general",
        label="Deducts Leave",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        disabled=True,
        help_text=(
            "Turunan dari master Travel Purpose. Field Break tidak "
            "memotong saldo; Cuti Tahunan memotong, dan catatan "
            "cutinya diterbitkan otomatis saat pengajuan disetujui."
        ),
        order=50,
    ),

    "notes": field.textarea(
        tab="general",
        label="Remarks",
        rows=2,
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        order=60,
    ),
}


PURPOSE_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "request",
        "sequence",
        "purpose_name",
        "employee_leave",
        "employee_leave_label",
        # Penanda internal "catatan cutinya terbit dari dokumen ini",
        # dipakai `cancel_leave_records` untuk memisahkan cuti terbitan
        # dari cuti milik HR yang cuma diadopsi. Bukan kolom yang perlu
        # dibaca pengisi form, dan bukan kolom yang boleh diketik.
        "leave_issued",
        # Dict bersarang berisi temuan Leave Policy yang berlaku untuk
        # baris ini. Dirender komponen tersendiri, bukan sebagai kolom
        # — kolom tabel yang isinya dict tampil sebagai "[object
        # Object]" di seluruh barisnya. Sebentuk dengan `policy_rules`
        # di modul Cuti.
        "policy_rules",
    )
}


TRAVEL_REQUEST_PURPOSE_SCHEMA = {
    "module": "hr/travel-request-purposes",
    "name": "TravelRequestPurpose",
    "label": "Travel Purpose",
    "endpoint": "/api/hr/travel-request-purposes/",
    "schema_type": "crud",

    "ui": {**ui.dialog(title="Travel Purpose", size="lg", columns=2)},
    "tabs": [
        tabs.form(
            key="general",
            label="Purpose",
            fields=list(PURPOSE_FIELDS.keys()),
            order=10,
            show_on_create=True,
        ),
    ],
    "fields": {
        **PURPOSE_FIELDS,
        **PURPOSE_DISPLAY_FIELDS,
    },
}


# ----------------------------------------------------------------------
# Tabel "Travel Arrangement" + "Accommodation"
# ----------------------------------------------------------------------

ARRANGEMENT_FIELDS = {
    "direction": field.select(
        tab="general",
        label="Direction",
        display_key="direction_label",
        options=TRAVEL_DIRECTION_OPTIONS,
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Outbound = pulang dari site. Inbound = kembali ke site. "
            "Satu arah boleh terdiri dari beberapa etape."
        ),
        order=10,
    ),

    "sequence": field.integer(
        tab="general",
        label="Leg",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        help_text=(
            "Urutan etape dalam satu arah. Dikosongkan = nomor bebas "
            "berikutnya. Jakarta → Sorong = 1, Sorong → Gebe = 2."
        ),
        order=15,
    ),

    "travel_start_date": field.date(
        tab="general",
        label="Departure Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=20,
    ),

    "travel_end_date": field.date(
        tab="general",
        label="Arrival Date",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text="Dikosongkan = tiba di hari yang sama.",
        order=30,
    ),

    "origin": field.text(
        tab="general",
        label="From",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        placeholder="mis. Gebe",
        order=40,
    ),

    "destination": field.text(
        tab="general",
        label="To",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        placeholder="mis. Jakarta",
        order=50,
    ),

    "transport_mode": field.lookup(
        tab="general",
        label="Transport Mode",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/transport-modes/"
        ),
        display_key="transport_mode_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=60,
    ),

    "transport_detail": field.text(
        tab="general",
        label="Transport Detail",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        placeholder="mis. GA-642 / KM Sabuk Nusantara",
        order=70,
    ),

    "ticket_number": field.text(
        tab="general",
        label="Ticket Number",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        order=80,
    ),

    "justification": field.textarea(
        tab="general",
        label="Justification",
        rows=2,
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        help_text=(
            "Alasan perjalanan ini menyimpang dari rotasi normal. "
            "Kosong = perjalanan rutin."
        ),
        order=90,
    ),

    "counts_as_work": field.switch(
        tab="general",
        label="Counts As Work",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Menyala sendiri untuk Kepulangan (kembali ke site). Boleh "
            "dinyalakan untuk keberangkatan yang tertunda."
        ),
        order=100,
    ),

    "is_special_arrangement": field.switch(
        tab="general",
        label="Special Arrangement",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text="Charter, evakuasi medis, rombongan keluarga.",
        order=110,
    ),

    "special_arrangement_notes": field.text(
        tab="general",
        label="Arrangement Detail",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        order=120,
    ),
}


ACCOMMODATION_FIELDS = {
    "accommodation_needed": field.switch(
        tab="accommodation",
        label="Needs Accommodation",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        help_text="Menyala sendiri begitu salah satu isian diisi.",
        order=210,
    ),

    "accommodation_type": field.lookup(
        tab="accommodation",
        label="Accommodation Type",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/accommodation-types/"
        ),
        display_key="accommodation_type_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=220,
    ),

    "accommodation_name": field.text(
        tab="accommodation",
        label="Accommodation Name",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        placeholder="mis. Hotel Bukit Pelangi",
        order=230,
    ),

    "accommodation_checkin": field.date(
        tab="accommodation",
        label="Check-in",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=240,
    ),

    "accommodation_checkout": field.date(
        tab="accommodation",
        label="Check-out",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=250,
    ),

    "accommodation_nights": field.integer(
        tab="accommodation",
        label="Nights",
        # Malam, bukan hari: check-in 30 → check-out 31 = 1 malam.
        compute={
            "kind": "date_diff",
            "from": "accommodation_checkin",
            "to": "accommodation_checkout",
            "inclusive": False,
        },
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        disabled=True,
        order=260,
    ),

    "notes": field.textarea(
        tab="accommodation",
        label="Notes",
        rows=2,
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        order=270,
    ),
}


TRAVEL_ARRANGEMENT_FIELDS = {
    **ARRANGEMENT_FIELDS,
    **ACCOMMODATION_FIELDS,
}


ARRANGEMENT_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "request",
        "direction_label",
        "transport_mode_name",
        "accommodation_type_name",
    )
}


TRAVEL_ARRANGEMENT_SCHEMA = {
    "module": "hr/travel-arrangements",
    "name": "TravelArrangement",
    "label": "Travel Arrangement",
    "endpoint": "/api/hr/travel-arrangements/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Travel & Accommodation",
            size="xl",
            columns=2,
        ),
    },
    "tabs": [
        tabs.form(
            key="general",
            label="Travel",
            fields=list(ARRANGEMENT_FIELDS.keys()),
            order=10,
            show_on_create=True,
        ),
        tabs.form(
            key="accommodation",
            label="Accommodation",
            fields=list(ACCOMMODATION_FIELDS.keys()),
            order=20,
            show_on_create=True,
        ),
    ],
    "fields": {
        **TRAVEL_ARRANGEMENT_FIELDS,
        **ARRANGEMENT_DISPLAY_FIELDS,
    },
}


def _grid(source: dict, keys: tuple[str, ...]) -> dict:
    """
    Salinan config kolom untuk satu tabel inline.

    Grid memilih kolomnya dari flag `table`, jadi dua tabel yang
    membaca endpoint sama wajib membawa salinannya sendiri — mengubah
    flag di tempat akan ikut mengubah tabel yang satunya.
    """
    grid = {}

    for key in keys:
        config = dict(source[key])
        config["table"] = True
        grid[key] = config

    return grid


ARRANGEMENT_GRID_FIELDS = _grid(
    TRAVEL_ARRANGEMENT_FIELDS,
    (
        "direction",
        "sequence",
        "travel_start_date",
        "travel_end_date",
        "origin",
        "destination",
        "transport_mode",
        "transport_detail",
        "ticket_number",
        "justification",
        "counts_as_work",
        "is_special_arrangement",
        "special_arrangement_notes",
    ),
)


ACCOMMODATION_GRID_FIELDS = _grid(
    TRAVEL_ARRANGEMENT_FIELDS,
    (
        "direction",
        "sequence",
        "origin",
        "destination",
        "accommodation_type",
        "accommodation_name",
        "accommodation_checkin",
        "accommodation_checkout",
        "accommodation_nights",
        "notes",
    ),
)

# Arah, nomor etape, dan rutenya menunjuk etape tempat penginapan
# transit menempel ("semalam di Sorong"). Bisa diketik (TR-CLEANUP-1):
# baris yang ditambahkan dari tab ini adalah etape baru, dan tanpa
# arahnya server menolaknya. Departure Date-nya diisi service dari
# check-in (`TravelArrangementService.apply_departure_from_stay`).


# Dokumen yang `is_editable`-nya false: SUBMITTED, APPROVED, CANCELLED.
TRAVEL_REQUEST_LOCKED_WHEN = {
    "field": "is_editable",
    "op": "is_false",
}


TRAVEL_REQUEST_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="employee",
        label="Employee",
        fields=list(EMPLOYEE_FIELDS.keys()),
        order=20,
        show_on_create=False,
    ),

    # Tiga tabel inline, sejajar formulir kertasnya. `inline=True`:
    # barisnya disunting langsung di tabel, tanpa dialog per baris —
    # ini jadwal, dan baris yang justru harus dibandingkan tidak boleh
    # tersembunyi di balik lima modal.
    #
    # Ketiganya dikunci begitu dokumennya tidak lagi bisa disunting.
    # Syaratnya menunjuk `is_editable`, property model yang sama dengan
    # yang dipakai `assert_editable` — bukan daftar status yang disalin
    # ulang ke schema, jadi aturannya tetap satu tempat.
    #
    # Ini pagar tampilan, bukan pagar keamanan: baris yang tetap dikirim
    # ditolak `TravelRequestService.assert_editable()` di service.
    # Gunanya supaya tombol tambah/sunting/hapus tidak ditawarkan untuk
    # sesuatu yang sudah pasti ditolak.
    tabs.resource(
        key="purposes",
        label="Travel Purpose",
        endpoint="/api/hr/travel-request-purposes/",
        module="hr/travel-request-purposes",
        foreign_key="request",
        fields=PURPOSE_FIELDS,
        inline=True,
        requires_record=True,
        order=30,
        readonly_when=TRAVEL_REQUEST_LOCKED_WHEN,
    ),
    tabs.resource(
        key="travels",
        label="Travel Arrangement",
        endpoint="/api/hr/travel-arrangements/",
        module="hr/travel-arrangements",
        foreign_key="request",
        fields=ARRANGEMENT_GRID_FIELDS,
        inline=True,
        requires_record=True,
        order=40,
        readonly_when=TRAVEL_REQUEST_LOCKED_WHEN,
    ),
    tabs.resource(
        key="accommodation",
        label="Accommodation",
        endpoint="/api/hr/travel-arrangements/",
        module="hr/travel-arrangements",
        foreign_key="request",
        fields=ACCOMMODATION_GRID_FIELDS,
        inline=True,
        # Dulu `create=False` — tombol Add Row hilang dan hotel transit
        # tidak bisa dicatat dari tab ini sama sekali (TR-CLEANUP-1).
        #
        # `delete=False` (TR-CLEANUP-2): baris di tab ini adalah etape
        # perjalanannya sendiri, jadi Hapus di sini menghapus tiket dan
        # transportnya juga. Tombolnya hanya untuk baris baru yang belum
        # disimpan; menghapus penginapan = kosongkan kolomnya lalu Save.
        # Hapus etape tetap di tab Travel Arrangement, dan semantik
        # DELETE di API tidak berubah.
        delete=False,
        description=(
            "Each stay belongs to a trip leg. Adding a row here also "
            "adds a leg — complete or correct it in Travel Arrangement. "
            "To remove a stay, clear its fields and save; the leg stays."
        ),
        requires_record=True,
        order=50,
        readonly_when=TRAVEL_REQUEST_LOCKED_WHEN,
    ),

    tabs.form(
        key="notes",
        label="Notes",
        fields=list(NOTE_FIELDS.keys()),
        order=60,
        show_on_create=True,
    ),
]


TRAVEL_REQUEST_ACTIONS = [
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
        endpoint="/api/hr/travel-requests/{id}/submit/",
        method="post",
        refresh=True,
        visible_when={"status": ["draft", "rejected"]},
        confirm={
            "title": "Ajukan Travel Request?",
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
        endpoint="/api/hr/travel-requests/{id}/approve/",
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
        endpoint="/api/hr/travel-requests/{id}/reject/",
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
        icon="Undo2",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/travel-requests/{id}/withdraw/",
        method="post",
        refresh=True,
        visible_when={"status": ["submitted"]},
        confirm={
            "title": "Tarik kembali pengajuan?",
            "description": (
                "Dokumen kembali ke Draft dan bisa disunting lagi. "
                "Jejak pengajuannya tetap tersimpan."
            ),
        },
    ),

    # Bukan pasangan Withdraw, melainkan lanjutannya untuk dokumen
    # yang alurnya sudah selesai: Withdraw menarik pengajuan yang
    # masih menunggu, Cancel menutup dokumen yang sudah disetujui dan
    # mencabut catatan cuti yang terlanjur terbit.
    # Key-nya `cancel_request`, bukan `cancel`: `action.cancel()` di
    # builder sudah memakai key itu untuk tombol "tutup formulir", dan
    # dua arti untuk satu key adalah cara membuat generator frontend
    # memasang tombol yang salah.
    action.custom(
        "cancel_request",
        label="Cancel Request",
        icon="Ban",
        variant="destructive",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/travel-requests/{id}/cancel/",
        method="post",
        refresh=True,
        visible_when={"status": ["approved"]},
        confirm={
            "title": "Batalkan Travel Request?",
            "description": (
                "Dokumen ditutup berstatus Cancelled dan catatan cuti "
                "yang terbit darinya ikut dibatalkan — saldonya "
                "kembali. Nomor cutinya tetap tersimpan. Dokumen ini "
                "tidak bisa diajukan ulang; buat dokumen baru kalau "
                "perjalanannya jadi lagi."
            ),
        },
        fields=[
            {
                "key": "notes",
                "type": "textarea",
                "label": "Alasan Pembatalan",
                "required": False,
            },
        ],
    ),
]


TRAVEL_REQUEST_SCHEMA = {
    "module": "hr/travel-requests",
    "name": "TravelRequest",
    "label": "Travel Request",
    "endpoint": "/api/hr/travel-requests/",
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Travel Request",
            description=(
                "Pengajuan kepulangan pegawai site: alasan, "
                "perjalanan, dan akomodasinya."
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
    "tabs": TRAVEL_REQUEST_TABS,
    "actions": TRAVEL_REQUEST_ACTIONS,
    "fields": {
        **TRAVEL_REQUEST_FIELDS,
        **TRAVEL_REQUEST_DISPLAY_FIELDS,
    },
}
