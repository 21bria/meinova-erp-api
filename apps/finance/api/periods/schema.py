"""Schema UI Accounting Period."""

from apps.framework.builders import action, field, tabs, ui


PERIOD_STATUS_OPTIONS = [
    {"label": "Open", "value": "open"},
    {"label": "Soft Closed", "value": "soft_closed"},
    {"label": "Closed", "value": "closed"},
    {"label": "Locked", "value": "locked"},
]


PERIOD_FIELDS = {
    "fiscal_year": field.lookup(
        tab="general",
        label="Fiscal Year",
        lookup_endpoint="/api/finance/lookup/fiscal-years/",
        display_key="fiscal_year_name",
        required=True,
        table=True,
        filter={"group": "quick", "order": 10},
        sortable=True,
        overview=True,
        order=10,
    ),

    "period_number": field.integer(
        tab="general",
        label="No.",
        required=True,
        table=True,
        filter=False,
        sortable=True,
        order=20,
    ),

    "code": field.text(
        tab="general",
        label="Code",
        required=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        order=30,
    ),

    "name": field.text(
        tab="general",
        label="Name",
        required=True,
        table=True,
        search=True,
        sortable=True,
        order=40,
    ),

    "start_date": field.date(
        tab="general",
        label="Start Date",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        order=50,
    ),

    "end_date": field.date(
        tab="general",
        label="End Date",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        order=60,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        options=PERIOD_STATUS_OPTIONS,
        display_key="status_label",
        default="open",
        table=True,
        filter={"group": "quick", "order": 20},
        sortable=True,
        overview=True,
        order=70,
        # Status **tidak** disunting lewat form. Perpindahannya punya
        # aturan (peta `TRANSITIONS`) dan jejak (siapa menutup, siapa
        # membuka, alasannya), dan dropdown yang bisa melompat dari
        # Locked ke Open dalam satu simpanan membuang keduanya.
        disabled=True,
        help_text=(
            "Diubah lewat tombol Open / Soft Close / Close / Lock, "
            "bukan dari sini — supaya jejaknya tercatat."
        ),
    ),
}


PERIOD_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "fiscal_year_name",
        "fiscal_year_code",
        "company",
        "company_name",
        "status_label",
        "closed_at",
        "closed_by",
        "closed_by_name",
        "reopened_at",
        "reopened_by",
        "reopened_by_name",
        "reopen_reason",
        "allowed_transitions",
        "has_posted_journals",
        "is_active",
    )
}


def _status_action(key, label, icon, target, *, variant="outline", **extra):
    """
    Satu tombol per perpindahan status.

    Empat tombol, bukan satu dropdown: yang membedakan keempatnya bukan
    nilai melainkan akibatnya, dan dropdown menyamakan "tutup sementara"
    dengan "kunci permanen" jadi dua baris yang terlihat sama.

    `visible_when` membaca `allowed_transitions` dari serializer —
    daftar yang dihitung dari peta perpindahan di service, jadi tombol
    yang tampil selalu tombol yang endpoint-nya akan menerima.
    """
    return action.record(
        key,
        endpoint="/api/finance/accounting-periods/{id}/change-status/",
        label=label,
        icon=icon,
        variant=variant,
        placement="secondary",
        modes=["edit"],
        payload={"status": target},
        refresh=True,
        visible_when={
            "field": "allowed_transitions",
            "op": "contains",
            "value": target,
        },
        **extra,
    )


PERIOD_ACTIONS = [
    action.save(),
    action.save_and_close(),

    _status_action(
        "period_open", "Open", "LockOpen", "open",
        variant="default",
        fields=[
            {
                "key": "reason",
                "type": "textarea",
                "label": "Reason",
                "required": False,
                "help_text": (
                    "Wajib diisi kalau periodenya sedang terkunci."
                ),
            },
        ],
    ),

    _status_action(
        "period_soft_close", "Soft Close", "CalendarMinus", "soft_closed",
        confirm={
            "title": "Tutup sementara periode ini?",
            "description": (
                "Transaksi harian berhenti. Yang punya wewenang "
                "'Post to soft-closed accounting period' masih bisa "
                "memposting jurnal penyesuaian."
            ),
        },
    ),

    _status_action(
        "period_close", "Close", "CalendarX", "closed",
        confirm={
            "title": "Tutup periode ini?",
            "description": (
                "Tidak ada jurnal yang bisa diposting ke periode ini "
                "sampai dibuka kembali."
            ),
        },
    ),

    _status_action(
        "period_lock", "Lock", "Lock", "locked",
        variant="destructive",
        confirm={
            "title": "Kunci periode ini?",
            "description": (
                "Dipakai setelah periodenya diaudit atau dilaporkan ke "
                "luar. Membukanya kembali perlu wewenang tersendiri dan "
                "alasan tertulis."
            ),
        },
    ),

    action.export(),
]


ACCOUNTING_PERIOD_SCHEMA = {
    "module": "finance/accounting-periods",
    "name": "AccountingPeriod",
    "label": "Accounting Period",
    "endpoint": "/api/finance/accounting-periods/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Accounting Periods",
            description=(
                "Periode di dalam tahun buku. Statusnya yang menentukan "
                "sebuah jurnal boleh diposting atau tidak."
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
    "actions": PERIOD_ACTIONS,

    "fields": {
        **PERIOD_FIELDS,
        **PERIOD_DISPLAY_FIELDS,
    },
}
