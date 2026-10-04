"""
Pemindahan sisa cuti antar tahun, dan penghangusannya.

`LeavePolicy` sudah lama punya `allow_carry_over`, `carry_over_max_days`,
dan `carry_over_expiry_months` — ketiganya bisa dicentang di layar sejak
awal, dan **tidak ada satu baris kode pun yang membacanya**. Pola yang
sama untuk kesekian kalinya di codebase ini. Berkas ini yang menutupnya.

Dua operasi, dan keduanya sengaja **manual**, bukan otomatis saat tahun
berganti:

- `carry_over(year)` — memindahkan sisa tahun lalu ke tahun ini.
- `expire(today)` — menghanguskan sisa bawaan yang lewat tanggalnya.

Kenapa manual: keduanya mengubah angka yang tercetak di kartu cuti
seseorang. Perintah yang berjalan sendiri tengah malam pergantian tahun
akan memindahkan saldo pegawai yang datanya belum selesai dirapikan, dan
hasilnya baru ketahuan saat ada yang mengajukan cuti di bulan Februari.
Menjalankannya adalah keputusan HR, dan `--dry-run` ada supaya
keputusannya bisa dilihat dulu.

**Aturan pemakaian: sisa bawaan dipakai lebih dulu.** `used` menghitung
seluruh cuti yang diambil tahun itu tanpa membedakan sumbernya, jadi
sisa bawaan yang belum terpakai dihitung `max(0, carried_over - used)`.
Ini yang membuat "pakai dulu yang mau hangus" berlaku dengan sendirinya
— kalau dibalik (jatah tahun berjalan dipakai dulu), setiap orang akan
kehilangan bawaannya walau cutinya banyak, dan tidak ada yang bisa
menjelaskan kenapa.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from django.db import transaction

from apps.hr.models import LeaveBalance

from .entitlement import LeavePolicyResolver, add_months

logger = logging.getLogger(__name__)

ZERO = Decimal("0.0")


def unused_carry_over(balance: LeaveBalance) -> Decimal:
    """
    Sisa bawaan yang belum terpakai dan belum hangus.

    Dulu dihitung `carried_over - used`, dan itu benar hanya selama
    kartunya cuma punya dua kantong. Begitu saldo awal migrasi ikut,
    pengurangan kasar itu **menghukum orang dua kali**: cuti yang
    sebenarnya menggerus saldo awal tetap terhitung mengurangi bawaan,
    sehingga bawaannya terlihat habis padahal masih ada. Sekarang
    memakai hasil alokasi FIFO yang sudah disimpan di kartu.

    Tidak pernah negatif.
    """
    return balance.carried_over_remaining


class LeaveCarryOverService:
    # ------------------------------------------------------------------
    # Pemindahan
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def carry_over(
        cls,
        *,
        year: int,
        employees=None,
        user=None,
        dry_run: bool = False,
    ) -> dict:
        """
        Memindahkan sisa tahun `year - 1` ke baris saldo tahun `year`.

        Baris tujuan **harus sudah ada** — diterbitkan
        `generate_leave_balances`. Membuatnya di sini berarti menerbitkan
        saldo tanpa menghitung jatahnya, dan pegawai yang belum berhak
        apa-apa akan punya baris berisi bawaan saja.

        Aman diulang: `carried_over` **ditimpa**, bukan ditambahkan.
        Menambahkan membuat perintah yang dijalankan dua kali
        menggandakan sisa cuti semua orang, dan tidak ada yang
        menyadarinya sampai ada yang mengambil cuti lebih banyak dari
        haknya.
        """
        previous = year - 1

        sources = (
            LeaveBalance.objects
            .filter(year=previous, is_deleted=False)
            .select_related("employee", "leave_type")
        )

        if employees is not None:
            sources = sources.filter(employee__in=employees)

        stats = {
            "year": year,
            "examined": 0,
            "moved": 0,
            "skipped_no_policy": 0,
            "skipped_non_balance": 0,
            "skipped_not_allowed": 0,
            "skipped_no_target": 0,
            "skipped_nothing_left": 0,
            "details": [],
        }

        for source in sources:
            stats["examined"] += 1

            policy = LeavePolicyResolver.resolve(
                employee=source.employee,
                leave_type=source.leave_type,
            )

            if policy is None:
                stats["skipped_no_policy"] += 1

                continue

            # Baris saldo dari aturan yang tidak bersaldo seharusnya
            # tidak pernah ada — `LeaveBalanceGenerator` tidak
            # menerbitkannya. Tetap dijaga di sini karena baris lama
            # bisa saja terbit sebelum saklarnya dimatikan, dan
            # memindahkannya ke tahun depan berarti menghidupkan
            # kembali saldo yang sudah dinyatakan tidak ada.
            if not policy.uses_balance:
                stats["skipped_non_balance"] += 1

                continue

            if not policy.allow_carry_over:
                stats["skipped_not_allowed"] += 1

                continue

            remaining = source.remaining

            if remaining is None or remaining <= ZERO:
                stats["skipped_nothing_left"] += 1

                continue

            amount = remaining

            if policy.carry_over_max_days is not None:
                amount = min(amount, policy.carry_over_max_days)

            if amount <= ZERO:
                stats["skipped_nothing_left"] += 1

                continue

            target = (
                LeaveBalance.objects
                .filter(
                    employee=source.employee,
                    leave_type=source.leave_type,
                    year=year,
                    is_deleted=False,
                )
                .first()
            )

            if target is None:
                # Bukan kesalahan yang bisa diperbaiki di sini —
                # jalankan `generate_leave_balances --year=<year>` dulu.
                # Dilaporkan supaya kelalaian itu terlihat, bukan
                # menghasilkan pegawai yang diam-diam kehilangan
                # bawaannya.
                stats["skipped_no_target"] += 1

                continue

            expires_at = cls.expiry_for(policy=policy, year=year)

            stats["details"].append(
                {
                    "employee": source.employee.employee_number,
                    "leave_type": source.leave_type.code,
                    "from_year": previous,
                    "days": str(amount),
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
            )

            if dry_run:
                continue

            target.carried_over = amount
            target.carried_over_expires_at = expires_at
            # Yang hangus dari periode sebelumnya tidak ikut terbawa —
            # baris ini bicara soal bawaan yang baru saja dipindah.
            target.carried_over_forfeited = ZERO
            target.updated_by = user

            target.save(
                update_fields=[
                    "carried_over",
                    "carried_over_expires_at",
                    "carried_over_forfeited",
                    "updated_by",
                    "updated_at",
                ],
            )

            stats["moved"] += 1

        logger.info("Carry over cuti %s: %s", year, {
            key: value for key, value in stats.items() if key != "details"
        })

        return stats

    @staticmethod
    def expiry_for(*, policy, year: int) -> date | None:
        """
        Tanggal hangus untuk bawaan tahun `year`.

        Dihitung dari **1 Januari tahun itu**, bukan dari tanggal
        perintahnya dijalankan: HR yang menjalankan carry over di bulan
        Maret tidak boleh membuat batas hangusnya mundur tiga bulan
        dibanding tenant yang menjalankannya tepat waktu.
        """
        months = policy.carry_over_expiry_months

        if not months:
            return None

        return add_months(date(year, 1, 1), int(months))

    # ------------------------------------------------------------------
    # Penghangusan
    # ------------------------------------------------------------------

    # Dua kantong yang punya masa berlaku, dan keduanya dihanguskan
    # dengan cara yang sama. Saldo awal migrasi ikut karena ia memang
    # sejenis bawaan — sisa dari sebelum periode ini dimulai.
    EXPIRING_POCKETS = (
        {
            "key": "carried_over",
            "label": "Sisa tahun lalu",
            "expiry_field": "carried_over_expires_at",
            "granted_field": "carried_over",
            "used_field": "carried_over_used",
            "forfeited_field": "carried_over_forfeited",
        },
        {
            "key": "opening",
            "label": "Saldo awal",
            "expiry_field": "opening_expires_at",
            "granted_field": "opening_balance",
            "used_field": "opening_used",
            "forfeited_field": "opening_forfeited",
        },
    )

    @classmethod
    @transaction.atomic
    def expire(
        cls,
        *,
        today: date | None = None,
        user=None,
        dry_run: bool = False,
    ) -> dict:
        """
        Menghanguskan sisa bawaan **dan** sisa saldo awal migrasi yang
        tanggalnya sudah lewat.

        Yang ditulis kolom `*_forfeited`; kolom pemberiannya
        (`carried_over`, `opening_balance`) **tidak** dikurangi, dan itu
        perubahan dari perilaku sebelumnya. Alasannya keras: keduanya
        ditulis ulang oleh proses lain — `carried_over` ditimpa tiap kali
        carry over dijalankan, `opening_balance` dijumlah ulang dari
        dokumen migrasi. Mengurangi di sana berarti hari yang sudah
        dihanguskan **hidup lagi** pada sinkronisasi berikutnya, tanpa
        satu pun pesan. `remaining` yang mengurangkan `*_forfeited`.

        Berapa yang hangus diambil dari hasil alokasi FIFO
        (`carried_over_used` / `opening_used`), bukan dari `used` yang
        satu angka untuk seluruh kartu. Tanpa itu, bawaan yang sudah
        dipakai bulan Maret tetap terhitung hangus di bulan Juli — dan
        orang kehilangan hari yang sebenarnya sudah ia nikmati.

        Aman diulang: sisa yang sudah dihanguskan tidak tersisa lagi,
        jadi jalan kedua tidak mengubah apa pun.
        """
        today = today or date.today()

        stats = {
            "examined": 0,
            "forfeited": 0,
            "days": ZERO,
            "by_pocket": {},
            "details": [],
        }

        for pocket in cls.EXPIRING_POCKETS:
            rows = (
                LeaveBalance.objects
                .filter(
                    is_deleted=False,
                    **{
                        f"{pocket['expiry_field']}__isnull": False,
                        f"{pocket['expiry_field']}__lte": today,
                        f"{pocket['granted_field']}__gt": ZERO,
                    },
                )
                .select_related("employee", "leave_type")
            )

            moved = ZERO
            count = 0

            for balance in rows:
                stats["examined"] += 1

                granted = getattr(balance, pocket["granted_field"]) or ZERO
                consumed = getattr(balance, pocket["used_field"]) or ZERO
                already = getattr(balance, pocket["forfeited_field"]) or ZERO

                amount = granted - consumed - already

                if amount <= ZERO:
                    # Seluruh kantongnya sudah terpakai atau sudah
                    # pernah dihanguskan. Tidak ada yang perlu ditulis.
                    continue

                expires_at = getattr(balance, pocket["expiry_field"])

                stats["details"].append(
                    {
                        "employee": balance.employee.employee_number,
                        "leave_type": balance.leave_type.code,
                        "year": balance.year,
                        "pocket": pocket["key"],
                        "label": pocket["label"],
                        "days": str(amount),
                        "expired_at": expires_at.isoformat(),
                    },
                )

                count += 1
                moved += amount

                if dry_run:
                    continue

                setattr(
                    balance,
                    pocket["forfeited_field"],
                    already + amount,
                )

                balance.updated_by = user

                balance.save(
                    update_fields=[
                        pocket["forfeited_field"],
                        "updated_by",
                        "updated_at",
                    ],
                )

            stats["by_pocket"][pocket["key"]] = {
                "rows": count,
                "days": str(moved),
            }

            stats["forfeited"] += count
            stats["days"] += moved

        stats["days"] = str(stats["days"])

        logger.info("Penghangusan saldo cuti: %s", {
            key: value
            for key, value in stats.items()
            if key != "details"
        })

        return stats
