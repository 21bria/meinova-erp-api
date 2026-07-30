from rest_framework.permissions import IsAuthenticated
from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.audit.serializers.audit import AuditTrailSerializer
from apps.administration.api.audit.services.audit_service import AuditTrailService


class AuditTrailViewSet(BaseMasterViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = AuditTrailSerializer
    service_class = AuditTrailService
    framework_module = "administration/audit/audit-trail"

    schema_type = "crud"

    search_fields = [
        "action",
        "module",
        "object_type",
        "object_id",
        "object_repr",
        "ip_address",
        "user_agent",
        "user__username",
    ]
    ordering = ["-created_at"]

    schema = {
        "title": "Audit Trail",
        "description": "Review system activity and audit logs.",
        "endpoint": "/api/administration/audit/trails/",
        "ui": {
            "create": False,
            "edit": False,
            "delete": False,
            "bulk_delete": False,
            "import": False,
            "export": True,
        },
        "fields": {
            "created_at": {
                "table": True,
                "label": "Created At",
            },
            "user": {
                "table": True,
                "label": "User",
            },
            "action": {
                "table": True,
                "label": "Action",
            },
            "module": {
                "table": True,
                "label": "Module",
            },
            "object_type": {
                "table": True,
                "label": "Object Type",
            },
            "object_id": {
                "table": True,
                "label": "Object ID",
            },
            "object_repr": {
                "table": True,
                "label": "Object",
            },
            "ip_address": {
                "table": True,
                "label": "IP Address",
            },
        },
    }