"""Schema UI Journal."""

from apps.framework.builders import action, field, tabs, ui


JOURNAL_STATUS_OPTIONS = [
    {"label": "Draft", "value": "draft"},
    {"label": "Pending Approval", "value": "submitted"},
    {"label": "Approved", "value": "approved"},
    {"label": "Posted", "value": "posted"},
    {"label": "Rejected", "value": "rejected"},
    {"label": "Cancelled", "value": "cancelled"},
    {"label": "Reversed", "value": "reversed"},
]

JOURNAL_TYPE_OPTIONS = [
    {"label": "Manual", "value": "manual"},
    {"label": "Automatic", "value": "automatic"},
    {"label": "Adjustment", "value": "adjustment"},
    {"label": "Accrual", "value": "accrual"},
    {"label": "Reversal", "value": "reversal"},
    {"label": "Recurring", "value": "recurring"},
    {"label": "Opening", "value": "opening"},
    {"label": "Closing", "value": "closing"},
    {"label": "Intercompany", "value": "intercompany"},
    {"label": "Allocation", "value": "allocation"},
]


HEADER_FIELDS = {
    "journal_number": field.text(
        tab="general",
        label="Journal No.",
        required=False,
        disabled=True,
        # Diisi backend, jadi disembunyikan di layar create — kotak
        # kosong yang tidak bisa diketik cuma mengundang orang mencoba
        # mengisinya.
        modes=["edit"],
        table=True,
        search=True,
        sortable=True,
        overview=True,
        order=10,
        help_text=(
            "Terisi otomatis dari pola penomoran finance/journal. Kosong "
            "berarti polanya belum diseed — jalankan "
            "seed_administration --only=numbering."
        ),
    ),

    "company": field.lookup(
        tab="general",
        label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        default="$me.placement.company",
        # Terkunci untuk yang cakupannya memang menyiratkan satu
        # perusahaan. Yang cakupannya luas tetap bebas memilih — lihat
        # catatan `$me.*` di docs/claude/security-rbac.md.
        readonly_when={
            "field": "$me.data_scope.values.company",
            "op": "is_not_null",
        },
        required=True,
        table=True,
        filter={"group": "quick", "order": 10},
        sortable=True,
        overview=True,
        order=20,
    ),

    "posting_date": field.date(
        tab="general",
        label="Posting Date",
        required=True,
        table=True,
        filter={"group": "quick", "order": 20},
        sortable=True,
        overview=True,
        order=30,
        help_text=(
            "Menentukan periode akuntansinya. Periode dan tahun buku "
            "diisi sendiri dari tanggal ini."
        ),
    ),

    "document_date": field.date(
        tab="general",
        label="Document Date",
        required=False,
        table=False,
        filter=False,
        order=40,
        help_text="Tanggal dokumen sumbernya. Kosong = tanggal pembukuan.",
    ),

    "journal_type": field.select(
        tab="general",
        label="Journal Type",
        options=JOURNAL_TYPE_OPTIONS,
        display_key="journal_type_label",
        default="manual",
        required=True,
        table=True,
        filter={"group": "quick", "order": 30},
        sortable=True,
        order=50,
    ),

    "currency": field.lookup(
        tab="general",
        label="Currency",
        lookup_endpoint="/api/administration/currency/lookup/currencies/",
        display_key="currency_code",
        required=False,
        table=False,
        filter=False,
        order=60,
        help_text="Kosong = mata uang buku besar perusahaan.",
    ),

    "exchange_rate": field.decimal(
        tab="general",
        label="Exchange Rate",
        decimal_places=6,
        max_digits=20,
        required=False,
        table=False,
        filter=False,
        order=70,
        help_text=(
            "Terhadap mata uang buku besar. Diabaikan kalau mata uang "
            "transaksinya sama."
        ),
    ),

    "description": field.textarea(
        tab="general",
        label="Description",
        rows=3,
        required=False,
        table=True,
        search=True,
        sortable=False,
        order=80,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        options=JOURNAL_STATUS_OPTIONS,
        display_key="status_label",
        default="draft",
        disabled=True,
        modes=["edit"],
        table=True,
        filter={"group": "quick", "order": 40},
        sortable=True,
        overview=True,
        order=90,
    ),
}


