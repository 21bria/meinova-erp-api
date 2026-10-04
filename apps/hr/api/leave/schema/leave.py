from apps.framework.builders import action, field, tabs, ui


# Dua jalur hidup berdampingan, dan itu disengaja. RECORDED = dicatat
# HR untuk cuti yang sudah terjadi di luar sistem (dan yang diterbitkan
# Travel Request). DRAFT → SUBMITTED → APPROVED/REJECTED = pegawai
# mengajukan sendiri lewat alur persetujuan.
LEAVE_STATUS_OPTIONS = [
    {"label": "Draft", "value": "draft"},
    {"label": "Submitted", "value": "submitted"},
    {"label": "Approved", "value": "approved"},
    {"label": "Rejected", "value": "rejected"},
    {"label": "Recorded", "value": "recorded"},
    {"label": "Cancelled", "value": "cancelled"},
]


GENERAL_FIELDS = {
    "document_number": field.text(
        tab="general",
        label="Document No.",
        required=False,
        read_only=True,
        display=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        help_text=(
            "Terisi otomatis dari deret LV saat cuti disimpan. "
            "Dipakai mencari dokumennya di layar Workflow."
        ),
        order=5,
    ),

    "employee": field.lookup(
        tab="general",
        label="Employee",
        lookup_endpoint="/api/hr/employees/lookup/",
        display_key="employee_name",
        autofill={
            "company": "company",
            "branch": "branch",
            "location": "location",
        },
        required=True,
        table=True,
        filter=True,
        search=True,
        sortable=True,
        overview=True,
        order=10,
    ),

    "leave_type": field.lookup(
        tab="general",
        label="Leave Type",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/leave-types/"
        ),
        display_key="leave_type_name",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=20,
    ),

    "leave_reason": field.lookup(
        tab="general",
        label="Leave Reason",
        lookup_endpoint=(
            "/api/administration/references/hr/lookup/leave-reasons/"
        ),
        display_key="leave_reason_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        order=30,
    ),

    # **Kolom tabel dan filter, bukan isian.** Status cuti berpindah
    # lewat jalurnya sendiri (`submit/`, alur, `withdraw/`, `record/`,
    # `cancel/`), dan serializer menolak body yang menyebut `status`.
    # Karena itu ia sengaja tidak masuk daftar field tab "general" di
    # bawah — formulir yang menawarkannya cuma bisa menghasilkan 400.
    "status": field.select(
        tab="general",
        label="Status",
        display_key="status_label",
        options=LEAVE_STATUS_OPTIONS,
        required=False,
        form=False,
        read_only=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=40,
    ),
}


# Field tab "General" yang benar-benar diketik orang.
GENERAL_FORM_FIELDS = [
    name for name in GENERAL_FIELDS if name != "status"
]


PERIOD_FIELDS = {
    "start_date": field.date(
        tab="period",
        label="Start Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        overview=True,
        order=110,
    ),

    "end_date": field.date(
        tab="period",
        label="End Date",
        required=True,
        table=True,
        filter=True,
        search=False,
        sortable=True,
        order=120,
    ),

    "is_half_day": field.switch(
        tab="period",
        label="Half Day",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=False,
        help_text=(
            "Hanya berlaku kalau Start Date dan End Date sama."
        ),
        order=130,
    ),

    "total_days": field.decimal(
        tab="period",
        label="Total Days",
        decimal_places=1,
        max_digits=5,
        required=False,
        table=True,
        filter=False,
        search=False,
        sortable=True,
        overview=True,
        help_text=(
            "Dikosongkan = dihitung otomatis dari hari kerja pegawai. "
            "Akhir pekan dan hari libur tidak memotong saldo."
        ),
        order=140,
    ),
}


