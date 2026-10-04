from django.apps import AppConfig


class HrConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.hr'
    label = 'hr'

    def ready(self):
        # Mendaftarkan importer ke registry framework.
        # Tanpa ini endpoint /api/imports/<module>/ tidak dikenali.
        from apps.hr.imports import (  # noqa: F401
            attendance,
            employee,
            leave_opening,
        )

        # Mendaftarkan lookup transaksional HR.
        # Tanpa ini /api/hr/lookup/<name>/ membalas 404.
        from apps.hr.api.lookup import registry  # noqa: F401

        # Mendaftarkan pemetaan status dokumen HR ke engine approval.
        # Tanpa ini tombol Approve di kotak masuk generik tetap jalan
        # tapi status cuti/TR-nya tidak ikut berpindah — gagal tanpa
        # suara.
        from apps.hr import workflow_handlers  # noqa: F401
