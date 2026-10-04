from apps.framework.builders import field, tabs, ui


GENERAL_FIELDS = {
    "code": field.text(
        tab="general",
        label="Code",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        order=10,
    ),

    "name": field.text(
        tab="general",
        label="Crew Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),

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
        search=False,
        sortable=True,
        order=30,
    ),

    "location": field.lookup(
        tab="general",
        label="Location",
        lookup_endpoint=(
            "/api/administration/organization/lookup/locations/"
        ),
        display_key="location_name",
        lookup_params={"company_id": "$company"},
        depends_on="company",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text="Site tempat gelombang ini bekerja.",
        order=40,
    ),
}


CYCLE_FIELDS = {
    "work_schedule": field.lookup(
        tab="cycle",
        label="Work Schedule",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/work-schedules/"
        ),
        lookup_params={"schedule_type": "ROSTER"},
        display_key="work_schedule_name",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        help_text=(
            "Harus bertipe Roster dan sudah mengisi cycle work/off "
            "days — dari situ panjang siklusnya dibaca."
        ),
        order=110,
    ),

    "cycle_start_date": field.date(
        tab="cycle",
        label="Cycle Start Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Hari pertama blok kerja pada siklus mana pun. Ini titik "
            "jangkarnya — tanpa ini pola 6 minggu on / 2 minggu off "
            "tidak bisa dipetakan ke tanggal."
        ),
        order=120,
    ),

    "description": field.textarea(
        tab="cycle",
        label="Description",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=130,
    ),
}


ROSTER_CREW_FIELDS = {
    **GENERAL_FIELDS,
    **CYCLE_FIELDS,
}


ROSTER_CREW_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "company_name",
        "location_name",
        "work_schedule_name",
    )
}

ROSTER_CREW_DISPLAY_FIELDS["cycle_pattern"] = {
    "label": "Cycle",
    "table": True,
    "filter": False,
    "search": False,
    "sortable": False,
    "overview": True,
    "order": 115,
}


ROSTER_CREW_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="cycle",
        label="Cycle",
        fields=list(CYCLE_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
]


ROSTER_CREW_UI = {
    **ui.dialog(
        title="Roster Crew",
        description=(
            "Gelombang rotasi pegawai site beserta titik mulai "
            "siklusnya."
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


ROSTER_CREW_SCHEMA = {
    "module": "administration/calendar/roster-crew",
    "name": "RosterCrew",
    "label": "Roster Crew",
    "endpoint": "/api/administration/calendar/roster-crews/",
    "schema_type": "crud",

    "ui": ROSTER_CREW_UI,
    "tabs": ROSTER_CREW_TABS,
    "fields": {
        **ROSTER_CREW_FIELDS,
        **ROSTER_CREW_DISPLAY_FIELDS,
    },
}
