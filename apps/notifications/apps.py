from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.notifications"
    label = "notifications"
    verbose_name = "Notifications"

    def ready(self):
        # Mendaftarkan event bawaan. Tanpa baris ini registry-nya kosong,
        # layar template tidak punya satu pun event untuk dipilih, dan
        # setiap pemanggil `notify()` gagal dengan `UnknownEvent` —
        # berisik, bukan diam. Pola yang sama dengan registry lookup dan
        # registry importer di codebase ini.
        from . import events  # noqa: F401
