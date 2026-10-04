# python manage.py tenant_command payroll_uat --schema=demo
"""
UAT payroll: empat pegawai, dijalankan ujung ke ujung, dicetak
rinciannya sampai rupiah terakhir.

Bukan pengganti test otomatis (`apps/payroll/tests/`) melainkan
pelengkapnya: test membuktikan aturannya jalan, perintah ini
memperlihatkan **angkanya** di atas data yang bisa dibuka orang di
layar dan dicocokkan dengan hitungan tangan.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.core.exceptions import ValidationError
from django.db.models import Q

from apps.accounts.models import AuthorityMode, DataScopeLevel
from apps.accounts.services.role_assignment import grant_role
from apps.payroll.models import (
    PayrollComponentType,
    PayrollRun,
    PayrollRunEmployee,
    PayrollRunEmployeeStatus,
    PayrollRunStatus,
    PayrollTaxBracket,
    Payslip,
)
from apps.payroll.seeds import payroll_uat as uat
from apps.payroll.services import PayrollRunService


LINE = "-" * 78


def rupiah(value) -> str:
    return f"{Decimal(value or 0):,.2f}".replace(",", "_").replace(
        ".", ",",
    ).replace("_", ".")


class Command(BaseCommand):
    help = (
        "Menyiapkan dan menjalankan UAT payroll 4 pegawai, lalu "
        "mencetak breakdown perhitungannya."
    )

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Kode company.")
        parser.add_argument(
            "--month",
            type=int,
            default=6,
            choices=[6, 7],
            help="6 = periode Juni (bawaan), 7 = periode Juli.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Hapus seluruh data UAT lalu berhenti.",
        )
        parser.add_argument(
            "--role-setup",
            action="store_true",
            help=(
                "Berikan role FINANCE-MANAGER kepada pegawai yang "
                "jabatannya memang Finance Manager, supaya alur "
                "persetujuan payroll punya approver."
            ),
        )
        parser.add_argument(
            "--approve",
            action="store_true",
            help=(
                "Lanjutkan sampai APPROVED: keluarkan pegawai yang "
                "ERROR, akui peringatan, ajukan, lalu setujui tiap "
                "meja atas nama approver-nya."
            ),
        )
        parser.add_argument(
            "--finalize",
            action="store_true",
            help="Finalisasi run yang sudah APPROVED dan terbitkan slip.",
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        if options["reset"]:
            removed = uat.reset()

            self.stdout.write(
                self.style.SUCCESS(
                    f"Data UAT dihapus: {removed['employees']} pegawai, "
                    f"{removed['periods']} periode, "
                    f"{removed['runs']} run.",
                ),
            )

            return

        company = uat.target_company(options.get("company"))

        if company is None:
            self.stderr.write("Tidak ada company. Seed organisasi dulu.")

            return

        if options["role_setup"]:
            self._role_setup(company)

        period_range = uat.JUNE if options["month"] == 6 else uat.JULY

        masters = uat.build_masters(company=company)

        if masters["payroll_group"] is None or masters["currency"] is None:
            self.stderr.write(
                "Payroll Group / Currency belum ada. Jalankan "
                "seed_payroll dan seed_administration dulu.",
            )

            return

        uat.build_employees(masters=masters)
        counts = uat.build_transactions(
            masters=masters, period_range=period_range,
        )
        period = uat.ensure_period(masters=masters, period_range=period_range)
        inputs = uat.build_inputs(period=period)

        self._header("SETUP")
        self.stdout.write(
            f"Company        : {company.code} — {company.name}\n"
            f"Section         : {masters['section'].code}\n"
            f"Periode         : {period.code} "
            f"({period.start_date} s/d {period.end_date}), "
            f"pembagi {period.divisor_days} hari\n"
            f"Master UAT      : {masters['allowance'].code} / "
            f"{masters['deduction'].code} / "
            f"{masters['overtime_group'].code}\n"
            f"Tax bracket     : {masters['brackets']} lapis, PTKP "
            f"{rupiah(masters['tax_status'].non_taxable_income)}\n"
            f"Transaksi       : {counts['attendance']} absensi, "
            f"{counts['overtime']} lembur, {counts['leave']} cuti, "
            f"{inputs} payroll input",
        )

        run = self._ensure_run(period=period, masters=masters)

        # Run yang sudah keluar dari tahap penyuntingan tidak dihitung
        # ulang. Perintah ini dijalankan berkali-kali dengan bendera
        # berbeda (--approve, lalu --finalize), dan menghitung ulang di
        # tengah alur persetujuan adalah persis yang dilarang service-nya.
        if not run.is_editable:
            self.stdout.write(
                self.style.WARNING(
                    f"\nRun {run.document_number} berstatus "
                    f"{run.get_status_display()} — tidak dihitung "
                    "ulang. Pakai --reset untuk mulai dari awal.",
                ),
            )
        else:
            generated = PayrollRunService.generate_employees(run=run)
            result = PayrollRunService.calculate(run=run)

            self.stdout.write(
                f"\nGenerate        : {generated['total']} pegawai\n"
                f"Calculate       : {result['calculated']} dihitung, "
                f"{result['failed']} gagal",
            )

        run.refresh_from_db()

        self._breakdown(run)
        self._validation(run)

        if options["approve"]:
            self._approve(run)

        if options["finalize"]:
            self._finalize(run)
            self._reconcile(run)

    # ------------------------------------------------------------------

    def _header(self, title):
        self.stdout.write(f"\n{LINE}\n{title}\n{LINE}")

    def _ensure_run(self, *, period, masters):
        run = (
            PayrollRun.objects
            .filter(period=period, is_deleted=False)
            .exclude(status=PayrollRunStatus.CANCELLED)
            .first()
        )

        if run is not None:
            return run

        return PayrollRunService.create(
            data={
                "period": period,
                "run_type": "regular",
                "name": "UAT Payroll Run",
                # Disempitkan ke section UAT supaya 26 pegawai peragaan
                # tidak ikut terhitung.
                "section": masters["section"],
                "department": masters["department"],
            },
        )

    # ------------------------------------------------------------------
    # Breakdown
    # ------------------------------------------------------------------

    def _breakdown(self, run):
        cases = {person["number"]: person["case"] for person in uat.PEOPLE}

        lines = (
            PayrollRunEmployee.objects
            .filter(run=run, is_deleted=False)
            .select_related("employee", "overtime_group", "tax_status")
            .prefetch_related("components")
            .order_by("employee__employee_number")
        )

        for line in lines:
            number = line.employee.employee_number

            self._header(f"{number}  {line.employee.full_name}")
            self.stdout.write(f"Kasus           : {cases.get(number, '-')}")
            self.stdout.write(
                f"Status          : {line.get_status_display()}"
                + ("  [EXCLUDED]" if line.is_excluded else ""),
            )
            self.stdout.write(
                f"Basic Salary    : {rupiah(line.basic_salary)}   "
                f"(prorata {line.proration_factor})",
            )
            self.stdout.write(
                f"Hari            : hadir {line.attendance_days}, "
                f"absen {line.absent_days}, cuti {line.leave_days} "
                f"(tidak dibayar {line.unpaid_leave_days}), "
                f"lembur {line.overtime_hours} jam",
            )

            self._components(line, PayrollComponentType.EARNING, "EARNINGS")
            self._components(
                line, PayrollComponentType.DEDUCTION, "DEDUCTIONS",
            )

            self.stdout.write(
                f"\n  {'Gross Pay':<34}{rupiah(line.gross_earning):>18}"
                f"\n  {'Taxable Earning':<34}"
                f"{rupiah(line.taxable_earning):>18}"
                f"\n  {'Total Deduction':<34}"
                f"{rupiah(line.total_deduction):>18}"
                f"\n  {'  di antaranya pajak':<34}"
                f"{rupiah(line.tax_amount):>18}"
                f"\n  {'NET PAY':<34}{rupiah(line.net_pay):>18}",
            )

            if line.findings:
                self.stdout.write("\n  Temuan:")

                for item in line.findings:
                    style = (
                        self.style.ERROR
                        if item.get("level") == "error"
                        else self.style.WARNING
                    )

                    self.stdout.write(
                        style(
                            f"    [{item.get('level', '?').upper():7}] "
                            f"{item.get('message', '')}",
                        ),
                    )

    def _components(self, line, side, title):
        rows = [
            component
            for component in line.components.all()
            if component.component_type == side
        ]

        if not rows:
            self.stdout.write(f"\n  {title}: (tidak ada)")

            return

        self.stdout.write(f"\n  {title}")
        self.stdout.write(
            f"    {'code':<16}{'source':<20}{'qty':>8}"
            f"{'rate':>16}{'amount':>16}",
        )

        for component in sorted(rows, key=lambda r: (r.sequence, r.code)):
            self.stdout.write(
                f"    {component.code:<16}{component.source:<20}"
                f"{component.quantity:>8}"
                f"{rupiah(component.rate):>16}"
                f"{rupiah(component.amount):>16}",
            )

            if component.calculation_note:
                self.stdout.write(f"      ↳ {component.calculation_note}")

    def _validation(self, run):
        summary = run.validation_summary or {}
        counts = summary.get("counts", {})

        self._header("VALIDASI RUN")
        self.stdout.write(
            f"{counts.get('employees', 0)} pegawai, "
            f"{counts.get('excluded', 0)} dikeluarkan, "
            f"{counts.get('errors', 0)} error, "
            f"{counts.get('warnings', 0)} warning",
        )

        for item in summary.get("errors", []):
            self.stdout.write(self.style.ERROR(f"  ERROR  {item['message']}"))

        for item in summary.get("warnings", []):
            self.stdout.write(
                self.style.WARNING(f"  WARN   {item['message']}"),
            )

        self.stdout.write(
            f"\nTotal run: earning {rupiah(run.total_earning)}, "
            f"deduction {rupiah(run.total_deduction)}, "
            f"pajak {rupiah(run.total_tax)}, "
            f"net {rupiah(run.total_net)}",
        )

    # ------------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------------

    def _role_setup(self, company):
        """
        Memberi role FINANCE-MANAGER kepada orang yang **jabatannya**
        memang Finance Manager.

        Bukan user karangan dan bukan nama yang ditanam di kode: yang
        dicari pemegang posisi bernama "Finance Manager" di company itu,
        lalu role yang sudah diseed `seed_workflows` dipasang ke akunnya.
        Kalau tidak ada, perintahnya menyebutkannya dan berhenti —
        approver payroll adalah keputusan organisasi, bukan sesuatu yang
        boleh ditebak seed.
        """
        from apps.accounts.models import Role
        from apps.hr.models import Employee

        self._header("SETUP APPROVER")

        role = Role.objects.filter(
            code="FINANCE-MANAGER", is_deleted=False,
        ).first()

        if role is None:
            self.stderr.write(
                "Role FINANCE-MANAGER belum ada. Jalankan "
                "seed_workflows dulu.",
            )

            return

        candidate = (
            Employee.objects
            .filter(
                organization__company=company,
                user__isnull=False,
                is_deleted=False,
            )
            .filter(
                Q(organization__position__name__icontains="finance manager")
                | Q(organization__position__code__icontains="fin-mgr"),
            )
            .select_related("user", "organization__position")
            .first()
        )

        if candidate is None:
            self.stderr.write(
                self.style.WARNING(
                    "Tidak ada pegawai ber-akun yang jabatannya Finance "
                    "Manager di company ini. Isi dulu penempatannya — "
                    "siapa yang menyetujui payroll adalah keputusan "
                    "organisasi, bukan tebakan seed.",
                ),
            )

            return

        # **WHERE-nya disebut, bukan diturunkan dari `Role`.**
        # Perintah ini memilih penerimanya justru karena penempatannya —
        # Finance Manager di company ini — jadi cakupan yang benar
        # adalah penempatan orangnya sendiri, sedalam company. Itu juga
        # yang membuatnya tetap benar kalau dijalankan di company lain.
        grant_role(
            candidate.user,
            role,
            mode=AuthorityMode.PLACEMENT,
            level=DataScopeLevel.COMPANY,
        )

        self.stdout.write(
            f"Role FINANCE-MANAGER → {candidate.employee_number} "
            f"{candidate.full_name} "
            f"({candidate.organization.position.name}, akun "
            f"{candidate.user.username})",
        )

    def _approve(self, run):
        from apps.workflow.models import InstanceStatus
        from apps.workflow.registry import completion_handler
        from apps.workflow.services import WorkflowService

        self._header("APPROVAL")

        run.refresh_from_db()

        if run.status == PayrollRunStatus.REVIEW:
            excluded = self._exclude_blocking(run)

            if excluded:
                self.stdout.write(
                    f"{excluded} pegawai dikeluarkan dari run karena "
                    "konfigurasinya belum lengkap (alasannya tercatat "
                    "di barisnya).",
                )

            PayrollRunService._refresh_totals(run=run)
            summary = PayrollRunService.validate(run=run)

            self.stdout.write(
                f"Validasi ulang: {summary['counts']['errors']} error, "
                f"{summary['counts']['warnings']} warning",
            )

            if summary["warnings"]:
                PayrollRunService.acknowledge(run=run)
                self.stdout.write("Peringatan diakui.")

            try:
                PayrollRunService.submit(run=run)
            except ValidationError as error:
                self.stderr.write(
                    self.style.ERROR(
                        f"Submit gagal: {error.message_dict}",
                    ),
                )

                return

            run.refresh_from_db()

            self.stdout.write(f"Submit OK → status {run.status}")

        instance = WorkflowService.instance_for(
            document=run, module="payroll", document_type="payroll_run",
        )

        if instance is None:
            self.stdout.write("Tidak ada pengajuan aktif.")

            return

        handler = completion_handler(
            module="payroll", document_type="payroll_run",
        )

        guard = 0

        while instance.status == InstanceStatus.PENDING and guard < 10:
            guard += 1

            row = (
                instance.approvals
                .filter(
                    status="pending",
                    step_id=instance.current_step_id,
                )
                .select_related("approver", "step")
                .first()
            )

            if row is None or row.approver is None:
                self.stderr.write(
                    self.style.ERROR(
                        "Meja berikutnya tidak punya approver.",
                    ),
                )

                break

            try:
                WorkflowService.approve(
                    instance=instance,
                    user=row.approver,
                    comment="Disetujui (UAT).",
                    on_complete=handler,
                )
            except ValidationError as error:
                self.stderr.write(
                    self.style.ERROR(
                        f"  Meja #{row.sequence} {row.step.name} gagal: "
                        f"{error.message_dict}",
                    ),
                )

                break

            self.stdout.write(
                f"  Meja #{row.sequence} {row.step.name} → disetujui "
                f"{row.approver.username}",
            )

            instance.refresh_from_db()

        run.refresh_from_db()

        self.stdout.write(
            f"Alur {instance.definition.code} selesai: "
            f"{instance.status}. Status run: {run.status}",
        )

        if run.status == PayrollRunStatus.APPROVED:
            self.stdout.write(
                self.style.SUCCESS(
                    "Approve TIDAK otomatis Finalize — slip belum "
                    "terbit dan periodenya belum dikunci.",
                ),
            )

    def _exclude_blocking(self, run) -> int:
        """
        Mengeluarkan pegawai yang konfigurasinya belum lengkap.

        Ini **jalan keluar bisnisnya**, bukan bypass validasi: barisnya
        tetap ada beserta alasannya, dan pegawainya tidak ikut dibayar.
        Yang dilarang adalah membiarkannya lolos diam-diam.
        """
        blocking = PayrollRunEmployee.objects.filter(
            run=run,
            is_deleted=False,
            is_excluded=False,
            payroll_assignment__isnull=True,
        )

        return blocking.update(
            is_excluded=True,
            status=PayrollRunEmployeeStatus.EXCLUDED,
            exclusion_reason=(
                "Belum punya Payroll Assignment yang berlaku pada "
                "periode ini. Dikeluarkan dari run; harus dilengkapi "
                "sebelum bisa dibayar."
            ),
        )

    # ------------------------------------------------------------------
    # Finalize & rekonsiliasi
    # ------------------------------------------------------------------

    def _finalize(self, run):
        self._header("FINALIZE")

        run.refresh_from_db()

        if run.status == PayrollRunStatus.FINALIZED:
            self.stdout.write("Run sudah FINALIZED.")

            return

        try:
            result = PayrollRunService.finalize(run=run)
        except ValidationError as error:
            self.stderr.write(
                self.style.ERROR(f"Finalize ditolak: {error.message_dict}"),
            )

            return

        run.refresh_from_db()

        self.stdout.write(
            self.style.SUCCESS(
                f"Run dikunci. {result['employees']} pegawai, "
                f"{result['payslips']} slip terbit. "
                f"Periode: {run.period.get_status_display()}",
            ),
        )

    def _reconcile(self, run):
        self._header("REKONSILIASI PAYSLIP")

        slips = (
            Payslip.objects
            .filter(run=run, is_deleted=False)
            .select_related("employee", "run_employee")
            .order_by("employee__employee_number")
        )

        if not slips:
            self.stdout.write("Belum ada slip.")

            return

        self.stdout.write(
            f"  {'employee':<12}{'slip':<18}{'run net':>18}"
            f"{'slip net':>18}  cocok",
        )

        for slip in slips:
            line = slip.run_employee

            matched = line.net_pay == slip.net_pay

            snapshot_codes = {
                row["code"]
                for row in (
                    slip.snapshot.get("earnings", [])
                    + slip.snapshot.get("deductions", [])
                )
            }

            component_codes = set(
                line.components.values_list("code", flat=True),
            )

            self.stdout.write(
                f"  {slip.employee.employee_number:<12}"
                f"{slip.document_number:<18}"
                f"{rupiah(line.net_pay):>18}{rupiah(slip.net_pay):>18}"
                f"  {'YA' if matched else 'TIDAK'}"
                f"  komponen {'sama' if snapshot_codes == component_codes else 'BEDA'}",
            )
