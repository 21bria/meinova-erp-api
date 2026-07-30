from django.contrib.auth import get_user_model

from apps.administration.models import FavoriteMenu

User = get_user_model()


DEFAULT_MENUS = [
    {
        "menu_code": "employee-master",
        "title": "Employee Master",
        "description": "Human Resources",
        "link": "/hr/employees",
        "icon": "users",
        "color": "emerald",
    },
    {
        "menu_code": "attendance",
        "title": "Attendance",
        "description": "Human Resources",
        "link": "/hr/attendance",
        "icon": "calendar-check",
        "color": "emerald",
    },
    {
        "menu_code": "payroll-run",
        "title": "Payroll Run",
        "description": "Payroll",
        "link": "/payroll/runs",
        "icon": "wallet",
        "color": "violet",
    },
    {
        "menu_code": "purchase-request",
        "title": "Purchase Request",
        "description": "Supply Chain",
        "link": "/scm/purchase-requests",
        "icon": "package",
        "color": "orange",
    },
    {
        "menu_code": "journal-entry",
        "title": "Journal Entry",
        "description": "Finance",
        "link": "/finance/journals",
        "icon": "file-text",
        "color": "sky",
    },
]


def seed_favorite_menus():
    created = 0
    updated = 0

    for user in User.objects.all():
        for position, menu in enumerate(DEFAULT_MENUS, start=1):
            _, is_created = FavoriteMenu.objects.update_or_create(
                user=user,
                menu_code=menu["menu_code"],
                defaults={
                    "title": menu["title"],
                    "description": menu["description"],
                    "link": menu["link"],
                    "icon": menu["icon"],
                    "color": menu["color"],
                    "badge": "",
                    "position": position,
                    "is_visible": True,
                },
            )

            created += int(is_created)
            updated += int(not is_created)

    return {"created": created, "updated": updated}