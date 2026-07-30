from apps.framework.views.master import BaseMasterViewSet

from .serializers import UserSerializer
from .services import UserService


class UserViewSet(BaseMasterViewSet):
    serializer_class = UserSerializer
    service_class = UserService

    framework_module = "administration/security/users"
    schema_type = "crud"

    schema = {
        "title": "Users",
        "description": "Manage system users and authentication accounts.",
    }

    ordering = ["username"]
    search_fields = [
        "username",
        "email",
        "first_name",
        "last_name",
    ]
    filterset_fields = ["is_active"]