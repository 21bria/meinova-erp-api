from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.administration.api.dashboard.serializers import FavoriteMenuSerializer
from apps.administration.api.dashboard.services import FavoriteMenuService


class FavoriteMenuAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        menus = FavoriteMenuService.get_favorites(
            request.user,
        )

        serializer = FavoriteMenuSerializer(menus, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = FavoriteMenuSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        serializer.save(
            user=request.user,
        )

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def delete(self, request):
        menu_code = request.data.get("menu_code")

        FavoriteMenuService.delete_favorite(
            request.user,
            menu_code,
        )

        return Response(status=status.HTTP_204_NO_CONTENT)