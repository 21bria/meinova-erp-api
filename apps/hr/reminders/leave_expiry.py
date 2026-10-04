"""
Pengingat saldo cuti yang akan hangus.

Hanya untuk kantong yang **punya tanggal hangus** — sisa bawaan tahun
lalu dan saldo awal migrasi. Jatah tahun berjalan tidak punya masa
berlaku, dan mengirimkan "cuti Anda akan hangus" untuk saldo yang
sebenarnya aman adalah cara tercepat membuat orang berhenti mempercayai
pengingat ini.

Tonggak harinya dari `LeavePolicy.carry_over_reminder_days` — aturan
yang sama yang menciptakan tanggal hangusnya. Menaruhnya di setelan
sistem akan memisahkan "kapan hangus" dari "kapan diingatkan", dan
keduanya berubah bersamaan.

Berapa hari yang akan hangus diambil dari **hasil alokasi FIFO** yang
sudah tersimpan di kartu, bukan dari `used` yang satu angka untuk
seluruh kartu. Tanpa itu, orang yang cutinya menggerus saldo awal akan
dikabari bahwa bawaannya akan hangus padahal bawaannya utuh.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

logger = logging.getLogger(__name__)

ZERO = Decimal("0.0")


# Dua kantong bermasa berlaku. Bentuknya sengaja sama dengan
# `LeaveCarryOverService.EXPIRING_POCKETS` — yang mengingatkan dan yang
# menghanguskan harus melihat kantong yang sama persis, kalau tidak ada
# hari yang hangus tanpa pernah dikabarkan.
POCKETS = (
    {
        "key": "carried_over",
        "label": "Sisa cuti tahun lalu",
        "expiry_field": "carried_over_expires_at",
        "granted_field": "carried_over",
        "remaining_attr": "carried_over_remaining",
    },
    {
        "key": "opening",
        "label": "Saldo awal",
        "expiry_field": "opening_expires_at",
        "granted_field": "opening_balance",
        "remaining_attr": "opening_remaining",
    },
)


def run(*, today: date | None = None, dry_run: bool = False) -> dict:
    """
    Jalankan untuk satu tenant. Wajib sudah di dalam `schema_context()`.

    Aman diulang berkali-kali sehari: `dedup_key` memuat kantong dan
    tonggaknya, jadi satu tonggak menghasilkan tepat satu surat per
    kantong.
    """
    from apps.hr.api.leave.entitlement import LeavePolicyResolver
    from apps.hr.models import LeaveBalance
    from apps.notifications import notify

    today = today or date.today()

    stats = {
        "examined": 0,
        "notified": 0,
        "skipped_no_policy": 0,
        "skipped_nothing_left": 0,
    }

    for pocket in POCKETS:
        rows = (
            LeaveBalance.objects
            .filter(
                is_deleted=False,
                **{
                    f"{pocket['expiry_field']}__isnull": False,
                    # Yang sudah lewat tanggalnya bukan urusan pengingat
                    # lagi — itu urusan `LeaveCarryOverService.expire`.
                    # Mengingatkan sesuatu yang sudah hangus cuma
                    # memberi tahu orang bahwa ia terlambat.
                    f"{pocket['expiry_field']}__gte": today,
                    f"{pocket['granted_field']}__gt": ZERO,
                },
            )
            .select_related("employee", "leave_type")
        )

        for balance in rows:
            stats["examined"] += 1

            expires_at = getattr(balance, pocket["expiry_field"])

            days_left = (expires_at - today).days

            policy = LeavePolicyResolver.resolve(
                employee=balance.employee,
                leave_type=balance.leave_type,
            )

            if policy is None:
                # Aturannya dicabut setelah saldonya terbit. Tanggal
                # hangusnya tetap berlaku (ia menempel di baris saldo),
                # tapi tidak ada lagi yang menentukan kapan
                # mengingatkan.
                stats["skipped_no_policy"] += 1

                continue

            if days_left not in set(policy.reminder_days):
                continue

            expiring = getattr(balance, pocket["remaining_attr"])

            if expiring <= ZERO:
                # Kantongnya sudah habis dipakai. Tidak ada yang akan
                # hangus, jadi tidak ada yang perlu dikabarkan.
                stats["skipped_nothing_left"] += 1

                continue

            if dry_run:
                stats["notified"] += 1

                continue

            notify(
                event="hr.leave_balance_expiring",
                context={
                    "employee_name": balance.employee.full_name,
                    "employee_number": balance.employee.employee_number,
                    "leave_type_name": balance.leave_type.name,
                    "pocket_label": pocket["label"],
                    "expiring_days": str(expiring),
                    "expiry_date": expires_at.strftime("%d %B %Y"),
                    "days_left": days_left,
                    "remaining": str(balance.remaining),
                    "year": balance.year,
                },
                subject_employee=balance.employee,
                module="hr",
                object_type="leave-balance-expiring",
                object_id=balance.pk,
                link="/hr/leave-balances",
                # Kantong **dan** tonggaknya ikut: pengingat H-7 tidak
                # boleh ditolak sebagai duplikat pengingat H-30 (yang
                # mendesak justru yang belakangan), dan pengingat saldo
                # awal tidak boleh ditolak sebagai duplikat pengingat
                # sisa tahun lalu — keduanya hak yang berbeda.
                dedup_key=(
                    f"hr.leave_balance_expiring:{balance.pk}:"
                    f"{pocket['key']}:{days_left}"
                ),
                tone="warning",
            )

            stats["notified"] += 1

    logger.info("Pengingat kedaluwarsa cuti: %s", stats)

    return stats
