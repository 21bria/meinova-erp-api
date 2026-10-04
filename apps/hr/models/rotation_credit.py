"""
Rotation credit: saldo hari yang lahir dari kelebihan kerja di site.

**Terpisah total dari cuti tahunan.** Bukan `LeaveType`, bukan
`LeaveBalance`, tidak punya tahun. Menaruhnya di sana akan membuatnya
ikut terhitung di kartu cuti dan bisa dipotong lewat modul Cuti —
padahal ini hak yang lahir dari roster dan dipakai untuk memajukan
field break, bukan untuk mengambil cuti.

Ledger, bukan angka
-------------------
Yang disimpan **transaksinya**, dan saldo dihitung darinya. Alasannya
satu: saat pegawai bertanya "kenapa saldo saya 12", jawabannya harus
bisa ditunjuk baris per baris — kapan lahir, dari dokumen mana, siapa
yang mencatat.

Konsekuensinya keras dan ditegakkan service:

* transaksi **tidak pernah** di-UPDATE dan tidak pernah dihapus
* koreksi = `ADJUSTMENT_PLUS` / `ADJUSTMENT_MINUS`
* pembatalan = `REVERSAL` yang menunjuk barisnya, satu kali saja

Sisa yang dibawa adalah **hari kerja yang belum terkonversi**, bukan
pecahan kredit. 7 hari lebih dengan rasio 3 = 2 kredit, sisa 1 hari —
dan "1 hari lembur site kamu belum genap jadi kredit" bisa dijelaskan,
sementara "0,33 kredit" tidak.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .employee import Employee


class CreditEntryType(models.TextChoices):
    OPENING_BALANCE = "opening_balance", "Opening Balance"
    EARNED = "earned", "Earned"
    USED = "used", "Used"
    ADJUSTMENT_PLUS = "adjustment_plus", "Adjustment (+)"
    ADJUSTMENT_MINUS = "adjustment_minus", "Adjustment (−)"
    EXPIRED = "expired", "Expired"
    REVERSAL = "reversal", "Reversal"


# Arah tiap jenis terhadap saldo. Disimpan sebagai peta, bukan
# disimpulkan dari nama: `REVERSAL` arahnya ditentukan transaksi yang
# dibalikkannya, dan itu tidak bisa dibaca dari kodenya sendiri.
CREDIT_SIGN = {
    CreditEntryType.OPENING_BALANCE: 1,
    CreditEntryType.EARNED: 1,
    CreditEntryType.ADJUSTMENT_PLUS: 1,
    CreditEntryType.USED: -1,
    CreditEntryType.ADJUSTMENT_MINUS: -1,
    CreditEntryType.EXPIRED: -1,
}


class RotationCreditTransaction(BaseModel):
    """
    Satu baris ledger. Append-only.

    `days` **selalu positif**; arahnya dari `entry_type`. Menyimpan
    angka negatif berarti ada dua cara menulis pengurangan yang sama,
    dan penjumlahannya jadi bergantung pada mana yang kebetulan dipakai.
    """

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="rotation_credits",
    )

    entry_type = models.CharField(
        max_length=20,
        choices=CreditEntryType.choices,
    )

    days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        help_text="Selalu positif. Arahnya ditentukan Entry Type.",
    )

    transaction_date = models.DateField(
        help_text="Kapan transaksi ini dicatat.",
    )

    effective_date = models.DateField(
        help_text=(
            "Kapan berlakunya. Boleh mundur — saldo awal dari sistem "
            "lama berlaku sejak tanggal go-live, bukan sejak diketik."
        ),
    )

    # Asal-usul, ditunjuk pasangan string. Pola yang sama dengan
    # `WorkflowInstance`: ledger tidak perlu mengenal model modul mana
    # pun, dan tidak ada FK yang menghalangi dokumen sumbernya dihapus.
    source_type = models.CharField(max_length=50, blank=True, default="")
    source_id = models.CharField(max_length=50, blank=True, default="")

    plan = models.ForeignKey(
        "hr.SiteRotation",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotation_credits",
    )

    segment = models.ForeignKey(
        "hr.RotationPeriod",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rotation_credits",
    )

    # Hari kelebihan yang **belum** terkonversi jadi kredit penuh.
    # Dibawa ke konversi berikutnya kalau policy menyalakan carry.
    remainder_days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=(
            "Sisa hari kerja yang belum genap jadi satu kredit."
        ),
    )

    # Rasio yang dipakai saat transaksi ini lahir, dibekukan. Policy
    # yang diubah tahun depan tidak boleh mengubah arti angka yang sudah
    # tercatat.
    conversion_ratio = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    reason = models.TextField(blank=True, default="")

    reverses = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversed_by",
        help_text="Transaksi yang dibatalkan baris ini.",
    )

    class Meta:
        db_table = "hr_rotation_credit_transaction"

        ordering = ["-effective_date", "-id"]

        constraints = [
            # Satu pembalikan per transaksi. Membalik dua kali membuat
            # saldonya salah, dan tidak ada satu pun layar yang
            # memperlihatkannya.
            models.UniqueConstraint(
                fields=["reverses"],
                condition=Q(is_deleted=False) & Q(reverses__isnull=False),
                name="uniq_active_rotation_credit_reversal",
            ),
        ]

        indexes = [
            models.Index(
                fields=["employee", "effective_date"],
                name="idx_rotation_credit_emp_date",
            ),
            models.Index(
                fields=["entry_type"],
                name="idx_rotation_credit_type",
            ),
            models.Index(
                fields=["source_type", "source_id"],
                name="idx_rotation_credit_source",
            ),
        ]

    @property
    def signed_days(self) -> Decimal:
        """
        Kontribusi baris ini ke saldo.

        `REVERSAL` mengambil arah **berlawanan** dari transaksi yang
        dibalikkannya: membatalkan `EARNED` berarti mengurangi, dan
        membatalkan `USED` berarti mengembalikan.
        """
        amount = self.days or Decimal("0.00")

        if self.entry_type == CreditEntryType.REVERSAL:
            if self.reverses_id is None:
                return Decimal("0.00")

            return -CREDIT_SIGN.get(
                self.reverses.entry_type, 0,
            ) * amount

        return CREDIT_SIGN.get(self.entry_type, 0) * amount

    def clean(self):
        super().clean()

        errors = {}

        if self.days is not None and self.days <= 0:
            errors["days"] = (
                "Jumlah hari harus lebih besar dari nol. Pengurangan "
                "dicatat lewat Entry Type, bukan lewat angka negatif."
            )

        if self.entry_type == CreditEntryType.REVERSAL:
            if not self.reverses_id:
                errors["reverses"] = (
                    "Pembalikan harus menunjuk transaksi yang "
                    "dibatalkannya."
                )
            elif self.reverses.entry_type == CreditEntryType.REVERSAL:
                errors["reverses"] = (
                    "Pembalikan tidak bisa membatalkan pembalikan lain. "
                    "Catat penyesuaian baru."
                )
            elif self.reverses.employee_id != self.employee_id:
                errors["reverses"] = (
                    "Transaksi itu milik pegawai lain."
                )
        elif self.reverses_id:
            errors["reverses"] = (
                "Kolom ini hanya diisi untuk Entry Type Reversal."
            )

        if (
            self.entry_type
            in {
                CreditEntryType.ADJUSTMENT_PLUS,
                CreditEntryType.ADJUSTMENT_MINUS,
                CreditEntryType.EXPIRED,
                CreditEntryType.REVERSAL,
            }
            and not (self.reason or "").strip()
        ):
            errors["reason"] = (
                "Alasan wajib diisi untuk penyesuaian, kedaluwarsa, dan "
                "pembalikan — saldo yang berubah tanpa alasan tidak bisa "
                "dijelaskan ke pegawainya."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee_id} {self.get_entry_type_display()} "
            f"{self.days} ({self.effective_date})"
        )


class RotationCreditBalance(BaseModel):
    """
    Cache saldo per pegawai.

    **Dihitung ulang dari ledger** setiap kali ada transaksi — bukan
    ditambah/dikurangi inkremental. Alasannya sama dengan
    `LeaveBalance.used`: penjumlahan ulang tidak bisa hanyut, dan
    saldonya perlu bisa disortir dan difilter langsung di tabel.
    """

    employee = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        related_name="rotation_credit_balance",
    )

    earned = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00"),
    )
    used = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00"),
    )
    adjustment = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00"),
    )
    expired = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00"),
    )

    balance = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal("0.00"),
    )

    # Hari kerja lebih yang belum genap jadi satu kredit. Terpisah dari
    # saldo karena satuannya berbeda: yang ini hari kerja, yang di atas
    # hari kredit.
    carried_excess_days = models.DecimalField(
        max_digits=6, decimal_places=2, default=Decimal("0.00"),
    )

    last_transaction_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "hr_rotation_credit_balance"

        ordering = ["employee__employee_number"]

        indexes = [
            models.Index(
                fields=["balance"],
                name="idx_rotation_credit_balance",
            ),
        ]

    def __str__(self):
        return f"{self.employee_id}: {self.balance}"
