from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.administration.api.dashboard.serializers import (
    AppCatalogEntrySerializer,
    FavoriteAppSerializer,
    FavoriteAppSelectionSerializer,
)
from apps.administration.api.dashboard.services import FavoriteAppService


class AppCatalogAPIView(APIView):
    """
    Seluruh aplikasi yang tersedia + penanda mana yang sedang dipilih.

    Ini yang selama ini tidak ada, dan sebabnya bagian Applications di
    halaman depan selalu kosong: `FavoriteApp` tabel per pengguna, dan
    tanpa katalog tidak ada tempat untuk memilih isinya.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            AppCatalogEntrySerializer(
                FavoriteAppService.get_catalog(request.user),
                many=True,
            ).data
        )


class FavoriteAppAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            FavoriteAppSerializer(
                FavoriteAppService.get_favorites(request.user),
                many=True,
            ).data
        )

    def put(self, request):
        """
        Menyimpan susunan pilihan sekaligus — urutan daftar = posisinya.

        Satu kiriman untuk seluruh susunan, bukan satu request per kartu:
        menyeret kartu ke urutan baru mengubah posisi semua yang di
        bawahnya, dan mengirimnya satu per satu membuat susunan di layar
        sempat berbeda dari yang tersimpan.
        """
        serializer = FavoriteAppSelectionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = FavoriteAppService.set_favorites(
            request.user,
            serializer.validated_data["codes"],
        )

        return Response(FavoriteAppSerializer(result, many=True).data)

    def post(self, request):
        """Menambahkan satu aplikasi ke ujung susunan."""
        code = str(request.data.get("app_code") or "").strip()

        if not code:
            return Response(
                {"detail": "Field 'app_code' wajib diisi."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        codes = [
            item["app_code"]
            for item in FavoriteAppService.get_favorites(request.user)
        ]

        if code not in codes:
            codes.append(code)

        result = FavoriteAppService.set_favorites(request.user, codes)

        return Response(
            FavoriteAppSerializer(result, many=True).data,
            status=status.HTTP_201_CREATED,
        )

    def delete(self, request):
        code = str(request.data.get("app_code") or "").strip()

        codes = [
            item["app_code"]
            for item in FavoriteAppService.get_favorites(request.user)
            if item["app_code"] != code
        ]

        FavoriteAppService.set_favorites(request.user, codes)

        return Response(status=status.HTTP_204_NO_CONTENT)
