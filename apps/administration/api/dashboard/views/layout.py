"""
Susunan beranda per pengguna.

`PUT` menyimpan **seluruh** susunan sekaligus, sejajar dengan
`favorite-apps/`: menggeser satu kartu mengubah posisi semua yang di
bawahnya, jadi menyimpannya satu per satu berarti puluhan request untuk
satu tarikan — dan keadaan setengah tersimpan kalau salah satunya gagal.

Endpoint `POST`/`PATCH` per baris yang lama dihapus. Keduanya menerima
`id` baris `UserDashboardLayout` mentah, dan tidak ada satu pun
pemanggil di frontend yang pernah memakainya.
"""

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.responses.api import error_response, success_response

from apps.administration.api.dashboard.services import LayoutService


class UserDashboardLayoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return success_response(
            data=LayoutService.catalog(request.user),
            message="Susunan beranda berhasil dimuat.",
        )

    def put(self, request):
        items = request.data.get("items")

        if not isinstance(items, list):
            return error_response(
                message="Kirim `items` berisi daftar widget.",
                errors={"items": "Harus berupa daftar."},
            )

        return success_response(
            data=LayoutService.set_layout(request.user, items),
            message="Susunan beranda tersimpan.",
        )

    def delete(self, request):
        """Kembali ke susunan bawaan."""
        return success_response(
            data=LayoutService.reset(request.user),
            message="Susunan beranda dikembalikan ke bawaan.",
        )
