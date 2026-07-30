from apps.framework.views.master import BaseMasterViewSet

from .serializers import PermissionSerializer
from .services import PermissionService


class PermissionViewSet(BaseMasterViewSet):
    serializer_class = PermissionSerializer
    service_class = PermissionService
    framework_module = "administration/security/permissions"
    schema_type = "crud"

    schema = {
        "title": "Permissions",
        "description": "Manage system permissions used by roles and access control.",
    }

    ordering = ["content_type__app_label", "content_type__model", "codename"]
    search_fields = [
        "name",
        "codename",
        "content_type__app_label",
        "content_type__model",
    ]