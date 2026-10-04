"""
Cakupan reset Finance untuk tenant `demo`.

Tiap angka berasal dari discovery yang tercatat, bukan tebakan: 12
jurnal + 25 baris + 1 kejadian, seluruhnya milik company 1 (MNI),
lahir dalam satu sesi 3,5 jam pada 16 Sep 2026, dengan satu-satunya
aktor `demo.bod2` (id 158).

MMR dan MLS tidak punya satu pun transaksi Finance, jadi keduanya tidak
masuk cakupan — dan pagar company memastikan mereka tetap begitu.
"""

from __future__ import annotations

from datetime import date

from .finance_reset import FinanceResetSpec


# Aktor satu-satunya yang muncul pada fixture: demo.bod2
# (brya.seran+bod2@gmail.com), akun uji non-superuser.
DEMO_FIXTURE_ACTOR_IDS = (158,)

# Seluruh 12 jurnal dibuat 2026-09-16 antara 15:31 dan 18:55.
DEMO_FIXTURE_WINDOW = (date(2026, 9, 16), date(2026, 9, 16))

# Pengajuan alur yang masih HIDUP dan karenanya ikut dibersihkan:
# instance 138 berstatus `pending` untuk journal 7, dengan satu kotak
# tanda tangan yang juga masih `pending` atas nama employee 157 /
# user 158. Instance 139 dan 140 sudah `approved` — arsip, dibiarkan.
DEMO_LIVE_INSTANCE_IDS = (138,)
DEMO_LIVE_APPROVAL_IDS = (481,)


DEMO_FINANCE_RESET_SPEC = FinanceResetSpec(
    schema_names=("demo",),
    company_ids=(1,),
    allowed_actor_ids=DEMO_FIXTURE_ACTOR_IDS,
    fixture_window_start=DEMO_FIXTURE_WINDOW[0],
    fixture_window_end=DEMO_FIXTURE_WINDOW[1],
    allowed_source_types=("payroll_run",),
    workflow_instance_ids=DEMO_LIVE_INSTANCE_IDS,
    workflow_approval_ids=DEMO_LIVE_APPROVAL_IDS,
    expected_instance_state=(
        {
            "id": 138,
            "module": "finance",
            "document_type": "journal",
            "object_id": "7",
            "status": "pending",
        },
    ),
    expected_approval_state=(
        {
            "id": 481,
            "instance_id": 138,
            "status": "pending",
            "approver_employee_id": 157,
            "approver_id": 158,
        },
    ),
    protected_counts=(
        ("finance.Account", 141),
        ("finance.AccountMapping", 54),
        ("finance.AccountingDimension", 7),
        ("finance.AccountingPeriod", 36),
        ("finance.AccountingPolicy", 6),
        ("finance.AccountingPolicyLine", 51),
        ("finance.AccountingPolicyRule", 45),
        ("finance.FiscalYear", 3),
        ("administration.Currency", 7),
        # 12 BARIS, bukan 13. `FIN-JOURNAL-STD` memang ber-id 13, tapi
        # id 9 tidak pernah ada — pagar ini menagih jumlah baris, dan
        # perbedaannya sempat tertukar waktu spec ini pertama ditulis.
        ("workflow.WorkflowDefinition", 12),
    ),
)


# Rencana yang diharapkan, dari discovery. Perintah membandingkannya
# dengan rencana yang dihitung ulang — selisih berarti tenant berubah
# sejak diaudit dan harus dijelaskan sebelum apa pun dihapus.
DEMO_FINANCE_RESET_BASELINE = {
    "finance.JournalLineDimension": 0,
    "finance.JournalLine": 25,
    "finance.AccountingEvent": 1,
    "finance.Journal": 12,
    "workflow.WorkflowApproval": 1,
    "workflow.WorkflowInstance": 1,
}
