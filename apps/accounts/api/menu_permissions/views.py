from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.framework.views.tree import BaseTreeAPIView
from .serializers import MenuPermissionSaveSerializer
from .services import MenuPermissionService


class MenuPermissionTreeView(BaseTreeAPIView):
    permission_classes = [IsAuthenticated]

    framework_module = "administration/security/menu-permission"
    schema_type = "tree"

    schema = {
        "title": "Menu Permission",
        "description": "Manage role-based menu access.",
        "endpoint": "/api/accounts/menu-permissions/tree/",
        "save_endpoint": "/api/accounts/menu-permissions/save/",
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

    def get(self, request):
        role_id = request.query_params.get("role")

        if not role_id:
            return Response({
                "detail": "role query parameter is required."
            }, status=400)

        return Response(MenuPermissionService.get_tree(role_id))


class MenuPermissionSaveView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = MenuPermissionSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = MenuPermissionService.save(
            role_id=serializer.validated_data["role"],
            menu_ids=serializer.validated_data["menus"],
        )

        return Response(result)