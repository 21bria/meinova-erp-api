from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.administration.models import UserDashboardLayout
from apps.administration.api.dashboard.serializers import UserDashboardLayoutSerializer
from apps.administration.api.dashboard.services import LayoutService


class UserDashboardLayoutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        layouts = LayoutService.get_layout(
            request.user,
        )

        serializer = UserDashboardLayoutSerializer(layouts, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = UserDashboardLayoutSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        serializer.save(
            user=request.user,
        )

        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def patch(self, request):
        items = request.data

        if not isinstance(items, list):
            return Response(
                {"detail": "Expected list of layout items."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        updated = []

        for item in items:
            layout_id = item.get("id")

            if not layout_id:
                continue

            try:
                layout = UserDashboardLayout.objects.get(
                    id=layout_id,
                    user=request.user,
                )
            except UserDashboardLayout.DoesNotExist:
                continue

            layout = LayoutService.update_layout_item(
                layout,
                item,
                UserDashboardLayoutSerializer,
            )

            updated.append(UserDashboardLayoutSerializer(layout).data)

        return Response(updated)