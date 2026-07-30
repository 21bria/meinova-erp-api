from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.administration.api.dashboard.serializers import DashboardWidgetSerializer
from apps.administration.api.dashboard.services import WidgetService


class DashboardWidgetListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        widgets = WidgetService.get_widgets(request.user)
        serializer = DashboardWidgetSerializer(widgets, many=True)

        return Response(serializer.data)