"""
Schema layar Workflow Instance — daftar dokumen yang sedang berjalan.

Read-only sepenuhnya: dokumen masuk ke sini lewat tombol Submit di
modulnya masing-masing, tidak pernah diketik langsung. Layar ini
gunanya menjawab "dokumen saya sedang di meja siapa".
"""

from apps.framework.builders import field, tabs, ui


STATUS_OPTIONS = [
    {"label": "Draft", "value": "draft"},
    {"label": "Pending", "value": "pending"},
    {"label": "Approved", "value": "approved"},
    {"label": "Rejected", "value": "rejected"},
    {"label": "Returned", "value": "returned"},
    {"label": "Cancelled", "value": "cancelled"},
]


DOCUMENT_FIELDS = {
    "document_number": field.text(
        tab="document",
        label="Document No.",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        order=10,
    ),

    "document_label": field.text(
        tab="document",
        label="Document",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        overview=True,
        order=20,
    ),

    "module": field.text(
        tab="document",
        label="Module",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        order=30,
    ),

    "document_type": field.text(
        tab="document",
        label="Document Type",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        order=40,
    ),

    "subject_employee": field.lookup(
        tab="document",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        # **Wajib disebut.** Generator memetakan kolom lookup ke
        # `<nama_field>_name` kalau `display_key` kosong — dan
        # `subject_employee_name` tidak pernah ada di serializer, jadi
        # kolomnya tampil "-" untuk semua baris. Persis yang sempat
        # terjadi di layar ini.
        display_key="subject_name",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=50,
    ),
}


# Kolom hasil introspeksi model yang **sengaja dimatikan**.
#
# Tanpa ini tiap relasi muncul dua kali: `definition` (lookup, jadi
# kolom "Definition") plus `definition_name` (teks, kolom "Workflow")
# yang isinya sama persis. Tabelnya sempat 17 kolom dan harus digulir
# ke samping hanya untuk melihat statusnya.
HIDDEN_COLUMNS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "definition",
        "current_step",
        "submitted_by",
        "company",
        "branch",
        "location",
        "object_id",
        "context",
        "progress",
        "waiting_for",
        "document_url",
        "can_act",
        "approvals",
        "definition_code",
        "status_label",
    )
}

# Nomor pegawai jadi kolom tersendiri, bukan ikut tenggelam di kolom
# Subject. Layar monitoring memuat dokumen dari seluruh modul dan
# seluruh lokasi sekaligus, jadi justru di sinilah dua nama yang mirip
# paling sulit dibedakan — dan yang membaca layar ini tidak selalu
# mengenal orangnya.
HIDDEN_COLUMNS["subject_number"] = field.text(
    # Duduk di sebelah kolom Subject, bukan terlempar ke ujung kanan
    # tabel — lihat `column_after` di columns.mjs.
    column_after="subject_employee",
    label="Employee No.",
    read_only=True,
    table=True,
    search=True,
    sortable=True,
    order=25,
)


STATE_FIELDS = {
    "status": field.select(
        tab="state",
        label="Status",
        display_key="status_label",
        options=STATUS_OPTIONS,
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=110,
    ),

    "current_step_name": field.text(
        tab="state",
        label="Waiting At",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        overview=True,
        help_text="Kotak tanda tangan yang sedang ditunggu.",
        order=120,
    ),

    "definition_name": field.text(
        tab="state",
        label="Workflow",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=False,
        search=True,
        sortable=False,
        order=130,
    ),

    "submitted_at": field.datetime(
        tab="state",
        label="Submitted At",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=140,
    ),

    "completed_at": field.datetime(
        tab="state",
        label="Completed At",
        required=False,
        read_only=True,
        display=True,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        order=150,
    ),

    "submitted_by_name": field.text(
        tab="state",
        label="Submitted By",
        required=False,
        read_only=True,
        display=True,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        order=160,
    ),

    "notes": field.textarea(
        tab="state",
        label="Notes",
        rows=3,
        required=False,
        read_only=True,
        display=True,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=170,
    ),
}


ORGANIZATION_FIELDS = {
    "company_name": field.text(
        tab="document",
        label="Company",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        order=60,
    ),

    "location_name": field.text(
        tab="document",
        label="Location",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=False,
        search=False,
        sortable=False,
        order=70,
    ),
}


INSTANCE_FIELDS = {
    **DOCUMENT_FIELDS,
    **ORGANIZATION_FIELDS,
    **STATE_FIELDS,
}


INSTANCE_SCHEMA = {
    # Namespace katalog terjemahan frontend.
    #
    # Dibaca generator (`scripts/meinova/generators/i18n.mjs`): label
    # kolom/form/filter dipancarkan sebagai
    # `resourceLabel("workflow.instances.fields.<field>", "<label Inggris>")`
    # alih-alih literal. Argumen keduanya label yang ada di berkas ini,
    # jadi modul tetap benar walau katalognya belum diisi.
    #
    # **Nama field tidak ikut** — hanya labelnya. `approver_type` tetap
    # `approver_type` di payload, di query string, dan di database.
    "i18n": {"namespace": "workflow.instances"},

    "module": "workflow/instances",
    "name": "Workflow Instance",
    "label": "Running Document",
    "endpoint": "/api/workflow/instances/",
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Running Documents",
            description=(
                "Dokumen yang sedang berjalan di alur persetujuan, "
                "beserta kotak tanda tangannya."
            ),
            size="full",
            columns=2,
            create=False,
            edit=False,
            delete=False,
            bulk_delete=False,
            export=True,
        ),
    },
    "tabs": [
        tabs.form(
            key="document",
            label="Document",
            fields=(
                list(DOCUMENT_FIELDS.keys())
                + list(ORGANIZATION_FIELDS.keys())
            ),
            order=10,
        ),
        tabs.form(
            key="state",
            label="Workflow",
            fields=list(STATE_FIELDS.keys()),
            order=20,
        ),
        # Jejak persetujuan sengaja **tidak** ditaruh sebagai tab custom
        # di sini. Generator `crud-workspace` belum bisa merender tab
        # bertipe custom — hasilnya cuma kotak "belum tersambung", yang
        # lebih buruk daripada tidak ada. Halaman detailnya ditulis
        # tangan di `app/pages/workflow/instances/[id]/index.vue` dan
        # membaca `GET /api/workflow/instances/<id>/trail/`.
    ],
    "fields": {
        **INSTANCE_FIELDS,
        **HIDDEN_COLUMNS,
    },
}
