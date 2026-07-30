# Run :
from apps.administration.models import DashboardWidget

WIDGETS = [
    {
        "code": "favorite_apps",
        "title": "Favorite Apps",
        "description": "Quick access to favorite applications.",
        "widget_type": "CARD",
        "module": "Core",
    },
    {
        "code": "favorite_menus",
        "title": "Favorite Menus",
        "description": "Frequently used menus.",
        "widget_type": "CARD",
        "module": "Core",
    },
    {
        "code": "pending_approvals",
        "title": "Pending Approvals",
        "description": "Approval tasks waiting for action.",
        "widget_type": "CARD",
        "module": "Core",
    },
    {
        "code": "executive_insight",
        "title": "Executive Insight",
        "description": "AI executive summary.",
        "widget_type": "CARD",
        "module": "Core",
    },
]


def seed_widgets():
    created = 0
    updated = 0

    for widget in WIDGETS:
        _, is_created = DashboardWidget.objects.update_or_create(
            code=widget["code"],
            defaults=widget,
        )

        created += int(is_created)
        updated += int(not is_created)

    return {
        "created": created,
        "updated": updated,
    }