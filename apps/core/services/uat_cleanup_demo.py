"""
Cakupan UAT untuk tenant `demo`, persis seperti hasil audit.

Angkanya bukan tebakan: tiap ID di bawah berasal dari penelusuran FK
nyata (`pg_constraint`) pada schema `demo`, dan tiap kelompok punya
alasan yang dicatat di sebelahnya. Yang tidak tercantum di sini tidak
akan disentuh perintah pembuangan.

Dipisahkan dari service-nya supaya isi tenant tidak tertanam di logika,
dan supaya test bisa memakai spesifikasinya sendiri.
"""

from __future__ import annotations

from .uat_cleanup import UatCleanupSpec


# Pegawai UAT: 18 baris, nomor ber-prefix UAT, company 2 (MMR),
# department 484 (UAT-PAY). Tidak satu pun punya akun user.
DEMO_UAT_EMPLOYEE_IDS = tuple(range(160, 178))

# Run 2–8 seluruhnya berisi pegawai UAT saja. Run 1 (26 pegawai riil)
# sengaja di luar daftar dan masuk pagar mati.
DEMO_UAT_RUN_IDS = (2, 3, 4, 5, 6, 7, 8)

# Period 1 (August 2026) milik run riil. Sisanya lahir untuk UAT.
DEMO_UAT_PERIOD_IDS = (2, 3, 7, 8, 9, 10, 11)

# Catatan kejadian yang menunjuk run 2 tanpa FK. Provenance-nya
# diverifikasi ulang saat perintah jalan, bukan dipercaya dari sini.
DEMO_UAT_WORKFLOW_INSTANCE_IDS = (133,)
DEMO_UAT_WORKFLOW_APPROVAL_IDS = (467, 468, 469)
DEMO_UAT_NOTIFICATION_LOG_IDS = tuple(range(529, 539))

# Master kategori C — lahir khusus UAT, nol pemakai riil.
DEMO_UAT_LEAVE_RULE_IDS = (1, 2)
DEMO_UAT_LEAVE_TYPE_IDS = (16, 17)
DEMO_UAT_OVERTIME_GROUP_IDS = (4, 5, 6)
DEMO_UAT_ALLOWANCE_TEMPLATE_IDS = (4, 5)
DEMO_UAT_DEDUCTION_TEMPLATE_IDS = (3,)
DEMO_UAT_PAYROLL_POLICY_IDS = (1, 2, 3, 4, 5)
DEMO_UAT_SECTION_IDS = (491,)
DEMO_UAT_DEPARTMENT_IDS = (484,)


# ----------------------------------------------------------------------
# Pagar mati
# ----------------------------------------------------------------------
#
# Bukan sekadar "jangan dimasukkan daftar sasaran": ID di bawah dihitung
# ulang sesudah pembuangan, dan hilangnya satu saja membatalkan seluruh
# transaksi.

DEMO_PROTECTED_EMPLOYEE_IDS = tuple(range(130, 160))
DEMO_PROTECTED_RUN_IDS = (1,)
DEMO_PROTECTED_PERIOD_IDS = (1,)

# Payroll group 1 MONTHLY / 3 DAILY dipakai 26 pegawai riil; tax bracket
# 1–5 tarif PPh21 statutori; keduanya tidak pernah masuk daftar sasaran
# sehingga tidak perlu pagar terpisah — yang diberi pagar adalah master
# yang ID-nya berdekatan dengan sasaran dan rawan salah ketik.
DEMO_PROTECTED_DEPARTMENT_IDS = ()
DEMO_PROTECTED_SECTION_IDS = ()
DEMO_PROTECTED_LEAVE_TYPE_IDS = tuple(range(1, 16))
DEMO_PROTECTED_OVERTIME_GROUP_IDS = (1, 2, 3)
DEMO_PROTECTED_ALLOWANCE_TEMPLATE_IDS = (1, 2, 3)
DEMO_PROTECTED_DEDUCTION_TEMPLATE_IDS = (1, 2)

# `PAY-RUN-STD` — satu-satunya alur approval payroll tenant ini.
DEMO_PROTECTED_WORKFLOW_DEFINITION_IDS = (11,)


