from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.framework.views.tree import BaseTreeAPIView

from .serializers import DataPermissionSaveSerializer
from .services import DataPermissionService


class DataPermissionTreeView(BaseTreeAPIView):
    permission_classes = [IsAuthenticated]
    framework_module = "administration/security/data-permission"
    schema_type = "tree"

   
class DataPermissionTreeView(BaseTreeAPIView):
    permission_classes = [IsAuthenticated]
    framework_module = "administration/security/data-permission"
    schema_type = "tree"

    schema = {
        "title": "Data Permission",
        "description": "Manage role-based access to organization data.",
        "endpoint": "/api/accounts/data-permissions/tree/",
        "save_endpoint": "/api/accounts/data-permissions/save/",
        "query": {
            "role": {
                "required": True,
                "type": "lookup",
                "label": "Role",
                "endpoint": "/api/accounts/roles/",
                "label_key": "name",
                "value_key": "id",
            }
        },
        "ui": {
            "mode": "checkbox-tree",
            "expand_all": True,
            "cascade_check": True,
            "show_search": True,
        },
    }

class DataPermissionSaveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DataPermissionSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = DataPermissionService.save(
            role_id=serializer.validated_data["role"],
            resources=serializer.validated_data["resources"],
        )

        return Response(result)