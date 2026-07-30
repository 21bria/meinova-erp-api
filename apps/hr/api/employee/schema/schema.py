from apps.framework.builders import (
    action,
    permission,
    ui,
    workflow,
)

from .fields import (
    EMPLOYMENT_FIELDS,
    GENERAL_FIELDS,
    ORGANIZATION_FIELDS,
    PAYROLL_FIELDS,
)
from .tabs import EMPLOYEE_TABS


EMPLOYEE_SCHEMA = {
    "endpoint": "/api/hr/employees/",

    "ui": ui.workspace(
        size="full",
        columns=2,
        show_activity=True,
        show_history=True,
    ),

    "tabs": EMPLOYEE_TABS,

    "actions": [
        action.save(),
        action.save_and_new(),
        action.save_and_close(),
        action.delete(),
        action.export(),
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
        **PAYROLL_FIELDS,
    },
}