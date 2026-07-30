from django.contrib.auth import get_user_model

from apps.administration.models import DashboardWidget, UserDashboardLayout

User = get_user_model()


def seed_default_layout():
    created = 0
    updated = 0

    widgets = DashboardWidget.objects.filter(
        is_active=True,
        is_deleted=False,
    ).order_by("module", "title")

    for user in User.objects.all():
        for index, widget in enumerate(widgets):
            _, is_created = UserDashboardLayout.objects.update_or_create(
                user=user,
                widget=widget,
                defaults={
                    "x": 0,
                    "y": index,
                    "width": widget.default_width,
                    "height": widget.default_height,
                    "is_visible": True,
                },
            )

            created += int(is_created)
            updated += int(not is_created)

    return {
        "created": created,
        "updated": updated,
    }