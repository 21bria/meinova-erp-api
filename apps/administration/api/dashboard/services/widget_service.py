from apps.administration.models import DashboardWidget


class WidgetService:
    @staticmethod
    def get_widgets(user):
        widgets = DashboardWidget.objects.filter(
            is_active=True,
        ).order_by("module", "title")

        allowed = []

        for widget in widgets:
            permission = getattr(widget, "permission", "")

            if not permission or user.has_perm(permission):
                allowed.append(widget)

        return allowed