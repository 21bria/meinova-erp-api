from apps.accounts.permissions import CanManageSecurity
from apps.framework.views.master import BaseMasterViewSet

from .serializers import UserSerializer
from .services import UserService


class UserViewSet(BaseMasterViewSet):
    serializer_class = UserSerializer
    service_class = UserService

    # Membuat user / memberi role adalah wewenang paling
    # berbahaya di sistem. Baca dibiarkan terbuka (dropdown
    # 'pilih pengguna' di layar lain membutuhkannya), tulis
    # dikunci ke superuser + role administrator keamanan.
    permission_classes = [CanManageSecurity]

    framework_module = "administration/security/users"
    schema_type = "crud"

    schema = {
        "title": "Users",
        "description": "Manage system users and authentication accounts.",
        # Wajib disebut. Generator FE menurunkan endpoint dari
        # `framework_module` kalau kunci ini kosong, dan modul ini
        # rutenya memang berbeda: module-nya "administration/security/…"
        # tapi API-nya di bawah /api/accounts/. Akibatnya tabelnya
        # menembak URL yang tidak ada dan tampil "No results." — tanpa
        # pesan error apa pun.
        "endpoint": "/api/accounts/users/",

        # Kolom dideklarasikan eksplisit. Introspeksi model membuat
        # kolom untuk **setiap** field AbstractUser — termasuk
        # `password`, yang sempat muncul sebagai judul kolom di layar
        # daftar pengguna, plus `last_login`/`date_joined` yang tidak
        # ada di serializer sehingga isinya "-".
        "fields": {
            "username": {
                "label": "Username", "type": "text", "table": True,
                "search": True, "sortable": True, "order": 10,
            },
            "full_name": {
                "label": "Name", "type": "text", "table": True,
                "search": False, "sortable": False, "read_only": True,
                "display": True, "order": 20,
            },
            "email": {
                "label": "Email", "type": "email", "table": True,
                "search": True, "sortable": True, "order": 30,
            },
            "role_names": {
                "label": "Roles", "type": "text", "table": True,
                "search": False, "sortable": False, "read_only": True,
                "display": True,
                "help_text": (
                    "Hak akses yang sebenarnya berlaku. Kolom `groups` "
                    "bawaan Django ada di model tapi tidak dibaca satu "
                    "baris kode pun."
                ),
                "order": 40,
            },
            "is_active": {
                "label": "Active", "type": "boolean", "table": True,
                "filter": True, "sortable": True, "order": 50,
            },
            "is_staff": {
                "label": "Staff", "type": "boolean", "table": False,
                "filter": True, "order": 60,
            },
            "is_superuser": {
                "label": "Superuser", "type": "boolean", "table": True,
                "filter": True, "read_only": True, "display": True,
                "order": 70,
            },
            "last_login": {
                "label": "Last Login", "type": "datetime", "table": True,
                "read_only": True, "display": True, "sortable": True,
                "order": 80,
            },

            # Tidak pernah jadi kolom.
            "password": {"table": False, "filter": False, "search": False},
            "date_joined": {"table": False, "filter": False, "search": False},
            "groups": {"table": False, "filter": False, "search": False},
            "user_permissions": {"table": False, "filter": False, "search": False},
            "roles": {"table": False, "filter": False, "search": False},
        },
    }

    ordering = ["username"]
    search_fields = [
        "username",
        "email",
        "first_name",
        "last_name",
    ]
    filterset_fields = ["is_active"]