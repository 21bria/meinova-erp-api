"""
Schema UI Payroll Run.

Tombolnya mengikuti tahapan, bukan berjejer semuanya sekaligus:
Generate Employees hanya muncul selama run masih bisa diubah, Calculate
setelah ada pegawainya, Submit setelah dihitung, Finalize setelah
disetujui. Tombol yang selalu terlihat dan kadang menolak adalah cara
membuat orang belajar mengabaikan pesan error.
"""

from apps.framework.builders import action, field, tabs, ui


PAYROLL_RUN_STATUS_OPTIONS = [
    {"label": "Draft", "value": "draft"},
    {"label": "Processing", "value": "processing"},
    {"label": "Review", "value": "review"},
    {"label": "Pending Approval", "value": "submitted"},
    {"label": "Approved", "value": "approved"},
    {"label": "Finalized / Locked", "value": "finalized"},
    {"label": "Rejected", "value": "rejected"},
    {"label": "Cancelled", "value": "cancelled"},
]

PAYROLL_RUN_TYPE_OPTIONS = [
    {"label": "Regular", "value": "regular"},
    {"label": "Off Cycle", "value": "off_cycle"},
    {"label": "Correction", "value": "correction"},
]

# Status yang isinya masih boleh disunting. Dipakai `readonly_when`
# tab dan `visible_when` tombol.
EDITABLE_STATUSES = ["draft", "processing", "review", "rejected"]

LOCKED_WHEN = {"status": ["submitted", "approved", "finalized", "cancelled"]}


GENERAL_FIELDS = {
    "document_number": field.text(
        tab="general",
        label="Run No.",
        disabled=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        help_text=(
            "Terisi otomatis dari pola penomoran payroll/payroll_run. "
            "Kosong berarti pola itu belum diseed — jalankan "
            "seed_administration --only=numbering."
        ),
        order=10,
    ),
    "period": field.lookup(
        tab="general",
        label="Payroll Period",
        lookup_endpoint="/api/payroll/payroll-periods/lookup/",
        display_key="period_name",
        required=True,
        table=True,
        filter=True,
        search=True,
        overview=True,
        order=20,
    ),
    "name": field.text(
        tab="general",
        label="Run Name",
        table=True,
        search=True,
        order=30,
    ),
    "run_type": field.select(
        tab="general",
        label="Run Type",
        options=PAYROLL_RUN_TYPE_OPTIONS,
        default="regular",
        table=True,
        filter=True,
        overview=True,
        order=40,
    ),

    # Penyaring cakupan. Semuanya opsional — kosong berarti seluruh
    # company periode ini, dan itu keadaan yang paling lazim.
    "branch": field.lookup(
        tab="general",
        label="Branch",
        lookup_endpoint="/api/administration/organization/lookup/branches/",
        table=False,
        filter=True,
        help_text="Kosong = seluruh company.",
        order=50,
    ),
    "location": field.lookup(
        tab="general",
        label="Location / Site",
        lookup_endpoint="/api/administration/organization/lookup/locations/",
        display_key="location_name",
        table=True,
        filter=True,
        help_text="Kosong = seluruh company.",
        order=60,
    ),
    "department": field.lookup(
        tab="general",
        label="Department",
        lookup_endpoint=(
            "/api/administration/organization/lookup/departments/"
        ),
        display_key="department_name",
        table=False,
        filter=True,
        order=70,
    ),
    "section": field.lookup(
        tab="general",
        label="Section",
        lookup_endpoint="/api/administration/organization/lookup/sections/",
        depends_on="department",
        lookup_params={"department_id": "$department"},
        table=False,
        filter=True,
        order=80,
    ),

    "status": field.select(
        tab="general",
        label="Status",
        options=PAYROLL_RUN_STATUS_OPTIONS,
        default="draft",
        disabled=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        order=90,
    ),
    "notes": field.textarea(
        tab="general",
        label="Notes",
        rows=3,
        layout="full",
        table=False,
        order=100,
    ),
}


RESULT_FIELDS = {
    "employee_count": field.integer(
        tab="result",
        label="Employees",
        read_only=True,
        table=True,
        sortable=True,
        overview=True,
        order=10,
    ),
    "total_earning": field.currency(
        tab="result",
        label="Total Earning",
        read_only=True,
        table=True,
        sortable=True,
        overview=True,
        order=20,
    ),
    "total_deduction": field.currency(
        tab="result",
        label="Total Deduction",
        read_only=True,
        table=True,
        sortable=True,
        order=30,
    ),
    "total_tax": field.currency(
        tab="result",
        label="Total Tax",
        read_only=True,
        table=False,
        order=40,
    ),
    "total_net": field.currency(
        tab="result",
        label="Total Net Pay",
        read_only=True,
        table=True,
        sortable=True,
        overview=True,
        order=50,
    ),
    "calculated_at": field.datetime(
        tab="result",
        label="Calculated At",
        read_only=True,
        table=False,
        order=60,
    ),
    "finalized_at": field.datetime(
        tab="result",
        label="Finalized At",
        read_only=True,
        table=False,
        order=70,
    ),
    "warnings_acknowledged": field.boolean(
        tab="result",
        label="Warnings Acknowledged",
        read_only=True,
        table=False,
        order=80,
    ),
}


DISPLAY_FIELDS = {
    "error_count": field.integer(
        label="Errors", read_only=True, table=True, order=110,
    ),
    "warning_count": field.integer(
        label="Warnings", read_only=True, table=True, order=120,
    ),
    "validation_summary": field.json(
        label="Validation Summary", read_only=True, table=False, order=130,
    ),
    "approval": field.json(
        label="Approval", read_only=True, table=False, order=140,
    ),
}


