"""
Tahun buku dan periode akuntansi.

**Januari–Desember tidak diasumsikan di satu baris pun.** Tanggal
awal dan akhir diketik, dan periodenya diturunkan dari situ — jadi
tahun buku 1 April 2026 – 31 Maret 2027 berjalan sama saja dengan tahun
kalender. Jumlah periode juga tidak dipatok dua belas: perusahaan yang
memakai empat periode kuartalan, atau tiga belas periode empat
mingguan, menyusunnya sendiri.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .choices import FiscalYearStatus, PeriodStatus


class FiscalYear(BaseModel):
    """Satu tahun buku milik satu perusahaan."""

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="fiscal_years",
    )

    code = models.CharField(max_length=30)
    name = models.CharField(max_length=150)

    start_date = models.DateField()
    end_date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=FiscalYearStatus.choices,
        default=FiscalYearStatus.OPEN,
    )

    # Penanda tampilan, bukan penjagaan. Yang menentukan sebuah jurnal
    # boleh diposting adalah tanggal posting-nya jatuh di periode yang
    # mana dan periode itu berstatus apa — bukan tahun buku mana yang
    # sedang ditandai berjalan. Dipakai form untuk memilihkan tahun buku
    # yang masuk akal, dan dashboard untuk memilih angka mana yang
    # ditampilkan lebih dulu.
    is_current = models.BooleanField(default=False)

    # Jejak penutupan. Ada di sini **dan** di periode, dan keduanya
    # memang menjawab hal berbeda: tahun buku ditutup sekali di akhir
    # tahun, periode ditutup dua belas kali. Kolomnya kembar supaya
    # baris asal `master_fiscal_year` tidak kehilangan jejaknya waktu
    # kepemilikannya pindah ke Finance.
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "finance_fiscal_year"

        ordering = ["company_id", "-start_date"]

        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                condition=Q(is_deleted=False),
                name="uniq_active_finance_fiscal_year_code",
            ),
            models.CheckConstraint(
                condition=Q(end_date__gt=models.F("start_date")),
                name="ck_finance_fiscal_year_dates",
            ),
        ]

        indexes = [
            models.Index(
                fields=["company", "start_date", "end_date"],
                name="idx_fin_fy_company_range",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.company_id})"

    def contains(self, value) -> bool:
        return self.start_date <= value <= self.end_date

    def clean(self):
        super().clean()

        errors: dict[str, str] = {}

        if self.start_date and self.end_date:
            if self.end_date <= self.start_date:
                errors["end_date"] = (
                    "Tanggal akhir harus sesudah tanggal mulai."
                )
            else:
                self._assert_no_overlap(errors)

        if errors:
            raise ValidationError(errors)

    def _assert_no_overlap(self, errors: dict) -> None:
        """
        Dua tahun buku yang beririsan pada satu perusahaan ditolak.

        Kalau dibiarkan, satu tanggal posting jatuh di dua tahun buku
        sekaligus dan yang dipakai ditentukan urutan `id` — laporan
        tahunannya benar sendiri-sendiri dan tidak pernah cocok kalau
        dijumlahkan.

        Tidak ada pengecualian yang didukung hari ini. Perusahaan yang
        mengubah akhir tahun bukunya menutup tahun berjalan lebih awal
        lalu membuka tahun transisi yang lebih pendek — dua tahun buku
        yang tidak beririsan, dan itu memang cara yang benar.
        """
        if self.company_id is None:
            return

        clash = (
            FiscalYear.objects
            .filter(
                company_id=self.company_id,
                is_deleted=False,
                start_date__lte=self.end_date,
                end_date__gte=self.start_date,
            )
            .exclude(pk=self.pk)
            .order_by("start_date")
            .first()
        )

        if clash is not None:
            errors["start_date"] = (
                f"Beririsan dengan tahun buku '{clash.code}' "
                f"({clash.start_date} – {clash.end_date})."
            )


class AccountingPeriod(BaseModel):
    """
    Satu periode di dalam sebuah tahun buku.

    `company` sengaja **tidak** disimpan di sini — ia milik tahun
    bukunya, dan menyalinnya berarti dua sumber untuk satu fakta yang
    bisa berselisih saat tahun bukunya dipindah. Yang membutuhkannya
    membaca `fiscal_year__company`; `Journal` dan `JournalLine`
    menyimpannya sendiri karena keduanya memang dokumen milik
    perusahaan, bukan turunan tahun buku.
    """

    fiscal_year = models.ForeignKey(
        FiscalYear,
        on_delete=models.PROTECT,
        related_name="periods",
    )

    period_number = models.PositiveSmallIntegerField()

    code = models.CharField(max_length=30)
    name = models.CharField(max_length=150)

    start_date = models.DateField()
    end_date = models.DateField()

    status = models.CharField(
        max_length=20,
        choices=PeriodStatus.choices,
        default=PeriodStatus.OPEN,
    )

    # ------------------------------------------------------------------
    # Jejak penutupan dan pembukaan kembali
    # ------------------------------------------------------------------
    #
    # Membuka kembali periode yang sudah ditutup adalah tindakan yang
    # mengubah angka yang mungkin sudah dilaporkan ke luar. Ia harus
    # meninggalkan jejak yang bisa dibaca tanpa membuka tabel audit —
    # karena pertanyaannya ("kenapa Agustus dibuka lagi") ditanyakan di
    # layar periode, bukan di layar audit.

    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    reopen_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "finance_accounting_period"

        ordering = ["fiscal_year_id", "period_number"]

        constraints = [
            models.UniqueConstraint(
                fields=["fiscal_year", "period_number"],
                condition=Q(is_deleted=False),
                name="uniq_active_finance_period_number",
            ),
            models.UniqueConstraint(
                fields=["fiscal_year", "code"],
                condition=Q(is_deleted=False),
                name="uniq_active_finance_period_code",
            ),
            models.CheckConstraint(
                condition=Q(end_date__gte=models.F("start_date")),
                name="ck_finance_period_dates",
            ),
        ]

        indexes = [
            models.Index(
                fields=["fiscal_year", "start_date", "end_date"],
                name="idx_fin_period_fy_range",
            ),
            models.Index(
                fields=["status"],
                name="idx_fin_period_status",
            ),
        ]

        # Dua wewenang yang tidak punya model sendiri, jadi ia
        # menumpang model yang paling dekat artinya. Keduanya izin
        # Django biasa — artinya keduanya muncul di layar Roles dan bisa
        # dicentang per tenant, bukan daftar kode role yang ditanam di
        # kode dan menuntut rilis untuk diubah.
        permissions = [
            (
                "post_soft_closed_period",
                "Can post to soft-closed accounting period",
            ),
            (
                "reopen_locked_period",
                "Can reopen locked accounting period",
            ),
        ]

    def __str__(self) -> str:
        return self.code

    @property
    def company_id(self):
        return self.fiscal_year.company_id

    def contains(self, value) -> bool:
        return self.start_date <= value <= self.end_date

    def clean(self):
        super().clean()

        errors: dict[str, str] = {}

        if not (self.start_date and self.end_date):
            if errors:
                raise ValidationError(errors)

            return

        if self.end_date < self.start_date:
            errors["end_date"] = "Tanggal akhir tidak boleh sebelum tanggal mulai."

            raise ValidationError(errors)

        if self.fiscal_year_id:
            year = self.fiscal_year

            if not (year.contains(self.start_date) and year.contains(self.end_date)):
                errors["start_date"] = (
                    f"Periode harus berada di dalam tahun buku "
                    f"'{year.code}' ({year.start_date} – {year.end_date})."
                )
            else:
                self._assert_no_overlap(errors)

        if errors:
            raise ValidationError(errors)

    def _assert_no_overlap(self, errors: dict) -> None:
        clash = (
            AccountingPeriod.objects
            .filter(
                fiscal_year_id=self.fiscal_year_id,
                is_deleted=False,
                start_date__lte=self.end_date,
                end_date__gte=self.start_date,
            )
            .exclude(pk=self.pk)
            .order_by("start_date")
            .first()
        )

        if clash is not None:
            errors["start_date"] = (
                f"Beririsan dengan periode '{clash.code}' "
                f"({clash.start_date} – {clash.end_date})."
            )
