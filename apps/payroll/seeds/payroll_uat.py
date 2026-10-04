"""
Data UAT payroll: empat pegawai, angka bulat, bisa dicek tangan.

**Kenapa terpisah dari `seed_payroll_demo`.** Yang itu menjalankan
payroll atas 26 pegawai peragaan — berguna untuk melihat modulnya
bekerja, tidak berguna untuk membuktikan angkanya benar. Dua puluh enam
baris tidak bisa dicocokkan manual, dan yang tidak bisa dicocokkan
manual tidak bisa dinyatakan benar.

Empat pegawai, masing-masing satu keadaan:

| | keadaan | yang diuji |
| --- | --- | --- |
| UATA | normal, hadir penuh | gaji pokok + tunjangan + iuran + pajak |
| UATB | lembur + input earning | pembagi & pengali dari master, input manual |
| UATC | absen + cuti tidak dibayar + input potongan | potongan harian, adapter cuti |
| UATD | tanpa payroll assignment | ERROR yang mengunci Finalize |

**Seluruh nominalnya data UAT, bukan kebijakan perusahaan.** Ia dipilih
bulat supaya hasilnya bisa dihitung di kepala; berapa tunjangan
transport yang sebenarnya adalah keputusan perusahaan. Master UAT diberi
kode berawalan `UAT-` supaya tidak pernah tertukar dengan master
sungguhan, dan seluruhnya bisa dihapus lagi lewat `--reset`.

Cakupannya satu **section** tersendiri di dalam company yang sudah ada,
bukan company baru: approver alur payroll dicari per company, dan
company karangan berarti approver karangan juga. Section-nya yang
menyaring supaya run UAT tidak menarik 26 pegawai peragaan.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Count, Q

from apps.administration.models import (
    Company,
    Currency,
    Department,
    LeaveType,
    Location,
    Section,
)
from apps.hr.models import (
    Employee,
    EmployeeAttendance,
    EmployeeLeave,
    EmployeeOvertime,
    EmploymentAssignment,
    OrganizationAssignment,
    PayrollAssignment,
)
from apps.hr.models.attendance import AttendanceStatus
from apps.hr.models.leave import LeaveStatus
from apps.hr.models.overtime import OvertimeStatus
from apps.payroll.models import (
    AllowanceTemplate,
    AllowanceTemplateLine,
    DeductionTemplate,
    DeductionTemplateLine,
    OvertimeGroup,
    PayrollBasis,
    PayrollGroup,
    PayrollInput,
    PayrollInputStatus,
    PayrollInputType,
    PayrollLeaveRule,
    PayrollPeriod,
    PayrollRun,
    PayrollTaxBracket,
    TaxStatus,
)


PREFIX = "UAT-"

DEPARTMENT_CODE = "UAT-PAY"
SECTION_CODE = "UAT-PAY-SEC"

ALLOWANCE_CODE = "UAT-ALW"
DEDUCTION_CODE = "UAT-DED"
OVERTIME_CODE = "UAT-OT"
LEAVE_TYPE_CODE = "UAT-UNPAID"

BASIC_SALARY = Decimal("10000000")

# Periode uji dipatok, bukan "bulan ini": angka yang berubah tiap kali
# perintahnya dijalankan tidak bisa dibandingkan dengan hitungan tangan
# yang ditulis kemarin. Juni 30 hari, Juli 31 — selisih itu sendiri
# yang membuktikan pembagi harian ikut periodenya.
JUNE = (date(2026, 6, 1), date(2026, 6, 30))
JULY = (date(2026, 7, 1), date(2026, 7, 31))


# ----------------------------------------------------------------------
# Master UAT
# ----------------------------------------------------------------------

ALLOWANCE_LINES = [
    {
        "code": "UAT-POSITION",
        "name": "UAT Position Allowance",
        "sequence": 10,
        "basis": PayrollBasis.PERCENT_OF_BASIC,
        "rate": Decimal("10"),
        "is_taxable": True,
        "is_prorated": True,
    },
    {
        "code": "UAT-MEAL",
        "name": "UAT Meal Allowance",
        "sequence": 20,
        "basis": PayrollBasis.PER_ATTENDANCE_DAY,
        "amount": Decimal("30000"),
        "is_taxable": True,
        "is_prorated": False,
    },
    {
        "code": "UAT-TRANSPORT",
        "name": "UAT Transport Allowance",
        "sequence": 30,
        "basis": PayrollBasis.PER_ATTENDANCE_DAY,
        "amount": Decimal("25000"),
        "is_taxable": True,
        "is_prorated": False,
    },
    {
        "code": "UAT-COMM",
        "name": "UAT Communication Allowance",
        "sequence": 40,
        "basis": PayrollBasis.FIXED,
        "amount": Decimal("300000"),
        "is_taxable": True,
        "is_prorated": True,
    },
]

DEDUCTION_LINES = [
    {
        "code": "UAT-BPJS-KES",
        "name": "UAT BPJS Kesehatan (1%)",
        "sequence": 10,
        "basis": PayrollBasis.PERCENT_OF_BASIC,
        "rate": Decimal("1"),
        "maximum_base": Decimal("12000000"),
        "reduces_taxable": True,
    },
    {
        "code": "UAT-BPJS-JHT",
        "name": "UAT BPJS JHT (2%)",
        "sequence": 20,
        "basis": PayrollBasis.PERCENT_OF_BASIC,
        "rate": Decimal("2"),
        "reduces_taxable": True,
    },
    {
        "code": "UAT-PPH21",
        "name": "UAT PPh 21",
        "sequence": 90,
        "basis": PayrollBasis.PPH21_PROGRESSIVE,
    },
]


# ----------------------------------------------------------------------
# Pegawai UAT
# ----------------------------------------------------------------------

PEOPLE = [
    {
        "number": "UATA001",
        "first_name": "UAT",
        "last_name": "Alpha (Normal)",
        "case": "A — Normal, hadir penuh",
        "with_assignment": True,
        "attendance_present": 20,
        "attendance_absent": 0,
        "overtime_minutes": 0,
        "unpaid_leave_days": 0,
        "inputs": [],
    },
    {
        "number": "UATB002",
        "first_name": "UAT",
        "last_name": "Bravo (Overtime)",
        "case": "B — Lembur + input earning manual",
        "with_assignment": True,
        "overtime_eligible": True,
        "attendance_present": 20,
        "attendance_absent": 0,
        # 10 jam. Bulat supaya upah sejamnya bisa dicek tangan.
        "overtime_minutes": 600,
        "unpaid_leave_days": 0,
        "inputs": [
            {
                "input_type": PayrollInputType.INCENTIVE,
                "code": "UAT-INCENTIVE",
                "name": "UAT Insentif Proyek",
                "amount": Decimal("1500000"),
                "is_taxable": True,
                "notes": "Data UAT: membuktikan input earning ikut dihitung.",
            },
        ],
    },
    {
        "number": "UATC003",
        "first_name": "UAT",
        "last_name": "Charlie (Leave)",
        "case": "C — Absen + cuti tidak dibayar + input potongan",
        "with_assignment": True,
        "attendance_present": 18,
        "attendance_absent": 2,
        "overtime_minutes": 0,
        "unpaid_leave_days": 3,
        "inputs": [
            {
                "input_type": PayrollInputType.DEDUCTION,
                "code": "UAT-LOAN",
                "name": "UAT Cicilan Pinjaman",
                "amount": Decimal("500000"),
                "is_taxable": False,
                "notes": "Data UAT: membuktikan input potongan ikut dihitung.",
            },
        ],
    },
    {
        "number": "UATD004",
        "first_name": "UAT",
        "last_name": "Delta (No Assignment)",
        "case": "D — Tanpa payroll assignment (harus ERROR)",
        "with_assignment": False,
        "attendance_present": 20,
        "attendance_absent": 0,
        "overtime_minutes": 0,
        "unpaid_leave_days": 0,
        "inputs": [],
    },
]


# ----------------------------------------------------------------------
# Penyusunan
# ----------------------------------------------------------------------


def target_company(code: str | None = None) -> Company | None:
    queryset = Company.objects.filter(is_deleted=False)

    if code:
        return queryset.filter(code=code).first()

    # Company dengan pegawai aktif terbanyak: di situlah approver alur
    # payroll punya kemungkinan terbesar sudah ada.
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


@transaction.atomic
def build_masters(*, company: Company) -> dict:
    """
    Master UAT. Berkode `UAT-` dan berdiri sendiri.

    Sengaja **tidak** memakai master peragaan yang sudah ada: angka di
    sana boleh disunting siapa saja lewat layarnya, dan UAT yang
    hasilnya bergeser karena orang lain mengubah satu baris master tidak
    membuktikan apa pun.
    """
    location = (
        Location.objects.filter(company=company, is_deleted=False).first()
    )

    department, _ = Department.objects.get_or_create(
        company=company,
        code=DEPARTMENT_CODE,
        defaults={"name": "UAT Payroll", "location": location},
    )

    section, _ = Section.objects.get_or_create(
        company=company,
        code=SECTION_CODE,
        defaults={
            "name": "UAT Payroll Section",
            "department": department,
            "location": location,
        },
    )

    allowance, _ = AllowanceTemplate.objects.get_or_create(
        code=ALLOWANCE_CODE,
        is_deleted=False,
        defaults={
            "name": "UAT Allowance Package",
            "description": (
                "Paket tunjangan untuk UAT. Nominalnya data uji, bukan "
                "kebijakan perusahaan."
            ),
        },
    )

    deduction, _ = DeductionTemplate.objects.get_or_create(
        code=DEDUCTION_CODE,
        is_deleted=False,
        defaults={
            "name": "UAT Deduction Package",
            "description": (
                "Paket potongan untuk UAT. Persentase dan plafonnya "
                "data uji, bukan kebijakan perusahaan."
            ),
        },
    )

    for row in ALLOWANCE_LINES:
        payload = dict(row)

        AllowanceTemplateLine.objects.update_or_create(
            template=allowance,
            code=payload.pop("code"),
            is_deleted=False,
            defaults={**payload, "is_active": True},
        )

    for row in DEDUCTION_LINES:
        payload = dict(row)

        DeductionTemplateLine.objects.update_or_create(
            template=deduction,
            code=payload.pop("code"),
            is_deleted=False,
            defaults={**payload, "is_active": True},
        )

    overtime_group, _ = OvertimeGroup.objects.get_or_create(
        code=OVERTIME_CODE,
        is_deleted=False,
        defaults={
            "name": "UAT Overtime",
            "hourly_multiplier": Decimal("1.5"),
            "hourly_divisor": Decimal("173"),
        },
    )

    leave_type, _ = LeaveType.objects.get_or_create(
        code=LEAVE_TYPE_CODE,
        defaults={"name": "UAT Cuti Tanpa Gaji"},
    )

    PayrollLeaveRule.objects.update_or_create(
        leave_type=leave_type,
        is_deleted=False,
        defaults={
            "is_unpaid": True,
            "is_active": True,
            "notes": "Aturan UAT: jenis cuti ini memotong gaji.",
        },
    )

    payroll_group = (
        PayrollGroup.objects.filter(code="MONTHLY", is_deleted=False).first()
        or PayrollGroup.objects.filter(is_deleted=False).first()
    )

    tax_status = (
        TaxStatus.objects.filter(code="TK/0", is_deleted=False).first()
        or TaxStatus.objects.filter(is_deleted=False).first()
    )

    currency = (
        Currency.objects.filter(code="IDR", is_deleted=False).first()
        or Currency.objects.filter(is_deleted=False).first()
    )

    return {
        "company": company,
        "location": location,
        "department": department,
        "section": section,
        "allowance": allowance,
        "deduction": deduction,
        "overtime_group": overtime_group,
        "leave_type": leave_type,
        "payroll_group": payroll_group,
        "tax_status": tax_status,
        "currency": currency,
        "brackets": PayrollTaxBracket.objects.filter(
            is_deleted=False, is_active=True,
        ).count(),
    }


@transaction.atomic
def build_employees(*, masters: dict) -> list[Employee]:
    employees = []

    for person in PEOPLE:
        employee, _ = Employee.objects.update_or_create(
            employee_number=person["number"],
            is_deleted=False,
            defaults={
                "first_name": person["first_name"],
                "last_name": person["last_name"],
                "is_active": True,
            },
        )

        OrganizationAssignment.objects.update_or_create(
            employee=employee,
            defaults={
                "company": masters["company"],
                "location": masters["location"],
                "department": masters["department"],
                "section": masters["section"],
                "organization_effective_date": date(2025, 1, 1),
            },
        )

        EmploymentAssignment.objects.update_or_create(
            employee=employee,
            defaults={"join_date": date(2025, 1, 1)},
        )

        if person["with_assignment"]:
            _ensure_assignment(
                employee=employee,
                masters=masters,
                effective_from=date(2025, 1, 1),
                basic_salary=BASIC_SALARY,
                overtime_eligible=person.get("overtime_eligible", False),
            )

        employees.append(employee)

    return employees


def _ensure_assignment(
    *,
    employee,
    masters,
    effective_from,
    basic_salary,
    overtime_eligible=False,
    allowance_template=None,
):
    """
    Baris `PayrollAssignment` awal, dibuat **hanya kalau belum ada**.

    Dua hal yang sengaja tidak dilakukan:

    * **Tidak lewat `PayrollAssignmentService.create`.** Service itu
      menutup baris sebelumnya dan menuntut `effective_from` yang lebih
      baru, jadi seed yang dijalankan dua kali akan menumpuk riwayat
      palsu. Effective date-nya diuji tersendiri, lewat service yang
      sebenarnya.
    * **Tidak menyentuh riwayat yang sudah ada.** Kalau pegawai UAT
      sudah dinaikkan gajinya untuk periode berikutnya, seed yang
      memaksa `is_current=True` pada baris 2025 akan menabrak
      `uniq_current_employee_payroll_assignment` — dan kalau lolos, ia
      justru membatalkan perubahan yang sedang diuji.
    """
    existing = (
        PayrollAssignment.objects
        .filter(employee=employee, is_deleted=False)
        .order_by("-effective_from")
        .first()
    )

    if existing is not None:
        return existing, False

    return PayrollAssignment.objects.update_or_create(
        employee=employee,
        effective_from=effective_from,
        defaults={
            "payroll_group": masters["payroll_group"],
            "currency": masters["currency"],
            "tax_status": masters["tax_status"],
            "overtime_eligible": overtime_eligible,
            "overtime_group": (
                masters["overtime_group"] if overtime_eligible else None
            ),
            "basic_salary": basic_salary,
            "allowance_template": allowance_template or masters["allowance"],
            "deduction_template": masters["deduction"],
            "is_current": True,
            "effective_to": None,
        },
    )


@transaction.atomic
def build_transactions(*, masters: dict, period_range: tuple) -> dict:
    """
    Absensi, lembur, dan cuti untuk periode uji.

    Ditulis ulang tiap kali (hapus lalu buat): UAT yang barisnya
    menumpuk dari run sebelumnya menghasilkan angka yang berbeda tiap
    dijalankan, dan itu justru yang mau dihindari.
    """
    start, end = period_range

    counts = {"attendance": 0, "overtime": 0, "leave": 0}

    for person in PEOPLE:
        employee = Employee.objects.filter(
            employee_number=person["number"], is_deleted=False,
        ).first()

        if employee is None:
            continue

        EmployeeAttendance.objects.filter(
            employee=employee, work_date__gte=start, work_date__lte=end,
        ).delete()
        EmployeeOvertime.objects.filter(
            employee=employee, work_date__gte=start, work_date__lte=end,
        ).delete()
        EmployeeLeave.objects.filter(
            employee=employee, start_date__gte=start, end_date__lte=end,
        ).delete()

        day = start

        for _ in range(person["attendance_present"]):
            EmployeeAttendance.objects.create(
                employee=employee,
                company=masters["company"],
                location=masters["location"],
                work_date=day,
                status=AttendanceStatus.PRESENT,
            )
            counts["attendance"] += 1
            day += timedelta(days=1)

        for _ in range(person["attendance_absent"]):
            EmployeeAttendance.objects.create(
                employee=employee,
                company=masters["company"],
                location=masters["location"],
                work_date=day,
                status=AttendanceStatus.ABSENT,
            )
            counts["attendance"] += 1
            day += timedelta(days=1)

        if person["overtime_minutes"]:
            EmployeeOvertime.objects.create(
                employee=employee,
                company=masters["company"],
                location=masters["location"],
                work_date=start + timedelta(days=9),
                start_time="18:00",
                end_time="23:00",
                duration_minutes=person["overtime_minutes"],
                status=OvertimeStatus.APPROVED,
                is_paid=True,
                reason="Data UAT",
            )
            counts["overtime"] += 1

        if person["unpaid_leave_days"]:
            leave_start = start + timedelta(days=20)

            EmployeeLeave.objects.create(
                employee=employee,
                company=masters["company"],
                location=masters["location"],
                leave_type=masters["leave_type"],
                start_date=leave_start,
                end_date=leave_start
                + timedelta(days=person["unpaid_leave_days"] - 1),
                total_days=Decimal(person["unpaid_leave_days"]),
                status=LeaveStatus.APPROVED,
                notes="Data UAT",
            )
            counts["leave"] += 1

    return counts


@transaction.atomic
def build_inputs(*, period: PayrollPeriod) -> int:
    created = 0

    for person in PEOPLE:
        employee = Employee.objects.filter(
            employee_number=person["number"], is_deleted=False,
        ).first()

        if employee is None:
            continue

        for row in person["inputs"]:
            payload = dict(row)

            PayrollInput.objects.update_or_create(
                period=period,
                employee=employee,
                code=payload.pop("code"),
                is_deleted=False,
                defaults={
                    **payload,
                    "quantity": Decimal("1"),
                    "status": PayrollInputStatus.CONFIRMED,
                },
            )

            created += 1

    return created


@transaction.atomic
def ensure_period(*, masters: dict, period_range: tuple) -> PayrollPeriod:
    start, end = period_range

    code = f"UAT-{start.year}-{start.month:02d}"

    period, _ = PayrollPeriod.objects.get_or_create(
        company=masters["company"],
        payroll_group=masters["payroll_group"],
        code=code,
        is_deleted=False,
        defaults={
            "name": f"UAT {start.strftime('%B %Y')}",
            "start_date": start,
            "end_date": end,
            "cutoff_date": end,
            "payment_date": end + timedelta(days=5),
            # Sengaja dikosongkan: pembaginya jadi jumlah hari kalender
            # periode (Juni 30, Juli 31). Itu yang membuat selisih
            # potongan harian antara dua bulan terlihat, dan sekaligus
            # memperlihatkan keputusan yang belum diambil perusahaan —
            # lihat BUSINESS DECISION REQUIRED di docs/claude/payroll.md.
            "working_days": None,
        },
    )

    return period


# ----------------------------------------------------------------------
# Pembersihan
# ----------------------------------------------------------------------


@transaction.atomic
def reset() -> dict:
    """
    Menghapus seluruh data UAT. Hard delete, bukan soft.

    Ini satu-satunya tempat di modul payroll yang menghapus permanen,
    dan itu disengaja: data UAT bukan dokumen bisnis, dan menyisakannya
    sebagai baris ter-soft-delete membuat run berikutnya menghitung
    ulang sampah yang tidak pernah dilihat siapa pun.
    """
    numbers = [person["number"] for person in PEOPLE]

    employees = Employee.objects.filter(employee_number__in=numbers)

    removed = {
        "runs": 0,
        "periods": 0,
        "employees": employees.count(),
    }

    periods = PayrollPeriod.objects.filter(code__startswith="UAT-")

    removed["runs"] = PayrollRun.objects.filter(period__in=periods).count()

    PayrollRun.objects.filter(period__in=periods).delete()
    PayrollInput.objects.filter(period__in=periods).delete()

    removed["periods"] = periods.count()
    periods.delete()

    EmployeeAttendance.objects.filter(employee__in=employees).delete()
    EmployeeOvertime.objects.filter(employee__in=employees).delete()
    EmployeeLeave.objects.filter(employee__in=employees).delete()
    PayrollAssignment.objects.filter(employee__in=employees).delete()
    OrganizationAssignment.objects.filter(employee__in=employees).delete()
    EmploymentAssignment.objects.filter(employee__in=employees).delete()
    employees.delete()

    AllowanceTemplateLine.objects.filter(
        template__code=ALLOWANCE_CODE,
    ).delete()
    DeductionTemplateLine.objects.filter(
        template__code=DEDUCTION_CODE,
    ).delete()
    AllowanceTemplate.objects.filter(code=ALLOWANCE_CODE).delete()
    DeductionTemplate.objects.filter(code=DEDUCTION_CODE).delete()
    OvertimeGroup.objects.filter(code=OVERTIME_CODE).delete()
    PayrollLeaveRule.objects.filter(
        leave_type__code=LEAVE_TYPE_CODE,
    ).delete()
    LeaveType.objects.filter(code=LEAVE_TYPE_CODE).delete()
    Section.objects.filter(code=SECTION_CODE).delete()
    Department.objects.filter(code=DEPARTMENT_CODE).delete()

    return removed
