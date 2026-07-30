from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.administration.api.dashboard.serializers import FavoriteAppSerializer
from apps.administration.api.dashboard.services import FavoriteAppService


class FavoriteAppAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        apps = FavoriteAppService.get_favorites(
            request.user,
        )

        serializer = FavoriteAppSerializer(apps, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = FavoriteAppSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        serializer.save(
            user=request.user,
        )

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def delete(self, request):
        app_code = request.data.get("app_code")

        FavoriteAppService.delete_favorite(
            request.user,
            app_code,
        )

        return Response(status=status.HTTP_204_NO_CONTENT)

    def delete(self, request):
        app_code = request.data.get("app_code")

        FavoriteAppService.delete_favorite(
            request.user,
            app_code,
        )

        return Response(status=status.HTTP_204_NO_CONTENT)