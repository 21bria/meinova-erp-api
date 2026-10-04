"""Schema UI Accounting Dimension."""

from apps.framework.builders import action, field, tabs, ui


DATA_TYPE_OPTIONS = [
    {"label": "Reference", "value": "reference"},
    {"label": "Text", "value": "text"},
]


DIMENSION_FIELDS = {
    "code": field.text(
        tab="general",
        label="Code",
        required=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        order=10,
        # Kode dimensi inti adalah nama kolom pada baris jurnal.
        # Menggantinya memutus seluruh pemetaan kebijakan yang
        # menyebutnya, dan putusnya tidak berbunyi.
        readonly_when={"field": "is_locked", "op": "is_true"},
        help_text=(
            "Huruf kecil dan garis bawah, mis. `project`. Dipakai "
            "kebijakan akuntansi untuk menunjuk dimensi ini."
        ),
    ),

    "name": field.text(
        tab="general",
        label="Name",
        required=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),

    "data_type": field.select(
        tab="general",
        label="Data Type",
        options=DATA_TYPE_OPTIONS,
        display_key="data_type_label",
        default="reference",
        table=True,
        filter={"group": "quick", "order": 10},
        order=30,
    ),

    "is_required": field.switch(
        tab="general",
        label="Required on Every Line",
        default=False,
        table=True,
        filter={"group": "quick", "order": 20},
        order=40,
        help_text=(
            "Diperiksa saat posting, bukan saat menyimpan draf — draf "
            "yang datanya belum lengkap harus tetap bisa disimpan."
        ),
    ),

    "lookup_endpoint": field.text(
        tab="general",
        label="Lookup Endpoint",
        required=False,
        table=False,
        filter=False,
        order=50,
        visible_when={"field": "data_type", "op": "eq", "value": "reference"},
        help_text=(
            "Endpoint dropdown pemilih nilainya. Kosong = nilainya "
            "diketik."
        ),
    ),

    "lookup_display_key": field.text(
        tab="general",
        label="Lookup Label Key",
        required=False,
        table=False,
        filter=False,
        order=60,
        visible_when={"field": "data_type", "op": "eq", "value": "reference"},
    ),

    "sort_order": field.integer(
        tab="general",
        label="Sort Order",
        default=0,
        table=False,
        filter=False,
        order=70,
    ),

    "is_active": field.switch(
        tab="general",
        label="Active",
        default=True,
        table=True,
        filter=False,
        order=80,
    ),

    "description": field.textarea(
        tab="general",
        label="Notes",
        required=False,
        table=False,
        filter=False,
        order=90,
    ),
}


DIMENSION_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in ("data_type_label", "can_delete", "is_core")
}

DIMENSION_DISPLAY_FIELDS["is_locked"] = field.boolean(
    label="Built-in",
    table=True,
    filter=False,
    search=False,
    sortable=False,
    order=15,
)


ACCOUNTING_DIMENSION_SCHEMA = {
    "module": "finance/accounting-dimensions",
    "name": "AccountingDimension",
    "label": "Accounting Dimension",
    "endpoint": "/api/finance/accounting-dimensions/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Accounting Dimensions",
            description=(
                "Dimensi yang boleh menempel pada baris jurnal. Tujuh "
                "dimensi organisasi sudah terpasang sebagai kolom; yang "
                "ditambahkan di sini disimpan sebagai baris dimensi."
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
    "actions": [action.save(), action.save_and_close(), action.export()],

    "fields": {
        **DIMENSION_FIELDS,
        **DIMENSION_DISPLAY_FIELDS,
    },
}
