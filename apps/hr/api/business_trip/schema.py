"""
Schema UI Business Trip.

Backend adalah sumber kebenaran bentuk form/tabel. Modul FE-nya belum
digenerate — layar, menu, dan `/me` milik BT-5. Tab mengikuti kontrak
BT-0B §20; tab "Cost & Advance" sengaja belum ada (DEFERRED: belum ada
uang muka/penyelesaian perjalanan).

`visible_when` bukan penjagaan. Yang menolak tetap service.
"""

from apps.framework.builders import action, field, tabs, ui

from apps.hr.models import (
    BusinessTripDestinationType,
    BusinessTripLinkType,
    BusinessTripPurpose,
    BusinessTripStatus,
)


def _options(choices):
    return [
        {"label": str(label), "value": value}
        for value, label in choices.choices
    ]


STATUS_OPTIONS = _options(BusinessTripStatus)
PURPOSE_OPTIONS = _options(BusinessTripPurpose)
DESTINATION_TYPE_OPTIONS = _options(BusinessTripDestinationType)
LINK_TYPE_OPTIONS = _options(BusinessTripLinkType)

IS_INTERNAL = {"destination_type": ["internal_location"]}
IS_EXTERNAL = {
    "destination_type": ["external_domestic", "external_international"],
}


GENERAL_FIELDS = {
    "document_number": field.text(
        tab="general",
        label="Document No.",
        read_only=True,
        required=False,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        help_text="Terbit otomatis saat dokumen disimpan.",
        order=10,
    ),
    "employee": field.lookup(
        tab="general",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        lookup_params={"feature": "business_trip"},
        display_key="employee_name",
        required=False,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        help_text=(
            "Kosongkan untuk mengajukan atas nama sendiri. Hanya pegawai "
            "yang Employee Group-nya memakai Business Trip."
        ),
        order=20,
    ),
    "request_date": field.date(
        tab="general",
        label="Request Date",
        required=False,
        table=False,
        sortable=True,
        order=30,
    ),
    "status": field.select(
        tab="general",
        label="Status",
        display_key="status_label",
        options=STATUS_OPTIONS,
        read_only=True,
        required=False,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        help_text="Berpindah lewat tombol alur, bukan lewat form.",
        order=40,
    ),
}


TRIP_FIELDS = {
    "purpose_category": field.select(
        tab="trip",
        label="Purpose",
        display_key="purpose_category_label",
        options=PURPOSE_OPTIONS,
        required=True,
        table=True,
        filter=True,
        overview=True,
        order=110,
    ),
    "purpose": field.textarea(
        tab="trip",
        label="Purpose Detail",
        required=True,
        table=False,
        search=True,
        order=120,
    ),
    "destination_type": field.select(
        tab="trip",
        label="Destination Type",
        display_key="destination_type_label",
        options=DESTINATION_TYPE_OPTIONS,
        required=True,
        table=False,
        filter=True,
        order=130,
    ),
    "destination_location": field.lookup(
        tab="trip",
        label="Destination Location",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="destination_location_name",
        required=False,
        visible_when=IS_INTERNAL,
        table=False,
        filter=True,
        order=140,
    ),
    "destination_city": field.lookup(
        tab="trip",
        label="Destination City",
        lookup_endpoint="/api/administration/references/geography/lookup/cities/",
        display_key="destination_city_name",
        required=False,
        visible_when=IS_EXTERNAL,
        table=False,
        filter=False,
        order=150,
    ),
    "destination_country": field.lookup(
        tab="trip",
        label="Destination Country",
        lookup_endpoint=(
            "/api/administration/references/geography/lookup/countries/"
        ),
        display_key="destination_country_name",
        required=False,
        visible_when=IS_EXTERNAL,
        table=False,
        filter=False,
        order=160,
    ),
    "destination_detail": field.text(
        tab="trip",
        label="Destination Detail",
        required=False,
        table=False,
        order=170,
    ),
    "origin_location": field.lookup(
        tab="trip",
        label="Origin",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="origin_location_name",
        required=False,
        table=False,
        filter=False,
        help_text="Bawaannya lokasi kerja pegawai.",
        order=180,
    ),
    "departure_datetime": field.datetime(
        tab="trip",
        label="Departure",
        required=True,
        table=True,
        # Bukan kotak ketik: backend tidak menyaring rentang tanggal di
        # kolom ini, jadi filter teks selalu kosong hasilnya.
        filter=False,
        sortable=True,
        overview=True,
        order=190,
    ),
    "return_datetime": field.datetime(
        tab="trip",
        label="Return",
        required=True,
        table=True,
        sortable=True,
        overview=True,
        order=200,
    ),
    "supersedes": field.lookup(
        tab="trip",
        label="Replaces / Extends",
        lookup_endpoint="/api/hr/business-trips/",
        display_key="supersedes_number",
        required=False,
        table=False,
        filter=False,
        help_text=(
            "Isi hanya untuk dokumen pengganti (dokumen lama sudah "
            "dibatalkan) atau perpanjangan."
        ),
        order=210,
    ),
    "supersede_type": field.select(
        tab="trip",
        label="Link Type",
        display_key="supersede_type_label",
        options=LINK_TYPE_OPTIONS,
        required=False,
        table=False,
        filter=False,
        order=220,
    ),
    "notes": field.textarea(
        tab="trip",
        label="Notes",
        required=False,
        table=False,
        order=230,
    ),
}


