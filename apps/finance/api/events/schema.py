"""Schema UI Accounting Event — pemantauan, seluruhnya baca."""

from apps.framework.builders import action, field, tabs, ui


EVENT_STATUS_OPTIONS = [
    {"label": "Pending", "value": "pending"},
    {"label": "Processing", "value": "processing"},
    {"label": "Processed", "value": "processed"},
    {"label": "Failed", "value": "failed"},
    {"label": "Skipped", "value": "skipped"},
    {"label": "Cancelled", "value": "cancelled"},
]


EVENT_FIELDS = {
    "event_type": field.text(
        tab="general", label="Event Type", disabled=True,
        table=True, search=True, sortable=True, overview=True,
        filter={"group": "quick", "order": 10}, order=10,
    ),
    "company": field.lookup(
        tab="general",
        label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        disabled=True,
        table=True,
        filter={"group": "quick", "order": 20},
        sortable=True,
        order=20,
    ),
    "event_date": field.date(
        tab="general", label="Event Date", disabled=True,
        table=True, filter={"group": "quick", "order": 30},
        sortable=True, overview=True, order=30,
    ),
    "status": field.select(
        tab="general", label="Status", options=EVENT_STATUS_OPTIONS,
        display_key="status_label", disabled=True,
        table=True, filter={"group": "quick", "order": 40},
        sortable=True, overview=True, order=40,
    ),
    "source_module": field.text(
        tab="source", label="Source Module", disabled=True,
        table=True, filter={"group": "advanced", "order": 10},
        sortable=True, order=50,
    ),
    "source_type": field.text(
        tab="source", label="Source Type", disabled=True,
        table=True, sortable=True, order=60,
    ),
    "source_id": field.text(
        tab="source", label="Source ID", disabled=True,
        table=True, search=True, order=70,
    ),
    "source_reference": field.text(
        tab="source", label="Reference", disabled=True,
        table=False, search=True, order=80,
    ),
    "idempotency_key": field.text(
        tab="source", label="Idempotency Key", disabled=True,
        table=False, search=True, order=90,
        help_text=(
            "Penanda unik yang mencegah satu kejadian menerbitkan dua "
            "jurnal."
        ),
    ),
    "payload": field.json(
        tab="payload", label="Payload", disabled=True,
        table=False, filter=False, order=100,
    ),
    "error_message": field.textarea(
        tab="general", label="Message", disabled=True,
        table=False, filter=False, order=110,
    ),
    "attempts": field.integer(
        tab="general", label="Attempts", disabled=True,
        table=False, filter=False, order=120,
    ),
    "processed_at": field.datetime(
        tab="general", label="Processed At", disabled=True,
        table=False, filter=False, order=130,
    ),
}


EVENT_DISPLAY_FIELDS = {
    name: {
        "table": False, "filter": False, "search": False, "sortable": False,
    }
    for name in (
        "company_name", "status_label", "policy_code",
        "applied_policy", "generated_journal", "can_retry",
        "is_active",
    )
}

EVENT_DISPLAY_FIELDS["journal_number"] = field.text(
    label="Journal", table=True, filter=False,
    search=True, sortable=False, order=45,
)


ACCOUNTING_EVENT_SCHEMA = {
    "module": "finance/accounting-events",
    "name": "AccountingEvent",
    "label": "Accounting Event",
    "endpoint": "/api/finance/accounting-events/",
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Accounting Events",
            description=(
                "Kejadian yang dikirim modul lain beserta jurnal yang "
                "lahir darinya."
            ),
            size="full",
            columns=2,
            # Seluruhnya baca: kejadian dicatat modul sumber, tidak
            # diketik orang.
            create=False,
            edit=True,
            delete=False,
            bulk_delete=False,
            export=True,
        ),
    },

    "tabs": [
        tabs.form("general", label="General"),
        tabs.form("source", label="Source"),
        tabs.form("payload", label="Payload"),
    ],

    "actions": [
        action.record(
            "retry",
            endpoint="/api/finance/accounting-events/{id}/retry/",
            label="Retry",
            icon="RefreshCw",
            variant="default",
            placement="primary",
            modes=["edit"],
            visible_when={"field": "can_retry", "op": "is_true"},
            confirm={
                "title": "Proses ulang kejadian ini?",
                "description": (
                    "Dipakai setelah kebijakan atau pemetaan akunnya "
                    "diperbaiki. Kejadian yang sudah menerbitkan jurnal "
                    "tidak bisa diproses ulang."
                ),
            },
        ),
        action.export(),
    ],

    "fields": {
        **EVENT_FIELDS,
        **EVENT_DISPLAY_FIELDS,
    },
}
