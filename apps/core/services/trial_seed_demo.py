"""
Preset dataset trial untuk tenant `demo`.

Angka dan kode di sini hasil TRL-0/TRL-0B — setiap gaji, tanggal masuk,
dan pilihan template sudah dibuktikan menghasilkan angka yang
diharapkan lewat `apps/payroll/tests/test_trl_readiness.py`. Mengubah
satu nilai di sini berarti membatalkan pembuktian itu.
"""

from __future__ import annotations

from datetime import date

from apps.core.services.trial_seed import EmployeePlan, TrialSeedSpec


TRIAL_ID = "TRL-2026-09-E2E"

#: Berkas manifest tinggal di dalam repo, bukan di direktori sementara:
#: ia dipakai untuk audit dan purge berbulan-bulan sesudah trial dibuat.
MANIFEST_DIR = "var/trial"

FULL_TENURE_JOIN = date(2025, 1, 6)
MID_PERIOD_JOIN = date(2026, 9, 16)


DEMO_TRIAL_SPEC = TrialSeedSpec(
    trial_id=TRIAL_ID,
    schema_names=("demo",),

    # --- rujukan kanonik, seluruhnya kunci bisnis -------------------
    company_code="MMR",
    branch_code="DEFAULT",
    location_code="JKT-HO",
    department_code="PROC",
    section_code="PROC_GENERAL",
    work_schedule_code="REG5",
    # Kalender global (company IS NULL) — yang dipakai sembilan pegawai
    # HO MMR yang sudah ada. Kalender tingkat company milik MMR sendiri
    # sudah di-soft-delete, dan itu dicatat sebagai temuan, bukan
    # diperbaiki di sini.
    work_calendar_code="OFFICE-2026",
    shift_code="OFFICE-10",
    currency_code="IDR",
    tax_status_code="TK/0",
    annual_leave_type_code="ANNUAL",
    unpaid_leave_type_code="UNPAID",

    # --- master milik trial -----------------------------------------
    overtime_group_code="TRL-OT-TIER",
    overtime_tiers=(
        # (urutan, dari jam, sampai jam, pengali). `None` = tanpa batas
        # atas; validasi menuntut tingkat teratas terbuka.
        (1, "0", "2", "1.5"),
        (2, "2", None, "2.0"),
    ),
    daily_policy_code="TRL-DAILY",
    daily_policy_divisor="26",

    employees=(
        EmployeePlan(
            tag="TRL01",
            first_name="Trial",
            last_name="Satu",
            basic_salary="10000000",
            join_date=FULL_TENURE_JOIN,
            payroll_group_code="MONTHLY",
            allowance_template_code="STANDARD",
        ),
        EmployeePlan(
            tag="TRL02",
            first_name="Trial",
            last_name="Dua",
            basic_salary="12000000",
            join_date=MID_PERIOD_JOIN,
            payroll_group_code="MONTHLY",
            # Template STAFF membawa satu baris per hari yang tidak
            # boleh diprorata dan satu baris persentase yang harus —
            # dua perlakuan berbeda dalam satu slip.
            allowance_template_code="STAFF",
        ),
        EmployeePlan(
            tag="TRL03",
            first_name="Trial",
            last_name="Tiga",
            basic_salary="9000000",
            join_date=FULL_TENURE_JOIN,
            payroll_group_code="MONTHLY",
            allowance_template_code="STANDARD",
            overtime_group_code="TRL-OT-TIER",
        ),
        EmployeePlan(
            tag="TRL04",
            first_name="Trial",
            last_name="Empat",
            basic_salary="8000000",
            join_date=FULL_TENURE_JOIN,
            payroll_group_code="MONTHLY",
            allowance_template_code="STANDARD",
        ),
        EmployeePlan(
            tag="TRL05",
            first_name="Trial",
            last_name="Lima",
            basic_salary="5200000",
            join_date=FULL_TENURE_JOIN,
            payroll_group_code="DAILY",
            allowance_template_code="STANDARD",
            payroll_policy_code="TRL-DAILY",
        ),
        EmployeePlan(
            tag="TRL06",
            first_name="Trial",
            last_name="Enam",
            basic_salary="7500000",
            join_date=FULL_TENURE_JOIN,
            payroll_group_code="MONTHLY",
            allowance_template_code="STANDARD",
        ),
    ),

    # Enam hari: jatah setahun `ANNUAL-STD` 12 hari, separuhnya sudah
    # terpakai di sistem lama sebelum go-live 1 September. Cukup untuk
    # dua hari cuti dibayar di Fase 2 dengan sisa yang masih masuk akal,
    # dan bukan angka maksimum yang menyamarkan kesalahan pemotongan.
    opening_balance_tag="TRL04",
    opening_balance_days="6.0",

    manifest_dir=MANIFEST_DIR,

    # Pagar keadaan tenant sebelum menulis. Angka ini keadaan demo
    # sesudah reset Finance TRL-0B dan harus tetap segitu.
    protected_counts=(
        ("hr.Employee", 30),
        ("payroll.PayrollPeriod", 1),
        ("payroll.PayrollRun", 1),
        ("finance.Journal", 0),
        ("finance.JournalLine", 0),
        ("finance.AccountingEvent", 0),
        ("finance.Account", 141),
        ("finance.AccountingPolicy", 6),
        ("administration.Currency", 7),
        ("workflow.WorkflowDefinition", 12),
    ),
)


#: Rencana yang diharapkan dari TRL-0B. Perintah membandingkannya
#: dengan rencana yang dihitung ulang; selisih berarti tenant bergeser
#: sejak dirancang dan harus dijelaskan sebelum apa pun ditulis.
DEMO_TRIAL_BASELINE = {
    "payroll.PayrollLeaveRule": 1,
    "payroll.OvertimeGroup": 1,
    "payroll.OvertimeGroupTier": 2,
    "payroll.PayrollPolicy": 1,
    "hr.Employee": 6,
    "hr.EmploymentAssignment": 6,
    "hr.OrganizationAssignment": 6,
    "hr.PayrollAssignment": 6,
    "hr.EmployeeShiftAssignment": 6,
    "hr.LeaveOpeningBalance": 1,
}
