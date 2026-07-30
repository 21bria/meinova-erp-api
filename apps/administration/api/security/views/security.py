from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.framework.views.setting import BaseSettingAPIView

from apps.administration.api.security.serializers.security import (
    SecuritySettingSerializer,
    SessionSettingSerializer,
    LoginHistorySerializer,
    UserSessionSerializer,
)
from apps.administration.api.security.services.security_service import SecurityService


class SecuritySettingAPIView(BaseSettingAPIView):
    serializer_class = SecuritySettingSerializer
    framework_module = "administration/security/security-setting"
    schema_type = "setting"

    schema = {
        "title": "Security Settings",
        "description": "Configure authentication and security policies.",
        "endpoint": "/api/administration/security/security-setting/",
        "ui": {
            "layout": "form",
            "show_header": True,
        },
        "sections": [
            {
                "title": "Password Policy",
                "description": "Configure password rules and authentication security.",
                "fields": {
                    "password_min_length": {
                        "type": "number",
                        "label": "Minimum Password Length",
                        "form": True,
                    },
                    "password_require_uppercase": {
                        "type": "boolean",
                        "label": "Require Uppercase",
                        "form": True,
                    },
                    "password_require_number": {
                        "type": "boolean",
                        "label": "Require Number",
                        "form": True,
                    },
                    "password_require_symbol": {
                        "type": "boolean",
                        "label": "Require Symbol",
                        "form": True,
                    },
                },
            },
            {
                "title": "Login Protection",
                "description": "Control login attempts and account lock behavior.",
                "fields": {
                    "max_login_attempts": {
                        "type": "number",
                        "label": "Maximum Login Attempts",
                        "form": True,
                    },
                    "lockout_minutes": {
                        "type": "number",
                        "label": "Lockout Duration Minutes",
                        "form": True,
                    },
                    "enable_two_factor": {
                        "type": "boolean",
                        "label": "Enable Two-Factor Authentication",
                        "form": True,
                    },
                },
            },
        ],
    }

    def get_object(self):
        return SecurityService.get_security_setting()


class SessionSettingAPIView(BaseSettingAPIView):
    serializer_class = SessionSettingSerializer

    framework_module = "administration/security/session-setting"
    schema_type = "setting"
    schema = {
        "title": "Session Settings",
        "description": "Configure user session and timeout policies.",
        "endpoint": "/api/administration/security/session-setting/",
        "ui": {
            "layout": "form",
            "show_header": True,
        },
        "sections": [
            {
                "title": "Session Policy",
                "description": "Configure user session timeout and concurrent login behavior.",
                "fields": {
                    "session_timeout_minutes": {
                        "type": "number",
                        "label": "Session Timeout Minutes",
                        "form": True,
                    },
                    "remember_me_days": {
                        "type": "number",
                        "label": "Remember Me Days",
                        "form": True,
                    },
                    "allow_multiple_sessions": {
                        "type": "boolean",
                        "label": "Allow Multiple Sessions",
                        "form": True,
                    },
                    "force_logout_on_password_change": {
                        "type": "boolean",
                        "label": "Force Logout On Password Change",
                        "form": True,
                    },
                },
            },
        ],
    }

    def get_object(self):
        return SecurityService.get_session_setting()


class LoginHistoryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = SecurityService.login_history()
        return Response(LoginHistorySerializer(qs, many=True).data)


class UserSessionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = SecurityService.user_sessions()
        return Response(UserSessionSerializer(qs, many=True).data)