DEMO_UAT_SPEC = UatCleanupSpec(
    employee_ids=DEMO_UAT_EMPLOYEE_IDS,
    run_ids=DEMO_UAT_RUN_IDS,
    period_ids=DEMO_UAT_PERIOD_IDS,
    workflow_instance_ids=DEMO_UAT_WORKFLOW_INSTANCE_IDS,
    workflow_approval_ids=DEMO_UAT_WORKFLOW_APPROVAL_IDS,
    notification_log_ids=DEMO_UAT_NOTIFICATION_LOG_IDS,
    leave_rule_ids=DEMO_UAT_LEAVE_RULE_IDS,
    leave_type_ids=DEMO_UAT_LEAVE_TYPE_IDS,
    overtime_group_ids=DEMO_UAT_OVERTIME_GROUP_IDS,
    allowance_template_ids=DEMO_UAT_ALLOWANCE_TEMPLATE_IDS,
    deduction_template_ids=DEMO_UAT_DEDUCTION_TEMPLATE_IDS,
    payroll_policy_ids=DEMO_UAT_PAYROLL_POLICY_IDS,
    section_ids=DEMO_UAT_SECTION_IDS,
    department_ids=DEMO_UAT_DEPARTMENT_IDS,
    employee_number_prefix="UAT",
    expected_company_id=2,
    expected_department_id=484,
    protected_employee_ids=DEMO_PROTECTED_EMPLOYEE_IDS,
    protected_run_ids=DEMO_PROTECTED_RUN_IDS,
    protected_period_ids=DEMO_PROTECTED_PERIOD_IDS,
    protected_department_ids=DEMO_PROTECTED_DEPARTMENT_IDS,
    protected_section_ids=DEMO_PROTECTED_SECTION_IDS,
    protected_leave_type_ids=DEMO_PROTECTED_LEAVE_TYPE_IDS,
    protected_overtime_group_ids=DEMO_PROTECTED_OVERTIME_GROUP_IDS,
    protected_allowance_template_ids=(
        DEMO_PROTECTED_ALLOWANCE_TEMPLATE_IDS
    ),
    protected_deduction_template_ids=(
        DEMO_PROTECTED_DEDUCTION_TEMPLATE_IDS
    ),
    protected_workflow_definition_ids=(
        DEMO_PROTECTED_WORKFLOW_DEFINITION_IDS
    ),
)


# Angka baseline dari audit. Dipakai perintah untuk membandingkan
# rencana dengan apa yang dulu dihitung — selisihnya berarti tenant
# sudah berubah sejak diaudit, dan itu harus dijelaskan sebelum
# eksekusi, bukan diterima diam-diam.
DEMO_AUDIT_BASELINE = {
    "payroll.PayrollRunComponent": 366,
    "payroll.PayrollRunEmployee": 50,
    "payroll.Payslip": 3,
    "payroll.PayrollInput": 4,
    "workflow.WorkflowApproval": 3,
    "workflow.WorkflowInstance": 1,
    "notifications.NotificationLog": 10,
    # Bel in-app untuk run 2 — ditemukan sesudah pembuangan utama, saat
    # audit yatim. Tiga barisnya memang bagian dataset UAT sejak awal;
    # yang luput waktu itu adalah tabelnya, bukan datanya.
    "administration.Notification": 3,
    "payroll.PayrollRun": 7,
    "payroll.PayrollPeriod": 7,
    "hr.EmployeeAttendance": 219,
    "hr.EmployeeLeave": 6,
    "hr.EmployeeOvertime": 5,
    "hr.PayrollAssignment": 18,
    "hr.EmploymentAssignment": 18,
    "hr.OrganizationAssignment": 18,
    "hr.Employee": 18,
    "payroll.PayrollLeaveRule": 2,
    "administration.LeaveType": 2,
    "payroll.OvertimeGroup": 3,
    "payroll.AllowanceTemplate": 2,
    "payroll.DeductionTemplate": 1,
    "payroll.PayrollPolicy": 5,
    "administration.Section": 1,
    "administration.Department": 1,
}