SOURCE_FIELDS = {
    "source_module": field.text(
        tab="source",
        label="Source Module",
        required=False,
        disabled=True,
        table=False,
        filter={"group": "advanced", "order": 10},
        order=100,
    ),
    "source_type": field.text(
        tab="source",
        label="Source Type",
        required=False,
        disabled=True,
        table=False,
        filter=False,
        order=110,
    ),
    "source_id": field.text(
        tab="source",
        label="Source ID",
        required=False,
        disabled=True,
        table=False,
        filter=False,
        order=120,
    ),
    "source_reference": field.text(
        tab="source",
        label="Source Reference",
        required=False,
        disabled=True,
        table=False,
        search=True,
        order=130,
    ),
}


# Kolom grid baris jurnal. Bentuknya dict schema apa adanya, jadi
# `MWorkspaceResourceInline` merendernya dengan aturan yang sama dengan
# form penuh — lookup berantai dan kolom read-only ikut tanpa ditulis
# ulang.
LINE_FIELDS = {
    "account": field.lookup(
        label="Account",
        lookup_endpoint="/api/finance/lookup/accounts/",
        lookup_params={"company_id": "$parent.company"},
        display_key="account_name",
        required=True,
        table=True,
        order=10,
        help_text="Hanya akun posting yang muncul — akun grup dikecualikan.",
    ),
    "description": field.text(label="Description", table=True, order=20),
    "debit": field.currency(
        label="Debit", decimal_places=2, default=0, table=True, order=30,
    ),
    "credit": field.currency(
        label="Credit", decimal_places=2, default=0, table=True, order=40,
    ),
    "location": field.lookup(
        label="Site",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        lookup_params={"company_id": "$parent.company"},
        display_key="location_name",
        required=False,
        table=True,
        order=50,
    ),
    "department": field.lookup(
        label="Department",
        lookup_endpoint="/api/administration/organization/lookup/departments/",
        lookup_params={"company_id": "$parent.company"},
        display_key="department_name",
        required=False,
        table=False,
        order=60,
    ),
    "cost_center": field.lookup(
        label="Cost Center",
        lookup_endpoint="/api/administration/organization/lookup/cost-centers/",
        lookup_params={"company_id": "$parent.company"},
        display_key="cost_center_name",
        required=False,
        table=True,
        order=70,
    ),
}


JOURNAL_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "company_name",
        "currency_code",
        "base_currency_code",
        "fiscal_year",
        "fiscal_year_code",
        "accounting_period",
        "accounting_period_code",
        "period_status",
        "base_currency",
        "status_label",
        "journal_type_label",
        "posted_by_name",
        "reversal_of",
        "reversal_of_number",
        "reversed_by",
        "reversed_by_number",
        "lines",
        "base_total_debit",
        "base_total_credit",
        "difference",
        "is_balanced",
        "can_edit",
        "can_save",
        "can_delete",
        "can_post",
        "can_reverse",
        "metadata",
        "status_reason",
        "submitted_at", "submitted_by",
        "approved_at", "approved_by",
        "posted_at", "posted_by",
        "reversed_at", "reversed_by_user",
        "cancelled_at", "cancelled_by",
        "is_active",
    )
}

# Dua total yang memang ditampilkan — kaki tabel dan kaki form membaca
# keduanya untuk menunjukkan seimbang atau tidak.
JOURNAL_DISPLAY_FIELDS["total_debit"] = field.currency(
    label="Total Debit", table=True, filter=False, sortable=True, order=95,
)
JOURNAL_DISPLAY_FIELDS["total_credit"] = field.currency(
    label="Total Credit", table=True, filter=False, sortable=True, order=96,
)


