"""Schema UI Fiscal Year."""

from apps.framework.builders import action, field, tabs, ui


FISCAL_YEAR_STATUS_OPTIONS = [
    {"label": "Open", "value": "open"},
    {"label": "Closed", "value": "closed"},
    {"label": "Locked", "value": "locked"},
]


FISCAL_YEAR_FIELDS = {
    "company": field.lookup(
        tab="general",
        label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        default="$me.placement.company",
        required=True,
        table=True,
        filter={"group": "quick", "order": 10},
        sortable=True,
        overview=True,
        order=10,
    ),

    "code": field.text(
        tab="general",
        label="Code",
        required=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    "name": field.text(
        tab="general",
        label="Name",
        required=True,
        table=True,
        search=True,
        sortable=True,
        order=30,
    ),

    "start_date": field.date(
        tab="general",
        label="Start Date",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        order=40,
        help_text=(
            "Tidak harus 1 Januari. Tahun buku 1 April – 31 Maret "
            "berjalan sama saja."
        ),
    ),

    "end_date": field.date(
        tab="general",
        label="End Date",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        order=50,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        options=FISCAL_YEAR_STATUS_OPTIONS,
        display_key="status_label",
        default="open",
        table=True,
        filter={"group": "quick", "order": 20},
        sortable=True,
        order=60,
    ),

    "is_current": field.switch(
        tab="general",
        label="Current Fiscal Year",
        default=False,
        table=True,
        filter=False,
        order=70,
        help_text=(
            "Penanda tampilan, bukan penjagaan. Yang menentukan sebuah "
            "jurnal boleh diposting adalah status periodenya."
        ),
    ),

    "is_active": field.switch(
        tab="general",
        label="Active",
        default=True,
        table=False,
        filter=False,
        order=80,
    ),
}


FISCAL_YEAR_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "company_name",
        "status_label",
        "can_generate_periods",
        "closed_at",
        "closed_by",
    )
}

FISCAL_YEAR_DISPLAY_FIELDS["period_count"] = field.integer(
    label="Periods",
    table=True,
    filter=False,
    search=False,
    sortable=False,
    order=55,
)


FISCAL_YEAR_ACTIONS = [
    action.save(),
    action.save_and_close(),
    action.record(
        "generate_periods",
        endpoint="/api/finance/fiscal-years/{id}/generate-periods/",
        label="Generate Periods",
        icon="CalendarRange",
        variant="default",
        placement="primary",
        modes=["edit"],
        # Hanya selama belum ada periodenya. Dijawab serializer, bukan
        # dihitung layar — lihat `get_can_generate_periods`.
        visible_when={"field": "can_generate_periods", "op": "is_true"},
        fields=[
            {
                "key": "count",
                "type": "integer",
                "label": "Number of Periods",
                "required": True,
                "default": 12,
                "help_text": (
                    "12 = bulanan. 4 = kuartalan. 13 = empat mingguan."
                ),
            },
        ],
        confirm={
            "title": "Susun periode akuntansi?",
            "description": (
                "Periode dibuat merata sepanjang tahun buku dan semuanya "
                "berstatus Open. Bisa disunting satu per satu sesudahnya."
            ),
        },
    ),
    action.export(),
]


FISCAL_YEAR_SCHEMA = {
    "module": "finance/fiscal-years",
    "name": "FiscalYear",
    "label": "Fiscal Year",
    "endpoint": "/api/finance/fiscal-years/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Fiscal Years",
            description=(
                "Tahun buku per perusahaan. Tidak diasumsikan Januari–"
                "Desember."
            ),
            size="lg",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=False,
            export=True,
        ),
    },

    "tabs": [tabs.form("general", label="General")],
    "actions": FISCAL_YEAR_ACTIONS,

    "fields": {
        **FISCAL_YEAR_FIELDS,
        **FISCAL_YEAR_DISPLAY_FIELDS,
    },
}
