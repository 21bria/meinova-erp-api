from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.administration.api.dashboard.serializers import (
    FavoriteMenuSelectionSerializer,
    FavoriteMenuSerializer,
    MenuCatalogEntrySerializer,
)
from apps.administration.api.dashboard.services import FavoriteMenuService


class MenuCatalogAPIView(APIView):
    """
    Seluruh menu yang bisa dijadikan pintasan + mana yang sedang dipilih.

    Ini yang selama ini tidak ada, dan sebabnya bagian Favorite Menus
    tidak bisa disusun siapa pun: barisnya cuma bisa lahir dari seed,
    dan tanpa katalog tidak ada tempat untuk memilih isinya.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            MenuCatalogEntrySerializer(
                FavoriteMenuService.get_catalog(request.user),
                many=True,
            ).data
        )


class FavoriteMenuAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            FavoriteMenuSerializer(
                FavoriteMenuService.get_favorites(request.user),
                many=True,
            ).data
        )

    def put(self, request):
        """
        Menyimpan susunan pilihan sekaligus — urutan daftar = posisinya.

        `POST`/`DELETE` per baris yang dulu ada di sini sudah dibuang:
        keduanya menerima `title`/`link`/`icon` mentah dari klien — jadi
        sumber kebenarannya klien, bukan master menu — dan tidak pernah
        dipanggil siapa pun. Menggeser satu pintasan mengubah posisi
        semua yang di bawahnya, jadi menyimpan per baris berarti
        belasan request untuk satu tarikan.
        """
        serializer = FavoriteMenuSelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = FavoriteMenuService.set_favorites(
            request.user,
            serializer.validated_data["codes"],
        )

        return Response(FavoriteMenuSerializer(result, many=True).data)
