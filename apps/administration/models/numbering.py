from django.db import models

from apps.core.models.base import BaseModel
from .organization import Company


class NumberingSequence(BaseModel):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="numbering_sequences",
    )

    module = models.CharField(max_length=50)
    document_type = models.CharField(max_length=80)

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)

    prefix = models.CharField(max_length=50, blank=True)
    suffix = models.CharField(max_length=30, blank=True)

    separator = models.CharField(
        max_length=5,
        default="/",
        blank=True,
    )

    padding = models.PositiveSmallIntegerField(default=5)

    # Berapa digit tahun yang ikut dicetak. Empat itu bawaan dan itu
    # yang dipakai seluruh deret dokumen yang sudah ada
    # (TR-2026-00001). Dua dibutuhkan nomor pegawai, yang formatnya
    # menempel tanpa pemisah: KW260001.
    #
    # Ditaruh di master penomoran, bukan di kode modul HR: formatnya jadi
    # bisa diubah dari layar setting seperti pola lain, dan modul
    # berikutnya yang butuh tahun dua digit tidak perlu menulis
    # formatternya sendiri.
    year_digits = models.PositiveSmallIntegerField(
        default=4,
        choices=[(2, "2 digit (26)"), (4, "4 digit (2026)")],
    )

    current_number = models.PositiveIntegerField(default=0)

    reset_yearly = models.BooleanField(default=True)
    reset_monthly = models.BooleanField(default=False)

    class Meta:
        db_table = "master_numbering_sequence"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "company",
                    "module",
                    "document_type",
                ],
                name="uniq_numbering_sequence",
            ),
        ]

        ordering = [
            "module",
            "document_type",
            "name",
        ]

    def __str__(self):
        return self.name


class DocumentSeries(BaseModel):
    sequence = models.ForeignKey(
        NumberingSequence,
        on_delete=models.CASCADE,
        related_name="series",
    )

    year = models.PositiveIntegerField()

    month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "master_document_series"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "sequence",
                    "year",
                    "month",
                ],
                name="uniq_document_series",
            ),
        ]

        ordering = [
            "-year",
            "-month",
        ]

    def __str__(self):
        if self.month:
            return f"{self.sequence.name} {self.year}/{self.month:02d}"
        return f"{self.sequence.name} {self.year}"