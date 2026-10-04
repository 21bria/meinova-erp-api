"""
Schema UI komponen pembentuk dasar iuran.

Layar tersendiri, bukan tab — pola yang sama dengan Allowance Component
terhadap Allowance Template, dan dengan Overtime Tier terhadap Overtime
Group.
"""

from apps.framework.builders import field, ui


BPJS_BASE_COMPONENT_SCHEMA = {
    "module": "payroll/bpjs-base-components",
    "name": "BpjsBaseComponent",
    "label": "BPJS Base Component",
    "endpoint": "/api/payroll/bpjs-base-components/",
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="BPJS Base Components",
            description=(
                "Komponen tunjangan yang ikut membentuk dasar iuran. "
                "Lembur dan input variabel tidak pernah bisa masuk."
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
        "definition": field.lookup(
            label="Base Definition",
            lookup_endpoint="/api/payroll/bpjs-base-definitions/lookup/",
            display_key="definition_label",
            required=True,
            table=True,
            filter=True,
            search=True,
            order=10,
        ),
        "allowance_code": field.text(
            label="Allowance Code",
            required=True,
            table=True,
            search=True,
            sortable=True,
            order=20,
            help_text=(
                "Kode komponen tunjangan, persis seperti tertulis di "
                "Allowance Component."
            ),
        ),
        "sequence": field.integer(
            label="Order", default=1, table=True, sortable=True, order=30,
        ),
        "is_active": field.boolean(
            label="Active", default=True, table=True, filter=True, order=999,
        ),
    },
}
