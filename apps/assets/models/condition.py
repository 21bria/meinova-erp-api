from django.conf import settings
from django.db import models

from .choices import AssetCondition, ConditionSource


class AssetConditionLog(models.Model):
    """
    Riwayat kondisi aset — **append-only**.

    Bukan turunan `BaseModel`: baris ini tidak punya jalur hapus maupun
    sunting sama sekali, jadi kolom soft delete hanya akan menjadi pintu
    belakang. `save()` menolak update dan `delete()` selalu menolak —
    kalau ditembak dari shell atau kode lain sekalipun.

    `Asset.condition` adalah salinan baris terakhir; keduanya ditulis
    `AssetService` dalam satu transaksi.
    """

    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.PROTECT,
        related_name="condition_logs",
    )

    # Kosong hanya untuk REGISTRATION — kondisi pertama tidak punya
    # pendahulu.
    previous_condition = models.CharField(
        max_length=20,
        choices=AssetCondition.choices,
        blank=True,
        default="",
    )
    new_condition = models.CharField(
        max_length=20,
        choices=AssetCondition.choices,
    )

    source = models.CharField(
        max_length=20,
        choices=ConditionSource.choices,
    )

    effective_at = models.DateTimeField()

    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    note = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assets_asset_condition_log"
        ordering = ["asset", "effective_at", "id"]
        verbose_name = "Asset Condition Log"
        verbose_name_plural = "Asset Condition Logs"

        indexes = [
            models.Index(
                fields=["asset", "effective_at"],
                name="idx_assets_condlog_asset_at",
            ),
        ]

    def __str__(self):
        return f"{self.asset_id}: {self.previous_condition or '-'} → {self.new_condition}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError(
                "Riwayat kondisi aset tidak bisa diubah sesudah tercatat."
            )

        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError(
            "Riwayat kondisi aset tidak bisa dihapus."
        )
