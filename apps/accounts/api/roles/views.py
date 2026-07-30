from apps.framework.views.master import BaseMasterViewSet

from .serializers import RoleSerializer
from .services import RoleService


class RoleViewSet(BaseMasterViewSet):
    serializer_class = RoleSerializer
    service_class = RoleService
    framework_module = "administration/security/roles"
    schema_type = "crud"

    schema = {
        "title": "Roles",
        "description": "Manage security roles and access assignments.",
    }

    ordering = ["name"]
    search_fields = ["code", "name", "description"]
    filterset_fields = ["is_active"]