ORGANIZATION_FIELDS = {
    "company": field.lookup(
        tab="organization",
        label="Company",
        lookup_endpoint="/api/administration/organization/lookup/companies/",
        display_key="company_name",
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        help_text="Terisi otomatis dari penempatan pegawai.",
        order=210,
    ),

    "branch": field.lookup(
        tab="organization",
        label="Branch",
        lookup_endpoint="/api/administration/organization/lookup/branches/",
        display_key="branch_name",
        lookup_params={"company_id": "$company"},
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        order=220,
    ),

    "location": field.lookup(
        tab="organization",
        label="Location",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="location_name",
        lookup_params={
            "company_id": "$company",
            "branch_id": "$branch",
        },
        required=False,
        table=False,
        filter=True,
        search=False,
        sortable=True,
        disabled=True,
        order=230,
    ),
}


DOCUMENT_FIELDS = {
    "uploaded_file": field.file(
        tab="document",
        label="Attachment",
        accept=".pdf,.jpg,.jpeg,.png",
        max_size_mb=5,
        required=False,
        table=False,
        filter=False,
        search=False,
        sortable=False,
        help_text="Surat dokter atau dokumen pendukung lainnya.",
        order=310,
    ),

    "notes": field.textarea(
        tab="document",
        label="Notes",
        rows=3,
        required=False,
        table=False,
        filter=False,
        search=True,
        sortable=False,
        order=320,
    ),
}


LEAVE_FIELDS = {
    **GENERAL_FIELDS,
    **PERIOD_FIELDS,
    **ORGANIZATION_FIELDS,
    **DOCUMENT_FIELDS,
}


# Terkunci begitu dokumennya tidak boleh disunting **oleh pembacanya**.
#
# Menunjuk `can_edit`, bukan `is_editable`: yang kedua cuma bicara soal
# status dokumennya, dan sejak approver boleh membuka dokumen yang bukan
# miliknya, status saja tidak lagi menjawab "boleh diketik atau tidak".
# Dokumen yang dikembalikan berstatus DRAFT — `is_editable` benar —
# padahal yang boleh membetulkannya cuma pengajunya.
#
# Ini **pagar tampilan, bukan pagar keamanan**: field yang tetap dikirim
# ditolak `EmployeeLeaveService.assert_editable()` di service, dan baris
# yang bukan cakupannya tidak akan ketemu sama sekali. Gunanya supaya
# approver tidak disodori formulir yang bisa diketik lalu ditolak saat
# disimpan.
#
# Mode Create tidak punya record, jadi `can_edit` belum ada nilainya di
# form — `is_false` hanya benar untuk `false` yang sungguhan, jadi
# formulir baru tetap bisa diisi.
LEAVE_LOCKED_WHEN = {
    "field": "can_edit",
    "op": "is_false",
}

for _meta in LEAVE_FIELDS.values():
    # `setdefault`: field yang sudah punya syaratnya sendiri tidak
    # ditimpa diam-diam.
    _meta.setdefault("readonly_when", LEAVE_LOCKED_WHEN)


# Field turunan hasil serializer — muncul sebagai nilai tampilan pada
# kolom lookup-nya, jadi tidak boleh jadi kolom/filter tersendiri.
LEAVE_DISPLAY_FIELDS = {
    name: {
        "table": False,
        "filter": False,
        "search": False,
        "sortable": False,
    }
    for name in (
        "employee_name",
        "company_name",
        "branch_name",
        "location_name",
        "leave_type_name",
        "leave_reason_name",
        "status_label",
        "uploaded_file_detail",
        "workflow",
        "is_editable",
        "can_edit",
        # Dict bersarang berisi temuan aturan + riwayat. Dirender
        # komponen tersendiri di layar dokumen, bukan sebagai kolom —
        # kolom tabel yang isinya dict tampil sebagai "[object
        # Object]" di seluruh barisnya.
        "policy_rules",
    )
}

# Nomor pegawai jadi kolom tersendiri, bukan ikut tenggelam di kolom
# Employee: nama kembar lazim di tenant besar, dan nomor inilah yang
# dipakai orang mencocokkan baris cuti dengan surat dan file klien.
LEAVE_DISPLAY_FIELDS["employee_number"] = field.text(
    # Duduk di sebelah kolom Employee, bukan terlempar ke ujung
    # kanan tabel — lihat `column_after` di columns.mjs.
    column_after="employee",
    label="Employee No.",
    read_only=True,
    table=True,
    search=True,
    sortable=True,
    order=5,
)


