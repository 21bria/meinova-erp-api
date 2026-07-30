from apps.administration.models import Notification, NotificationSetting


class NotificationService:
    @staticmethod
    def list(user):
        return Notification.objects.filter(user=user).order_by("-created_at")


class NotificationSettingService:
    @staticmethod
    def list(user):
        return NotificationSetting.objects.filter(user=user)