from apps.framework.builders import tabs

from .fields import (
    APPROVAL_FIELDS,
    GENERAL_FIELDS,
    LOCATION_FIELDS,
    SYSTEM_FIELDS,
    TIME_FIELDS,
)


ATTENDANCE_TABS = [
    tabs.form(
        key="general",
        label="General",
        fields=list(
            GENERAL_FIELDS.keys(),
        ),
        order=10,
        show_on_create=True,
    ),

    tabs.form(
        key="time",
        label="Time & Duration",
        fields=list(
            TIME_FIELDS.keys(),
        ),
        order=20,
        show_on_create=True,
    ),

    tabs.form(
        key="location",
        label="Location",
        fields=list(
            LOCATION_FIELDS.keys(),
        ),
        order=30,
        show_on_create=True,
    ),

    tabs.form(
        key="approval",
        label="Approval",
        fields=list(
            APPROVAL_FIELDS.keys(),
        ),
        order=40,
        show_on_create=True,
    ),

    tabs.form(
        key="system",
        label="System",
        fields=list(
            SYSTEM_FIELDS.keys(),
        ),
        order=50,
        show_on_create=True,
    ),
]