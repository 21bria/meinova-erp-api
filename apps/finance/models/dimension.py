"""
Dimensi akuntansi.

Arsitekturnya **hibrida**, dan pilihan itu dijelaskan di sini karena
ia yang menentukan apakah laporan masih bisa dibuka dua tahun lagi:

* **Tujuh dimensi inti adalah kolom FK terindeks di `JournalLine`** —
  company, branch, location, division, department, section, cost
  center. Ketujuhnya persis `SCOPE_TYPES` di `apps/accounts/scoping.py`,
  dan itu bukan kebetulan: dimensi inti adalah unit organisasi yang
  sudah dipakai menyaring baris di seluruh ERP ini, jadi memetakannya
  jadi kolom membuat cakupan data, filter layar, dan pengelompokan
  laporan memakai satu jalan yang sama dan terindeks.
* **Dimensi lain memakai baris `JournalLineDimension`** — project,
  customer, vendor, employee, product, warehouse, asset, contract, dan
  apa pun yang datang kemudian. Ditambahkan dari layar setting, tanpa
  migrasi.

**Kenapa tidak semuanya generik:** Trial Balance per cost center pada
sepuluh juta baris jurnal berarti join ke tabel dimensi yang barisnya
tujuh kali lebih banyak, untuk pertanyaan yang ditanyakan setiap hari.
Kolom terindeks menjawabnya tanpa join.

**Kenapa tidak semuanya kolom:** menambah dimensi berarti migrasi pada
tabel terbesar di sistem, dan setiap tenant membayar kolom yang cuma
dipakai satu tenant. Dua puluh FK nullable pada `JournalLine` adalah
bentuk yang §6 secara khusus meminta dihindari.

**Batas yang harus disadari:** dimensi generik tidak ikut
`DataScopeService`. Cakupan data disaring lewat kolom inti, jadi
dimensi tambahan boleh dipakai mengelompokkan dan menyaring laporan,
tapi tidak pernah menjadi batas keamanan. Begitu Administration punya
master Project dan `AuthorityResourceType.PROJECT` bisa dipetakan,
project naik jadi dimensi inti lewat satu migrasi — dan `is_core` di
bawah ini yang menandai perpindahan itu.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .choices import DimensionDataType


# Dimensi inti — kolom pada `JournalLine`, bukan baris
# `JournalLineDimension`. Urutannya = urutan kolom di layar dan di
# laporan.
CORE_DIMENSIONS = (
    "company",
    "branch",
    "location",
    "division",
    "department",
    "section",
    "cost_center",
)


class AccountingDimension(BaseModel):
    """
    Satu dimensi yang boleh menempel pada baris jurnal.

    Baris untuk dimensi inti **ikut dibuat** (`is_core=True`), dan itu
    disengaja: layar setting harus memperlihatkan seluruh dimensi yang
    berlaku dalam satu daftar, bukan tujuh yang tidak kelihatan di mana
    pun plus beberapa yang kelihatan. Yang membedakannya cuma tempat
    nilainya disimpan, dan itu urusan mesin.
    """

    code = models.CharField(
        max_length=50,
        help_text=(
            "Pengenal teknis, dipakai kebijakan akuntansi dan API. "
            "Huruf kecil dan garis bawah, mis. `project`."
        ),
    )

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")

    data_type = models.CharField(
        max_length=20,
        choices=DimensionDataType.choices,
        default=DimensionDataType.REFERENCE,
    )

    # Endpoint lookup untuk dropdown di form jurnal. Kosong = nilainya
    # diketik. Tidak divalidasi terhadap daftar rute: dimensi tambahan
    # boleh menunjuk modul yang belum ada saat dimensinya dibuat.
    lookup_endpoint = models.CharField(max_length=255, blank=True, default="")

    # Kunci label pada baris lookup. Kosong = `label`.
    lookup_display_key = models.CharField(max_length=80, blank=True, default="")

    is_core = models.BooleanField(
        default=False,
        editable=False,
        help_text=(
            "Disimpan sebagai kolom pada baris jurnal, bukan sebagai "
            "baris dimensi. Ditentukan sistem."
        ),
    )

    is_required = models.BooleanField(
        default=False,
        help_text=(
            "Wajib diisi pada setiap baris jurnal. Kewajiban yang hanya "
            "berlaku untuk sebagian akun atau sebagian kejadian "
            "dinyatakan di kebijakan akuntansi, bukan di sini."
        ),
    )

    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "finance_accounting_dimension"

        ordering = ["sort_order", "name"]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_finance_dimension_code",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def clean(self):
        super().clean()

        if self.code:
            self.code = self.code.strip().lower().replace("-", "_")

        if self.is_core and self.code not in CORE_DIMENSIONS:
            raise ValidationError({
                "code": (
                    "Dimensi inti hanya boleh salah satu dari: "
                    f"{', '.join(CORE_DIMENSIONS)}."
                ),
            })


class JournalLineDimension(BaseModel):
    """
    Nilai satu dimensi tambahan pada satu baris jurnal.

    Tidak pernah disunting sendiri — ia lahir dan mati bersama baris
    jurnalnya, dan baris jurnal yang sudah diposting tidak bisa
    disentuh. `CASCADE` karena itu benar di sini: tidak ada keadaan
    "baris dimensi yatim" yang punya arti.
    """

    journal_line = models.ForeignKey(
        "finance.JournalLine",
        on_delete=models.CASCADE,
        related_name="dimension_values",
    )

    dimension = models.ForeignKey(
        AccountingDimension,
        on_delete=models.PROTECT,
        related_name="line_values",
    )

    # Salinan kode dimensi. Denormalisasi yang disengaja: laporan
    # mengelompokkan lewat kode, dan tanpa kolom ini setiap pengelompokan
    # menyeret join ke master dimensi hanya untuk membaca satu string
    # yang tidak pernah berubah.
    dimension_code = models.CharField(max_length=50, db_index=True)

    value_id = models.BigIntegerField(null=True, blank=True)
    value_text = models.CharField(max_length=255, blank=True, default="")

    # Label saat baris jurnal dibuat. Dibekukan, bukan dibaca ulang:
    # jurnal yang sudah diposting adalah fakta, dan proyek yang berganti
    # nama tahun depan tidak boleh mengubah bunyi dokumen tahun ini.
    value_label = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "finance_journal_line_dimension"

        ordering = ["journal_line_id", "dimension_code"]

        constraints = [
            models.UniqueConstraint(
                fields=["journal_line", "dimension"],
                name="uniq_finance_line_dimension",
            ),
        ]

        indexes = [
            # Bentuk query laporan berdimensi: "seluruh baris yang
            # project-nya X". Kode + nilai, bukan FK dimensi, supaya
            # tidak perlu menyelesaikan pk dimensinya lebih dulu.
            models.Index(
                fields=["dimension_code", "value_id"],
                name="idx_fin_dimval_code_value",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.dimension_code}={self.value_label or self.value_id}"
