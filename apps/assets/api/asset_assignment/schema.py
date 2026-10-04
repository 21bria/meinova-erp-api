from apps.framework.builders import action, field, tabs, ui

from apps.assets.models import AssetCondition, AssignmentStatus, CustodyType


ENDPOINT = "/api/assets/assignments/"

STATUS_OPTIONS = [
    {"label": label, "value": value}
    for value, label in AssignmentStatus.choices
]

TARGET_OPTIONS = [
    {"label": CustodyType.EMPLOYEE.label, "value": CustodyType.EMPLOYEE},
    {"label": CustodyType.ORGANIZATION.label, "value": CustodyType.ORGANIZATION},
]

CONDITION_OPTIONS = [
    {"label": label, "value": value}
    for value, label in AssetCondition.choices
]

DRAFT_ONLY = {"status": [AssignmentStatus.DRAFT]}
IS_EMPLOYEE = {"target_custody_type": [CustodyType.EMPLOYEE]}
IS_ORGANIZATION = {"target_custody_type": [CustodyType.ORGANIZATION]}


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
    "target_custody_type": field.select(
        tab="general",
        label="Assign To",
        options=TARGET_OPTIONS,
        required=True,
        readonly_when={"status": [
            AssignmentStatus.SUBMITTED,
            AssignmentStatus.APPROVED,
            AssignmentStatus.COMPLETED,
            AssignmentStatus.REJECTED,
            AssignmentStatus.CANCELLED,
        ]},
        table=True,
        filter=True,
        order=30,
    ),
    "asset": field.lookup(
        tab="general",
        label="Asset",
        lookup_endpoint="/api/assets/lookup/available-assets/",
        display_key="asset_code",
        lookup_params={"target_custody_type": "$target_custody_type"},
        depends_on="target_custody_type",
        required=True,
        table=True,
        filter=True,
        help_text=(
            "Hanya aset aktif di penyimpanan (STORAGE) yang belum dipesan "
            "Assignment lain, dan kategorinya boleh dipegang tujuan ini."
        ),
        order=40,
    ),
    "employee": field.lookup(
        tab="general",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="employee_name",
        visible_when=IS_EMPLOYEE,
        required=False,
        table=True,
        filter=True,
        help_text="Penerima — subjek dokumen, bukan approver.",
        order=50,
    ),
    "cross_company_reason": field.textarea(
        tab="general",
        label="Cross-Company Reason",
        rows=2,
        visible_when=IS_EMPLOYEE,
        required=False,
        table=False,
        help_text=(
            "Wajib bila penerima berpenempatan di company lain. Kepemilikan "
            "aset tidak berubah."
        ),
        order=55,
    ),
    "department": field.lookup(
        tab="general",
        label="Department",
        lookup_endpoint="/api/administration/organization/lookup/departments/",
        display_key="department_name",
        visible_when=IS_ORGANIZATION,
        required=False,
        table=True,
        filter=True,
        order=60,
    ),
    "pic_employee": field.lookup(
        tab="general",
        label="PIC",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="pic_employee_name",
        visible_when=IS_ORGANIZATION,
        required=False,
        table=False,
        help_text=(
            "Penanggung jawab resmi (opsional). Sopir/operator harian bukan "
            "PIC dan tidak dicatat."
        ),
        order=70,
    ),
    "location": field.lookup(
        tab="general",
        label="Target Location",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="location_name",
        required=True,
        table=True,
        filter=True,
        help_text=(
            "Lokasi fisik barang, milik company pemilik. Boleh berbeda dari "
            "penempatan pegawai — penempatannya tidak diubah."
        ),
        order=80,
    ),
    "facility": field.lookup(
        tab="general",
        label="Target Facility",
        lookup_endpoint="/api/administration/organization/lookup/facilities/",
        display_key="facility_name",
        lookup_params={"location_id": "$location"},
        depends_on="location",
        required=False,
        table=False,
        order=90,
    ),
    "purpose": field.textarea(
        tab="general",
        label="Purpose",
        rows=2,
        required=False,
        table=False,
        order=100,
    ),
}

RESULT_FIELDS = {
    "company": field.lookup(
        tab="result",
        label="Owner Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        read_only=True,
        modes=["edit"],
        table=True,
        filter=True,
        order=200,
    ),
    "source_location": field.lookup(
        tab="result",
        label="Source Location",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="source_location_name",
        read_only=True,
        modes=["edit"],
        table=False,
        filter=True,
        order=210,
    ),
    "is_cross_company": field.switch(
        tab="result",
        label="Cross-Company",
        read_only=True,
        modes=["edit"],
        table=True,
        filter=True,
        order=220,
    ),
    "handover_date": field.date(
        tab="result",
        label="Handover Date",
        read_only=True,
        modes=["edit"],
        table=True,
        sortable=True,
        order=230,
    ),
    "handover_condition": field.select(
        tab="result",
        label="Handover Condition",
        options=CONDITION_OPTIONS,
        read_only=True,
        modes=["edit"],
        table=False,
        order=240,
    ),
}


NOTES_FIELD = [
    {"key": "notes", "type": "textarea", "label": "Notes", "required": False},
]

ASSIGNMENT_ACTIONS = [
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
        label="Complete Handover",
        icon="PackageCheck",
        variant="default",
        placement="primary",
        modes=["edit", "detail"],
        visible_when={"can_complete": True},
        fields=[
            {"key": "handover_date", "type": "date", "label": "Handover Date", "required": False},
            {
                "key": "condition",
                "type": "select",
                "label": "Condition at Handover",
                "options": CONDITION_OPTIONS,
                "required": False,
                "help_text": "Diisi = dicatat ke riwayat kondisi (HANDOVER).",
            },
            {"key": "note", "type": "textarea", "label": "Note", "required": False},
        ],
        confirm={
            "title": "Selesaikan serah terima?",
            "description": (
                "Custody aset berpindah dari penyimpanan ke penerima. "
                "Dokumen tidak bisa diubah lagi."
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


ASSIGNMENT_FIELDS = {**GENERAL_FIELDS, **RESULT_FIELDS}

ASSET_ASSIGNMENT_SCHEMA = {
    "module": "assets/assignments",
    "name": "AssetAssignment",
    "label": "Asset Assignment",
    "endpoint": ENDPOINT,
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Asset Assignment",
            description=(
                "Penyerahan aset dari penyimpanan ke pegawai atau unit. "
                "Persetujuan tidak memindahkan aset — Complete Handover yang "
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
            key="result",
            label="Result",
            fields=list(RESULT_FIELDS.keys()),
            order=20,
            show_on_create=False,
        ),
    ],

    "actions": ASSIGNMENT_ACTIONS,
    "fields": ASSIGNMENT_FIELDS,
}
