from apps.framework.builders import ui


EMPLOYEE_UI = ui.workspace(
    size="full",
    columns=3,
    default_tab="general",
    stay_after_create=True,
    switch_to_edit_after_create=True,
)