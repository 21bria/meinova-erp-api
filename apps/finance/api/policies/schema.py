"""Schema UI Accounting Policy — kebijakan, aturan, dan barisnya."""

from apps.framework.builders import action, field, tabs, ui


SIDE_OPTIONS = [
    {"label": "Debit", "value": "debit"},
    {"label": "Credit", "value": "credit"},
]


POLICY_LINE_FIELDS = {
    "sequence": field.integer(label="No.", default=1, table=True, order=10),
    "side": field.select(
        label="Side",
        options=SIDE_OPTIONS,
        display_key="side_label",
        required=True,
        table=True,
        order=20,
    ),
    "mapping_key": field.text(
        label="Mapping Key",
        required=False,
        table=True,
        order=30,
        help_text=(
            "Peran akuntansi yang dicari di Account Mapping. Isi ini "
            "atau Account — salah satunya wajib."
        ),
    ),
    "account": field.lookup(
        label="Account (direct)",
        lookup_endpoint="/api/finance/lookup/accounts/",
        display_key="account_name",
        required=False,
        table=True,
        order=40,
        help_text="Untuk kasus yang memang tidak bercabang.",
    ),
    "amount_source": field.text(
        label="Amount Source",
        required=True,
        table=True,
        order=50,
        help_text=(
            "Jalur nilai di data kejadian, boleh menembus titik "
            "(`employer.bpjs_health`)."
        ),
    ),
    "dimension_sources": field.json(
        label="Dimension Sources",
        required=False,
        table=False,
        order=60,
        help_text=(
            'Peta {kode dimensi: jalur data}, mis. '
            '{"cost_center": "cost_center_id"}.'
        ),
    ),
    "description_template": field.text(
        label="Description Template", required=False, table=False, order=70,
    ),
    "skip_when_zero": field.switch(
        label="Skip When Zero", default=True, table=False, order=80,
    ),
}


POLICY_RULE_FIELDS = {
    "sequence": field.integer(label="No.", default=1, table=True, order=10),
    "name": field.text(label="Rule", required=True, table=True, order=20),
    "conditions": field.json(
        label="Conditions",
        required=False,
        table=False,
        order=30,
        help_text=(
            'Bentuknya sama dengan syarat step approval: '
            '{"field": ..., "op": ..., "value": ...} digabung '
            'all/any/not. Kosong = selalu cocok.'
        ),
    ),
    "iterate_over": field.text(
        label="Iterate Over",
        required=False,
        table=True,
        order=40,
        help_text=(
            "Kunci daftar di dalam data kejadian yang dijalankan per "
            "baris, mis. `components`. Kosong = data dinilai utuh."
        ),
    ),
    "stop_on_match": field.switch(
        label="Stop On Match", default=False, table=False, order=50,
    ),
}


POLICY_FIELDS = {
    "code": field.text(
        tab="general", label="Code", required=True,
        table=True, search=True, sortable=True, overview=True, order=10,
    ),
    "name": field.text(
        tab="general", label="Name", required=True,
        table=True, search=True, sortable=True, order=20,
    ),
    "event_type": field.text(
        tab="general",
        label="Event Type",
        required=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        filter={"group": "quick", "order": 10},
        order=30,
        help_text=(
            "Nama kejadian yang dilayani, mis. PAYROLL_POSTED. Finance "
            "tidak punya daftar tertutup — modul sumber yang menamainya."
        ),
    ),
    "company": field.lookup(
        tab="general",
        label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        required=False,
        table=True,
        filter={"group": "quick", "order": 20},
        sortable=True,
        order=40,
        help_text="Kosong = berlaku untuk semua perusahaan.",
    ),
    "journal_type": field.text(
        tab="general", label="Journal Type", default="automatic",
        table=False, filter=False, order=50,
    ),
    "auto_post": field.switch(
        tab="general",
        label="Auto Post",
        default=True,
        table=True,
        filter={"group": "quick", "order": 25},
        order=55,
        help_text=(
            "Aktif = jurnalnya langsung masuk buku besar. Nonaktif = "
            "terbit sebagai draft dan menunggu persetujuan Finance."
        ),
    ),
    "effective_from": field.date(
        tab="general", label="Effective From", required=False,
        table=False, filter=False, order=60,
    ),
    "effective_to": field.date(
        tab="general", label="Effective To", required=False,
        table=False, filter=False, order=70,
    ),
    "is_active": field.switch(
        tab="general", label="Active", default=True,
        table=True, filter={"group": "quick", "order": 30}, order=80,
    ),
    "description": field.textarea(
        tab="general", label="Notes", required=False,
        table=False, filter=False, order=90,
    ),
}


