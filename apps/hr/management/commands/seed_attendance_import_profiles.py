# python manage.py seed_attendance_import_profiles --schema=demo

from __future__ import annotations

from django.core.management.base import (
    BaseCommand,
    CommandError,
)
from django_tenants.utils import (
    get_tenant_model,
    tenant_context,
)

from apps.hr.models import (
    AttendanceImportProfile,
)


class Command(BaseCommand):
    help = (
        "Seed default attendance import "
        "profiles for a tenant."
    )

    def add_arguments(
        self,
        parser,
    ):
        parser.add_argument(
            "--schema",
            type=str,
            required=True,
            help="Tenant schema name.",
        )

    def handle(
        self,
        *args,
        **options,
    ):
        schema_name = str(
            options["schema"],
        ).strip()

        TenantModel = get_tenant_model()

        try:
            tenant = (
                TenantModel.objects
                .get(
                    schema_name=schema_name,
                )
            )
        except TenantModel.DoesNotExist as exc:
            raise CommandError(
                f"Tenant schema "
                f"'{schema_name}' not found."
            ) from exc

        with tenant_context(tenant):
            profile, created = (
                AttendanceImportProfile.objects
                .update_or_create(
                    code="HO-TERMINAL-CSV",
                    defaults={
                        "name":
                            "HO Terminal CSV",

                        "description": (
                            "CSV export from the "
                            "Head Office attendance "
                            "terminal."
                        ),

                        "delimiter": ",",
                        "encoding": "utf-8-sig",

                        "mapping": {
                            "employee_code": "no",
                            "attendance_date": "ymd",
                            "employee_name": "name",
                            "department": "depart",
                            "check_in": "work1",
                            "check_out": "work2",
                            "remark": "remark",
                        },

                        "value_mapping": {},

                        "datetime_formats": [
                            "%Y/%m/%d",
                        ],

                        "defaults": {
                            "source": "import",
                        },

                        "options": {
                            "skip_invalid": True,
                            "skip_duplicates": True,
                        },

                        "is_active": True,
                    },
                )
            )

        action = (
            "Created"
            if created
            else "Updated"
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{action}: "
                f"{profile.name} "
                f"on schema {schema_name}"
            )
        )