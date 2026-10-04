from django.apps import AppConfig


class PayrollConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.payroll'
    label = 'payroll'

    def ready(self):
        # Registry lookup memakai nama global, dan yang tidak pernah
        # di-import tidak pernah terdaftar — endpoint-nya 404 tanpa
        # pesan. Semua registry payroll di-import dari satu tempat ini.
        from apps.payroll.api.salary_grades import lookup  # noqa: F401
        from apps.payroll.api.allowance_template_lines.lookup import (  # noqa: F401
            registry as allowance_line_registry,
        )
        from apps.payroll.api.deduction_template_lines.lookup import (  # noqa: F401
            registry as deduction_line_registry,
        )
        from apps.payroll.api.bpjs_base_definitions.lookup import (  # noqa: F401
            registry as bpjs_base_definition_registry,
        )
        from apps.payroll.api.bpjs_programs.lookup import (  # noqa: F401
            registry as bpjs_program_registry,
        )
        from apps.payroll.api.bpjs_risk_classes.lookup import (  # noqa: F401
            registry as bpjs_risk_class_registry,
        )
        from apps.payroll.api.payroll_periods.lookup import (  # noqa: F401
            registry as period_registry,
        )
        from apps.payroll.api.payroll_runs.lookup import (  # noqa: F401
            registry as run_registry,
        )

        # Menyambungkan payroll run ke engine approval generik. Kalau
        # lupa, tombol Approve di kotak masuk tetap jalan tapi status
        # run-nya tidak ikut berpindah — dan gagalnya diam.
        from apps.payroll import workflow_handlers  # noqa: F401