# Tombol alur persetujuan. Belum digenerate FE — generator
# `crud-workspace` tidak membaca kunci `actions` sama sekali — jadi
# endpoint-nya jalan tapi tombolnya belum muncul di layar. Ditulis di
# sini supaya kontraknya sudah ada saat generator FE menyusul.
LEAVE_ACTIONS = [
    action.custom(
        "submit",
        label="Submit",
        icon="Send",
        variant="default",
        placement="primary",
        modes=["edit"],
        endpoint="/api/hr/leaves/{id}/submit/",
        method="post",
        refresh=True,
        visible_when={"status": ["draft", "rejected"]},
    ),

    action.custom(
        "approve",
        label="Approve",
        icon="CheckCircle2",
        variant="default",
        placement="primary",
        modes=["edit"],
        endpoint="/api/hr/leaves/{id}/approve/",
        method="post",
        refresh=True,
        visible_when={"workflow.can_act": True},
    ),

    action.custom(
        "reject",
        label="Reject",
        icon="XCircle",
        variant="destructive",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/leaves/{id}/reject/",
        method="post",
        refresh=True,
        visible_when={"workflow.can_act": True},
        fields=[
            {
                "key": "notes",
                "type": "textarea",
                "label": "Alasan Penolakan",
                "required": True,
            },
        ],
    ),

    action.custom(
        "return",
        label="Return to Requester",
        icon="Undo2",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/leaves/{id}/return/",
        method="post",
        refresh=True,
        visible_when={"workflow.can_act": True},
        fields=[
            {
                "key": "notes",
                "type": "textarea",
                "label": "Yang Perlu Diperbaiki",
                "required": True,
            },
        ],
    ),

    action.custom(
        "cancel",
        label="Cancel Record",
        icon="Ban",
        variant="destructive",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/leaves/{id}/cancel/",
        method="post",
        refresh=True,
        # Hanya cuti pencatatan. Dokumen yang lewat alur ditarik
        # pengajunya atau ditolak approver-nya.
        visible_when={"status": "recorded"},
    ),

    action.custom(
        "withdraw",
        label="Withdraw",
        icon="RotateCcw",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/hr/leaves/{id}/withdraw/",
        method="post",
        refresh=True,
        visible_when={"status": "submitted"},
    ),
]


LEAVE_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=GENERAL_FORM_FIELDS,
        order=10,
        show_on_create=True,
    ),
    tabs.form(
        key="period",
        label="Period",
        fields=list(PERIOD_FIELDS.keys()),
        order=20,
        show_on_create=True,
    ),
    tabs.form(
        key="organization",
        label="Organization",
        fields=list(ORGANIZATION_FIELDS.keys()),
        order=30,
        show_on_create=True,
    ),
    tabs.form(
        key="document",
        label="Document & Notes",
        fields=list(DOCUMENT_FIELDS.keys()),
        order=40,
        show_on_create=True,
    ),
    # Kotak tanda tangan. Komponennya sama dengan yang dipakai Travel
    # Request — bentuk data `workflow` di kedua serializer memang
    # sengaja disamakan.
    tabs.custom(
        key="approval",
        label="Approval",
        component="WorkflowApprovalTrail",
        requires_record=True,
        order=50,
    ),
]


LEAVE_UI = {
    **ui.workspace(
        title="Leave",
        description=(
            "Catat cuti dan izin pegawai beserta pemakaian saldonya."
        ),
        size="full",
        columns=2,
        create=True,
        edit=True,
        delete=True,
        bulk_delete=True,
        export=True,
    ),
}


LEAVE_SCHEMA = {
    "module": "hr/leave",
    "name": "Leave",
    "label": "Leave",
    "endpoint": "/api/hr/leaves/",
    "schema_type": "crud",

    "ui": LEAVE_UI,
    "tabs": LEAVE_TABS,
    "actions": LEAVE_ACTIONS,
    "fields": {
        **LEAVE_FIELDS,
        **LEAVE_DISPLAY_FIELDS,
    },
}
