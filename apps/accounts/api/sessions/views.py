from rest_framework.decorators import action
from rest_framework.response import Response

from apps.framework.views.master import BaseMasterViewSet

from apps.accounts.models import UserSession
from .serializers import UserSessionSerializer
from .services import UserSessionService


class UserSessionViewSet(BaseMasterViewSet):
    serializer_class = UserSessionSerializer
    service_class = UserSessionService

    ordering = ["-login_at"]

    search_fields = [
        "user__username",
        "user__email",
        "ip_address",
        "browser",
        "os",
        "device",
    ]

    @action(detail=True, methods=["post"], url_path="logout")
    def logout(self, request, pk=None):
        session = self.get_object()
        UserSessionService.logout_session(session)

        return Response({"detail": "Session logged out."})

    @action(detail=False, methods=["post"], url_path="logout-user")
    def logout_user(self, request):
        user_id = request.data.get("user")

        if not user_id:
            return Response({"detail": "user is required."}, status=400)

        count = UserSessionService.logout_user_sessions(user_id)

        return Response({
            "detail": "User sessions logged out.",
            "count": count,
        })