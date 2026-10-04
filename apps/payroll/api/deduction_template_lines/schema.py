"""
Schema UI komponen potongan.

Di sinilah BPJS dan PPh21 dikonfigurasi kalau tenant memakainya. Basis
`pph21_progressive` sengaja tidak memakai Amount maupun Rate: angkanya
datang dari `TaxStatus.non_taxable_income` dan tabel Tax Bracket, dan
menyediakan kolom yang tidak dibaca siapa pun adalah cara membuat orang
mengisinya lalu bertanya kenapa tidak berpengaruh.
"""

from apps.framework.builders import field, ui


DEDUCTION_BASIS_OPTIONS = [
    {"label": "Fixed Amount", "value": "fixed"},
    {"label": "% of Basic Salary", "value": "percent_of_basic"},
    {"label": "% of Gross Earning", "value": "percent_of_gross"},
    {"label": "% of Taxable Earning", "value": "percent_of_taxable"},
    {"label": "Amount x Working Day", "value": "per_working_day"},
    {"label": "Amount x Paid Day", "value": "per_paid_day"},
    {"label": "Amount x Absent Day", "value": "per_absent_day"},
    {"label": "Amount x Unpaid Leave Day", "value": "per_unpaid_leave_day"},
    {"label": "PPh21 Progressive", "value": "pph21_progressive"},
]

PERCENT_BASES = [
    "percent_of_basic",
    "percent_of_gross",
    "percent_of_taxable",
]

AMOUNT_BASES = [
    "fixed",
    "per_working_day",
    "per_paid_day",
    "per_absent_day",
    "per_unpaid_leave_day",
]


DEDUCTION_TEMPLATE_LINE_SCHEMA = {
    "module": "payroll/deduction-template-lines",
    "name": "DeductionTemplateLine",
    "label": "Deduction Component",
    "endpoint": "/api/payroll/deduction-template-lines/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Deduction Components",
            description=(
                "Komponen di dalam Deduction Template, termasuk BPJS "
                "dan PPh21."
            ),
            size="xl",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            export=True,
        ),
    },

    "fields": {
        "template": field.lookup(
            label="Deduction Template",
            lookup_endpoint="/api/payroll/deduction-templates/lookup/",
            display_key="template_name",
            required=True,
            table=True,
            filter=True,
            search=True,
            sortable=True,
            order=10,
        ),
        "code": field.text(
            label="Component Code",
            placeholder="e.g. BPJS-KES",
            required=True,
            table=True,
            search=True,
            sortable=True,
            order=20,
        ),
        "name": field.text(
            label="Component Name",
            placeholder="e.g. BPJS Kesehatan (Pegawai)",
            required=True,
            table=True,
            search=True,
            sortable=True,
            order=30,
        ),
        "sequence": field.integer(
            label="Sequence",
            default=1,
            table=True,
            sortable=True,
            order=40,
        ),
        "basis": field.select(
            label="Calculation Basis",
            options=DEDUCTION_BASIS_OPTIONS,
            default="fixed",
            required=True,
            table=True,
            filter=True,
            order=50,
        ),
        "amount": field.currency(
            label="Amount",
            min=0,
            table=True,
            sortable=True,
            visible_when={"basis": AMOUNT_BASES},
            order=60,
        ),
        "rate": field.decimal(
            label="Rate (%)",
            min=0,
            decimal_places=4,
            visible_when={"basis": PERCENT_BASES},
            table=False,
            order=70,
        ),
        "minimum_base": field.currency(
            label="Minimum Base",
            min=0,
            table=False,
            visible_when={"basis": PERCENT_BASES},
            help_text="Batas bawah dasar perhitungan persentase.",
            order=80,
        ),
        "maximum_base": field.currency(
            label="Maximum Base",
            min=0,
            table=False,
            visible_when={"basis": PERCENT_BASES},
            help_text=(
                "Plafon dasar perhitungan — bentuk batas atas BPJS."
            ),
            order=90,
        ),
        "minimum_amount": field.currency(
            label="Minimum Amount", min=0, table=False, order=100,
        ),
        "maximum_amount": field.currency(
            label="Maximum Amount", min=0, table=False, order=110,
        ),
        "reduces_taxable": field.boolean(
            label="Reduces Taxable Income",
            default=False,
            table=True,
            filter=True,
            help_text=(
                "Iuran yang mengurangi dasar perhitungan PPh21."
            ),
            order=120,
        ),
        "is_employer_cost": field.boolean(
            label="Employer Cost",
            default=False,
            table=True,
            filter=True,
            help_text=(
                "Iuran yang dibayar perusahaan. Tidak dipotong dari "
                "pegawai dan tidak mengubah Take Home Pay; masuk "
                "biaya tenaga kerja."
            ),
            order=125,
        ),
        "is_prorated": field.boolean(
            label="Prorated",
            default=False,
            table=False,
            order=130,
        ),
        "description": field.textarea(
            label="Description", rows=3, layout="full", table=False, order=140,
        ),
        "is_active": field.boolean(
            label="Active", default=True, table=True, filter=True, order=999,
        ),
    },
}
