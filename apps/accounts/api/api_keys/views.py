from apps.framework.views.master import BaseMasterViewSet

from .serializers import APIKeySerializer
from .services import APIKeyService


class APIKeyViewSet(BaseMasterViewSet):
    serializer_class = APIKeySerializer
    service_class = APIKeyService

    framework_module = "administration/security/api-keys"
    schema_type = "crud"

    schema = {
        "title": "API Keys",
        "description": "Manage API keys for users and integrations.",
    }

    ordering = ["name"]

    search_fields = [
        "name",
        "prefix",
        "user__username",
        "user__email",
    ]