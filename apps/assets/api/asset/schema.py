from apps.framework.builders import action, field, tabs, ui

from apps.assets.models import AssetCondition, AssetStatus, CustodyType


ENDPOINT = "/api/assets/assets/"

STATUS_OPTIONS = [
    {"label": label, "value": value}
    for value, label in AssetStatus.choices
]

CONDITION_OPTIONS = [
    {"label": label, "value": value}
    for value, label in AssetCondition.choices
]

CUSTODY_OPTIONS = [
    {"label": label, "value": value}
    for value, label in CustodyType.choices
]

# Kolom penempatan/kondisi dikunci sesudah aktif; service yang menolak,
# ini hanya supaya layar tidak menawarkan sesuatu yang pasti ditolak.
LOCKED_WHEN_ACTIVE = {"status": [AssetStatus.ACTIVE]}


GENERAL_FIELDS = {
    "asset_code": field.text(
        tab="general",
        label="Asset Code",
        required=False,
        read_only=True,
        modes=["edit"],
        table=True,
        search=True,
        sortable=True,
        overview=True,
        help_text="Diisi sistem (AST) saat aset dibuat dan tidak berubah.",
        order=10,
    ),
    "status": field.select(
        tab="general",
        label="Status",
        options=STATUS_OPTIONS,
        required=False,
        read_only=True,
        modes=["edit"],
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        order=20,
    ),
    "company": field.lookup(
        tab="general",
        label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        required=True,
        readonly_when={"status": [AssetStatus.DRAFT, AssetStatus.ACTIVE]},
        modes=["create", "edit"],
        table=True,
        filter=True,
        sortable=True,
        help_text="Pemilik aset. Tidak bisa diubah sesudah aset dibuat.",
        order=30,
    ),
    "category": field.lookup(
        tab="general",
        label="Category",
        lookup_endpoint="/api/assets/lookup/asset-categories/",
        display_key="category_name",
        required=True,
        readonly_when=LOCKED_WHEN_ACTIVE,
        table=True,
        filter=True,
        sortable=True,
        order=40,
    ),
    "name": field.text(
        tab="general",
        label="Name",
        required=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        order=50,
    ),
    "description": field.textarea(
        tab="general",
        label="Description",
        rows=2,
        required=False,
        table=False,
        order=60,
    ),
    "manufacturer": field.text(
        tab="general",
        label="Manufacturer",
        required=False,
        table=True,
        search=True,
        order=70,
    ),
    "model": field.text(
        tab="general",
        label="Model",
        required=False,
        table=False,
        search=True,
        order=80,
    ),
    "serial_number": field.text(
        tab="general",
        label="Serial Number",
        required=False,
        table=True,
        search=True,
        sortable=True,
        help_text=(
            "Opsional, kecuali kategorinya mewajibkan. Unik per company "
            "tanpa membedakan huruf."
        ),
        order=90,
    ),
    "tag_number": field.text(
        tab="general",
        label="Tag Number",
        required=False,
        table=False,
        search=True,
        help_text="Label/barcode fisik. Unik per company bila diisi.",
        order=100,
    ),
    "condition": field.select(
        tab="general",
        label="Condition",
        options=CONDITION_OPTIONS,
        required=True,
        readonly_when=LOCKED_WHEN_ACTIVE,
        table=True,
        filter=True,
        sortable=True,
        help_text=(
            "Sesudah aktif, kondisi dicatat lewat Record Condition "
            "supaya riwayatnya utuh."
        ),
        order=110,
    ),
}

PLACEMENT_FIELDS = {
    "location": field.lookup(
        tab="placement",
        label="Location",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="location_name",
        lookup_params={"company_id": "$company"},
        depends_on="company",
        required=True,
        readonly_when=LOCKED_WHEN_ACTIVE,
        table=True,
        filter=True,
        sortable=True,
        help_text=(
            "Saat DRAFT: lokasi penyimpanan awal. Sesudah aktif: lokasi "
            "custody saat ini — berpindah hanya lewat dokumen custody."
        ),
        order=200,
    ),
    "facility": field.lookup(
        tab="placement",
        label="Facility",
        lookup_endpoint="/api/administration/organization/lookup/facilities/",
        display_key="facility_name",
        lookup_params={"company_id": "$company", "location_id": "$location"},
        depends_on="location",
        required=False,
        readonly_when=LOCKED_WHEN_ACTIVE,
        table=False,
        filter=True,
        order=210,
    ),
    "custody_type": field.select(
        tab="placement",
        label="Custody",
        options=CUSTODY_OPTIONS,
        required=False,
        read_only=True,
        modes=["edit"],
        table=True,
        order=220,
    ),
    # Ringkasan pemegang siap-tampil (serializer) — kolom "Holder" tabel.
    "custody_holder": field.text(
        tab="placement",
        label="Holder",
        required=False,
        read_only=True,
        modes=["edit"],
        table=True,
        order=225,
    ),
    "custody_started_on": field.date(
        tab="placement",
        label="Custody Since",
        required=False,
        read_only=True,
        modes=["edit"],
        table=False,
        order=230,
    ),
}

