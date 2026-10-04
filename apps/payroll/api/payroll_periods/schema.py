"""
Schema UI Payroll Period.

Status **tidak** bisa disunting: ia dirangkum dari run-run di dalamnya
oleh `PayrollPeriodService.sync_status`. Menyediakan dropdown-nya di
form berarti menawarkan tombol yang hasilnya akan ditimpa proses
berikutnya.
"""

from apps.framework.builders import action, field, tabs, ui


PAYROLL_PERIOD_STATUS_OPTIONS = [
    {"label": "Draft", "value": "draft"},
    {"label": "Processing", "value": "processing"},
    {"label": "Review", "value": "review"},
    {"label": "Approved", "value": "approved"},
    {"label": "Finalized / Locked", "value": "finalized"},
]


GENERAL_FIELDS = {
    "code": field.text(
        tab="general",
        label="Period Code",
        placeholder="e.g. 2026-09",
        required=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        order=10,
    ),
    "name": field.text(
        tab="general",
        label="Period Name",
        placeholder="e.g. September 2026",
        required=True,
        table=True,
        search=True,
        sortable=True,
        overview=True,
        order=20,
    ),
    "company": field.lookup(
        tab="general",
        label="Company",
        lookup_endpoint=(
            "/api/administration/organization/lookup/companies/"
        ),
        display_key="company_name",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        order=30,
    ),
    "payroll_group": field.lookup(
        tab="general",
        label="Payroll Group",
        lookup_endpoint="/api/payroll/payroll-groups/lookup/",
        display_key="payroll_group_name",
        required=True,
        table=True,
        filter=True,
        overview=True,
        order=40,
    ),
    "start_date": field.date(
        tab="general",
        label="Start Date",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        order=50,
    ),
    "end_date": field.date(
        tab="general",
        label="End Date",
        required=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        order=60,
    ),
    "cutoff_date": field.date(
        tab="general",
        label="Cutoff Date",
        table=False,
        help_text=(
            "Batas terakhir absensi, lembur, dan input diambil. "
            "Kosong = sama dengan End Date."
        ),
        order=70,
    ),
    "payment_date": field.date(
        tab="general",
        label="Payment Date",
        table=True,
        sortable=True,
        order=80,
    ),
    "working_days": field.integer(
        tab="general",
        label="Working Days (Divisor)",
        min=1,
        table=False,
        help_text=(
            "Pembagi prorata dan potongan harian. Kosong = jumlah hari "
            "kalender periode."
        ),
        order=90,
    ),
    "status": field.select(
        tab="general",
        label="Status",
        options=PAYROLL_PERIOD_STATUS_OPTIONS,
        default="draft",
        disabled=True,
        table=True,
        filter=True,
        sortable=True,
        overview=True,
        help_text=(
            "Dirangkum otomatis dari payroll run di dalam periode ini."
        ),
        order=100,
    ),
    "notes": field.textarea(
        tab="general",
        label="Notes",
        rows=3,
        layout="full",
        table=False,
        order=110,
    ),
}


DISPLAY_FIELDS = {
    "run_count": field.integer(
        label="Runs",
        table=True,
        sortable=False,
        read_only=True,
        order=120,
    ),
    "is_locked": field.boolean(
        label="Locked",
        table=False,
        read_only=True,
        order=130,
    ),
}


RUN_GRID_FIELDS = {
    "document_number": field.text(label="Run No.", table=True, order=10),
    "run_type": field.text(label="Type", table=True, order=20),
    "status": field.text(label="Status", table=True, order=30),
    "employee_count": field.integer(label="Employees", table=True, order=40),
    "total_net": field.currency(label="Net Pay", table=True, order=50),
}


PAYROLL_PERIOD_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(GENERAL_FIELDS.keys()),
        order=10,
        show_on_create=True,
    ),
    tabs.resource(
        key="runs",
        label="Payroll Runs",
        endpoint="/api/payroll/payroll-runs/",
        module="payroll/payroll-runs",
        foreign_key="period",
        fields=RUN_GRID_FIELDS,
        inline=False,
        create=False,
        requires_record=True,
        order=20,
    ),
]


PAYROLL_PERIOD_ACTIONS = [
    action.save(),
    action.save_and_close(),
    action.delete(),
    action.export(),
]


PAYROLL_PERIOD_SCHEMA = {
    "module": "payroll/payroll-periods",
    "name": "PayrollPeriod",
    "label": "Payroll Period",
    "endpoint": "/api/payroll/payroll-periods/",
    "schema_type": "crud",

    "ui": {
        **ui.workspace(
            title="Payroll Period",
            description=(
                "Rentang penggajian per company dan payroll group. "
                "Status-nya mengikuti payroll run di dalamnya."
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

    "tabs": PAYROLL_PERIOD_TABS,
    "actions": PAYROLL_PERIOD_ACTIONS,
    "fields": {**GENERAL_FIELDS, **DISPLAY_FIELDS},
}