DISPLAY_FIELDS = {
    name: {
        "label": label,
        "table": False,
        "filter": False,
        "search": False,
        "read_only": True,
        "overview": True,
        "order": order,
    }
    for name, label, order in (
        ("company_name", "Company", 300),
        ("location_name", "Work Location", 310),
        ("department_name", "Department", 320),
        ("position_name", "Position", 330),
        ("cost_center_name", "Cost Center", 340),
        ("actual_departure_datetime", "Actual Departure", 400),
        ("actual_return_datetime", "Actual Return", 410),
        ("cancellation_reason", "Cancellation Reason", 420),
    )
}

# Kolom model yang ikut terbawa introspeksi tapi **bukan** kolom daftar
# atau penyaring (BT-5). Salinan organisasi dan jejak waktu tetap
# terbaca di tab Assignment / Approval; `is_active` bukan konsep dokumen.
for _name in (
    "is_active",
    "requester",
    "branch",
    "location",
    "division",
    "department",
    "section",
    "position",
    "cost_center",
    "submitted_at",
    "approved_at",
    "rejected_at",
    "departed_at",
    "completed_at",
    "cancelled_at",
    "cancelled_by",
):
    DISPLAY_FIELDS[_name] = {"table": False, "filter": False}


DISPLAY_FIELDS.update({
    # Company tetap kolom daftar dan penyaring — lookup-nya dicakup
    # Organization Scope. Read-only: salinan diisi service.
    "company": field.lookup(
        label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        read_only=True,
        required=False,
        table=True,
        filter=True,
        order=25,
    ),
    # Satu kolom "Destination" untuk ketiga jenis tujuan — lokasi
    # perusahaan, kota/negara, dan keterangan bebas.
    "destination_summary": {
        "label": "Destination",
        "table": True,
        "filter": False,
        "search": False,
        "sortable": False,
        "read_only": True,
        "order": 135,
    },
    "attachment": {"label": "Attachment", "tab": "attachments",
                   "table": False, "filter": False, "order": 600},
    "legs": {"label": "Travel & Accommodation", "table": False,
             "filter": False, "search": False, "sortable": False,
             "order": 500},
    "approval": {"label": "Approval", "table": False, "filter": False,
                 "search": False, "sortable": False, "order": 510},
})


BUSINESS_TRIP_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="trip",
        label="Trip Information",
        # `supersedes` / `supersede_type` belum diisi dari form: belum ada
        # lookup Business Trip yang tersaring per pegawai (BT-5 gap).
        # Hubungannya tetap terbaca di tab Approval / History.
        fields=[
            name
            for name in TRIP_FIELDS
            if name not in ("supersedes", "supersede_type")
        ],
        order=20,
        show_on_create=True,
    ),
    tabs.form(
        key="attachments",
        label="Attachment",
        fields=["attachment"],
        order=50,
        show_on_create=True,
    ),
    tabs.custom(
        key="assignment",
        label="Assignment",
        component="BusinessTripAssignment",
        requires_record=True,
        order=30,
    ),
    tabs.custom(
        key="travel",
        label="Travel & Accommodation",
        component="BusinessTripLegs",
        requires_record=True,
        order=40,
    ),
    tabs.custom(
        key="approval",
        label="Approval / History",
        component="BusinessTripApproval",
        requires_record=True,
        order=60,
    ),
]


def _post(key, label, *, icon, variant, placement, visible_when,
          fields=None, confirm=None):
    extra = {}

    if fields:
        extra["fields"] = fields

    if confirm:
        extra["confirm"] = confirm

    return action.custom(
        key,
        label=label,
        icon=icon,
        variant=variant,
        placement=placement,
        modes=["edit"],
        endpoint=f"/api/hr/business-trips/{{id}}/{key}/",
        method="post",
        refresh=True,
        visible_when=visible_when,
        **extra,
    )


NOTES_FIELD = [
    {"key": "notes", "type": "textarea", "label": "Catatan", "required": True},
]


