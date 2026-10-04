"""
Schema UI Payroll Input.

Komponen dipilih dari master lewat dua lookup yang saling meniadakan —
tunjangan atau potongan, tidak keduanya — dan yang tidak ada di master
diketik sendiri. Itu batas yang dijaga model: input menyimpan **nilai**,
definisinya tetap milik Payroll Master.
"""

from apps.framework.builders import field, ui


INPUT_TYPE_OPTIONS = [
    {"label": "Overtime", "value": "overtime"},
    {"label": "Variable Allowance", "value": "allowance"},
    {"label": "Incentive / Bonus", "value": "incentive"},
    {"label": "Deduction", "value": "deduction"},
    {"label": "Reimbursement", "value": "reimbursement"},
    {"label": "Correction / Adjustment", "value": "adjustment"},
    {"label": "Unpaid Leave", "value": "unpaid_leave"},
    {"label": "Attendance Adjustment", "value": "attendance"},
]

COMPONENT_TYPE_OPTIONS = [
    {"label": "Earning", "value": "earning"},
    {"label": "Deduction", "value": "deduction"},
]

INPUT_STATUS_OPTIONS = [
    {"label": "Draft", "value": "draft"},
    {"label": "Confirmed", "value": "confirmed"},
    {"label": "Cancelled", "value": "cancelled"},
]

EARNING_TYPES = [
    "overtime", "allowance", "incentive", "reimbursement", "adjustment",
]

DEDUCTION_TYPES = ["deduction", "unpaid_leave", "attendance", "adjustment"]


PAYROLL_INPUT_SCHEMA = {
    "module": "payroll/payroll-inputs",
    "name": "PayrollInput",
    "label": "Payroll Input",
    "endpoint": "/api/payroll/payroll-inputs/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Payroll Input / Adjustment",
            description=(
                "Nilai transaksi per periode dan pegawai. Hanya yang "
                "berstatus Confirmed yang ikut dihitung."
            ),
            size="xl",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=True,
            export=True,
        ),
    },

    "fields": {
        "period": field.lookup(
            label="Payroll Period",
            lookup_endpoint="/api/payroll/payroll-periods/lookup/",
            display_key="period_name",
            required=True,
            table=True,
            filter=True,
            search=True,
            order=10,
        ),
        "employee": field.lookup(
            label="Employee",
            lookup_endpoint="/api/hr/employees/lookup/",
            display_key="employee_name",
            required=True,
            table=True,
            filter=True,
            search=True,
            order=20,
        ),
        "input_type": field.select(
            label="Input Type",
            options=INPUT_TYPE_OPTIONS,
            default="allowance",
            required=True,
            table=True,
            filter=True,
            order=30,
        ),
        "component_type": field.select(
            label="Side",
            options=COMPONENT_TYPE_OPTIONS,
            table=True,
            filter=True,
            help_text=(
                "Kosong = mengikuti sisi bawaan jenis input. Diisi "
                "hanya untuk koreksi yang arahnya memang berbeda."
            ),
            order=40,
        ),
        "allowance_line": field.lookup(
            label="Allowance Component",
            lookup_endpoint="/api/payroll/allowance-template-lines/lookup/",
            display_key="allowance_line_name",
            # `code`, `name`, dan `is_taxable` memang diserialisasi
            # lookup-nya; kunci yang tidak ada di sana akan dilewati
            # form dan field tujuannya tinggal kosong.
            autofill={
                "code": "code",
                "name": "name",
                "is_taxable": "is_taxable",
            },
            table=False,
            filter=True,
            visible_when={"input_type": EARNING_TYPES},
            help_text=(
                "Ambil definisinya dari Payroll Master. Kosongkan untuk "
                "komponen sekali jalan."
            ),
            order=50,
        ),
        "deduction_line": field.lookup(
            label="Deduction Component",
            lookup_endpoint="/api/payroll/deduction-template-lines/lookup/",
            display_key="deduction_line_name",
            autofill={"code": "code", "name": "name"},
            table=False,
            filter=True,
            visible_when={"input_type": DEDUCTION_TYPES},
            order=60,
        ),
        "code": field.text(
            label="Code",
            placeholder="e.g. BONUS-Q3",
            table=True,
            search=True,
            order=70,
        ),
        "name": field.text(
            label="Name",
            placeholder="e.g. Bonus Kuartal 3",
            table=True,
            search=True,
            order=80,
        ),
        "quantity": field.decimal(
            label="Quantity",
            default=1,
            min=0,
            decimal_places=4,
            table=True,
            order=90,
        ),
        "rate": field.currency(
            label="Rate",
            min=0,
            table=False,
            help_text="Diisi = Amount dihitung Rate x Quantity.",
            order=100,
        ),
        "amount": field.currency(
            label="Amount",
            min=0,
            table=True,
            sortable=True,
            order=110,
        ),
        "is_taxable": field.boolean(
            label="Taxable",
            default=True,
            table=False,
            visible_when={"input_type": EARNING_TYPES},
            order=120,
        ),
        "status": field.select(
            label="Status",
            options=INPUT_STATUS_OPTIONS,
            default="draft",
            table=True,
            filter=True,
            help_text=(
                "Hanya Confirmed yang ikut dihitung payroll run."
            ),
            order=130,
        ),
        "reference": field.text(
            label="Reference",
            placeholder="Nomor dokumen sumber",
            table=False,
            order=140,
        ),
        "notes": field.textarea(
            label="Notes", rows=2, layout="full", table=False, order=150,
        ),
    },
}
