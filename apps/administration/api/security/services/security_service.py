from apps.administration.models import (
    SecuritySetting,
    SessionSetting,
    LoginHistory,
    UserSession,
)


class SecurityService:
    @staticmethod
    def get_security_setting():
        obj, _ = SecuritySetting.objects.get_or_create(id=1)
        return obj

    @staticmethod
    def get_session_setting():
        obj, _ = SessionSetting.objects.get_or_create(id=1)
        return obj

    @staticmethod
    def login_history():
        return LoginHistory.objects.select_related("user").order_by("-created_at")

    @staticmethod
    def user_sessions():
        return UserSession.objects.select_related("user").order_by("-created_at")