"""
Rotation credit: pencatatan transaksi, konversi, dan saldo.

Satu aturan yang menentukan seluruh bentuk berkas ini: **transaksi
tidak pernah disunting dan tidak pernah dihapus.** `update()` dan
`soft_delete()` melempar. Koreksi lewat penyesuaian, pembatalan lewat
pembalikan — dua-duanya baris baru yang menunjuk yang lama.

Alasannya bukan kerapian akuntansi. Saat pegawai bertanya "kenapa saldo
saya berkurang tiga", jawabannya harus bisa ditunjuk baris per baris.
Baris yang bisa disunting tidak bisa menjawab itu, karena yang terbaca
sekarang belum tentu yang terjadi dulu.
"""

from __future__ import annotations

import logging

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.hr.api.site_rotation.policy import RosterPolicyResolver
from apps.hr.models import (
    CreditEntryType,
    RotationCreditBalance,
    RotationCreditTransaction,
)


logger = logging.getLogger(__name__)


ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Conversion:
    """
    Hasil mengubah kelebihan hari kerja jadi kredit.

    `remainder` adalah **hari kerja** yang belum genap jadi satu
    kredit, bukan pecahan kredit. Itu pilihan sadar: "1 hari lembur
    site kamu belum genap jadi kredit" bisa dijelaskan ke orangnya,
    sementara "0,33 kredit" tidak.
    """

    credit_days: Decimal
    remainder_days: Decimal
    ratio: Decimal
    rounding: str
    reason: str

    def as_dict(self) -> dict:
        return {
            "credit_days": str(self.credit_days),
            "remainder_days": str(self.remainder_days),
            "ratio": str(self.ratio),
            "rounding": self.rounding,
            "reason": self.reason,
        }


