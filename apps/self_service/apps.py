from django.apps import AppConfig


class SelfServiceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.self_service"
    label = "self_service"
    verbose_name = "Employee Self Service"
