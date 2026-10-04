from apps.accounts.permissions import CanManageSecurity
from apps.framework.views.master import BaseMasterViewSet

from .serializers import RoleSerializer
from .services import RoleService


class RoleViewSet(BaseMasterViewSet):
    serializer_class = RoleSerializer
    service_class = RoleService

    # Membuat user / memberi role adalah wewenang paling
    # berbahaya di sistem. Baca dibiarkan terbuka (dropdown
    # 'pilih pengguna' di layar lain membutuhkannya), tulis
    # dikunci ke superuser + role administrator keamanan.
    permission_classes = [CanManageSecurity]
    framework_module = "administration/security/roles"
    schema_type = "crud"

    schema = {
        "title": "Roles",
        "description": "Manage security roles and access assignments.",
        # Wajib disebut. Generator FE menurunkan endpoint dari
        # `framework_module` kalau kunci ini kosong, dan modul ini
        # rutenya memang berbeda: module-nya "administration/security/…"
        # tapi API-nya di bawah /api/accounts/. Akibatnya tabelnya
        # menembak URL yang tidak ada dan tampil "No results." — tanpa
        # pesan error apa pun.
        "endpoint": "/api/accounts/roles/",

        # Tanpa kolom cakupan lama. Sampai Stage 4H keduanya masih
        # ditampilkan read-only sebagai bahan banding; Stage 4I
        # mencabutnya karena kolom yang tidak menentukan akses siapa
        # pun, tapi tetap terbaca seperti kebijakan di layar
        # administrasi, adalah cara termurah membuat orang salah
        # menyimpulkan siapa melihat apa. WHERE yang berlaku ada di
        # layar User Role -> Kewenangan.
    }

    ordering = ["name"]
    search_fields = ["code", "name", "description"]
    filterset_fields = ["is_active"]