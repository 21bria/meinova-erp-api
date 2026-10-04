from apps.framework.builders import field


PAYROLL_FIELDS = {
    "payroll_group": field.lookup(
        tab="payroll",
        label="Payroll Group",
        lookup_endpoint="/api/payroll/payroll-groups/lookup/",
        required=True,
        table=False,
        filter=True,
        order=10,
    ),

    "salary_grade": field.lookup(
        tab="payroll",
        label="Salary Grade",
        lookup_endpoint="/api/payroll/salary-grades/lookup/",
        table=False,
        filter=True,
        order=20,
    ),

    "salary_level": field.lookup(
        tab="payroll",
        label="Salary Level",
        lookup_endpoint="/api/payroll/salary-levels/lookup/",
        depends_on="salary_grade",
        lookup_params={
            "salary_grade_id": "$salary_grade",
        },
        table=False,
        order=30,
    ),

    "currency": field.lookup(
        tab="payroll",
        label="Currency",
        lookup_endpoint="/api/administration/currency/lookup/currencies/",
        required=True,
        table=False,
        order=40,
    ),

    "payment_method": field.select(
        tab="payroll",
        label="Payment Method",
        options=[
            {
                "label": "Bank Transfer",
                "value": "bank_transfer",
            },
            {
                "label": "Cash",
                "value": "cash",
            },
            {
                "label": "Cheque",
                "value": "cheque",
            },
        ],
        default="bank_transfer",
        table=False,
        order=50,
    ),

    "tax_status": field.lookup(
        tab="payroll",
        label="Tax Status",
        lookup_endpoint="/api/payroll/tax-statuses/lookup/",
        table=False,
        filter=True,
        order=60,
    ),

    "tax_number_payroll": field.text(
        tab="payroll",
        label="Tax Number",
        permission="payroll.view_employee_payroll",
        table=False,
        order=70,
    ),

    "bpjs_kesehatan_number": field.text(
        tab="payroll",
        label="BPJS Kesehatan Number",
        permission="payroll.view_employee_payroll",
        table=False,
        filter=False,
        order=80,
    ),

    "bpjs_ketenagakerjaan_number": field.text(
        tab="payroll",
        label="BPJS Ketenagakerjaan Number",
        permission="payroll.view_employee_payroll",
        table=False,
        order=90,
    ),

    "overtime_eligible": field.boolean(
        tab="payroll",
        label="Overtime Eligible",
        default=False,
        table=False,
        order=100,
    ),

    "overtime_group": field.lookup(
        tab="payroll",
        label="Overtime Group",
        lookup_endpoint="/api/payroll/overtime-groups/lookup/",
        table=False,
        order=110,
    ),

    # Kebijakan perhitungan pegawai ini. Dikosongkan = ikut Payroll
    # Setting perusahaannya, dan itu keadaan yang paling lazim.
    #
    # Ditaruh di tab payroll pegawai — yaitu di `PayrollAssignment` —
    # karena hanya baris itu yang punya rentang berlaku: assignment
    # yang berlaku 1 Juli membawa kebijakan barunya untuk payroll Juli,
    # sementara payroll Juni tetap memakai kebijakan lama.
    "payroll_policy": field.lookup(
        tab="payroll",
        label="Payroll Policy",
        lookup_endpoint="/api/payroll/payroll-policies/lookup/",
        table=False,
        filter=True,
        order=115,
        help_text=(
            "Dikosongkan = ikut Payroll Setting perusahaan. Dipakai "
            "kalau kelompok pegawai ini dihitung berbeda dari default "
            "perusahaannya."
        ),
    ),

    "effective_from": field.date(
        tab="payroll",
        label="Effective From",
        required=True,
        table=False,
        order=120,
    ),

    "effective_to": field.date(
        tab="payroll",
        label="Effective To",
        table=False,
        order=125,
    ),

    "basic_salary": field.currency(
        tab="payroll",
        label="Basic Salary",
        min=0,
        permission="payroll.view_salary",
        table=False,
        order=130,
    ),

    "daily_rate": field.currency(
        tab="payroll",
        label="Daily Rate",
        min=0,
        permission="payroll.view_salary",
        table=False,
        order=135,
        help_text=(
            "Upah sehari. Hanya dipakai kalau Payroll Policy pegawai "
            "ini berdasar Harian dan tarifnya memang diambil dari "
            "sini."
        ),
    ),

    "allowance_template": field.lookup(
        tab="payroll",
        label="Allowance Template",
        lookup_endpoint="/api/payroll/allowance-templates/lookup/",
        table=False,
        order=140,
    ),

    "deduction_template": field.lookup(
        tab="payroll",
        label="Deduction Template",
        lookup_endpoint="/api/payroll/deduction-templates/lookup/",
        table=False,
        order=150,
    ),

    "payroll_notes": field.textarea(
        tab="payroll",
        label="Payroll Notes",
        rows=4,
        layout="full",
        permission="payroll.view_employee_payroll",
        table=False,
        order=160,
    ),
}