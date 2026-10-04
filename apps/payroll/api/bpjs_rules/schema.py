"""
Schema UI aturan BPJS.

Satu baris memuat **kedua sisi** — porsi pegawai dan porsi perusahaan.
Sebagai dua baris terpisah keduanya bisa berubah sendiri-sendiri tanpa
apa pun berbunyi; sebagai satu baris itu mustahil.

Kosongkan tarif satu sisi untuk program yang memang bersisi satu
(JKK/JKM lazimnya ditanggung perusahaan sepenuhnya). Sisi yang kosong
tidak menerbitkan baris apa pun — bukan baris bertarif nol, yang di
slip terbaca sebagai potongan yang tidak pernah ada.
"""

from apps.framework.builders import field, ui


BPJS_RULE_SCHEMA = {
    "module": "payroll/bpjs-rules",
    "name": "BpjsRule",
    "label": "BPJS Rule",
    "endpoint": "/api/payroll/bpjs-rules/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="BPJS Rules",
            description=(
                "Tarif satu program pada satu rentang tanggal. Untuk "
                "mengubah tarif, terbitkan aturan baru dan tutup yang "
                "lama — jangan disunting, supaya periode lama tetap "
                "bisa dihitung ulang dengan tarifnya sendiri."
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
        "program": field.lookup(
            label="Program",
            lookup_endpoint="/api/payroll/bpjs-programs/lookup/",
            display_key="program_name",
            required=True,
            table=True,
            filter=True,
            search=True,
            order=10,
        ),
        "risk_class": field.lookup(
            label="Risk Class",
            lookup_endpoint="/api/payroll/bpjs-risk-classes/lookup/",
            display_key="risk_class_name",
            required=False,
            table=True,
            filter=True,
            order=15,
            help_text=(
                "Wajib untuk program yang memakai kelas risiko, dan "
                "harus kosong untuk program yang tidak. Aturan kelas "
                "tidak pernah dipinjam kelas lain."
            ),
        ),
        "company": field.lookup(
            label="Company",
            lookup_endpoint="/api/administration/organization/lookup/companies/",
            display_key="company_name",
            required=False,
            table=False,
            filter=True,
            order=20,
            help_text=(
                "Kosongkan untuk aturan bawaan seluruh tenant. Diisi = "
                "aturan perusahaan itu, yang menggantikan bawaan "
                "secara utuh."
            ),
        ),
        "scope_label": field.text(
            label="Applies To",
            read_only=True,
            table=True,
            form=False,
            order=25,
        ),
        "effective_from": field.date(
            label="Effective From",
            required=True,
            table=True,
            sortable=True,
            filter=True,
            order=30,
        ),
        "effective_to": field.date(
            label="Effective To",
            table=True,
            sortable=True,
            order=40,
            help_text="Kosong = masih berlaku.",
        ),
        "base_definition": field.lookup(
            label="Contribution Base",
            lookup_endpoint="/api/payroll/bpjs-base-definitions/lookup/",
            display_key="base_definition_label",
            required=True,
            table=True,
            filter=True,
            order=50,
        ),
        "employee_rate": field.decimal(
            label="Employee Rate (%)",
            decimal_places=4,
            table=True,
            sortable=True,
            order=60,
            help_text="Kosongkan kalau program ini tidak dipotong dari pegawai.",
        ),
        "employer_rate": field.decimal(
            label="Employer Rate (%)",
            decimal_places=4,
            table=True,
            sortable=True,
            order=70,
            help_text="Kosongkan kalau program ini tidak ditanggung perusahaan.",
        ),
        "base_minimum": field.currency(
            label="Base Minimum", min=0, table=False, order=80,
        ),
        "base_maximum": field.currency(
            label="Base Maximum", min=0, table=False, order=90,
            help_text="Plafon BPJS: batas dasar perhitungan, bukan batas iurannya.",
        ),
        "employee_minimum_amount": field.currency(
            label="Employee Min Amount", min=0, table=False, order=100,
        ),
        "employee_maximum_amount": field.currency(
            label="Employee Max Amount", min=0, table=False, order=110,
        ),
        "employer_minimum_amount": field.currency(
            label="Employer Min Amount", min=0, table=False, order=120,
        ),
        "employer_maximum_amount": field.currency(
            label="Employer Max Amount", min=0, table=False, order=130,
        ),
        "reduces_taxable": field.boolean(
            label="Reduces Taxable Income",
            default=False,
            table=True,
            filter=True,
            order=140,
            help_text="Iuran pegawai ini mengurangi dasar perhitungan PPh21.",
        ),
        "description": field.textarea(
            label="Description", rows=3, layout="full", table=False, order=150,
        ),
        "is_active": field.boolean(
            label="Active", default=True, table=True, filter=True, order=999,
        ),
    },
}