BUSINESS_TRIP_ACTIONS = [
    _post("submit", "Submit for Approval", icon="Send", variant="default",
          placement="primary", visible_when={"status": ["draft", "rejected"]},
          confirm={
              "title": "Ajukan Business Trip?",
              "description": (
                  "Dokumen dikirim ke alur persetujuan dan tidak bisa "
                  "disunting sampai keputusannya keluar."
              ),
          }),
    _post("approve", "Approve", icon="CheckCircle2", variant="default",
          placement="primary", visible_when={"approval.can_act": True}),
    _post("reject", "Reject", icon="XCircle", variant="destructive",
          placement="secondary", visible_when={"approval.can_act": True},
          fields=NOTES_FIELD),
    _post("return", "Return", icon="Undo2", variant="outline",
          placement="secondary", visible_when={"approval.can_act": True},
          fields=NOTES_FIELD),
    _post("withdraw", "Withdraw", icon="RotateCcw", variant="outline",
          placement="secondary", visible_when={"status": ["submitted"]}),
    _post("depart", "Mark Departed", icon="PlaneTakeoff", variant="default",
          placement="primary", visible_when={"status": ["approved"]}),
    _post("complete", "Complete", icon="PlaneLanding", variant="default",
          placement="primary",
          visible_when={"status": ["approved", "on_trip"]},
          fields=[{"key": "actual_return_datetime", "type": "datetime",
                   "label": "Actual Return", "required": True}]),
    _post("cancel", "Cancel", icon="Ban", variant="destructive",
          placement="secondary",
          visible_when={"status": ["approved", "on_trip"]},
          fields=[{"key": "cancellation_reason", "type": "textarea",
                   "label": "Alasan Pembatalan", "required": True}]),
]


BUSINESS_TRIP_UI = {
    **ui.workspace(
        title="Business Trip",
        description=(
            "Perjalanan dinas resmi pegawai. Bukan kepulangan site "
            "(Travel Request) dan bukan kunjungan tamu (Visitor Request)."
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


BUSINESS_TRIP_SCHEMA = {
    "module": "hr/business-trips",
    "name": "Business Trip",
    "label": "Business Trip",
    "endpoint": "/api/hr/business-trips/",
    "schema_type": "crud",
    "ui": BUSINESS_TRIP_UI,
    "tabs": BUSINESS_TRIP_TABS,
    "actions": BUSINESS_TRIP_ACTIONS,
    "fields": {
        **GENERAL_FIELDS,
        **TRIP_FIELDS,
        **DISPLAY_FIELDS,
    },
}


BUSINESS_TRIP_LEG_FIELDS = {
    "trip": field.lookup(
        label="Business Trip",
        lookup_endpoint="/api/hr/business-trips/",
        required=True,
        table=False,
        order=10,
    ),
    "direction": field.select(
        label="Direction",
        display_key="direction_label",
        options=[
            {"label": "Outbound", "value": "outbound"},
            {"label": "Return", "value": "return"},
            {"label": "Intermediate", "value": "intermediate"},
        ],
        required=True,
        table=True,
        order=20,
    ),
    "sequence": field.integer(label="Sequence", table=True, order=30),
    "travel_start_date": field.date(
        label="Travel Date", required=True, table=True, order=40,
    ),
    "travel_end_date": field.date(label="Arrival Date", table=True, order=50),
    "origin": field.text(label="From", table=True, order=60),
    "destination": field.text(label="To", table=True, order=70),
    "transport_mode": field.lookup(
        label="Transport",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/transport-modes/"
        ),
        display_key="transport_mode_name",
        table=True,
        order=80,
    ),
    "transport_detail": field.text(label="Transport Detail", order=90),
    "ticket_number": field.text(label="Ticket No.", table=True, order=100),
    "accommodation_needed": field.boolean(
        label="Accommodation Needed", order=110,
    ),
    "accommodation_type": field.lookup(
        label="Accommodation Type",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/accommodation-types/"
        ),
        display_key="accommodation_type_name",
        visible_when={"accommodation_needed": [True]},
        order=120,
    ),
    "accommodation_name": field.text(
        label="Accommodation",
        visible_when={"accommodation_needed": [True]},
        order=130,
    ),
    "check_in_date": field.date(
        label="Check-in",
        visible_when={"accommodation_needed": [True]},
        order=140,
    ),
    "check_out_date": field.date(
        label="Check-out",
        visible_when={"accommodation_needed": [True]},
        order=150,
    ),
    "notes": field.textarea(label="Notes", order=160),
}


BUSINESS_TRIP_LEG_SCHEMA = {
    "module": "hr/business-trip-legs",
    "name": "Business Trip Leg",
    "label": "Business Trip Leg",
    "endpoint": "/api/hr/business-trip-legs/",
    "schema_type": "crud",
    "ui": ui.workspace(
        title="Travel & Accommodation",
        size="lg",
        columns=2,
        create=True,
        edit=True,
        delete=True,
        bulk_delete=False,
        export=False,
    ),
    "fields": BUSINESS_TRIP_LEG_FIELDS,
}