EMPLOYEE_GRID_FIELDS = {
    "employee": field.lookup(
        label="Employee",
        display_key="employee_name",
        table=True,
        order=10,
    ),
    "department": field.lookup(
        label="Department", display_key="department_name", table=True, order=20,
    ),
    "basic_salary": field.currency(label="Basic", table=True, order=30),
    "gross_earning": field.currency(label="Gross", table=True, order=40),
    "total_deduction": field.currency(label="Deduction", table=True, order=50),
    "tax_amount": field.currency(label="Tax", table=True, order=60),
    "net_pay": field.currency(label="Net Pay", table=True, order=70),
    "status": field.text(label="Status", table=True, order=80),
    "is_excluded": field.boolean(label="Excluded", table=True, order=90),
}


PAYROLL_RUN_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
        readonly_when=LOCKED_WHEN,
    ),
    tabs.form(
        key="result",
        label="Result",
        fields=list(RESULT_FIELDS.keys()),
        order=20,
        requires_record=True,
    ),
    tabs.resource(
        key="employees",
        label="Employees",
        endpoint="/api/payroll/payroll-run-employees/",
        module="payroll/payroll-run-employees",
        foreign_key="run",
        fields=EMPLOYEE_GRID_FIELDS,
        inline=True,
        create=False,
        requires_record=True,
        order=30,
        readonly_when=LOCKED_WHEN,
    ),
]


PAYROLL_RUN_ACTIONS = [
    action.save(),
    action.save_and_close(),
    action.delete(),
    action.export(),

    action.custom(
        "generate_employees",
        label="Generate Employees",
        icon="UsersRound",
        variant="outline",
        placement="primary",
        modes=["edit"],
        endpoint="/api/payroll/payroll-runs/{id}/generate-employees/",
        method="post",
        refresh=True,
        visible_when={"status": EDITABLE_STATUSES},
        confirm={
            "title": "Generate daftar pegawai?",
            "description": (
                "Pegawai aktif yang memenuhi syarat pada periode ini "
                "ditarik ke run. Baris yang sudah ada tidak "
                "diduplikasi; yang tidak lagi memenuhi syarat ditandai "
                "Excluded, bukan dihapus."
            ),
        },
    ),

    action.custom(
        "calculate",
        label="Calculate",
        icon="Calculator",
        variant="default",
        placement="primary",
        modes=["edit"],
        endpoint="/api/payroll/payroll-runs/{id}/calculate/",
        method="post",
        refresh=True,
        visible_when={"status": EDITABLE_STATUSES},
        confirm={
            "title": "Hitung ulang payroll?",
            "description": (
                "Seluruh baris dihitung ulang dari master, absensi, "
                "cuti, lembur, dan payroll input yang sudah Confirmed. "
                "Rincian lama diganti."
            ),
        },
    ),

    action.custom(
        "acknowledge",
        label="Acknowledge Warnings",
        icon="ShieldCheck",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/payroll/payroll-runs/{id}/acknowledge/",
        method="post",
        refresh=True,
        visible_when={"status": ["review", "rejected"]},
        confirm={
            "title": "Akui seluruh peringatan?",
            "description": (
                "Peringatan tidak menghalangi Finalize, tapi harus "
                "diakui dulu supaya tercatat siapa yang membacanya."
            ),
        },
    ),

    action.custom(
        "submit",
        label="Submit for Approval",
        icon="Send",
        variant="default",
        placement="primary",
        modes=["edit"],
        endpoint="/api/payroll/payroll-runs/{id}/submit/",
        method="post",
        refresh=True,
        visible_when={"status": ["review", "rejected"]},
        confirm={
            "title": "Ajukan payroll run?",
            "description": (
                "Dokumen dikirim ke alur persetujuan dan tidak bisa "
                "disunting sampai keputusannya keluar."
            ),
        },
    ),

    action.custom(
        "withdraw",
        label="Withdraw",
        icon="Undo2",
        variant="outline",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/payroll/payroll-runs/{id}/withdraw/",
        method="post",
        refresh=True,
        visible_when={"status": ["submitted"]},
    ),

    action.custom(
        "finalize",
        label="Finalize & Issue Payslip",
        icon="Lock",
        variant="default",
        placement="primary",
        modes=["edit"],
        endpoint="/api/payroll/payroll-runs/{id}/finalize/",
        method="post",
        refresh=True,
        visible_when={"status": ["approved"]},
        confirm={
            "title": "Finalisasi payroll run?",
            "description": (
                "Angkanya dibekukan, run dikunci, dan slip gaji "
                "terbit. Setelah ini perubahan master tidak lagi "
                "mengubah payroll periode ini, dan koreksi harus lewat "
                "run bertipe Correction."
            ),
        },
    ),

    action.custom(
        "cancel_run",
        label="Cancel Run",
        icon="Ban",
        variant="destructive",
        placement="secondary",
        modes=["edit"],
        endpoint="/api/payroll/payroll-runs/{id}/cancel/",
        method="post",
        refresh=True,
        visible_when={
            "status": ["draft", "processing", "review", "rejected"],
        },
        fields=[
            {
                "key": "notes",
                "type": "textarea",
                "label": "Alasan Pembatalan",
                "required": False,
            },
        ],
    ),
]


PAYROLL_RUN_SCHEMA = {
    "module": "payroll/payroll-runs",
    "name": "PayrollRun",
    "label": "Payroll Run",
    "endpoint": "/api/payroll/payroll-runs/",
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Payroll Run",
            description=(
                "Pelaksanaan payroll satu periode: generate pegawai, "
                "hitung, review, ajukan, finalisasi, terbitkan slip."
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

    "tabs": PAYROLL_RUN_TABS,
    "actions": PAYROLL_RUN_ACTIONS,
    "fields": {**GENERAL_FIELDS, **RESULT_FIELDS, **DISPLAY_FIELDS},
}
