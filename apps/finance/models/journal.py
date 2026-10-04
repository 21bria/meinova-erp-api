"""
Jurnal dan barisnya — transaksi akuntansi yang sesungguhnya.

**Baris jurnal adalah sumber kebenaran buku besar.** Tidak ada tabel
saldo yang bisa disunting sendiri; Trial Balance dan Account Ledger
keduanya dihitung dari tabel ini, dan apa pun ringkasan yang
ditambahkan nanti wajib bisa dibangun ulang dari sini.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .choices import JournalStatus, JournalType


# Presisi uang, seragam dengan payroll (`DecimalField(18, 2)`).
# Delapan belas digit menampung Rupiah sampai skala triliunan tanpa
# pembulatan tersembunyi. **Tidak pernah float** — 0.1 + 0.2 yang
# bukan 0.3 di neraca berarti debit dan kredit tidak pernah cocok, dan
# selisihnya muncul di tempat yang tidak bisa ditelusuri.
AMOUNT_DIGITS = 18
AMOUNT_PLACES = 2

# Kurs seragam dengan `administration.ExchangeRate`.
RATE_DIGITS = 20
RATE_PLACES = 6

ZERO = Decimal("0.00")


def _amount(**kwargs) -> models.DecimalField:
    return models.DecimalField(
        max_digits=AMOUNT_DIGITS,
        decimal_places=AMOUNT_PLACES,
        default=ZERO,
        **kwargs,
    )


class Journal(BaseModel):
    """
    Kepala dokumen jurnal.

    Nomornya diterbitkan **saat dokumen dibuat**, bukan saat diposting.
    Itu pilihan sadar dan punya harga: draf yang dibatalkan meninggalkan
    lompatan nomor. Yang dibeli dengan harga itu adalah dokumen yang
    punya identitas sejak menit pertama — bisa disebut di email, dicetak
    sebagai lampiran, dan dirujuk approver sebelum ada yang menekan
    Post. Pola yang sama dengan Travel Request dan Employee Action di
    modul HR, dan seragam lebih berharga daripada deret yang rapat.
    """

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="journals",
    )

    journal_number = models.CharField(max_length=60, blank=True, default="")

    fiscal_year = models.ForeignKey(
        "finance.FiscalYear",
        on_delete=models.PROTECT,
        related_name="journals",
    )

    accounting_period = models.ForeignKey(
        "finance.AccountingPeriod",
        on_delete=models.PROTECT,
        related_name="journals",
    )

    journal_type = models.CharField(
        max_length=20,
        choices=JournalType.choices,
        default=JournalType.MANUAL,
    )

    # ------------------------------------------------------------------
    # Dokumen sumber
    # ------------------------------------------------------------------
    #
    # Tiga kolom teks, bukan `GenericForeignKey` — pola yang sama persis
    # dengan `WorkflowInstance`, dan alasannya sama: Finance tidak boleh
    # mengenal model modul mana pun. Payroll, Inventory, dan Procurement
    # menyambung tanpa satu baris pun kode baru di sini, dan tanpa
    # `ContentType` yang bergeser saat app di-rename.
    #
    # Harganya tidak ada integritas referensial di level database.
    # Penggantinya: penghapusan di codebase ini selalu soft, dan
    # `AccountingEvent.idempotency_key` yang menjaga satu kejadian tidak
    # menerbitkan dua jurnal.

    source_module = models.CharField(max_length=50, blank=True, default="")
    source_type = models.CharField(max_length=80, blank=True, default="")
    source_id = models.CharField(max_length=80, blank=True, default="")
    source_reference = models.CharField(max_length=255, blank=True, default="")

    posting_date = models.DateField(
        help_text=(
            "Tanggal pembukuan — inilah yang menentukan periode dan "
            "masuk ke buku besar."
        ),
    )

    document_date = models.DateField(
        null=True,
        blank=True,
        help_text=(
            "Tanggal dokumen sumbernya (tanggal faktur, tanggal slip). "
            "Kosong = sama dengan tanggal pembukuan."
        ),
    )

    # ------------------------------------------------------------------
    # Mata uang
    # ------------------------------------------------------------------

    currency = models.ForeignKey(
        "administration.Currency",
        on_delete=models.PROTECT,
        related_name="journals",
        help_text="Mata uang transaksi — yang diketik operatornya.",
    )

    # Disimpan di dokumen, bukan dibaca dari master saat laporan
    # disusun. Mata uang pelaporan sebuah perusahaan boleh berubah
    # (redenominasi, perubahan fungsional), dan jurnal tahun lalu tetap
    # harus terbaca dalam mata uang yang berlaku saat ia dibukukan.
    base_currency = models.ForeignKey(
        "administration.Currency",
        on_delete=models.PROTECT,
        related_name="journals_as_base",
        help_text="Mata uang buku besar perusahaan saat jurnal dibuat.",
    )

    exchange_rate = models.DecimalField(
        max_digits=RATE_DIGITS,
        decimal_places=RATE_PLACES,
        default=Decimal("1.000000"),
    )

    description = models.TextField(blank=True, default="")

    status = models.CharField(
        max_length=20,
        choices=JournalStatus.choices,
        default=JournalStatus.DRAFT,
        db_index=True,
    )

    # ------------------------------------------------------------------
    # Total — turunan, ditulis `JournalService.sync_totals()`
    # ------------------------------------------------------------------
    #
    # Disimpan supaya daftar jurnal tidak menjumlahkan barisnya satu per
    # satu (N+1 pada layar yang paling sering dibuka). Selalu ditulis
    # ulang dari barisnya di dalam transaksi yang sama, tidak pernah
    # dari nilai kiriman klien.

    total_debit = _amount()
    total_credit = _amount()
    base_total_debit = _amount()
    base_total_credit = _amount()

    # ------------------------------------------------------------------
    # Pembalikan
    # ------------------------------------------------------------------
    #
    # Dua kolom, dan keduanya memang saling membalik. `reversal_of`
    # menjawab "jurnal ini membalik yang mana"; `reversed_by` menjawab
    # "jurnal ini sudah dibalik oleh siapa". Menyimpan cuma satu berarti
    # salah satu pertanyaan dijawab lewat pemindaian tabel, dan
    # keduanya ditanyakan di layar daftar.

    reversal_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversals",
    )

    reversed_by = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    # ------------------------------------------------------------------
    # Jejak
    # ------------------------------------------------------------------

    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    posted_at = models.DateTimeField(null=True, blank=True)
    posted_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by_user = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        "accounts.User", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    # Alasan perubahan keadaan terakhir — penolakan, pembatalan,
    # pembalikan. Satu kolom, bukan tiga: yang dibaca orang selalu
    # "kenapa dokumen ini begini sekarang", dan tiga kolom yang dua di
    # antaranya selalu kosong cuma membuat layar penuh.
    status_reason = models.TextField(blank=True, default="")

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "finance_journal"

        ordering = ["-posting_date", "-id"]

        constraints = [
            models.UniqueConstraint(
                fields=["company", "journal_number"],
                condition=Q(is_deleted=False) & ~Q(journal_number=""),
                name="uniq_active_finance_journal_number",
            ),
            models.CheckConstraint(
                condition=Q(exchange_rate__gt=0),
                name="ck_finance_journal_rate_positive",
            ),
        ]

        indexes = [
            # Bentuk query utama daftar jurnal dan seluruh laporan:
            # satu perusahaan, satu rentang tanggal.
            models.Index(
                fields=["company", "posting_date"],
                name="idx_fin_journal_company_date",
            ),
            models.Index(
                fields=["company", "status", "posting_date"],
                name="idx_fin_journal_co_status_date",
            ),
            models.Index(
                fields=["accounting_period", "status"],
                name="idx_fin_journal_period_status",
            ),
            # Penelusuran balik dari dokumen sumber ke jurnalnya —
            # separuh dari syarat "traceable both directions".
            models.Index(
                fields=["source_module", "source_type", "source_id"],
                name="idx_fin_journal_source",
            ),
        ]

        # FIN-B1/B2. Dua tindakan yang mengubah buku besar, dan karena
        # itu **bukan** `change_journal`: yang menyunting draf tidak
        # otomatis boleh membukukannya. Dicentang per role di layar
        # Roles seperti izin lain; seed memberikannya ke FINANCE-MANAGER.
        permissions = [
            ("post_journal", "Can post journal to the general ledger"),
            ("reverse_journal", "Can reverse posted journal"),
        ]

    def __str__(self) -> str:
        return self.journal_number or f"Journal #{self.pk}"

    # ------------------------------------------------------------------
    # Turunan
    # ------------------------------------------------------------------

    @property
    def is_posted(self) -> bool:
        return self.status in {JournalStatus.POSTED, JournalStatus.REVERSED}

    @property
    def is_balanced(self) -> bool:
        return self.total_debit == self.total_credit

    @property
    def effective_document_date(self):
        return self.document_date or self.posting_date

    def clean(self):
        super().clean()

        errors: dict[str, str] = {}

        if self.exchange_rate is not None and self.exchange_rate <= 0:
            errors["exchange_rate"] = "Kurs harus lebih besar dari nol."

        period = self.accounting_period if self.accounting_period_id else None

        if period is not None:
            year = period.fiscal_year

            if self.fiscal_year_id and year.pk != self.fiscal_year_id:
                errors["accounting_period"] = (
                    f"Periode '{period.code}' milik tahun buku "
                    f"'{year.code}', bukan tahun buku yang dipilih."
                )

            elif self.company_id and year.company_id != self.company_id:
                errors["accounting_period"] = (
                    "Periode yang dipilih milik perusahaan lain."
                )

            elif self.posting_date and not period.contains(self.posting_date):
                errors["posting_date"] = (
                    f"Tanggal pembukuan di luar periode '{period.code}' "
                    f"({period.start_date} – {period.end_date})."
                )

        if self.reversal_of_id and self.reversal_of_id == self.pk:
            errors["reversal_of"] = "Jurnal tidak bisa membalik dirinya sendiri."

        if errors:
            raise ValidationError(errors)


class JournalLine(BaseModel):
    """
    Satu baris jurnal — satu sisi dari sebuah ayat.

    Kolom organisasi di bawah adalah **dimensi inti**, bukan salinan
    kepala dokumen: satu jurnal boleh membebankan gaji tiga departemen
    sekaligus, dan yang membedakannya baris, bukan dokumen. `company`
    sendiri memang selalu sama dengan kepala dokumennya — ia ada di sini
    supaya penyaringan cakupan data dan laporan tidak perlu join ke
    kepala untuk pertanyaan yang paling sering ditanyakan.
    """

    journal = models.ForeignKey(
        Journal,
        on_delete=models.CASCADE,
        related_name="lines",
    )

    line_number = models.PositiveIntegerField(default=1)

    account = models.ForeignKey(
        "finance.Account",
        on_delete=models.PROTECT,
        related_name="journal_lines",
    )

    # Nilai dalam **mata uang transaksi** — yang diketik operatornya.
    debit = _amount()
    credit = _amount()

    transaction_currency = models.ForeignKey(
        "administration.Currency",
        on_delete=models.PROTECT,
        related_name="journal_lines",
    )

    exchange_rate = models.DecimalField(
        max_digits=RATE_DIGITS,
        decimal_places=RATE_PLACES,
        default=Decimal("1.000000"),
    )

    # Nilai dalam **mata uang buku besar**. Inilah yang dijumlahkan
    # Trial Balance dan Account Ledger; yang di atas tidak pernah
    # dijumlahkan lintas baris, karena menjumlahkan dua mata uang
    # berbeda tidak menghasilkan angka yang berarti.
    base_debit = _amount()
    base_credit = _amount()

    description = models.TextField(blank=True, default="")

    # ------------------------------------------------------------------
    # Dimensi inti — kolom terindeks
    # ------------------------------------------------------------------

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="journal_lines",
    )
    branch = models.ForeignKey(
        "administration.Branch", on_delete=models.PROTECT,
        null=True, blank=True, related_name="journal_lines",
    )
    location = models.ForeignKey(
        "administration.Location", on_delete=models.PROTECT,
        null=True, blank=True, related_name="journal_lines",
    )
    division = models.ForeignKey(
        "administration.Division", on_delete=models.PROTECT,
        null=True, blank=True, related_name="journal_lines",
    )
    department = models.ForeignKey(
        "administration.Department", on_delete=models.PROTECT,
        null=True, blank=True, related_name="journal_lines",
    )
    section = models.ForeignKey(
        "administration.Section", on_delete=models.PROTECT,
        null=True, blank=True, related_name="journal_lines",
    )
    cost_center = models.ForeignKey(
        "administration.CostCenter", on_delete=models.PROTECT,
        null=True, blank=True, related_name="journal_lines",
    )

    source_reference = models.CharField(max_length=255, blank=True, default="")
    reconciliation_reference = models.CharField(
        max_length=255, blank=True, default="",
    )

    metadata = models.JSONField(default=dict, blank=True)

    # ------------------------------------------------------------------
    # Turunan dari kepala dokumen — ditulis mesin, bisa dibangun ulang
    # ------------------------------------------------------------------
    #
    # Ketiganya disalin `FinancePostingService` di dalam transaksi
    # posting yang sama, dan bisa dibangun ulang kapan saja lewat
    # `manage.py tenant_command rebuild_finance_ledger_denorm`.
    #
    # **Kenapa disalin sama sekali:** Trial Balance dan Account Ledger
    # menjumlahkan jutaan baris dengan syarat "sudah diposting" dan
    # "tanggalnya di rentang ini". Tanpa kolom ini setiap penjumlahan
    # menyeret join ke `finance_journal`, dan indeks komposit yang
    # menjawab keduanya sekaligus tidak bisa dibuat sama sekali — ia
    # harus mencakup kolom dari dua tabel.
    #
    # **Kenapa ini bukan "saldo yang bisa menyimpang":** tidak satu
    # angka pun disimpan di sini. Yang disalin hanya *penyaring* —
    # tanggal dan penanda. Nilai debit/kredit tetap tinggal di barisnya
    # sendiri dan tidak pernah diringkas ke tabel lain.

    posting_date = models.DateField(null=True, blank=True)

    accounting_period = models.ForeignKey(
        "finance.AccountingPeriod",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="journal_lines",
    )

    is_posted = models.BooleanField(default=False)

    class Meta:
        db_table = "finance_journal_line"

        ordering = ["journal_id", "line_number"]

        constraints = [
            models.UniqueConstraint(
                fields=["journal", "line_number"],
                condition=Q(is_deleted=False),
                name="uniq_active_finance_journal_line_number",
            ),
            # Dua aturan pembukuan paling dasar, ditegakkan database —
            # bukan cuma serializer dan bukan cuma `clean()`. Importer,
            # seed, perintah manajemen, dan `bulk_create` semuanya
            # melewati keduanya, dan satu baris bersaldo nol di tengah
            # sepuluh juta baris tidak akan pernah ditemukan siapa pun.
            models.CheckConstraint(
                condition=(
                    Q(debit=0, credit__gt=0) | Q(credit=0, debit__gt=0)
                ),
                name="ck_finance_line_one_side_only",
            ),
            models.CheckConstraint(
                condition=Q(debit__gte=0) & Q(credit__gte=0),
                name="ck_finance_line_non_negative",
            ),
        ]

        indexes = [
            # **Indeks buku besar.** Bentuk query Account Ledger dan
            # Trial Balance: satu perusahaan, satu akun, satu rentang
            # tanggal, hanya yang sudah diposting. Parsial — baris draf
            # tidak pernah ikut dijumlahkan, jadi tidak perlu ikut
            # membesarkan indeksnya.
            models.Index(
                fields=["company", "account", "posting_date"],
                condition=Q(is_posted=True),
                name="idx_fin_line_ledger",
            ),
            # Trial Balance per periode tanpa rentang tanggal.
            models.Index(
                fields=["company", "accounting_period", "account"],
                condition=Q(is_posted=True),
                name="idx_fin_line_period",
            ),
            # Laporan berdimensi inti. Tiga yang paling sering
            # ditanyakan; sisanya tersaring lewat `company` lebih dulu.
            models.Index(
                fields=["cost_center", "posting_date"],
                condition=Q(is_posted=True),
                name="idx_fin_line_cost_center",
            ),
            models.Index(
                fields=["location", "posting_date"],
                condition=Q(is_posted=True),
                name="idx_fin_line_location",
            ),
            models.Index(
                fields=["department", "posting_date"],
                condition=Q(is_posted=True),
                name="idx_fin_line_department",
            ),
            models.Index(
                fields=["journal"],
                name="idx_fin_line_journal",
            ),
        ]

    def __str__(self) -> str:
        side = "D" if self.debit else "C"

        return f"{self.line_number}. {self.account_id} {side}"

    def clean(self):
        super().clean()

        errors: dict[str, str] = {}

        debit = self.debit or ZERO
        credit = self.credit or ZERO

        if debit < 0 or credit < 0:
            errors["debit"] = "Nilai tidak boleh negatif. Balik sisinya."

        elif debit > 0 and credit > 0:
            errors["credit"] = (
                "Satu baris hanya boleh berisi debit atau kredit, tidak "
                "keduanya. Pisahkan jadi dua baris."
            )

        elif debit == 0 and credit == 0:
            errors["debit"] = (
                "Baris tanpa nilai tidak membukukan apa pun. Isi salah "
                "satu sisinya atau hapus barisnya."
            )

        if self.account_id:
            self._clean_account(errors)

        if errors:
            raise ValidationError(errors)

    def _clean_account(self, errors: dict) -> None:
        account = self.account

        if not account.posting_allowed:
            errors["account"] = (
                f"'{account.code} — {account.name}' adalah akun grup dan "
                "tidak menerima jurnal. Pilih salah satu akun di "
                "bawahnya."
            )

            return

        if not account.is_active or account.is_deleted:
            errors["account"] = (
                f"Akun '{account.code}' sudah tidak aktif."
            )

            return

        if self.company_id and account.company_id != self.company_id:
            errors["account"] = (
                f"Akun '{account.code}' milik perusahaan lain. Bagan "
                "akun tidak dipakai bersama antarbadan usaha."
            )

            return

        if (
            account.default_currency_id
            and self.transaction_currency_id
            and account.default_currency_id != self.transaction_currency_id
        ):
            errors["transaction_currency"] = (
                f"Akun '{account.code}' hanya menerima mata uang "
                f"{account.default_currency.code}."
            )
