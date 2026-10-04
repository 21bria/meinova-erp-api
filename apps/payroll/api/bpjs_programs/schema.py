"""
Schema UI master Program BPJS.

Layar ini **tidak memuat satu angka pun**. Tarif dan plafon tinggal di
BPJS Rules yang bertanggal berlaku; menaruhnya di sini berarti mengubah
tarif menulis ulang arti masa lalu.
"""

from apps.framework.builders import field, ui


BPJS_PROGRAM_SCHEMA = {
    "module": "payroll/bpjs-programs",
    "name": "BpjsProgram",
    "label": "BPJS Program",
    "endpoint": "/api/payroll/bpjs-programs/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="BPJS Programs",
            description=(
                "Identitas program BPJS. Tarif dan plafonnya "
                "dikonfigurasi di BPJS Rules, terpisah supaya bisa "
                "bertanggal berlaku."
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
            help_text="Mis. JKN, JHT, JP, JKK, JKM.",
        ),
        "name": field.text(
            label="Name",
            required=True,
            table=True,
            search=True,
            sortable=True,
            order=20,
        ),
        "sequence": field.integer(
            label="Order", default=1, table=True, sortable=True, order=30,
        ),
        "uses_risk_class": field.boolean(
            label="Uses Risk Class",
            default=False,
            table=True,
            filter=True,
            order=35,
            help_text=(
                "Tarif program ini ditentukan kelas risiko kerja. "
                "Kepesertaan dan aturannya wajib menyebut kelasnya."
            ),
        ),
        "description": field.textarea(
            label="Description", rows=3, layout="full", table=False, order=40,
        ),
        "is_active": field.boolean(
            label="Active", default=True, table=True, filter=True, order=999,
        ),
    },
}
