"""
Schema UI master Kelas Risiko BPJS.

**Tanpa satu angka pun**, sama seperti BPJS Program. Tarif per kelas
tinggal di BPJS Rules yang bertanggal berlaku; menaruhnya di sini
berarti perubahan tarif menulis ulang arti masa lalu.
"""

from apps.framework.builders import field, ui


BPJS_RISK_CLASS_SCHEMA = {
    "module": "payroll/bpjs-risk-classes",
    "name": "BpjsRiskClass",
    "label": "BPJS Risk Class",
    "endpoint": "/api/payroll/bpjs-risk-classes/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="BPJS Risk Classes",
            description=(
                "Kelas risiko kerja untuk program yang tarifnya "
                "ditentukan risiko. Tarifnya dikonfigurasi di BPJS "
                "Rules per kelas."
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
        "description": field.textarea(
            label="Description", rows=3, layout="full", table=False, order=40,
        ),
        "is_active": field.boolean(
            label="Active", default=True, table=True, filter=True, order=999,
        ),
    },
}
