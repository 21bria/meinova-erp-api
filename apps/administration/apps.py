from django.apps import AppConfig


class AdministrationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.administration'
    label = 'administration'

    def ready(self):
        # Pendaftaran importer. Tanpa ini endpoint
        # `/api/imports/administration/calendar/<resource>/` membalas
        # 404 — registry-nya kosong, dan tidak ada pesan lain yang
        # menyebutkan sebabnya.
        from apps.administration.imports import calendar  # noqa: F401
