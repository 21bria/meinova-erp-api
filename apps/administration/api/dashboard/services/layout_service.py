from apps.administration.models import UserDashboardLayout


class LayoutService:
    @staticmethod
    def get_layout(user):
        return (
            UserDashboardLayout.objects.select_related("widget")
            .filter(
                user=user,
                is_deleted=False,
                is_active=True,
            )
            .order_by("y", "x")
        )

    @staticmethod
    def update_layout_item(layout, data, serializer_class):
        serializer = serializer_class(
            layout,
            data=data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        return serializer.save()