from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from .overtime_group import OvertimeGroup


class OvertimeGroupTier(BaseModel):
    """
    Satu tingkat pengali di dalam sebuah `OvertimeGroup`.

    **Kenapa tabel anak, bukan kolom tambahan di master.**
    `OvertimeGroup.hourly_multiplier` satu `DecimalField`. Kebijakan
    "jam pertama 1,5x, jam berikutnya 2x" bukan satu angka — ia daftar
    rentang, dan jumlah rentangnya berbeda antar perusahaan. Satu
    kolom tidak bisa menyimpannya, dan menambah `multiplier_2`,
    `multiplier_3` berarti membekukan jumlah tingkat di skema.

    Bentuknya mengikuti dua pola yang sudah ada di modul ini:
    hubungan induk-anak dari `AllowanceTemplateLine` (FK ke masternya,
    `sequence`, unik per induk) dan rentang berbatas dari
    `PayrollTaxBracket` (`*_from` / `*_to` yang boleh kosong untuk
    lapisan teratas). Tidak ada dialek ketiga yang diperkenalkan.

    **Rentangnya jam lembur kumulatif, bukan jam dinding.** `hour_from`
    0 sampai `hour_to` 1 berarti "jam lembur pertama", apa pun pukul
    berapa ia terjadi. Payroll tidak pernah memutuskan jam mana yang
    lembur — itu urusan HR/Attendance; yang di sini cuma harga per
    jamnya.
    """

    group = models.ForeignKey(
        OvertimeGroup,
        on_delete=models.CASCADE,
        related_name="tiers",
    )

    sequence = models.PositiveIntegerField(default=1)

    hour_from = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=0,
        help_text=(
            "Batas bawah jam lembur kumulatif, ikut terhitung. 0 = "
            "mulai dari jam lembur pertama."
        ),
    )

    hour_to = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Kosong = tingkat teratas, tanpa batas atas.",
    )

    multiplier = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=1,
        help_text="Pengali upah per jam pada rentang ini, mis. 1,5.",
    )

    description = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "payroll_overtime_group_tier"
        ordering = ["group__code", "sequence", "hour_from"]
        verbose_name = "Overtime Tier"
        verbose_name_plural = "Overtime Tiers"

        constraints = [
            models.UniqueConstraint(
                fields=["group", "sequence"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_overtime_tier_sequence",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.hour_from is not None and self.hour_from < 0:
            errors["hour_from"] = "Batas bawah tidak boleh negatif."

        if (
            self.hour_to is not None
            and self.hour_from is not None
            and self.hour_to <= self.hour_from
        ):
            errors["hour_to"] = (
                "Batas atas harus lebih besar dari batas bawah."
            )

        if self.multiplier is not None and self.multiplier <= 0:
            errors["multiplier"] = (
                "Pengali harus lebih besar dari nol."
            )

        if errors:
            raise ValidationError(errors)

    @property
    def span(self) -> Decimal | None:
        """Lebar rentang dalam jam; `None` untuk tingkat teratas."""
        if self.hour_to is None:
            return None

        return self.hour_to - self.hour_from

    def __str__(self) -> str:
        upper = self.hour_to if self.hour_to is not None else "~"

        return f"{self.hour_from} - {upper} @ {self.multiplier}x"
