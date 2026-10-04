# python manage.py tenant_command seed_payroll_demo --schema=demo
"""
Data peragaan payroll, bertahap dan aman diulang.

Sengaja **berhenti sebelum Finalize.** Finalize mengunci periode dan
menerbitkan slip bernomor — dokumen yang tidak bisa ditarik kembali —
dan itu keputusan orang, bukan efek samping sebuah perintah seed. Alur
sesudah Calculate (Submit → Approve → Finalize → Payslip) dijalankan
lewat layarnya, dan sudah diuji ujung ke ujung di
`apps/payroll/tests/test_payroll_flow.py`.
"""

from datetime import date

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.administration.models import Company
from apps.payroll.models import (
    AllowanceTemplate,
    DeductionTemplate,
    PayrollGroup,
    PayrollPeriod,
    PayrollRun,
    PayrollRunStatus,
)
from apps.payroll.services import PayrollRunService


class Command(BaseCommand):
    help = (
        "Membuat satu Payroll Period + Payroll Run peragaan, lalu "
        "menjalankan Generate Employees dan Calculate."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Kode company.")
        parser.add_argument(
            "--year", type=int, default=date.today().year,
        )
        parser.add_argument(
            "--month", type=int, default=date.today().month,
        )
        parser.add_argument(
            "--group", default="MONTHLY", help="Kode payroll group.",
        )
        parser.add_argument(
            "--attach-templates",
            action="store_true",
            help=(
                "Pasang Allowance/Deduction Template bawaan pada "
                "payroll assignment yang belum punya. Tanpa ini, "
                "peragaan hanya menghasilkan gaji pokok — data demo "
                "yang ada memang belum menunjuk template mana pun. "
                "Yang sudah terisi tidak pernah ditimpa."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        company = self._company(options.get("company"))

        if company is None:
            self.stderr.write(
                "Tidak ada company yang punya pegawai aktif. "
                "Seed data pegawai dulu.",
            )

            return

        group = (
            PayrollGroup.objects
            .filter(code=options["group"], is_deleted=False)
            .first()
        )

        if group is None:
            self.stderr.write(
                f"Payroll Group {options['group']} belum ada. "
                "Jalankan seed_payroll dulu.",
            )

            return

        if options.get("attach_templates"):
            attached = self._attach_templates(company)

            self.stdout.write(
                f"Template dipasang ke {attached} payroll assignment.",
            )

        year = options["year"]
        month = options["month"]

        start = date(year, month, 1)
        end = (
            date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        )
        end = date.fromordinal(end.toordinal() - 1)

        code = f"{year}-{month:02d}"

        period, created = PayrollPeriod.objects.get_or_create(
            company=company,
            payroll_group=group,
            code=code,
            is_deleted=False,
            defaults={
                "name": start.strftime("%B %Y"),
                "start_date": start,
                "end_date": end,
                "cutoff_date": end,
                "payment_date": None,
            },
        )

        self.stdout.write(
            f"Periode {period.code} "
            f"({'baru' if created else 'sudah ada'}) — "
            f"{period.start_date} s/d {period.end_date}",
        )

        run = (
            PayrollRun.objects
            .filter(
                period=period,
                is_deleted=False,
                run_type="regular",
            )
            .exclude(status=PayrollRunStatus.CANCELLED)
            .first()
        )

        if run is None:
            run = PayrollRunService.create(
                data={"period": period, "run_type": "regular"},
            )

            self.stdout.write(f"Run {run.document_number} dibuat.")
        else:
            self.stdout.write(
                f"Run {run.document_number} sudah ada "
                f"(status {run.get_status_display()}).",
            )

        if run.is_locked:
            self.stdout.write(
                self.style.WARNING(
                    "Run ini sudah difinalisasi; tidak dihitung ulang.",
                ),
            )

            return

        generated = PayrollRunService.generate_employees(run=run)

        self.stdout.write(
            f"Generate: {generated['total']} pegawai "
            f"({generated['created']} baru, "
            f"{generated['excluded']} dikeluarkan).",
        )

        result = PayrollRunService.calculate(run=run)

        run.refresh_from_db()

        counts = result["validation"]["counts"]

        self.stdout.write(
            f"Calculate: {result['calculated']} dihitung, "
            f"{result['failed']} gagal.",
        )
        self.stdout.write(
            f"Total earning {run.total_earning}, "
            f"deduction {run.total_deduction}, "
            f"tax {run.total_tax}, net {run.total_net}.",
        )
        self.stdout.write(
            f"Validasi: {counts['errors']} error, "
            f"{counts['warnings']} warning.",
        )

        for item in result["validation"]["errors"][:5]:
            self.stdout.write(self.style.ERROR(f"  ERROR  {item['message']}"))

        for item in result["validation"]["warnings"][:5]:
            self.stdout.write(
                self.style.WARNING(f"  WARN   {item['message']}"),
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Selesai sampai Review. Lanjutkan Submit → Approve → "
                "Finalize dari layar Payroll Run.",
            ),
        )

    @staticmethod
    def _attach_templates(company) -> int:
        """
        Mengisi template yang **kosong**, tidak menimpa yang sudah ada.

        Assignment yang sudah menunjuk template tertentu adalah
        keputusan yang pernah diambil seseorang; peragaan tidak berhak
        menggantinya.
        """
        from apps.hr.models import PayrollAssignment

        allowance = (
            AllowanceTemplate.objects
            .filter(code="STANDARD", is_deleted=False)
            .first()
        )
        deduction = (
            DeductionTemplate.objects
            .filter(code="STANDARD", is_deleted=False)
            .first()
        )

        if allowance is None or deduction is None:
            return 0

        queryset = PayrollAssignment.objects.filter(
            employee__organization__company=company,
            is_deleted=False,
        )

        return (
            queryset
            .filter(
                allowance_template__isnull=True,
                deduction_template__isnull=True,
            )
            .update(
                allowance_template=allowance,
                deduction_template=deduction,
            )
        )

    @staticmethod
    def _company(code):
        queryset = Company.objects.filter(is_deleted=False)

        if code:
            return queryset.filter(code=code).first()

        # Company dengan pegawai aktif terbanyak. Peragaan yang mendarat
        # di perusahaan kosong tidak memperagakan apa pun.
        from django.db.models import Count, Q

        return (
            queryset
            .annotate(
                headcount=Count(
                    "employee_organizations",
                    filter=Q(
                        employee_organizations__employee__is_deleted=False,
                        employee_organizations__employee__is_active=True,
                    ),
                ),
            )
            .order_by("-headcount")
            .first()
        )
