from django.apps import AppConfig


class HelpCenterConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.helpcenter"
    label = "helpcenter"
    verbose_name = "Help Center"

    def ready(self):
        # Mendaftarkan lookup kategori panduan.
        # Tanpa ini /api/helpcenter/lookup/help-categories/ 404, dan
        # dropdown Category di form artikel tampil kosong tanpa error.
        from apps.helpcenter.api.lookup import registry  # noqa: F401
