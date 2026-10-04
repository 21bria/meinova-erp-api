"""
Schema UI Payroll Policy.

**Tanpa `visible_when`.** Aturan kondisional yang ada di framework ini
ditulis `{field: value}` di 193 tempat sementara `MFormBuilder`
membacanya sebagai `{field, op, value}` — jadi ia tidak pernah menyala,
dan memperbaikinya berarti menyentuh seluruh 193 aturan itu sekaligus.
Layar ini karena itu menampilkan **semua** kolom dan menyerahkan
pemisahannya pada label dan hint: kolom aturan bulanan diberi awalan
"Bulanan -", kolom aturan harian "Harian -", dan `clean()` menolak
kombinasi yang mustahil di layar tempat ia ditulis.

Bentuk itu lebih jujur daripada kolom yang menghilang: orang yang
mengisi kolom harian pada kebijakan bulanan mendapat penolakan yang
menyebutkan alasannya, bukan kolom yang diam-diam tidak pernah dibaca.
"""

from apps.framework.builders import field, ui
from apps.payroll.models import (
    PayrollDailyRateMethod,
    PayrollPayBasis,
    PayrollPolicyToggle,
    PayrollProrationMethod,
)


# Kalimat, bukan nilai enumnya. Yang membacanya orang HR yang sedang
# memutuskan, bukan yang menulis kodenya.
PAY_BASIS_OPTIONS = [
    {
        "label": "Monthly - a monthly salary split into daily entitlement",
        "value": PayrollPayBasis.MONTHLY,
    },
    {
        "label": "Daily - wage built from the days paid",
        "value": PayrollPayBasis.DAILY,
    },
]

TOGGLE_OPTIONS = [
    {"label": label, "value": value}
    for value, label in PayrollPolicyToggle.choices
]

METHOD_OPTIONS = [
    {"label": label, "value": value}
    for value, label in PayrollProrationMethod.choices
]

METHOD_PLACEHOLDER = "Follow the company policy"

DAILY_RATE_OPTIONS = [
    {
        "label": "Daily rate recorded on the Payroll Assignment",
        "value": PayrollDailyRateMethod.ASSIGNMENT_RATE,
    },
    {
        "label": "Monthly salary divided by the divisor below",
        "value": PayrollDailyRateMethod.FROM_MONTHLY,
    },
]

PAID_LEAVE_OPTIONS = [
    {"label": "Dibayar - hari cuti tetap menghasilkan upah sehari", "value": "yes"},
    {"label": "Tidak dibayar - hanya hari kerja nyata yang dibayar", "value": "no"},
]


