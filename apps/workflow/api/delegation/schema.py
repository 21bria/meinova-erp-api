"""Schema layar Delegation — surat kuasa approval."""

from apps.framework.builders import field, tabs, ui


GENERAL_FIELDS = {
    "delegator": field.lookup(
        tab="general",
        label="Delegator",
        lookup_endpoint="/api/accounts/lookup/users/",
        display_key="delegator_name",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text="Approver yang berhalangan.",
        order=10,
    ),

    "delegate": field.lookup(
        tab="general",
        label="Delegate",
        lookup_endpoint="/api/accounts/lookup/users/",
        display_key="delegate_name",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Yang diberi kuasa memutuskan selama periode ini. "
            "Keputusannya tetap tercatat atas nama Delegator, dengan "
            "namanya sendiri di kolom 'Acted By'."
        ),
        order=20,
    ),

    "starts_at": field.datetime(
        tab="general",
        label="Starts",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=30,
    ),

    "ends_at": field.datetime(
        tab="general",
        label="Ends",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=40,
    ),

    "is_active": field.switch(
        tab="general",
        label="Active",
        required=False,
        table=True,
        filter=True,
        search=False,
        sortable=False,
        order=50,
    ),

    "is_running": field.boolean(
        tab="general",
        label="Currently Active",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        overview=True,
        help_text=(
            "Aktif dan periodenya sedang berjalan hari ini. Aktif saja "
            "belum berarti berlaku."
        ),
        order=60,
    ),
}


SCOPE_FIELDS = {
    "module": field.text(
        tab="scope",
        label="Module",
        required=False,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        help_text="Dikosongkan = berlaku untuk semua modul.",
        order=110,
    ),

    "document_type": field.text(
        tab="scope",
        label="Document Type",
        required=False,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        help_text=(
            "Dikosongkan = berlaku untuk semua jenis dokumen. Kalau "
            "diisi, Module wajib ikut diisi."
        ),
        order=120,
    ),

    "reason": field.textarea(
        tab="scope",
        label="Reason",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=130,
    ),
}


DELEGATION_FIELDS = {
    **GENERAL_FIELDS,
    **SCOPE_FIELDS,
}


DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "delegator_name",
        "delegate_name",
        "scope_label",
    )
}


DELEGATION_SCHEMA = {
    # Namespace katalog terjemahan frontend.
    #
    # Dibaca generator (`scripts/meinova/generators/i18n.mjs`): label
    # kolom/form/filter dipancarkan sebagai
    # `resourceLabel("workflow.delegations.fields.<field>", "<label Inggris>")`
    # alih-alih literal. Argumen keduanya label yang ada di berkas ini,
    # jadi modul tetap benar walau katalognya belum diisi.
    #
    # **Nama field tidak ikut** — hanya labelnya. `approver_type` tetap
    # `approver_type` di payload, di query string, dan di database.
    "i18n": {"namespace": "workflow.delegations"},

    "module": "workflow/delegations",
    "name": "Approval Delegation",
    "label": "Approval Delegation",
    "endpoint": "/api/workflow/delegations/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Approval Delegation",
            description=(
                "Siapa boleh memutuskan atas nama siapa, dan sampai "
                "kapan."
            ),
            size="lg",
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
            key="general",
            label="General",
            fields=list(GENERAL_FIELDS.keys()),
            order=10,
            show_on_create=True,
        ),
        tabs.form(
            key="scope",
            label="Scope",
            fields=list(SCOPE_FIELDS.keys()),
            order=20,
            show_on_create=True,
        ),
    ],
    "fields": {
        **DELEGATION_FIELDS,
        **DISPLAY_FIELDS,
    },
}
