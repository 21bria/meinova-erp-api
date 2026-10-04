from apps.framework.builders import field, tabs, ui


OVERTIME_STATUS_OPTIONS = [
    {"label": "Recorded", "value": "recorded"},
    {"label": "Cancelled", "value": "cancelled"},
]


GENERAL_FIELDS = {
    "employee": field.lookup(
        tab="general",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
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
        order=10,
    ),

    "work_date": field.date(
        tab="general",
        label="Work Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=20,
    ),

    "overtime_type": field.lookup(
        tab="general",
        label="Overtime Type",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/overtime-types/"
        ),
        display_key="overtime_type_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=30,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        display_key="status_label",
        options=OVERTIME_STATUS_OPTIONS,
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=40,
    ),

    "is_paid": field.switch(
        tab="general",
        label="Paid",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Matikan kalau lembur diganti libur pengganti, bukan uang."
        ),
        order=50,
    ),
}


TIME_FIELDS = {
    "start_time": field.time(
        tab="time",
        label="Start Time",
        required=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=110,
    ),

    "end_time": field.time(
        tab="time",
        label="End Time",
        required=True,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        help_text=(
            "Lebih kecil dari jam mulai dianggap lewat tengah malam."
        ),
        order=120,
    ),

    "duration_minutes": field.integer(
        tab="time",
        label="Duration (minutes)",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Dikosongkan = dihitung otomatis dari jam mulai dan "
            "selesai."
        ),
        order=130,
    ),
}


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
        help_text="Terisi otomatis dari penempatan pegawai.",
        order=210,
    ),

    "branch": field.lookup(
        tab="organization",
        label="Branch",
        lookup_endpoint="/api/administration/organization/lookup/branches/",
        display_key="branch_name",
        lookup_params={"company_id": "$company"},
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        order=220,
    ),

    "location": field.lookup(
        tab="organization",
        label="Location",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="location_name",
        lookup_params={
            "company_id": "$company",
            "branch_id": "$branch",
        },
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        order=230,
    ),
}


NOTE_FIELDS = {
    "reason": field.text(
        tab="notes",
        label="Reason",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        order=310,
    ),

    "notes": field.textarea(
        tab="notes",
        label="Notes",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=320,
    ),
}


OVERTIME_FIELDS = {
    **GENERAL_FIELDS,
    **TIME_FIELDS,
    **ORGANIZATION_FIELDS,
    **NOTE_FIELDS,
}


OVERTIME_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "employee_name",
        "company_name",
        "branch_name",
        "location_name",
        "overtime_type_name",
        "status_label",
    )
}

# Nomor pegawai jadi kolom tersendiri, bukan ikut tenggelam di kolom
# Employee: nama kembar lazim di tenant besar, dan rekap lembur
# dicocokkan dengan file penggajian lewat nomornya.
OVERTIME_DISPLAY_FIELDS["employee_number"] = field.text(
    # Duduk di sebelah kolom Employee, bukan terlempar ke ujung
    # kanan tabel — lihat `column_after` di columns.mjs.
    column_after="employee",
    label="Employee No.",
    read_only=True,
    table=True,
    search=True,
    sortable=True,
    order=5,
)

# Properti model, bukan kolom database — boleh tampil, tidak boleh
# jadi dasar pengurutan di level query.
OVERTIME_DISPLAY_FIELDS["duration_hours"] = {
    "label": "Duration (hours)",
    "table": True,
    "filter": False,
    "search": False,
    "sortable": False,
    "order": 140,
}


OVERTIME_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="time",
        label="Time & Duration",
        fields=list(TIME_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
    tabs.form(
        key="organization",
        label="Organization",
        fields=list(ORGANIZATION_FIELDS.keys()),
        order=30,
        show_on_create=True,
    ),
    tabs.form(
        key="notes",
        label="Reason & Notes",
        fields=list(NOTE_FIELDS.keys()),
        order=40,
        show_on_create=True,
    ),
]


OVERTIME_UI = {
    **ui.workspace(
        title="Overtime",
        description="Catat jam lembur pegawai beserta durasinya.",
        size="full",
        columns=2,
        create=True,
        edit=True,
        delete=True,
        bulk_delete=True,
        export=True,
    ),
}


OVERTIME_SCHEMA = {
    "module": "hr/overtime",
    "name": "Overtime",
    "label": "Overtime",
    "endpoint": "/api/hr/overtimes/",
    "schema_type": "crud",

    "ui": OVERTIME_UI,
    "tabs": OVERTIME_TABS,
    "fields": {
        **OVERTIME_FIELDS,
        **OVERTIME_DISPLAY_FIELDS,
    },
}
