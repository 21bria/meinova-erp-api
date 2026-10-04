from apps.framework.builders import field, tabs, ui


PROGRAM_STATUS_OPTIONS = [
    {"label": "Planned", "value": "planned"},
    {"label": "Ongoing", "value": "ongoing"},
    {"label": "Completed", "value": "completed"},
    {"label": "Cancelled", "value": "cancelled"},
]


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
        label="Program Name",
        required=True,
        table=True,
        filter=False,
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    "training_category": field.lookup(
        tab="general",
        label="Category",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/"
            "training-categories/"
        ),
        display_key="training_category_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=30,
    ),

    "provider": field.lookup(
        tab="general",
        label="Provider",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/"
            "training-providers/"
        ),
        display_key="provider_name",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=40,
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
        sortable=True,
        help_text=(
            "Kosongkan kalau program berlaku untuk seluruh company."
        ),
        order=50,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        display_key="status_label",
        options=PROGRAM_STATUS_OPTIONS,
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=60,
    ),

    "is_mandatory": field.switch(
        tab="general",
        label="Mandatory",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=70,
    ),
}


SCHEDULE_FIELDS = {
    "start_date": field.date(
        tab="schedule",
        label="Start Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=110,
    ),

    "end_date": field.date(
        tab="schedule",
        label="End Date",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=120,
    ),

    "duration_hours": field.decimal(
        tab="schedule",
        label="Duration (hours)",
        decimal_places=2,
        max_digits=8,
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=True,
        order=130,
    ),

    "venue": field.text(
        tab="schedule",
        label="Venue",
        required=False,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        help_text=(
            "Teks bebas — pelatihan sering di hotel atau kantor vendor "
            "yang tidak ada di master lokasi kerja."
        ),
        order=140,
    ),

    "quota": field.integer(
        tab="schedule",
        label="Quota",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        help_text=(
            "Dikosongkan = tanpa batas peserta. Diisi = pendaftaran "
            "ditolak setelah kuota penuh."
        ),
        order=150,
    ),
}


COST_FIELDS = {
    "cost": field.currency(
        tab="cost",
        label="Cost",
        currency_field="currency",
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        order=210,
    ),

    "currency": field.lookup(
        tab="cost",
        label="Currency",
        lookup_endpoint="/api/administration/currency/lookup/currencies/",
        display_key="currency_code",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        order=220,
    ),

    "description": field.textarea(
        tab="cost",
        label="Description",
        rows=4,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=230,
    ),
}


TRAINING_PROGRAM_FIELDS = {
    **GENERAL_FIELDS,
    **SCHEDULE_FIELDS,
    **COST_FIELDS,
}


TRAINING_PROGRAM_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "training_category_name",
        "provider_name",
        "company_name",
        "currency_code",
        "status_label",
    )
}

TRAINING_PROGRAM_DISPLAY_FIELDS["participant_count"] = {
    "label": "Participants",
    "table": True,
    "filter": False,
    "search": False,
    "sortable": False,
    "overview": True,
    "order": 160,
}


TRAINING_PROGRAM_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="schedule",
        label="Schedule & Venue",
        fields=list(SCHEDULE_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
    tabs.form(
        key="cost",
        label="Cost & Description",
        fields=list(COST_FIELDS.keys()),
        order=30,
        show_on_create=True,
    ),

    # Peserta baru bisa didaftarkan setelah programnya tersimpan —
    # `requires_record` yang menahannya di mode create.
    tabs.resource(
        key="participants",
        label="Participants",
        endpoint="/api/hr/training-participants/",
        module="hr/training-participants",
        foreign_key="program",
        requires_record=True,
        order=40,
    ),
]


TRAINING_PROGRAM_UI = {
    **ui.workspace(
        title="Training",
        description=(
            "Kelola program pelatihan beserta peserta dan hasilnya."
        ),
        size="full",
        columns=2,
        create=True,
        edit=True,
        delete=True,
        bulk_delete=True,
        export=True,
    ),
}


TRAINING_PROGRAM_SCHEMA = {
    "module": "hr/training",
    "name": "TrainingProgram",
    "label": "Training",
    "endpoint": "/api/hr/training-programs/",
    "schema_type": "crud",

    "ui": TRAINING_PROGRAM_UI,
    "tabs": TRAINING_PROGRAM_TABS,
    "fields": {
        **TRAINING_PROGRAM_FIELDS,
        **TRAINING_PROGRAM_DISPLAY_FIELDS,
    },
}
