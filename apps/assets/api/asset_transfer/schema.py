from apps.framework.builders import action, field, tabs, ui

from apps.assets.models import (
    AssetCondition,
    CustodyType,
    TransferReason,
    TransferStatus,
)


ENDPOINT = "/api/assets/transfers/"

STATUS_OPTIONS = [
    {"label": label, "value": value}
    for value, label in TransferStatus.choices
]

REASON_OPTIONS = [
    {"label": label, "value": value}
    for value, label in TransferReason.choices
]

CUSTODY_OPTIONS = [
    {"label": label, "value": value}
    for value, label in CustodyType.choices
]

# Pilihan tujuan mengikuti fase asal (§10): pemakaian → pemakaian,
# STORAGE → STORAGE. Ini cuma penyaring layar — service dan
# `ck_assets_transfer_same_phase` yang menolak. Sebelum aset dipilih,
# fase asal belum diketahui dan tidak ada pilihan yang ditawarkan.
USAGE_SOURCE = {
    "field": "source_custody_type",
    "op": "in",
    "value": [CustodyType.EMPLOYEE, CustodyType.ORGANIZATION],
}
STORAGE_SOURCE = {
    "field": "source_custody_type",
    "op": "eq",
    "value": CustodyType.STORAGE,
}

TARGET_OPTIONS = [
    {
        "label": CustodyType.EMPLOYEE.label,
        "value": CustodyType.EMPLOYEE,
        "visible_when": USAGE_SOURCE,
    },
    {
        "label": CustodyType.ORGANIZATION.label,
        "value": CustodyType.ORGANIZATION,
        "visible_when": USAGE_SOURCE,
    },
    {
        "label": CustodyType.STORAGE.label,
        "value": CustodyType.STORAGE,
        "visible_when": STORAGE_SOURCE,
    },
]

CONDITION_OPTIONS = [
    {"label": label, "value": value}
    for value, label in AssetCondition.choices
]

DRAFT_ONLY = {"status": [TransferStatus.DRAFT]}
NOT_DRAFT = {"status": [
    TransferStatus.SUBMITTED,
    TransferStatus.APPROVED,
    TransferStatus.COMPLETED,
    TransferStatus.REJECTED,
    TransferStatus.CANCELLED,
]}
TO_EMPLOYEE = {"target_custody_type": [CustodyType.EMPLOYEE]}
TO_ORGANIZATION = {"target_custody_type": [CustodyType.ORGANIZATION]}


def _readonly(label, *, tab, order, lookup=None, display_key=None, table=False, filter=False):
    if lookup is None:
        return field.select(
            tab=tab,
            label=label,
            options=CUSTODY_OPTIONS,
            read_only=True,
            modes=["edit"],
            table=table,
            filter=filter,
            order=order,
        )

    return field.lookup(
        tab=tab,
        label=label,
        lookup_endpoint=lookup,
        display_key=display_key,
        read_only=True,
        modes=["edit"],
        table=table,
        filter=filter,
        order=order,
    )


EMPLOYEES = "/api/hr/employees/lookup/"
DEPARTMENTS = "/api/administration/organization/lookup/departments/"
LOCATIONS = "/api/administration/organization/lookup/locations/"
FACILITIES = "/api/administration/organization/lookup/facilities/"


