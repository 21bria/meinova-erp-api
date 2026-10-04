from apps.accounts.permissions import IsSecurityAdmin
from rest_framework.response import Response
from rest_framework.views import APIView

from rest_framework.permissions import IsAuthenticated

from apps.framework.views.tree import BaseTreeAPIView
from .access import MenuAccessService
from .serializers import MenuPermissionSaveSerializer
from .services import MenuPermissionService


class MyMenuAccessView(APIView):
    """
    Menu yang boleh dilihat pengguna yang sedang login.

    Dibaca sidebar. **Bukan penjagaan** — halamannya tetap bisa dibuka
    lewat URL langsung, dan yang menolak sungguhan tetap API tiap
    resource. Ini soal tidak menyodorkan layar yang tidak relevan.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(MenuAccessService.visible_for(request.user))


class MenuPermissionTreeView(BaseTreeAPIView):
    permission_classes = [IsSecurityAdmin]

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
    permission_classes = [IsSecurityAdmin]

    def post(self, request):
        serializer = MenuPermissionSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = MenuPermissionService.save(
            role_id=serializer.validated_data["role"],
            menu_ids=serializer.validated_data["menus"],
            rules=serializer.validated_data.get("rules"),
        )

        return Response(result)