JOURNAL_ACTIONS = [
    action.save(),
    action.save_and_close(),

    action.submit(
        endpoint="/api/finance/journals/{id}/submit/",
        modes=["edit"],
        visible_when={"status": ["draft", "rejected"]},
        confirm={
            "title": "Ajukan jurnal ini?",
            "description": (
                "Isinya terkunci selama menunggu persetujuan. Kalau "
                "tidak ada alur persetujuan yang dikonfigurasi, jurnal "
                "langsung berstatus Approved dan siap diposting."
            ),
        },
    ),

    action.withdraw(
        endpoint="/api/finance/journals/{id}/withdraw/",
        modes=["edit"],
        visible_when={"status": ["submitted"]},
    ),

    action.record(
        "post",
        endpoint="/api/finance/journals/{id}/post/",
        label="Post",
        icon="BookCheck",
        variant="default",
        placement="primary",
        modes=["edit"],
        visible_when={"field": "can_post", "op": "is_true"},
        confirm={
            "title": "Posting jurnal ke buku besar?",
            "description": (
                "Sesudah diposting, jurnal ini tidak bisa diubah maupun "
                "dihapus. Koreksinya lewat Reverse."
            ),
        },
    ),

    action.record(
        "reverse",
        endpoint="/api/finance/journals/{id}/reverse/",
        label="Reverse",
        icon="Undo2",
        variant="destructive",
        placement="secondary",
        modes=["edit", "detail"],
        visible_when={"field": "can_reverse", "op": "is_true"},
        fields=[
            {
                "key": "reason",
                "type": "textarea",
                "label": "Reason",
                "required": True,
                "help_text": (
                    "Tercetak di keterangan jurnal pembaliknya."
                ),
            },
            {
                "key": "posting_date",
                "type": "date",
                "label": "Reversal Posting Date",
                "required": False,
                "help_text": (
                    "Kosong = tanggal jurnal aslinya. Isi kalau periode "
                    "lamanya sudah ditutup."
                ),
            },
        ],
    ),

    action.record(
        "cancel_journal",
        endpoint="/api/finance/journals/{id}/cancel/",
        label="Cancel",
        icon="Ban",
        variant="destructive",
        placement="secondary",
        modes=["edit"],
        visible_when={"status": ["draft", "rejected", "approved"]},
        fields=[
            {
                "key": "reason",
                "type": "textarea",
                "label": "Reason",
                "required": False,
            },
        ],
        confirm={
            "title": "Batalkan jurnal ini?",
            "description": (
                "Dokumen ditutup berstatus Cancelled. Yang sudah "
                "diposting tidak dibatalkan — ia dibalik."
            ),
        },
    ),

    action.collection(
        "post_all",
        endpoint="/api/finance/journals/post-all/",
        label="Post Selected",
        icon="BookCheck",
        selection="optional",
        confirm={
            "title": "Posting jurnal ke buku besar?",
            "description": (
                "Jurnal yang sudah diposting dilewati, bukan digagalkan. "
                "Yang tidak lolos pemeriksaan dilaporkan beserta "
                "alasannya dan tidak menghentikan sisanya."
            ),
        },
    ),

    action.export(),
]


JOURNAL_SCHEMA = {
    "module": "finance/journals",
    "name": "Journal",
    "label": "Journal",
    "endpoint": "/api/finance/journals/",
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Journals",
            description=(
                "Jurnal umum: entri manual, jurnal penyesuaian, dan "
                "jurnal otomatis dari modul lain."
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
            "lines",
            label="Journal Lines",
            endpoint="/api/finance/journal-lines/",
            foreign_key="journal",
            fields=LINE_FIELDS,
            requires_record=True,
        ),
        tabs.form("source", label="Source Document"),
    ],

    "actions": JOURNAL_ACTIONS,

    "fields": {
        **HEADER_FIELDS,
        **SOURCE_FIELDS,
        **JOURNAL_DISPLAY_FIELDS,
    },
}


# Schema baris jurnal sebagai resource tersendiri.
#
# Dibutuhkan `framework_schema_view` supaya tab `lines` di workspace
# punya endpoint yang bisa ditembak. `ui.create/edit/delete` dimatikan
# karena layarnya sendiri tidak pernah dibuka langsung — barisnya hanya
# diakses dari dalam dokumen induknya, dan daftar rata berisi seluruh
# baris jurnal se-tenant tidak berguna untuk siapa pun.
JOURNAL_LINE_SCHEMA = {
    "module": "finance/journal-lines",
    "name": "JournalLine",
    "label": "Journal Line",
    "endpoint": "/api/finance/journal-lines/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Journal Line",
            description="Satu sisi dari sebuah ayat jurnal.",
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
        "journal": field.hidden(tab="general", label="Journal", order=5),
        **{
            name: {**config, "tab": "general"}
            for name, config in LINE_FIELDS.items()
        },
    },
}