GENERAL_FIELDS = {
    "document_number": field.text(
        tab="general",
        label="Document No.",
        required=False,
        read_only=True,
        modes=["edit"],
        table=True,
        search=True,
        sortable=True,
        overview=True,
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
    "asset": field.lookup(
        tab="general",
        label="Asset",
        lookup_endpoint="/api/assets/lookup/transferable-assets/",
        display_key="asset_code",
        # Fase asal dari lookup → kolom read-only `source_custody_type`
        # (serializer juga mengirimnya saat draft dibuka), dipakai
        # `visible_when` pilihan "Transfer To" di bawah.
        autofill={"source_custody_type": "custody_type"},
        required=True,
        readonly_when=NOT_DRAFT,
        table=True,
        filter=True,
        help_text=(
            "Aset yang sedang dipakai (kondisi layak) atau di penyimpanan, "
            "dan tidak sedang dipesan dokumen lain. Asal diambil dari custody."
        ),
        order=30,
    ),
    "target_custody_type": field.select(
        tab="general",
        label="Transfer To",
        options=TARGET_OPTIONS,
        required=True,
        readonly_when=NOT_DRAFT,
        table=True,
        filter=True,
        help_text=(
            "Pemakaian → pemakaian, atau penyimpanan → penyimpanan. Dari "
            "penyimpanan ke pemakai = Assignment; dari pemakai ke "
            "penyimpanan = Return."
        ),
        order=40,
    ),
    "reason": field.select(
        tab="general",
        label="Reason",
        options=REASON_OPTIONS,
        required=True,
        readonly_when=NOT_DRAFT,
        table=True,
        filter=True,
        order=50,
    ),
    "target_employee": field.lookup(
        tab="general",
        label="Employee",
        lookup_endpoint=EMPLOYEES,
        display_key="target_employee_name",
        visible_when=TO_EMPLOYEE,
        required=False,
        table=True,
        filter=True,
        help_text="Pemegang baru — subjek dokumen, bukan approver.",
        order=60,
    ),
    "cross_company_reason": field.textarea(
        tab="general",
        label="Cross-Company Reason",
        rows=2,
        visible_when=TO_EMPLOYEE,
        required=False,
        table=False,
        help_text=(
            "Wajib bila pegawai tujuan berpenempatan di company lain. "
            "Kepemilikan aset tidak berubah."
        ),
        order=65,
    ),
    "target_department": field.lookup(
        tab="general",
        label="Department",
        lookup_endpoint=DEPARTMENTS,
        display_key="target_department_name",
        visible_when=TO_ORGANIZATION,
        required=False,
        table=True,
        filter=True,
        order=70,
    ),
    "target_pic_employee": field.lookup(
        tab="general",
        label="PIC",
        lookup_endpoint=EMPLOYEES,
        display_key="target_pic_employee_name",
        visible_when=TO_ORGANIZATION,
        required=False,
        table=False,
        help_text=(
            "Penanggung jawab resmi (opsional). Ganti PIC = Transfer dengan "
            "department sama. Sopir/operator harian bukan PIC."
        ),
        order=80,
    ),
    "target_location": field.lookup(
        tab="general",
        label="Target Location",
        lookup_endpoint=LOCATIONS,
        display_key="target_location_name",
        required=True,
        readonly_when=NOT_DRAFT,
        table=True,
        filter=True,
        help_text="Lokasi fisik tujuan, milik company pemilik aset.",
        order=90,
    ),
    "target_facility": field.lookup(
        tab="general",
        label="Target Facility",
        lookup_endpoint=FACILITIES,
        display_key="target_facility_name",
        lookup_params={"location_id": "$target_location"},
        depends_on="target_location",
        required=False,
        readonly_when=NOT_DRAFT,
        table=False,
        order=100,
    ),
    "notes": field.textarea(
        tab="general",
        label="Notes",
        rows=2,
        required=False,
        table=False,
        order=110,
    ),
}

SOURCE_FIELDS = {
    "company": _readonly(
        "Owner Company",
        tab="source",
        order=200,
        lookup="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        table=True,
        filter=True,
    ),
    "source_custody_type": _readonly("From", tab="source", order=210, table=True, filter=True),
    "source_employee": _readonly(
        "Employee", tab="source", order=220,
        lookup=EMPLOYEES, display_key="source_employee_name", table=True, filter=True,
    ),
    "source_department": _readonly(
        "Department", tab="source", order=230,
        lookup=DEPARTMENTS, display_key="source_department_name", filter=True,
    ),
    "source_pic_employee": _readonly(
        "PIC", tab="source", order=240,
        lookup=EMPLOYEES, display_key="source_pic_employee_name",
    ),
    "source_location": _readonly(
        "Source Location", tab="source", order=250,
        lookup=LOCATIONS, display_key="source_location_name", table=True, filter=True,
    ),
    "source_facility": _readonly(
        "Source Facility", tab="source", order=260,
        lookup=FACILITIES, display_key="source_facility_name",
    ),
}

RESULT_FIELDS = {
    "is_cross_company": field.switch(
        tab="result",
        label="Cross-Company",
        read_only=True,
        modes=["edit"],
        table=True,
        filter=True,
        order=300,
    ),
    "transfer_date": field.date(
        tab="result",
        label="Transfer Date",
        read_only=True,
        modes=["edit"],
        table=True,
        sortable=True,
        order=310,
    ),
    "transfer_condition": field.select(
        tab="result",
        label="Transfer Condition",
        options=CONDITION_OPTIONS,
        read_only=True,
        modes=["edit"],
        table=False,
        order=320,
    ),
}


NOTES_FIELD = [
    {"key": "notes", "type": "textarea", "label": "Notes", "required": False},
]

TRANSFER_ACTIONS = [
    action.record(
        "submit",
        endpoint=f"{ENDPOINT}{{id}}/submit/",
        label="Submit",
        icon="Send",
        variant="default",
        placement="primary",
        modes=["edit", "detail"],
        visible_when={"can_submit": True},
        fields=NOTES_FIELD,
    ),
    action.record(
        "approve",
        endpoint=f"{ENDPOINT}{{id}}/approve/",
        label="Approve",
        icon="Check",
        variant="default",
        placement="primary",
        modes=["edit", "detail"],
        visible_when={"approval.can_act": True},
        fields=NOTES_FIELD,
    ),
    action.record(
        "reject",
        endpoint=f"{ENDPOINT}{{id}}/reject/",
        label="Reject",
        icon="X",
        variant="destructive",
        placement="secondary",
        modes=["edit", "detail"],
        visible_when={"approval.can_act": True},
        fields=NOTES_FIELD,
    ),
    action.record(
        "complete",
        endpoint=f"{ENDPOINT}{{id}}/complete/",
        label="Complete Transfer",
        icon="PackageCheck",
        variant="default",
        placement="primary",
        modes=["edit", "detail"],
        visible_when={"can_complete": True},
        fields=[
            {"key": "transfer_date", "type": "date", "label": "Transfer Date", "required": False},
            {
                "key": "condition",
                "type": "select",
                "label": "Condition at Transfer",
                "options": CONDITION_OPTIONS,
                "required": True,
                "help_text": "Wajib — dicatat ke riwayat kondisi (TRANSFER).",
            },
            {"key": "note", "type": "textarea", "label": "Note", "required": False},
        ],
        confirm={
            "title": "Selesaikan Transfer?",
            "description": (
                "Custody aset berpindah ke tujuan. Dokumen tidak bisa diubah "
                "lagi."
            ),
        },
    ),
    action.record(
        "cancel",
        endpoint=f"{ENDPOINT}{{id}}/cancel/",
        label="Cancel",
        icon="Ban",
        variant="outline",
        placement="secondary",
        modes=["edit", "detail"],
        visible_when={"can_cancel": True},
        fields=NOTES_FIELD,
    ),
]


TRANSFER_FIELDS = {**GENERAL_FIELDS, **SOURCE_FIELDS, **RESULT_FIELDS}

ASSET_TRANSFER_SCHEMA = {
    "module": "assets/transfers",
    "name": "AssetTransfer",
    "label": "Asset Transfer",
    "endpoint": ENDPOINT,
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Asset Transfer",
            description=(
                "Perpindahan aset antar-pemegang, antar-unit, ganti PIC, atau "
                "antar-penyimpanan. Persetujuan tidak memindahkan aset — "
                "Complete Transfer yang memindahkannya."
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
        # Ringkasan siklus hidup (asal → tujuan, arti status, jejak
        # persetujuan) — komponen tulis tangan, `app/modules/assets/shared/`.
        tabs.custom(
            "summary",
            component="AssetMovementSummary",
            label="Summary",
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
            key="source",
            label="Source",
            fields=list(SOURCE_FIELDS.keys()),
            order=20,
            show_on_create=False,
        ),
        tabs.form(
            key="result",
            label="Result",
            fields=list(RESULT_FIELDS.keys()),
            order=30,
            show_on_create=False,
        ),
    ],

    "actions": TRANSFER_ACTIONS,
    "fields": TRANSFER_FIELDS,
}
