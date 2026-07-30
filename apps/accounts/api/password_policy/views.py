from apps.framework.views.setting import BaseSettingAPIView

from .serializers import PasswordPolicySerializer
from .services import PasswordPolicyService


class PasswordPolicyViewSet(BaseSettingAPIView):
    serializer_class = PasswordPolicySerializer
    service_class = PasswordPolicyService

    framework_module = "administration/security/password-policy"
    schema_type = "setting"

    schema = {
        "title": "Password Policy",
        "description": "Configure password security policies.",
        "endpoint": "/api/accounts/password-policy/",
        "ui": {
            "layout": "form",
            "show_header": True,
        },
        "sections": [
            {
                "title": "Password Rules",
                "fields": [
                    "minimum_length",
                    "require_uppercase",
                    "require_lowercase",
                    "require_number",
                    "require_special_character",
                ],
            },
            {
                "title": "Security",
                "fields": [
                    "password_expiry_days",
                    "password_history",
                    "max_login_attempts",
                    "lockout_duration_minutes",
                ],
            },
        ],
    }

    def get_object(self):
        return self.service_class.get_settings()