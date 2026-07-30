from django.contrib.auth.models import Permission


class PermissionService:
    @staticmethod
    def list():
        return (
            Permission.objects
            .select_related("content_type")
            .order_by("content_type__app_label", "content_type__model", "codename")
        )