class RotationCreditService:
    """Ledger + saldo. Satu-satunya jalan menulis rotation credit."""

    # ------------------------------------------------------------------
    # Konversi
    # ------------------------------------------------------------------

    @classmethod
    def convert(
        cls,
        *,
        excess_days,
        ratio: Decimal,
        rounding: str = "floor",
        carry_remainder: bool = True,
        carried_days: Decimal | None = None,
    ) -> Conversion:
        """
        Kelebihan hari kerja → kredit.

        Contoh yang jadi acuan (rasio 3, Round Down + Carry)::

            excess 7  + carry 0 = 7  → 2 kredit, sisa 1
            excess 5  + carry 1 = 6  → 2 kredit, sisa 0

        Sisa yang dibawa adalah hari kerja, jadi aritmetikanya bulat dan
        tidak pernah kehilangan pecahan di pembulatan berikutnya.
        """
        excess = Decimal(str(excess_days or 0))
        carried = Decimal(str(carried_days or 0)) if carry_remainder else ZERO

        if ratio is None or ratio <= 0:
            return Conversion(
                credit_days=ZERO,
                remainder_days=excess + carried,
                ratio=Decimal("0.00"),
                rounding=rounding,
                reason=(
                    "Rasio konversi belum bisa dihitung — pola roster "
                    "belum punya hari off."
                ),
            )

        total = excess + carried

        if total <= 0:
            return Conversion(
                credit_days=ZERO,
                remainder_days=ZERO,
                ratio=ratio,
                rounding=rounding,
                reason="Tidak ada kelebihan hari yang bisa dikonversi.",
            )

        raw = total / ratio

        if rounding == "exact":
            credit = raw.quantize(Decimal("0.01"))
            remainder = ZERO
        elif rounding == "ceil":
            credit = raw.quantize(Decimal("1"), rounding=ROUND_CEILING)
            remainder = ZERO
        elif rounding == "half_up":
            credit = raw.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
            remainder = ZERO
        else:
            credit = raw.quantize(Decimal("1"), rounding=ROUND_FLOOR)

            # Sisa dihitung dari hari kerjanya, bukan dari pecahan
            # kreditnya: 7 − (2 × 3) = 1 hari.
            remainder = (
                total - credit * ratio
                if carry_remainder
                else ZERO
            )

        return Conversion(
            credit_days=credit.quantize(Decimal("0.01")),
            remainder_days=remainder.quantize(Decimal("0.01")),
            ratio=ratio,
            rounding=rounding,
            reason=(
                f"{total} hari ÷ rasio {ratio} = {raw.quantize(Decimal('0.01'))}"
                f" → {credit} kredit"
                + (f", sisa {remainder} hari dibawa." if remainder else ".")
            ),
        )

    @classmethod
    def convert_for_employee(cls, *, employee, excess_days) -> Conversion:
        """
        Konversi memakai policy pegawai: rasio, pembulatan, dan carry.

        Sisa yang dibawa dibaca dari saldonya sendiri, jadi dua konversi
        berturut-turut menyambung dengan benar tanpa pemanggil perlu
        mengurusnya.
        """
        resolved = RosterPolicyResolver.policy_for(employee)
        policy = resolved.policy

        if policy is None or not policy.credit_enabled:
            return Conversion(
                credit_days=ZERO,
                remainder_days=ZERO,
                ratio=ZERO,
                rounding="floor",
                reason=(
                    "Rotation credit tidak aktif untuk site pegawai ini."
                    if policy is not None
                    else "Pegawai ini belum punya Roster Policy."
                ),
            )

        ratio = RosterPolicyResolver.ratio_for_employee(employee)

        balance = cls.balance_for(employee)

        return cls.convert(
            excess_days=excess_days,
            ratio=ratio.value,
            rounding=policy.credit_rounding,
            carry_remainder=policy.credit_carry_remainder,
            carried_days=balance.carried_excess_days,
        )

    # ------------------------------------------------------------------
    # Menulis
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def record(
        cls,
        *,
        employee,
        entry_type: str,
        days,
        effective_date: date | None = None,
        reason: str = "",
        source_type: str = "",
        source_id=None,
        plan=None,
        segment=None,
        remainder_days=None,
        conversion_ratio=None,
        reverses=None,
        user=None,
        allow_negative: bool | None = None,
    ) -> RotationCreditTransaction:
        """
        Satu-satunya jalan menulis ke ledger.

        Plafon dan saldo negatif diperiksa **di sini**, bukan di
        pemanggil: kalau tiap pemanggil harus mengingat aturannya
        sendiri, cepat atau lambat ada satu yang lupa dan saldonya
        menembus tanpa suara.
        """
        amount = Decimal(str(days or 0))

        if amount <= 0:
            raise ValidationError(
                {
                    "days": (
                        "Jumlah hari harus lebih besar dari nol. "
                        "Pengurangan dicatat lewat Entry Type."
                    ),
                },
            )

        today = timezone.localdate()

        entry = RotationCreditTransaction(
            employee=employee,
            entry_type=entry_type,
            days=amount,
            transaction_date=today,
            effective_date=effective_date or today,
            reason=reason,
            source_type=source_type,
            source_id=str(source_id or ""),
            plan=plan,
            segment=segment,
            remainder_days=Decimal(str(remainder_days or 0)),
            conversion_ratio=conversion_ratio,
            reverses=reverses,
            created_by=user,
            updated_by=user,
        )

        entry.full_clean()

        cls._assert_within_limits(
            employee=employee,
            entry=entry,
            allow_negative=allow_negative,
        )

        entry.save()

        cls.recalculate(employee)

        return entry

    @classmethod
    def _assert_within_limits(cls, *, employee, entry, allow_negative):
        resolved = RosterPolicyResolver.policy_for(employee)
        policy = resolved.policy

        balance = cls.balance_for(employee)

        projected = (balance.balance or ZERO) + entry.signed_days

        permitted = (
            allow_negative
            if allow_negative is not None
            else bool(policy and policy.credit_allow_negative)
        )

        if projected < 0 and not permitted:
            raise ValidationError(
                {
                    "days": (
                        f"Saldo rotation credit akan jadi {projected}. "
                        f"Saldo sekarang {balance.balance}. Nyalakan "
                        "Allow Negative Balance di Roster Policy kalau "
                        "memang boleh minus."
                    ),
                },
            )

        ceiling = getattr(policy, "credit_max_balance_days", None)

        if ceiling and projected > ceiling:
            raise ValidationError(
                {
                    "days": (
                        f"Saldo akan jadi {projected}, melewati plafon "
                        f"{ceiling} yang ditetapkan {policy.code}."
                    ),
                },
            )

    # ------------------------------------------------------------------
    # Jalan pintas yang bernama
    # ------------------------------------------------------------------

    @classmethod
    def open_balance(
        cls,
        *,
        employee,
        days,
        effective_date=None,
        reason: str = "",
        source_type: str = "",
        source_id=None,
        user=None,
    ) -> RotationCreditTransaction | None:
        """
        Saldo awal dari sistem lama.

        Dicatat sebagai transaksi, bukan diketik langsung ke saldo:
        angka tanpa jejak asal-usul tidak bisa dipertanggungjawabkan
        saat pegawainya bertanya. Plafon dilewati — saldo yang dibawa
        memang bisa melebihi aturan yang baru dibuat hari ini.
        """
        if not days:
            return None

        return cls.record(
            employee=employee,
            entry_type=CreditEntryType.OPENING_BALANCE,
            days=days,
            effective_date=effective_date,
            reason=reason or "Saldo awal go-live.",
            source_type=source_type,
            source_id=source_id,
            user=user,
            allow_negative=True,
        )

    @classmethod
    def earn(
        cls,
        *,
        employee,
        excess_days,
        effective_date=None,
        reason: str = "",
        source_type: str = "",
        source_id=None,
        plan=None,
        segment=None,
        user=None,
    ) -> RotationCreditTransaction | None:
        """
        Mengonversi kelebihan hari kerja lalu mencatatnya.

        Mengembalikan `None` kalau konversinya nol — dan itu bukan
        kegagalan: sisa yang belum genap tetap disimpan di saldo supaya
        ikut dihitung berikutnya.
        """
        conversion = cls.convert_for_employee(
            employee=employee,
            excess_days=excess_days,
        )

        if conversion.credit_days <= 0:
            cls._carry_only(
                employee=employee,
                conversion=conversion,
            )

            return None

        return cls.record(
            employee=employee,
            entry_type=CreditEntryType.EARNED,
            days=conversion.credit_days,
            effective_date=effective_date,
            reason=reason or conversion.reason,
            source_type=source_type,
            source_id=source_id,
            plan=plan,
            segment=segment,
            remainder_days=conversion.remainder_days,
            conversion_ratio=conversion.ratio,
            user=user,
        )

    @classmethod
    def use(
        cls,
        *,
        employee,
        days,
        effective_date=None,
        reason: str = "",
        source_type: str = "",
        source_id=None,
        plan=None,
        user=None,
    ) -> RotationCreditTransaction:
        return cls.record(
            employee=employee,
            entry_type=CreditEntryType.USED,
            days=days,
            effective_date=effective_date,
            reason=reason,
            source_type=source_type,
            source_id=source_id,
            plan=plan,
            user=user,
        )

    @classmethod
    @transaction.atomic
    def reverse(
        cls,
        *,
        entry: RotationCreditTransaction,
        reason: str,
        user=None,
    ) -> RotationCreditTransaction:
        """
        Membatalkan satu transaksi dengan baris baru yang menunjuknya.

        Bukan menghapus: yang terjadi tetap terjadi, dan jejak "pernah
        dicatat lalu dibatalkan, oleh siapa, kenapa" justru yang paling
        dicari saat angkanya dipersoalkan.
        """
        if entry.entry_type == CreditEntryType.REVERSAL:
            raise ValidationError(
                {
                    "reverses": (
                        "Pembalikan tidak bisa dibatalkan lagi. Catat "
                        "penyesuaian baru."
                    ),
                },
            )

        existing = (
            RotationCreditTransaction.objects
            .filter(reverses=entry, is_deleted=False)
            .exists()
        )

        if existing:
            raise ValidationError(
                {
                    "reverses": (
                        "Transaksi ini sudah pernah dibatalkan. "
                        "Membalik dua kali membuat saldonya salah."
                    ),
                },
            )

        if not (reason or "").strip():
            raise ValidationError(
                {"reason": "Alasan pembalikan wajib diisi."},
            )

        return cls.record(
            employee=entry.employee,
            entry_type=CreditEntryType.REVERSAL,
            days=entry.days,
            reason=reason,
            source_type=entry.source_type,
            source_id=entry.source_id,
            plan=entry.plan,
            reverses=entry,
            user=user,
            allow_negative=True,
        )

    # ------------------------------------------------------------------
    # Saldo
    # ------------------------------------------------------------------

    @staticmethod
    def balance_for(employee) -> RotationCreditBalance:
        balance, _ = RotationCreditBalance.objects.get_or_create(
            employee=employee,
        )

        return balance

    @classmethod
    def _carry_only(cls, *, employee, conversion) -> None:
        """
        Menyimpan sisa hari yang belum jadi kredit.

        Tanpa ini, kelebihan 1 hari yang belum genap akan hilang setiap
        kali — dan setelah setahun pegawainya kehilangan beberapa
        kredit yang tidak pernah bisa ditelusuri.
        """
        balance = cls.balance_for(employee)

        balance.carried_excess_days = conversion.remainder_days
        balance.last_transaction_at = timezone.now()

        balance.save(
            update_fields=[
                "carried_excess_days",
                "last_transaction_at",
                "updated_at",
            ],
        )

    @classmethod
    def recalculate(cls, employee) -> RotationCreditBalance:
        """
        Menjumlahkan ulang saldo dari seluruh ledger.

        **Bukan** menambah/mengurangi inkremental. Penjumlahan ulang
        tidak bisa hanyut: satu transaksi yang gagal tercatat separuh
        tidak meninggalkan saldo yang salah selamanya.
        """
        balance = cls.balance_for(employee)

        entries = list(
            RotationCreditTransaction.objects
            .filter(employee=employee, is_deleted=False)
            .select_related("reverses")
        )

        totals = {
            "earned": ZERO,
            "used": ZERO,
            "adjustment": ZERO,
            "expired": ZERO,
        }

        running = ZERO

        for entry in entries:
            signed = entry.signed_days

            running += signed

            bucket = cls._bucket_of(entry)

            if bucket:
                totals[bucket] += abs(signed) if bucket != "adjustment" else signed

        latest = (
            RotationCreditTransaction.objects
            .filter(employee=employee, is_deleted=False)
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )

        # Sisa yang dibawa diambil dari transaksi konversi terakhir —
        # ia menggambarkan keadaan sesudah konversi itu, bukan
        # penjumlahan seluruh sisa.
        carried = (
            RotationCreditTransaction.objects
            .filter(
                employee=employee,
                is_deleted=False,
                entry_type=CreditEntryType.EARNED,
            )
            .order_by("-effective_date", "-id")
            .values_list("remainder_days", flat=True)
            .first()
        )

        balance.earned = totals["earned"]
        balance.used = totals["used"]
        balance.adjustment = totals["adjustment"]
        balance.expired = totals["expired"]
        balance.balance = running
        balance.last_transaction_at = latest

        if carried is not None:
            balance.carried_excess_days = carried

        balance.save()

        return balance

    @staticmethod
    def _bucket_of(entry) -> str | None:
        """Kelompok rekap untuk satu transaksi."""
        kind = entry.entry_type

        if kind == CreditEntryType.REVERSAL:
            kind = (
                entry.reverses.entry_type
                if entry.reverses_id
                else None
            )

            # Pembalikan masuk ke kelompok yang sama dengan yang
            # dibalikkannya, dengan tanda berlawanan — supaya rekap
            # "earned" tetap menggambarkan berapa yang benar-benar
            # berlaku, bukan berapa yang pernah dicatat.
            if kind == CreditEntryType.EARNED:
                return "earned"

            if kind == CreditEntryType.USED:
                return "used"

            return "adjustment"

        if kind == CreditEntryType.EARNED:
            return "earned"

        if kind == CreditEntryType.OPENING_BALANCE:
            return "earned"

        if kind == CreditEntryType.USED:
            return "used"

        if kind == CreditEntryType.EXPIRED:
            return "expired"

        if kind in {
            CreditEntryType.ADJUSTMENT_PLUS,
            CreditEntryType.ADJUSTMENT_MINUS,
        }:
            return "adjustment"

        return None

    # ------------------------------------------------------------------
    # Yang sengaja dilarang
    # ------------------------------------------------------------------

    @classmethod
    def update(cls, **kwargs):
        raise ValidationError(
            {
                "ledger": (
                    "Transaksi rotation credit tidak bisa disunting. "
                    "Catat penyesuaian (Adjustment +/−) atau pembalikan "
                    "(Reversal) — yang sudah tercatat harus tetap "
                    "terbaca apa adanya."
                ),
            },
        )

    @classmethod
    def soft_delete(cls, **kwargs):
        raise ValidationError(
            {
                "ledger": (
                    "Transaksi rotation credit tidak bisa dihapus. "
                    "Pakai Reversal — jejak 'pernah dicatat lalu "
                    "dibatalkan' justru yang paling dicari saat "
                    "angkanya dipersoalkan."
                ),
            },
        )