POLICY_DISPLAY_FIELDS = {
    name: {
        "table": False, "filter": False, "search": False, "sortable": False,
    }
    for name in ("company_name",)
}

POLICY_DISPLAY_FIELDS["rule_count"] = field.integer(
    label="Rules", table=True, filter=False, search=False,
    sortable=False, order=35,
)


ACCOUNTING_POLICY_SCHEMA = {
    "module": "finance/accounting-policies",
    "name": "AccountingPolicy",
    "label": "Accounting Policy",
    "endpoint": "/api/finance/accounting-policies/",
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Accounting Policies",
            description=(
                "Menentukan jurnal apa yang lahir dari sebuah kejadian. "
                "Tidak ada kode akun yang ditanam di modul sumber."
            ),
            size="full",
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
        tabs.resource(
            "rules",
            label="Rules",
            endpoint="/api/finance/accounting-policy-rules/",
            foreign_key="policy",
            fields=POLICY_RULE_FIELDS,
            requires_record=True,
        ),
    ],

    "actions": [action.save(), action.save_and_close(), action.export()],

    "fields": {
        **POLICY_FIELDS,
        **POLICY_DISPLAY_FIELDS,
    },
}


ACCOUNTING_POLICY_RULE_SCHEMA = {
    "module": "finance/accounting-policy-rules",
    "name": "AccountingPolicyRule",
    "label": "Policy Rule",
    "endpoint": "/api/finance/accounting-policy-rules/",
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Policy Rule",
            description="Satu cabang di dalam sebuah kebijakan akuntansi.",
            size="full",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=False,
            export=False,
        ),
    },

    "tabs": [
        tabs.form("general", label="General"),
        tabs.resource(
            "lines",
            label="Journal Line Templates",
            endpoint="/api/finance/accounting-policy-lines/",
            foreign_key="rule",
            fields=POLICY_LINE_FIELDS,
            requires_record=True,
        ),
    ],

    "actions": [action.save(), action.save_and_close()],

    "fields": {
        "policy": field.lookup(
            tab="general",
            label="Policy",
            lookup_endpoint="/api/finance/lookup/accounting-policies/",
            display_key="policy_name",
            required=True,
            table=True,
            order=5,
        ),
        **{
            name: {**config, "tab": "general"}
            for name, config in POLICY_RULE_FIELDS.items()
        },
        "policy_name": {
            "table": False, "filter": False,
            "search": False, "sortable": False,
        },
        "line_count": field.integer(
            label="Lines", table=True, filter=False,
            search=False, sortable=False, order=45,
        ),
    },
}


ACCOUNTING_POLICY_LINE_SCHEMA = {
    "module": "finance/accounting-policy-lines",
    "name": "AccountingPolicyLine",
    "label": "Policy Line",
    "endpoint": "/api/finance/accounting-policy-lines/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Journal Line Template",
            description="Cetakan satu baris jurnal.",
            size="lg",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=False,
            export=False,
        ),
    },

    "tabs": [tabs.form("general", label="General")],
    "actions": [action.save(), action.save_and_close()],

    "fields": {
        "rule": field.hidden(tab="general", label="Rule", order=5),
        **{
            name: {**config, "tab": "general"}
            for name, config in POLICY_LINE_FIELDS.items()
        },
        "account_name": {
            "table": False, "filter": False,
            "search": False, "sortable": False,
        },
        "side_label": {
            "table": False, "filter": False,
            "search": False, "sortable": False,
        },
    },
}
