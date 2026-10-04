"""
Schema UI Payslip.

Seluruh kolomnya read-only dan tidak ada satu pun tombol tulis: slip
lahir dari Finalize, bukan diketik. Yang salah diperbaiki dengan
menerbitkan payroll run bertipe Correction — jalur yang meninggalkan
jejak.
"""

from apps.framework.builders import field, ui


PAYSLIP_STATUS_OPTIONS = [
    {"label": "Draft", "value": "draft"},
    {"label": "Published", "value": "published"},
]


PAYSLIP_SCHEMA = {
    "module": "payroll/payslips",
    "name": "Payslip",
    "label": "Payslip",
    "endpoint": "/api/payroll/payslips/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Payslips",
            description=(
                "Slip gaji hasil payroll run yang sudah difinalisasi."
            ),
            size="xl",
            columns=2,
            create=False,
            edit=False,
            delete=False,
            bulk_delete=False,
            export=True,
        ),
    },

    "fields": {
        "document_number": field.text(
            label="Payslip No.",
            read_only=True,
            table=True,
            search=True,
            sortable=True,
            overview=True,
            order=10,
        ),
        "period": field.lookup(
            label="Payroll Period",
            lookup_endpoint="/api/payroll/payroll-periods/lookup/",
            display_key="period_name",
            read_only=True,
            table=True,
            filter=True,
            overview=True,
            order=20,
        ),
        "employee": field.lookup(
            label="Employee",
            lookup_endpoint="/api/hr/employees/lookup/",
            display_key="employee_name",
            read_only=True,
            table=True,
            filter=True,
            search=True,
            overview=True,
            order=30,
        ),
        "company": field.lookup(
            label="Company",
            lookup_endpoint=(
                "/api/administration/organization/lookup/companies/"
            ),
            display_key="company_name",
            read_only=True,
            table=True,
            filter=True,
            order=40,
        ),
        "department": field.lookup(
            label="Department",
            lookup_endpoint=(
                "/api/administration/organization/lookup/departments/"
            ),
            display_key="department_name",
            read_only=True,
            table=True,
            filter=True,
            order=50,
        ),
        "issue_date": field.date(
            label="Issue Date",
            read_only=True,
            table=True,
            sortable=True,
            order=60,
        ),
        "basic_salary": field.currency(
            label="Basic Salary",
            read_only=True,
            table=True,
            permission="payroll.view_salary",
            order=70,
        ),
        "gross_earning": field.currency(
            label="Gross Earning",
            read_only=True,
            table=True,
            sortable=True,
            overview=True,
            order=80,
        ),
        "total_deduction": field.currency(
            label="Total Deduction",
            read_only=True,
            table=True,
            sortable=True,
            order=90,
        ),
        "tax_amount": field.currency(
            label="Tax",
            read_only=True,
            table=True,
            order=100,
        ),
        "net_pay": field.currency(
            label="Net Pay",
            read_only=True,
            table=True,
            sortable=True,
            overview=True,
            order=110,
        ),
        "status": field.select(
            label="Status",
            options=PAYSLIP_STATUS_OPTIONS,
            read_only=True,
            table=True,
            filter=True,
            order=120,
        ),
        "snapshot": field.json(
            label="Payslip Detail",
            read_only=True,
            table=False,
            layout="full",
            order=130,
        ),
    },
}
