from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsSecurityAdmin
from apps.framework.views.tree import BaseTreeAPIView

from apps.accounts.services.role_assignment import (
    AuthorityValidationError,
    EDITABLE_RESOURCE_TYPES,
    UnknownRoleError,
)

from .serializers import (
    AssignmentAuthoritySaveSerializer,
    UserRoleSaveSerializer,
)
from .services import UserRoleService


class UserRoleTreeView(BaseTreeAPIView):
    permission_classes = [IsSecurityAdmin]

    framework_module = "administration/security/user-role"
    schema_type = "tree"

    schema = {
        "title": "User Roles",
        "description": "Tentukan role yang dipegang tiap pengguna.",
        "endpoint": "/api/accounts/user-roles/tree/",
        "save_endpoint": "/api/accounts/user-roles/save/",
        "query": {
            "user": {
                "required": True,
                "type": "lookup",
                "label": "User",
                "endpoint": "/api/accounts/lookup/users/",
                "label_key": "label",
                "value_key": "value",
            }
        },
        "ui": {
            "mode": "checkbox-tree",
            "expand_all": True,
            "cascade_check": False,
            "show_search": True,
        },
    }

    def get(self, request):
        return Response(
            UserRoleService.get_tree(
                request.query_params.get("user"),
            )
        )


class UserRoleSaveView(APIView):
    permission_classes = [IsSecurityAdmin]

    def post(self, request):
        serializer = UserRoleSaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            result = UserRoleService.save(
                user_id=serializer.validated_data["user"],
                role_ids=serializer.validated_data["roles"],
            )
        except AuthorityValidationError as error:
            # Kombinasi mode/level/baris yang tidak sah pada entri
            # bentuk panjang. Ditolak seluruhnya: menyimpan sebagian
            # akan meninggalkan role terpasang tanpa WHERE yang diminta.
            raise ValidationError({"roles": str(error)}) from error
        except UnknownRoleError as error:
            # 400, bukan 500 — dan bukan pula sukses diam-diam.
            # Daftar yang dikirim adalah daftar utuh, jadi menerima
            # sebagian berarti mencabut sisanya tanpa diminta.
            raise ValidationError({"roles": str(error)}) from error

        return Response(result)


class UserRoleAuthorityView(APIView):
    """
    Membaca dan menyetel **WHERE** tiap penugasan milik satu pengguna.

    Sengaja terpisah dari layar Role. Cakupan yang dulu tinggal pada
    `Role` menjawab pertanyaan yang berbeda — "role ini umumnya seluas
    apa" — dan menyuntingnya di sana mengubah kewenangan **setiap**
    pemegangnya sekaligus; karena itu kolomnya dihapus. Yang dibutuhkan administrasi
    sehari-hari justru sebaliknya: satu orang, satu role, satu
    kewenangan.
    """

    permission_classes = [IsSecurityAdmin]

    def get(self, request):
        return Response({
            "assignments": UserRoleService.get_authority(
                request.query_params.get("user"),
            ),
            # Dikirim dari server supaya layar tidak perlu menyalin
            # daftarnya sendiri dan ketinggalan kalau berubah.
            "resource_types": list(EDITABLE_RESOURCE_TYPES),
        })

    def post(self, request):
        serializer = AssignmentAuthoritySaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        try:
            result = UserRoleService.save_authority(
                data["user"],
                data["role"],
                mode=data["authority_mode"],
                level=data.get("authority_level", ""),
                authorities=data.get("authorities", []),
            )
        except AuthorityValidationError as error:
            raise ValidationError({"authority": str(error)}) from error
        except ValueError as error:
            raise ValidationError({"user": str(error)}) from error

        return Response(result)
