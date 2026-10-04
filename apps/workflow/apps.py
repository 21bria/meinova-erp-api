from django.apps import AppConfig


class WorkflowConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"

    name = "apps.workflow"

    verbose_name = "Workflow"

    def ready(self):
        # Registry lookup diisi saat startup. Kalau modul ini tidak
        # pernah di-import, endpoint lookup-nya 404 tanpa pesan —
        # jebakan yang sama pernah kena di registry lookup HR.
        from apps.workflow.api.lookup import registry  # noqa: F401
