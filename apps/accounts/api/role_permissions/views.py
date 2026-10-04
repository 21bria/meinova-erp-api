from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsSecurityAdmin
from apps.framework.views.tree import BaseTreeAPIView

from .serializers import RolePermissionSaveSerializer
from .services import RolePermissionService


class RolePermissionTreeView(BaseTreeAPIView):
    """
    Layar yang membuat `Role.permissions` bisa diatur.

    Sebelum ini centangnya cuma bisa diubah lewat shell: form Role di
    layar Security tidak punya pemilih permission sama sekali, jadi
    penjagaan izin model tidak punya kenop.
    """

    permission_classes = [IsSecurityAdmin]

    framework_module = "administration/security/role-permission"
    schema_type = "tree"

    schema = {
        "title": "Role Permissions",
        "description": "Tentukan modul dan aksi apa yang boleh dilakukan tiap role.",
        "endpoint": "/api/accounts/role-permissions/tree/",
        "save_endpoint": "/api/accounts/role-permissions/save/",
        "query": {
            "role": {
                "required": True,
                "type": "lookup",
                "label": "Role",
                "endpoint": "/api/accounts/lookup/roles/",
                "label_key": "label",
                "value_key": "value",
            }
        },
        "ui": {
            "mode": "checkbox-tree",
            "expand_all": False,
            "cascade_check": True,
            "show_search": True,
        },
    }

    def get(self, request):
        return Response(
            RolePermissionService.get_tree(
                request.query_params.get("role"),
            )
        )


class RolePermissionSaveView(APIView):
    permission_classes = [IsSecurityAdmin]

    def post(self, request):
        serializer = RolePermissionSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        return Response(
            RolePermissionService.save(
                role_id=serializer.validated_data["role"],
                permission_ids=serializer.validated_data["permissions"],
            )
        )
