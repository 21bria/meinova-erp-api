"""
Penerbitan slip gaji.

Slip **tidak menghitung apa pun**. Ia menyalin hasil run yang sudah
dikunci, lalu membekukannya sebagai dokumen. Menghitung ulang saat slip
dibuka berarti slip yang sama bisa berubah isinya setelah master
diperbaiki — persis yang dilarang Tahap 9.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.administration.api.numbering.services.numbering_service import (
    DocumentNumberService,
)
from apps.core.services.master import BaseMasterService
from apps.payroll.models import (
    PayrollComponentSource,
    PayrollComponentType,
    PayrollRunEmployee,
    PayrollRunStatus,
    Payslip,
    PayslipStatus,
)

ZERO = Decimal("0.00")

MODULE = "payroll"
DOCUMENT_TYPE = "payslip"


class PayslipService(BaseMasterService):
    model = Payslip

    @classmethod
    def get_queryset(cls):
        return (
            super()
            .get_queryset()
            .select_related(
                "employee",
                "run",
                "period",
                "company",
                "department",
                "section",
            )
        )

    # ------------------------------------------------------------------

    @staticmethod
    def build_snapshot(*, run, line: PayrollRunEmployee) -> dict:
        """
        Isi slip, dibekukan sebagai data — bukan sebagai jalan menuju
        data.

        Nama unit organisasi disalin sebagai **teks**. Departemen yang
        diganti namanya tahun depan tidak boleh mengubah slip yang
        sudah terbit; FK-nya tetap ada untuk menyaring, tapi yang
        dicetak baris ini.
        """
        employee = line.employee
        period = run.period

        def label(value):
            return getattr(value, "name", "") or ""

        components = list(
            line.components.all().order_by(
                "component_type", "sequence", "code",
            ),
        )

        def allowance_total(taxable: bool):
            return sum(
                (
                    item.amount
                    for item in components
                    if item.source
                    == PayrollComponentSource.ALLOWANCE_TEMPLATE
                    and item.is_taxable is taxable
                ),
                Decimal("0.00"),
            )

        def rows(side):
            return [
                {
                    "code": item.code,
                    "name": item.name,
                    "source": item.source,
                    "basis": item.basis,
                    "base_amount": str(item.base_amount),
                    "rate": str(item.rate),
                    "quantity": str(item.quantity),
                    "amount": str(item.amount),
                    # Klasifikasi ikut dibekukan, bukan cuma angkanya.
                    # "Kenapa tunjangan ini menambah pajak dan yang itu
                    # tidak" adalah pertanyaan yang muncul justru
                    # setahun kemudian, waktu konfigurasinya sudah
                    # berubah dan tidak ada lagi yang bisa dibaca.
                    "is_taxable": item.is_taxable,
                    "is_prorated": item.is_prorated,
                    "note": item.calculation_note,
                }
                for item in components
                if item.component_type == side
            ]

        return {
            "employee": {
                "id": employee.pk,
                "employee_number": employee.employee_number,
                "name": employee.full_name,
                "position": label(line.position),
                "join_date": str(line.join_date) if line.join_date else "",
            },
            "organization": {
                "company": label(line.company),
                "branch": label(line.branch),
                "location": label(line.location),
                "division": label(line.division),
                "department": label(line.department),
                "section": label(line.section),
                "cost_center": label(line.cost_center),
            },
            "period": {
                "id": period.pk,
                "code": period.code,
                "name": period.name,
                "start_date": str(period.start_date),
                "end_date": str(period.end_date),
                "payment_date": (
                    str(period.payment_date) if period.payment_date else ""
                ),
            },
            "run": {
                "id": run.pk,
                "document_number": run.document_number,
                "run_type": run.run_type,
            },
            "payroll": {
                "payroll_group": label(line.payroll_group),
                "salary_grade": label(line.salary_grade),
                "salary_level": label(line.salary_level),
                "tax_status": getattr(line.tax_status, "code", "") or "",
                "currency": getattr(line.currency, "code", "") or "",
                "payment_method": line.payment_method,
                # Kebijakan perhitungan yang berlaku, dibekukan bersama
                # sisanya. Tanpa ini, slip harian yang diperiksa
                # setahun kemudian tidak punya cara menjelaskan kenapa
                # upahnya dibentuk dari hari dan bukan dari gaji
                # sebulan.
                "payroll_policy": label(line.payroll_policy),
                "pay_basis": line.pay_basis,
                "daily_rate": str(line.daily_rate),
            },
            "days": {
                "period_days": line.period_days,
                "working_days": str(line.working_days),
                "paid_days": str(line.paid_days),
                "attendance_days": str(line.attendance_days),
                # BT-3: hari dinas dibayar, terpisah dari hadir fisik.
                "business_trip_days": str(line.business_trip_days),
                "absent_days": str(line.absent_days),
                "leave_days": str(line.leave_days),
                "unpaid_leave_days": str(line.unpaid_leave_days),
                "overtime_hours": str(line.overtime_hours),
                "proration_factor": str(line.proration_factor),
                "proration_method": line.proration_method,
                "proration_base_days": str(line.proration_base_days),
                # Potongan ketidakhadiran, dibekukan bersama sisanya.
                # `paid_leave_days` diturunkan di sini, bukan disimpan
                # sebagai kolom: satu angka yang bisa dihitung dari dua
                # angka lain tidak boleh punya sumber kedua.
                "paid_leave_days": str(
                    line.leave_days - line.unpaid_leave_days,
                ),
                "attendance_deduction_method": (
                    line.attendance_deduction_method
                ),
                "deduction_base_days": str(line.deduction_base_days),
                "absence_deduction": str(line.absence_deduction),
                "unpaid_leave_deduction": str(line.unpaid_leave_deduction),
            },
            "earnings": rows(PayrollComponentType.EARNING),
            "deductions": rows(PayrollComponentType.DEDUCTION),
            # Bagian tersendiri, dan sengaja bukan di dalam
            # `deductions`. Iuran yang dibayar perusahaan muncul di
            # daftar potongan terbaca sebagai uang yang dipotong dari
            # pegawai — dan jumlah kolomnya tidak lagi sama dengan
            # `total_deduction` di bawahnya.
            "employer_contributions": rows(
                PayrollComponentType.EMPLOYER_CONTRIBUTION,
            ),
            "totals": {
                "basic_salary": str(line.basic_salary),
                # Tunjangan dipisah menurut klasifikasi pajaknya.
                # Diturunkan dari komponen di atas, bukan kolom kedua
                # yang harus dijaga tetap sepakat.
                "taxable_allowance": str(allowance_total(True)),
                "non_taxable_allowance": str(allowance_total(False)),
                "gross_earning": str(line.gross_earning),
                "taxable_earning": str(line.taxable_earning),
                "total_deduction": str(line.total_deduction),
                "tax_amount": str(line.tax_amount),
                "net_pay": str(line.net_pay),
                "employer_contribution": str(line.employer_contribution),
                # Dibekukan sebagai angka, bukan dihitung ulang pembaca
                # slip. Slip yang terbit tahun lalu harus tetap
                # menjawab biayanya walau rumusnya berubah.
                "total_payroll_cost": str(
                    line.gross_earning + line.employer_contribution,
                ),
            },
        }

    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def issue_for_run(cls, *, run, user=None) -> int:
        """
        Menerbitkan slip untuk seluruh baris run.

        Idempotent: baris yang slipnya sudah ada **diperbarui**, bukan
        digandakan. Nomor slipnya tidak pernah diterbitkan ulang —
        nomor yang sudah dicetak di dokumen tidak boleh berganti hanya
        karena Finalize dijalankan dua kali.
        """
        lines = list(
            PayrollRunEmployee.objects
            .filter(run=run, is_deleted=False, is_excluded=False)
            .select_related("employee")
            .prefetch_related("components")
        )

        existing = {
            slip.run_employee_id: slip
            for slip in Payslip.objects.filter(run=run, is_deleted=False)
        }

        issued = 0
        now = timezone.now()

        for line in lines:
            slip = existing.get(line.pk)

            if slip is None:
                slip = Payslip(run_employee=line)
                slip.created_by = user
                slip.document_number = DocumentNumberService.next(
                    module=MODULE,
                    document_type=DOCUMENT_TYPE,
                    company=run.company,
                    when=run.period.start_date,
                )

            slip.run = run
            slip.period = run.period
            slip.employee = line.employee
            slip.company = line.company
            slip.branch = line.branch
            slip.location = line.location
            slip.division = line.division
            slip.department = line.department
            slip.section = line.section

            slip.issue_date = run.period.payment_date or run.period.end_date

            slip.basic_salary = line.basic_salary
            slip.gross_earning = line.gross_earning
            slip.total_deduction = line.total_deduction
            slip.tax_amount = line.tax_amount
            slip.net_pay = line.net_pay
            slip.employer_contribution = line.employer_contribution

            slip.snapshot = line.snapshot or cls.build_snapshot(
                run=run, line=line,
            )

            slip.status = PayslipStatus.PUBLISHED
            slip.published_at = slip.published_at or now
            slip.published_by = slip.published_by or user
            slip.updated_by = user

            slip.full_clean()
            slip.save()

            issued += 1

        return issued

    # ------------------------------------------------------------------

    @classmethod
    def assert_immutable(cls, instance: Payslip) -> None:
        """
        Slip tidak bisa disunting lewat API sama sekali.

        Ia dokumen hasil, bukan formulir. Yang salah diperbaiki dengan
        menerbitkan run Correction untuk periode yang sama — jalur yang
        meninggalkan jejak.
        """
        raise ValidationError(
            {
                "payslip": (
                    "Payslip tidak bisa diubah. Terbitkan payroll run "
                    "bertipe Correction untuk periode yang sama."
                ),
            },
        )

    @classmethod
    def prepare_create_data(cls, *, data, user=None, **kwargs):
        cls.assert_immutable(None)

    @classmethod
    def prepare_update_data(cls, *, instance, data, user=None, **kwargs):
        cls.assert_immutable(instance)

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs):
        if instance.run.status == PayrollRunStatus.FINALIZED:
            raise ValidationError(
                {
                    "payslip": (
                        "Slip dari run yang sudah difinalisasi tidak "
                        "bisa dihapus."
                    ),
                },
            )

        return super().before_soft_delete(instance=instance, user=user, **kwargs)
