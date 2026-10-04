# semua employee
# python manage.py tenant_command audit_employee_reporting --schema=demo

# # lokasi tertentu

# python manage.py tenant_command audit_employee_reporting \
#   --schema=demo \
#   --location=SJKT-HO

# # site
# python manage.py tenant_command audit_employee_reporting \
#   --schema=demo \
#   --location=SAGEA-MINE

# # hanya yang bermasalah
# python manage.py tenant_command audit_employee_reporting \
#   --schema=demo \
#   --issues-only

from django.core.management.base import BaseCommand
from dateutil.relativedelta import relativedelta

from django.utils import timezone
from apps.hr.models import Employee


class Command(BaseCommand):
    help = (
        "Audit kesiapan Employee reporting line untuk workflow. "
        "Read-only: tidak mengubah data apa pun."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--location",
            type=str,
            help="Filter berdasarkan Location code, contoh: JKT-HO atau SAGEA-MINE.",
        )
        parser.add_argument(
            "--issues-only",
            action="store_true",
            help="Tampilkan hanya employee yang memiliki masalah reporting/account.",
        )

    def handle(self, *args, **options):
        location_code = options.get("location")
        issues_only = options.get("issues_only", False)

        qs = (
            Employee.objects
            .filter(
                is_deleted=False,
                is_active=True,
            )
            .select_related(
                "user",
                "organization__location",
                "organization__department",
                "organization__section",
                "organization__position",
                "organization__reports_to",
                "organization__reports_to__user",
                "employment__employee_group",
                "employment__employment_type",
            )
            .order_by("employee_number")
        )

        if location_code:
            qs = qs.filter(
                organization__location__code__iexact=location_code
            )

        rows = []

        for employee in qs:
            org = getattr(employee, "organization", None)

            employment = getattr(employee, "employment", None)

            employee_group = (
                getattr(employment, "employee_group", None)
                if employment
                else None
            )

            employment_type = (
                getattr(employment, "employment_type", None)
                if employment
                else None
            )

            join_date = (
                getattr(employment, "join_date", None)
                if employment
                else None
            )

            if join_date:
                tenure = relativedelta(timezone.localdate(), join_date)
                masa_kerja = f"{tenure.years}th {tenure.months}bl"
            else:
                masa_kerja = "-"

            report_to = (
                getattr(org, "reports_to", None)
                if org
                else None
            )

            employee_user = (
                employee.user
                if getattr(employee, "user_id", None)
                else None
            )

            report_to_user = (
                report_to.user
                if report_to and getattr(report_to, "user_id", None)
                else None
            )

            status = self._resolve_status(
                employee_user=employee_user,
                report_to=report_to,
                report_to_user=report_to_user,
            )

            if issues_only and status == "OK":
                continue

            employee_name = self._employee_name(employee)
            report_to_name = (
                self._employee_name(report_to)
                if report_to
                else "-"
            )

            rows.append(
                {
                    "employee_number": employee.employee_number or "-",
                    "employee_name": employee_name or "-",
                    
                    "location": self._code(
                        getattr(org, "location", None)
                    ),
                    "department": self._code(
                        getattr(org, "department", None)
                    ),
                    "section": self._code(
                        getattr(org, "section", None)
                    ),
                    "position": self._name(
                        getattr(org, "position", None)
                    ),

                    "group": self._code(employee_group),
                    "type": self._code(employment_type),
                    "join_date": (
                        join_date.strftime("%Y-%m-%d")
                        if join_date
                        else "-"
                    ),
                    "masa_kerja": masa_kerja,

                    "report_to_number": (
                        report_to.employee_number
                        if report_to
                        else "-"
                    ),
                    "report_to_name": report_to_name,
                    "employee_username": (
                        getattr(employee_user, "username", "-")
                        if employee_user
                        else "-"
                    ),
                    "report_to_username": (
                        getattr(report_to_user, "username", "-")
                        if report_to_user
                        else "-"
                    ),
                    "employee_active": (
                        getattr(employee_user, "is_active", False)
                        if employee_user
                        else False
                    ),
                    "report_to_active": (
                        getattr(report_to_user, "is_active", False)
                        if report_to_user
                        else False
                    ),
                    "status": status,
                }
            )

        self._print_table(rows)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Total: {len(rows)} employee"
            )
        )

    def _resolve_status(
        self,
        *,
        employee_user,
        report_to,
        report_to_user,
    ):
        if employee_user is None:
            return "EMPLOYEE NO ACCOUNT"

        if not employee_user.is_active:
            return "EMPLOYEE ACCOUNT INACTIVE"

        if report_to is None:
            return "NO REPORT TO"

        if report_to_user is None:
            return "REPORT TO NO ACCOUNT"

        if not report_to_user.is_active:
            return "REPORT TO ACCOUNT INACTIVE"

        return "OK"

    def _employee_name(self, employee):
        if not employee:
            return ""

        return " ".join(
            part
            for part in [
                employee.first_name,
                employee.last_name,
            ]
            if part
        ).strip()

    def _code(self, obj):
        if obj is None:
            return "-"

        return getattr(obj, "code", str(obj))

    def _name(self, obj):
        if obj is None:
            return "-"

        return getattr(obj, "name", str(obj))

    def _print_table(self, rows):
        headers = [
            ("NO", 8),
            ("NAMA", 24),
            ("LOKASI", 14),
            ("DEPT", 12),
            ("SECTION", 18),
            ("JABATAN", 24),
            ("GROUP", 12),
            ("TYPE", 10),
            ("JOIN DATE", 12),
            ("MASA KERJA", 12),
            ("REPORT TO NO", 14),
            ("REPORT TO", 24),
            ("ACCOUNT", 22),
            ("REPORT ACCOUNT", 22),
            ("ACC", 5),
            ("RPT", 5),
            ("STATUS", 28),
        ]
        header_line = "".join(
            f"{label:<{width}}"
            for label, width in headers
        )

        self.stdout.write(header_line)
        self.stdout.write("-" * len(header_line))

        for row in rows:
            values = [
                row["employee_number"],
                row["employee_name"],
                row["location"],
                row["department"],
                row["section"],
                row["position"],
                row["group"],
                row["type"],
                row["join_date"],
                row["masa_kerja"],
                row["report_to_number"],
                row["report_to_name"],
                row["employee_username"],
                row["report_to_username"],
                "YES" if row["employee_active"] else "NO",
                "YES" if row["report_to_active"] else "NO",
                row["status"],
            ]

            line = ""

            for (label, width), value in zip(headers, values):
                text = str(value or "-")
                line += f"{text[: width - 1]:<{width}}"

            self.stdout.write(line)