ACQUISITION_FIELDS = {
    "acquisition_date": field.date(
        tab="acquisition",
        label="Acquisition Date",
        required=False,
        table=False,
        filter=True,
        order=300,
    ),
    "acquisition_reference": field.text(
        tab="acquisition",
        label="Acquisition Reference",
        required=False,
        table=False,
        search=True,
        help_text="No. PO / invoice. Tanpa nilai uang — nilai milik Fixed Asset.",
        order=310,
    ),
    "supplier_name": field.text(
        tab="acquisition",
        label="Supplier",
        required=False,
        table=False,
        order=320,
    ),
    "warranty_until": field.date(
        tab="acquisition",
        label="Warranty Until",
        required=False,
        table=False,
        order=330,
    ),
}


ASSET_ACTIONS = [
    action.record(
        "activate",
        endpoint=f"{ENDPOINT}{{id}}/activate/",
        label="Activate",
        icon="CheckCircle",
        variant="default",
        placement="primary",
        modes=["edit", "detail"],
        # Status + izin + cakupan dijawab server (`can_activate`, ASSET-6).
        visible_when={"can_activate": True},
        confirm={
            "title": "Aktifkan aset ini?",
            "description": (
                "Aset masuk custody STORAGE di lokasinya. Sesudah aktif, "
                "lokasi hanya berpindah lewat dokumen custody dan aset "
                "tidak bisa dihapus."
            ),
        },
    ),
    action.record(
        "record_condition",
        endpoint=f"{ENDPOINT}{{id}}/record-condition/",
        label="Record Condition",
        icon="ClipboardCheck",
        placement="secondary",
        modes=["edit", "detail"],
        visible_when={"can_record_condition": True},
        fields=[
            {
                "key": "condition",
                "type": "select",
                "label": "Condition",
                "options": CONDITION_OPTIONS,
                "required": True,
            },
            {
                "key": "note",
                "type": "textarea",
                "label": "Note",
                "required": False,
            },
        ],
    ),
]


ASSET_FIELDS = {
    **GENERAL_FIELDS,
    **PLACEMENT_FIELDS,
    **ACQUISITION_FIELDS,
}


ASSET_SCHEMA = {
    "module": "assets/register",
    "name": "Asset",
    "label": "Asset",
    "endpoint": ENDPOINT,
    "schema_type": "crud",

    "ui": {
        # Workspace (ASSET-6): layar detail aset adalah pusat operasional —
        # ringkasan custody, riwayat custody/kondisi, dan dokumen terkait.
        **ui.workspace(
            title="Asset",
            description=(
                "Register aset fisik. Nilai buku dan penyusutan tidak di "
                "sini — itu milik Fixed Asset."
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
        # Tab `custom` diisi komponen tulis tangan di halaman rute
        # (`app/modules/assets/register/detail/`), hanya untuk aset yang
        # sudah ada. Riwayat dibaca dari endpoint read-only
        # `{id}/custody-history/` dan `{id}/condition-history/`.
        tabs.custom(
            "overview",
            component="AssetOverview",
            label="Overview",
            requires_record=True,
            order=5,
        ),
        tabs.form(
            key="general",
            label="General",
            fields=list(GENERAL_FIELDS.keys()),
            order=10,
            show_on_create=True,
        ),
        tabs.form(
            key="placement",
            label="Placement",
            fields=list(PLACEMENT_FIELDS.keys()),
            order=20,
            show_on_create=True,
        ),
        tabs.form(
            key="acquisition",
            label="Acquisition",
            fields=list(ACQUISITION_FIELDS.keys()),
            order=30,
            show_on_create=True,
        ),
        tabs.custom(
            "custody_history",
            component="AssetCustodyHistory",
            label="Custody History",
            requires_record=True,
            order=40,
        ),
        tabs.custom(
            "condition_history",
            component="AssetConditionHistory",
            label="Condition History",
            requires_record=True,
            order=50,
        ),
        tabs.custom(
            "documents",
            component="AssetDocuments",
            label="Documents",
            requires_record=True,
            order=60,
        ),
    ],

    "actions": ASSET_ACTIONS,
    "fields": ASSET_FIELDS,
}
