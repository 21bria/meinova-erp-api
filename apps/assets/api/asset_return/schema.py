from apps.framework.builders import action, field, tabs, ui

from apps.assets.models import AssetCondition, CustodyType, ReturnReason, ReturnStatus


ENDPOINT = "/api/assets/returns/"

STATUS_OPTIONS = [
    {"label": label, "value": value}
    for value, label in ReturnStatus.choices
]

REASON_OPTIONS = [
    {"label": label, "value": value}
    for value, label in ReturnReason.choices
]

SOURCE_TYPE_OPTIONS = [
    {"label": CustodyType.EMPLOYEE.label, "value": CustodyType.EMPLOYEE},
    {"label": CustodyType.ORGANIZATION.label, "value": CustodyType.ORGANIZATION},
]

CONDITION_OPTIONS = [
    {"label": label, "value": value}
    for value, label in AssetCondition.choices
]

DRAFT_ONLY = {"status": [ReturnStatus.DRAFT]}
NOT_DRAFT = [
    ReturnStatus.SUBMITTED,
    ReturnStatus.APPROVED,
    ReturnStatus.COMPLETED,
    ReturnStatus.REJECTED,
    ReturnStatus.CANCELLED,
]


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
        lookup_endpoint="/api/assets/lookup/assets-in-use/",
        display_key="asset_code",
        required=True,
        readonly_when={"status": NOT_DRAFT},
        table=True,
        filter=True,
        help_text=(
            "Hanya aset yang sedang dipegang pegawai atau unit dan tidak "
            "sedang dipesan dokumen lain. Pemegang diambil dari custody."
        ),
        order=30,
    ),
    "reason": field.select(
        tab="general",
        label="Reason",
        options=REASON_OPTIONS,
        required=True,
        readonly_when={"status": NOT_DRAFT},
        table=True,
        filter=True,
        order=40,
    ),
    "destination_location": field.lookup(
        tab="general",
        label="Storage Location",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="destination_location_name",
        required=True,
        readonly_when={"status": NOT_DRAFT},
        table=True,
        filter=True,
        help_text=(
            "Penyimpanan tujuan milik company pemilik aset — boleh lokasi "
            "asal maupun lokasi lain company itu."
        ),
        order=50,
    ),
    "destination_facility": field.lookup(
        tab="general",
        label="Storage Facility",
        lookup_endpoint="/api/administration/organization/lookup/facilities/",
        display_key="destination_facility_name",
        lookup_params={"location_id": "$destination_location"},
        depends_on="destination_location",
        required=False,
        readonly_when={"status": NOT_DRAFT},
        table=False,
        order=60,
    ),
    "notes": field.textarea(
        tab="general",
        label="Notes",
        rows=2,
        required=False,
        table=False,
        order=70,
    ),
}

SOURCE_FIELDS = {
    "company": field.lookup(
        tab="source",
        label="Owner Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        read_only=True,
        modes=["edit"],
        table=True,
        filter=True,
        order=200,
    ),
    "source_custody_type": field.select(
        tab="source",
        label="Returned From",
        options=SOURCE_TYPE_OPTIONS,
        read_only=True,
        modes=["edit"],
        table=True,
        filter=True,
        order=210,
    ),
    "source_employee": field.lookup(
        tab="source",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="source_employee_name",
        read_only=True,
        modes=["edit"],
        table=True,
        filter=True,
        order=220,
    ),
    "source_department": field.lookup(
        tab="source",
        label="Department",
        lookup_endpoint="/api/administration/organization/lookup/departments/",
        display_key="source_department_name",
        read_only=True,
        modes=["edit"],
        table=False,
        filter=True,
        order=230,
    ),
    "source_pic_employee": field.lookup(
        tab="source",
        label="PIC",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="source_pic_employee_name",
        read_only=True,
        modes=["edit"],
        table=False,
        order=240,
    ),
    "source_location": field.lookup(
        tab="source",
        label="Source Location",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="source_location_name",
        read_only=True,
        modes=["edit"],
        table=True,
        filter=True,
        order=250,
    ),
}

RESULT_FIELDS = {
    "return_date": field.date(
        tab="result",
        label="Return Date",
        read_only=True,
        modes=["edit"],
        table=True,
        sortable=True,
        order=300,
    ),
    "return_condition": field.select(
        tab="result",
        label="Return Condition",
        options=CONDITION_OPTIONS,
        read_only=True,
        modes=["edit"],
        table=True,
        filter=True,
        order=310,
    ),
}


NOTES_FIELD = [
    {"key": "notes", "type": "textarea", "label": "Notes", "required": False},
]

RETURN_ACTIONS = [
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
        label="Receive Return",
        icon="PackageCheck",
        variant="default",
        placement="primary",
        modes=["edit", "detail"],
        visible_when={"can_complete": True},
        fields=[
            {"key": "return_date", "type": "date", "label": "Return Date", "required": False},
            {
                "key": "condition",
                "type": "select",
                "label": "Condition at Return",
                "options": CONDITION_OPTIONS,
                "required": True,
                "help_text": "Wajib — dicatat ke riwayat kondisi (RETURN).",
            },
            {"key": "note", "type": "textarea", "label": "Note", "required": False},
        ],
        confirm={
            "title": "Terima pengembalian?",
            "description": (
                "Custody aset kembali ke penyimpanan tujuan. Dokumen tidak "
                "bisa diubah lagi."
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


RETURN_FIELDS = {**GENERAL_FIELDS, **SOURCE_FIELDS, **RESULT_FIELDS}

ASSET_RETURN_SCHEMA = {
    "module": "assets/returns",
    "name": "AssetReturn",
    "label": "Asset Return",
    "endpoint": ENDPOINT,
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Asset Return",
            description=(
                "Pengembalian aset dari pegawai atau unit ke penyimpanan. "
                "Persetujuan tidak memindahkan aset — Receive Return yang "
                "memindahkannya."
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

    "actions": RETURN_ACTIONS,
    "fields": RETURN_FIELDS,
}