PAYROLL_POLICY_SCHEMA = {
    "module": "payroll/payroll-policies",
    "name": "PayrollPolicy",
    "label": "Payroll Policy",
    "endpoint": "/api/payroll/payroll-policies/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Payroll Policies",
            description=(
                "Aturan perhitungan untuk sekelompok pegawai di dalam "
                "satu perusahaan. Yang dikosongkan mengikuti Payroll "
                "Setting perusahaan. Pegawai memilih kebijakannya di "
                "Payroll Assignment."
            ),
            size="lg",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            export=True,
        ),
    },

    "fields": {
        "code": field.text(
            label="Code",
            placeholder="e.g. HO-MONTHLY",
            required=True,
            table=True,
            search=True,
            sortable=True,
            order=10,
        ),
        "name": field.text(
            label="Name",
            required=True,
            table=True,
            search=True,
            sortable=True,
            order=20,
        ),
        "company": field.lookup(
            label="Company",
            lookup_endpoint="/api/administration/organization/lookup/companies/",
            display_key="company_name",
            required=True,
            table=True,
            filter=True,
            order=30,
            help_text=(
                "Kebijakan hanya boleh dipakai pegawai perusahaan ini."
            ),
        ),
        "pay_basis": field.select(
            label="Pay Basis",
            options=PAY_BASIS_OPTIONS,
            default=PayrollPayBasis.MONTHLY,
            required=True,
            table=True,
            display_key="pay_basis_label",
            filter=True,
            order=40,
            help_text=(
                "Menentukan kolom mana di bawah yang berlaku. Aturan "
                "bulanan tidak berlaku untuk dasar harian dan "
                "sebaliknya — yang salah tempat ditolak saat disimpan."
            ),
        ),

        # --- aturan bulanan -----------------------------------------
        "proration_method": field.select(
            label="Monthly - Salary Proration Method",
            options=METHOD_OPTIONS,
            placeholder=METHOD_PLACEHOLDER,
            default="",
            table=True,
            display_key="proration_method_label",
            order=50,
            help_text=(
                "Cara gaji sebulan dipecah untuk pegawai yang masuk "
                "atau berhenti di tengah periode. Dikosongkan = ikut "
                "Payroll Setting perusahaan."
            ),
        ),
        "prorate_on_join": field.select(
            label="Monthly - Prorate on Join",
            options=TOGGLE_OPTIONS,
            default=PayrollPolicyToggle.INHERIT,
            table=False,
            order=52,
        ),
        "prorate_on_termination": field.select(
            label="Monthly - Prorate on Termination",
            options=TOGGLE_OPTIONS,
            default=PayrollPolicyToggle.INHERIT,
            table=False,
            order=54,
        ),
        "attendance_deduction_method": field.select(
            label="Monthly - Absence Deduction Method",
            options=METHOD_OPTIONS,
            placeholder=METHOD_PLACEHOLDER,
            default="",
            table=True,
            display_key="attendance_deduction_method_label",
            order=56,
            help_text=(
                "Pembagi nilai sehari untuk potongan alpa dan cuti "
                "tidak dibayar. Boleh berbeda dari metode prorata di "
                "atas."
            ),
        ),
        "deduct_absence": field.select(
            label="Monthly - Deduct Absence",
            options=TOGGLE_OPTIONS,
            default=PayrollPolicyToggle.INHERIT,
            table=False,
            order=58,
        ),
        "deduct_unpaid_leave": field.select(
            label="Monthly - Deduct Unpaid Leave",
            options=TOGGLE_OPTIONS,
            default=PayrollPolicyToggle.INHERIT,
            table=False,
            order=60,
        ),

        # --- aturan harian ------------------------------------------
        "daily_rate_method": field.select(
            label="Daily - Daily Rate Method",
            options=DAILY_RATE_OPTIONS,
            placeholder="Not set - required for the Daily basis",
            default="",
            table=True,
            display_key="daily_rate_method_label",
            order=70,
            help_text=(
                "Sistem tidak memilihkan: kedua caranya lazim dan "
                "menghasilkan upah yang berbeda."
            ),
        ),
        "daily_rate_divisor": field.decimal(
            label="Daily - Monthly Salary Divisor",
            min=0,
            decimal_places=2,
            table=False,
            order=72,
            help_text=(
                "Mis. 25 atau 30. Hanya dipakai kalau upah sehari "
                "diturunkan dari gaji sebulan."
            ),
        ),
        "pay_paid_leave": field.select(
            label="Daily - Approved Leave Days",
            options=PAID_LEAVE_OPTIONS,
            placeholder="Not set - required for the Daily basis",
            default="",
            table=True,
            display_key="pay_paid_leave_label",
            layout="full",
            order=74,
            help_text=(
                "Belum ada aturan baku di sistem ini untuk pekerja "
                "harian pada hari cuti. Payroll Leave Rule menjawab "
                "pertanyaan yang berbeda — jenis cuti mana yang "
                "memotong gaji bulanan."
            ),
        ),

        "description": field.textarea(
            label="Description",
            rows=3,
            layout="full",
            table=False,
            order=90,
        ),

        # Isi kebijakan sebagai kalimat, dibaca dari daftarnya tanpa
        # membuka form dan membandingkan tujuh kolom satu per satu.
        "rules_summary": field.textarea(
            label="Ringkasan Aturan",
            read_only=True,
            display=True,
            table=False,
            layout="full",
            rows=7,
            order=95,
        ),

        "is_active": field.boolean(
            label="Active",
            default=True,
            table=True,
            filter=True,
            order=999,
        ),
    },
}
