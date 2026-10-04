from apps.accounts.permissions import CanManageSecurity
from apps.framework.views.master import BaseMasterViewSet

from .serializers import PermissionSerializer
from .services import PermissionService


class PermissionViewSet(BaseMasterViewSet):
    serializer_class = PermissionSerializer
    service_class = PermissionService

    # Membuat user / memberi role adalah wewenang paling
    # berbahaya di sistem. Baca dibiarkan terbuka (dropdown
    # 'pilih pengguna' di layar lain membutuhkannya), tulis
    # dikunci ke superuser + role administrator keamanan.
    permission_classes = [CanManageSecurity]
    framework_module = "administration/security/permissions"
    schema_type = "crud"

    schema = {
        "title": "Permissions",
        "description": "Manage system permissions used by roles and access control.",
        # Wajib disebut. Generator FE menurunkan endpoint dari
        # `framework_module` kalau kunci ini kosong, dan modul ini
        # rutenya memang berbeda: module-nya "administration/security/…"
        # tapi API-nya di bawah /api/accounts/. Akibatnya tabelnya
        # menembak URL yang tidak ada dan tampil "No results." — tanpa
        # pesan error apa pun.
        "endpoint": "/api/accounts/permissions/",

        # Kolom dideklarasikan eksplisit. Tanpa ini introspeksi model
        # membuat kolom `content_type` dan `codename` — dua-duanya
        # **tidak ada** di serializer (yang dikirim `module`, `model`,
        # `code`), jadi tabelnya menampilkan "-" di 708 baris tanpa
        # pesan error apa pun.
        "fields": {
            "name": {
                "label": "Permission",
                "type": "text",
                "table": True,
                "search": True,
                "sortable": True,
                "read_only": True,
                "display": True,
                "order": 10,
            },
            "module": {
                "label": "Module",
                "type": "text",
                "table": True,
                "search": True,
                "sortable": True,
                "read_only": True,
                "display": True,
                "order": 20,
            },
            "model": {
                "label": "Object",
                "type": "text",
                "table": True,
                "search": True,
                "sortable": True,
                "read_only": True,
                "display": True,
                "order": 30,
            },
            "code": {
                "label": "Codename",
                "type": "text",
                "table": True,
                "search": True,
                "sortable": True,
                "read_only": True,
                "display": True,
                "order": 40,
            },

            # Kolom hasil introspeksi model yang sengaja dimatikan.
            "content_type": {"table": False, "filter": False, "search": False},
            "codename": {"table": False, "filter": False, "search": False},
        },
    }

    ordering = ["content_type__app_label", "content_type__model", "codename"]
    search_fields = [
        "name",
        "codename",
        "content_type__app_label",
        "content_type__model",
    ]