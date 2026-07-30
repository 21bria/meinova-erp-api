from django.contrib.auth import get_user_model

from apps.administration.models import FavoriteApp

User = get_user_model()


DEFAULT_APPS = [
     {
        "app_code": "administration",
        "title": "Administration",
        "description": "Master data, security, workflow and settings",
        "link": "/administration",
        "icon": "settings-2",
        "color": "slate",
    },
    {
        "app_code": "hr",
        "title": "Human Resources",
        "description": "Employees, attendance and leave",
        "link": "/hr",
        "icon": "users",
        "color": "emerald",
    },
    {
        "app_code": "payroll",
        "title": "Payroll",
        "description": "Salary, payslip and taxation",
        "link": "/payroll",
        "icon": "wallet",
        "color": "violet",
        "is_visible": True,
    },
    {
        "app_code": "scm",
        "title": "Supply Chain",
        "description": "Procurement, inventory and warehouse",
        "link": "/scm",
        "icon": "package",
        "color": "orange",
    },
    {
        "app_code": "manufacturing",
        "title": "Manufacturing",
        "description": "Production planning, BOM and work orders",
        "link": "/manufacturing",
        "icon": "factory",
        "color": "amber",
    },
    {
        "app_code": "finance",
        "title": "Finance",
        "description": "General Ledger, AP, AR and Cash & Bank",
        "link": "/finance",
        "icon": "file-text",
        "color": "sky",
    },
    {
        "app_code": "crm",
        "title": "Customer Relationship",
        "description": "Customers, sales and opportunities",
        "link": "/crm",
        "icon": "handshake",
        "color": "cyan",
    },
    {
        "app_code": "reports",
        "title": "Reports",
        "description": "Analytics, dashboards and reporting",
        "link": "/reports",
        "icon": "bar-chart-3",
        "color": "rose",
    },

]

def seed_favorite_apps():
    created = 0
    updated = 0

    for user in User.objects.all():
        for position, app in enumerate(DEFAULT_APPS, start=1):
            _, is_created = FavoriteApp.objects.update_or_create(
                user=user,
                app_code=app["app_code"],
                defaults={
                    "title": app["title"],
                    "description": app["description"],
                    "link": app["link"],
                    "icon": app["icon"],
                    "color": app["color"],
                    "badge": "",
                    "position": position,
                    "is_visible": True,
                },
            )

            if is_created:
                created += 1
            else:
                updated += 1

    return {
        "created": created,
        "updated": updated,
    }