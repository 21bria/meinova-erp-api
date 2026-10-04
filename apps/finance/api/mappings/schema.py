"""Schema UI Account Mapping."""

from apps.framework.builders import action, field, tabs, ui


MAPPING_FIELDS = {
    "code": field.text(
        tab="general", label="Code", required=True,
        table=True, search=True, sortable=True, overview=True, order=10,
    ),

    "name": field.text(
        tab="general", label="Name", required=True,
        table=True, search=True, sortable=True, order=20,
    ),

    "mapping_key": field.text(
        tab="general",
        label="Mapping Key",
        required=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        filter={"group": "quick", "order": 10},
        order=30,
        help_text=(
            "Peran akuntansi yang dicari kebijakan, mis. SALARY_EXPENSE. "
            "Huruf besar; disamakan otomatis."
        ),
    ),

    "account": field.lookup(
        tab="general",
        label="Account",
        lookup_endpoint="/api/finance/lookup/accounts/",
        lookup_params={"company_id": "$company"},
        display_key="account_name",
        required=True,
        table=True,
        sortable=False,
        overview=True,
        order=40,
    ),

    "company": field.lookup(
        tab="scope",
        label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        required=False,
        table=True,
        filter={"group": "quick", "order": 20},
        sortable=True,
        order=50,
        help_text="Kosong = berlaku untuk semua perusahaan.",
    ),

    "event_type": field.text(
        tab="scope",
        label="Event Type",
        required=False,
        table=True,
        filter={"group": "quick", "order": 30},
        search=True,
        sortable=True,
        order=60,
        help_text="Kosong = berlaku untuk semua jenis kejadian.",
    ),

    "selectors": field.json(
        tab="scope",
        label="Conditions",
        required=False,
        table=False,
        filter=False,
        order=70,
        help_text=(
            'Pasangan kunci–nilai yang harus cocok dengan data '
            'kejadian, mis. {"component_type": "BASIC_SALARY"}. Kosong '
            "= tanpa syarat tambahan. Tiap pasangan menaikkan "
            "kekhususan baris ini."
        ),
    ),

    "location": field.lookup(
        tab="scope",
        label="Site",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        lookup_params={"company_id": "$company"},
        display_key="location_name",
        required=False,
        table=False,
        order=80,
    ),

    "department": field.lookup(
        tab="scope",
        label="Department",
        lookup_endpoint="/api/administration/organization/lookup/departments/",
        lookup_params={"company_id": "$company"},
        display_key="department_name",
        required=False,
        table=False,
        order=90,
    ),

    "cost_center": field.lookup(
        tab="scope",
        label="Cost Center",
        lookup_endpoint="/api/administration/organization/lookup/cost-centers/",
        lookup_params={"company_id": "$company"},
        display_key="cost_center_name",
        required=False,
        table=False,
        order=100,
    ),

    "effective_from": field.date(
        tab="scope", label="Effective From", required=False,
        table=False, filter=False, order=110,
    ),

    "effective_to": field.date(
        tab="scope", label="Effective To", required=False,
        table=False, filter=False, order=120,
    ),

    "is_active": field.switch(
        tab="general", label="Active", default=True,
        table=True, filter={"group": "quick", "order": 40}, order=130,
    ),
}


MAPPING_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "company_name",
        "account_code",
        "account_name",
        "location_name",
        "department_name",
        "cost_center_name",
    )
}

# Ditampilkan, dan itu disengaja: kolom inilah yang menjelaskan kenapa
# satu baris menang atas baris lain. Menyembunyikannya membuat
# pemenangnya terlihat seperti kebetulan.
MAPPING_DISPLAY_FIELDS["specificity"] = field.integer(
    label="Specificity",
    table=True,
    filter=False,
    search=False,
    sortable=True,
    order=45,
)


ACCOUNT_MAPPING_SCHEMA = {
    "module": "finance/account-mappings",
    "name": "AccountMapping",
    "label": "Account Mapping",
    "endpoint": "/api/finance/account-mappings/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Account Mapping",
            description=(
                "Menerjemahkan peran akuntansi jadi akun. Baris yang "
                "lebih khusus menang; dua baris yang sama-sama khusus "
                "ditolak saat dipakai."
            ),
            size="xl",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=False,
            export=True,
        ),
    },

    "tabs": [
        tabs.form("general", label="General"),
        tabs.form("scope", label="Conditions & Scope"),
    ],

    "actions": [action.save(), action.save_and_close(), action.export()],

    "fields": {
        **MAPPING_FIELDS,
        **MAPPING_DISPLAY_FIELDS,
    },
}
