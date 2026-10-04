from rest_framework import status
from rest_framework.generics import RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView

from .serializers import (
    ChangePasswordSerializer,
    LoginSerializer,
    MeSerializer,
    ProfileUpdateSerializer,
)


class LoginView(TokenObtainPairView):
    serializer_class = LoginSerializer


class MeView(RetrieveUpdateAPIView):
    """
    Identitas pengguna yang sedang login, dan sejak sekarang **bisa
    diperbarui olehnya sendiri**.

    Sebelumnya `RetrieveAPIView` — read-only. Tidak ada satu pun
    endpoint yang membuat seseorang bisa membetulkan namanya sendiri;
    yang ada cuma ganti password, jadi salah ketik nama saat pembuatan
    akun harus lewat admin.

    **Serializer baca dan tulisnya berbeda, dan itu bukan kerapian.**
    `MeSerializer` mengirim `is_staff`, `is_superuser`, `roles`, dan
    `permissions`; memakainya sebagai jalur tulis berarti siapa pun
    bisa menaikkan dirinya jadi superuser lewat satu PATCH ke
    endpoint profilnya sendiri.
    """

    permission_classes = [IsAuthenticated]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return ProfileUpdateSerializer

        return MeSerializer

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)

        # Dibalas dengan bentuk **baca**, bukan bentuk tulis: frontend
        # menyimpan seluruh profil dari respons ini, dan membalas empat
        # kolom saja akan menghapus role serta izin dari state-nya —
        # sidebar langsung kehilangan menunya tanpa satu pun error.
        return Response(
            MeSerializer(self.get_object(), context=self.get_serializer_context()).data,
        )


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.data.get("refresh")

        if refresh:
            try:
                token = RefreshToken(refresh)
                token.blacklist()
            except Exception:
                pass

        return Response(
            {"detail": "Logout berhasil."},
            status=status.HTTP_200_OK,
        )


class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()

        return Response(
            {"detail": "Password berhasil diubah."},
            status=status.HTTP_200_OK,
        )