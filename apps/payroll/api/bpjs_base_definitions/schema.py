"""
Schema UI komposisi dasar iuran BPJS.

Layarnya menyebut versinya, dan itu bukan hiasan: komposisi yang sudah
dipakai aturan **tidak bisa disunting**. Perubahan menerbitkan versi
baru, dan aturan lama tetap menunjuk versi lamanya — kalau tidak,
payroll bulan lalu yang dihitung ulang memakai dasar yang berbeda tanpa
satu baris aturan pun berubah.
"""

from apps.framework.builders import field, ui


BPJS_BASE_DEFINITION_SCHEMA = {
    "module": "payroll/bpjs-base-definitions",
    "name": "BpjsBaseDefinition",
    "label": "BPJS Base Definition",
    "endpoint": "/api/payroll/bpjs-base-definitions/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="BPJS Base Definitions",
            description=(
                "Komposisi dasar iuran: gaji pokok ditambah komponen "
                "tunjangan yang disebut satu per satu. Yang sudah "
                "dipakai aturan tidak bisa diubah — terbitkan versi "
                "baru."
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
            required=True,
            table=True,
            search=True,
            sortable=True,
            order=10,
        ),
        "version": field.integer(
            label="Version",
            default=1,
            required=True,
            table=True,
            sortable=True,
            order=20,
            help_text=(
                "Naikkan versinya untuk mengubah komposisi. Versi lama "
                "tetap dipakai aturan yang sudah menunjuknya."
            ),
        ),
        "name": field.text(
            label="Name", required=True, table=True, search=True, order=30,
        ),
        "include_basic": field.boolean(
            label="Include Basic Salary",
            default=True,
            table=True,
            filter=True,
            order=40,
            help_text=(
                "Gaji pokok sebulan menurut kontrak, bukan yang sudah "
                "diprorata."
            ),
        ),
        "daily_basic_method": field.select(
            label="Daily Employee Base",
            options=[
                {"value": "none", "label": "Not configured"},
                {"value": "daily_rate_x_factor", "label": "Daily Wage x Multiplier"},
                {
                    "value": "paid_days_x_daily_rate",
                    "label": "Paid Days x Daily Wage",
                },
            ],
            default="none",
            table=True,
            filter=True,
            order=45,
            help_text=(
                "Cara membentuk dasar iuran pegawai berbasis harian. "
                "Tidak diatur = dasarnya nol dan terbit peringatan."
            ),
        ),
        "daily_basic_factor": field.decimal(
            label="Daily Factor",
            required=False,
            table=True,
            order=46,
            visible_when={"daily_basic_method": "daily_rate_x_factor"},
            help_text=(
                "Pengali upah sehari jadi dasar sebulan. Tidak ada "
                "bawaan: angkanya kebijakan yang harus ditulis."
            ),
        ),
        "component_summary": field.text(
            label="Composition",
            read_only=True,
            table=True,
            form=False,
            order=50,
        ),
        "is_referenced": field.boolean(
            label="Locked",
            read_only=True,
            table=True,
            form=False,
            order=60,
            help_text="Sudah dipakai aturan BPJS, jadi isinya terkunci.",
        ),
        "description": field.textarea(
            label="Description", rows=3, layout="full", table=False, order=70,
        ),
        "is_active": field.boolean(
            label="Active", default=True, table=True, filter=True, order=999,
        ),
    },
}
