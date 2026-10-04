from apps.framework.builders import (
    action,
    permission,
    ui,
    workflow,
)

from apps.hr.api.employee_action.schema import EMPLOYEE_ACTION_FIELDS

from .fields import (
    EMPLOYMENT_FIELDS,
    GENERAL_FIELDS,
    ORGANIZATION_FIELDS,
)
from .importer import EMPLOYEE_IMPORT_SCHEMA
from .tabs import EMPLOYEE_TABS


EMPLOYEE_SCHEMA = {
    "endpoint": "/api/hr/employees/",

    "ui": {
        **ui.workspace(
            size="full",
            columns=2,
            default_tab="general",
            show_activity=True,
            show_history=True,
        ),

        # `import` adalah keyword Python, jadi tidak bisa dioper
        # sebagai kwarg ke ui.workspace().
        "import": True,
        "export": True,
        "bulk_delete": True,
    },

    "tabs": EMPLOYEE_TABS,

    "import": EMPLOYEE_IMPORT_SCHEMA,

    "actions": [
        action.save(),
        action.save_and_new(),
        action.save_and_close(),
        action.delete(),
        action.export(),

        # Pintu masuk perubahan kepegawaian dari kartu pegawai.
        #
        # Form yang dibuka **sama persis** dengan form di modul
        # Employee Action — dict field yang sama, jadi daftar jenis
        # action, syarat tampil per jenis, dan kolom pembanding
        # "current" ikut tanpa disalin. Yang berbeda cuma satu:
        # `parent_field` mengisi pegawainya dari record yang sedang
        # dibuka dan mencabut kolomnya dari form. Dari menu global,
        # form yang sama tetap meminta pegawainya dipilih.
        #
        # Dokumennya terbit DRAFT; Submit dan persetujuannya di modul
        # Employee Action, tempat kotak masuk dan jejaknya berada.
        action.create_resource(
            "employee_action",
            endpoint="/api/hr/employee-actions/",
            label="Actions",
            icon="FilePlus2",
            parent_field="employee",
            fields=EMPLOYEE_ACTION_FIELDS,
            title="New Employee Action",
            permission="hr.add_employeeaction",
        ),
    ],

    "permission": permission.module(
        "hr.employee",
        view="hr.view_employee",
        add="hr.add_employee",
        change="hr.change_employee",
        delete="hr.delete_employee",
    ),

    "workflow": workflow.none(),

    "fields": {
        **GENERAL_FIELDS,
        **ORGANIZATION_FIELDS,
        **EMPLOYMENT_FIELDS,
    },
}