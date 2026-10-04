"""
Kosakata tetap modul Finance.

Yang ada di berkas ini **hanya** hal yang merupakan aturan pembukuan
berpasangan itu sendiri — bukan kebijakan sebuah industri, bukan bagan
akun sebuah perusahaan. Aset/kewajiban/ekuitas/pendapatan/beban dan
debit/kredit berlaku sama di tambang, ritel, jasa keamanan, maupun
holding; menaruhnya di master yang bisa disunting tenant tidak membuat
sistem lebih fleksibel, cuma membuat neraca bisa dibuat tidak seimbang
dari layar setting.

Yang **tidak** ada di sini, dan memang tidak boleh ada: kode akun,
susunan bagan akun, nama perkiraan, dan penentuan akun per transaksi.
Ketiganya data (`Account`), dan yang terakhir kebijakan
(`AccountingPolicy` + `AccountMapping`).
"""

from __future__ import annotations

from django.db import models


class AccountType(models.TextChoices):
    """
    Golongan pokok perkiraan.

    Menentukan dua hal yang tidak bisa dikonfigurasi tanpa merusak
    laporan: saldo normalnya (lihat `default_normal_balance`) dan apakah
    ia berdiri di neraca atau di laba rugi (`is_balance_sheet`).
    """

    ASSET = "asset", "Asset"
    LIABILITY = "liability", "Liability"
    EQUITY = "equity", "Equity"
    REVENUE = "revenue", "Revenue"
    EXPENSE = "expense", "Expense"


# Golongan yang saldonya berdiri di neraca. Sisanya tutup buku ke
# ekuitas pada akhir tahun — belum diimplementasikan di fase ini, tapi
# pemisahannya sudah dipakai Trial Balance untuk menghitung saldo awal:
# perkiraan neraca membawa saldo tahun sebelumnya, perkiraan laba rugi
# selalu mulai dari nol di tiap tahun buku.
BALANCE_SHEET_TYPES = frozenset({
    AccountType.ASSET,
    AccountType.LIABILITY,
    AccountType.EQUITY,
})


class NormalBalance(models.TextChoices):
    DEBIT = "debit", "Debit"
    CREDIT = "credit", "Credit"


# Saldo normal bawaan tiap golongan. Dipakai sebagai **isian awal**,
# bukan sebagai kunci: akun kontra (akumulasi penyusutan pada golongan
# Asset, potongan penjualan pada Revenue) memang bersaldo terbalik, dan
# melarangnya berarti melarang akun kontra sama sekali.
DEFAULT_NORMAL_BALANCE = {
    AccountType.ASSET: NormalBalance.DEBIT,
    AccountType.EXPENSE: NormalBalance.DEBIT,
    AccountType.LIABILITY: NormalBalance.CREDIT,
    AccountType.EQUITY: NormalBalance.CREDIT,
    AccountType.REVENUE: NormalBalance.CREDIT,
}


class AccountCategory(models.TextChoices):
    """
    Klasifikasi penyajian, satu tingkat di bawah `AccountType`.

    **Ini bukan susunan bagan akun.** Susunannya tinggal di
    `Account.parent` dan boleh berbentuk apa pun; yang di sini cuma
    penanda baris laporan keuangan yang berlaku umum (aset lancar vs
    aset tetap, harga pokok vs beban usaha). Sengaja enum, bukan master:
    nilainya dibaca kode penyusun laporan, dan master yang bisa
    ditambahi tenant menghasilkan kategori yang tidak punya baris di
    laporan mana pun — hilang tanpa pesan.

    Opsional pada `Account`. Perusahaan yang belum memerlukannya
    mengosongkannya, dan Trial Balance tetap jalan.
    """

    CURRENT_ASSET = "current_asset", "Current Asset"
    NON_CURRENT_ASSET = "non_current_asset", "Non-Current Asset"
    FIXED_ASSET = "fixed_asset", "Fixed Asset"
    INTANGIBLE_ASSET = "intangible_asset", "Intangible Asset"
    OTHER_ASSET = "other_asset", "Other Asset"

    CURRENT_LIABILITY = "current_liability", "Current Liability"
    NON_CURRENT_LIABILITY = "non_current_liability", "Non-Current Liability"
    OTHER_LIABILITY = "other_liability", "Other Liability"

    EQUITY = "equity", "Equity"

    OPERATING_REVENUE = "operating_revenue", "Operating Revenue"
    OTHER_REVENUE = "other_revenue", "Other Income"

    COST_OF_SALES = "cost_of_sales", "Cost of Sales"
    OPERATING_EXPENSE = "operating_expense", "Operating Expense"
    OTHER_EXPENSE = "other_expense", "Other Expense"
    TAX_EXPENSE = "tax_expense", "Tax Expense"


# Kategori yang sah untuk tiap golongan. Diperiksa `Account.clean()`;
# tanpa itu sebuah akun bisa bergolongan Revenue berkategori Fixed Asset
# dan tetap tersimpan — lalu muncul di baris laporan yang salah tanpa
# satu pun angka terlihat janggal.
CATEGORIES_BY_TYPE = {
    AccountType.ASSET: {
        AccountCategory.CURRENT_ASSET,
        AccountCategory.NON_CURRENT_ASSET,
        AccountCategory.FIXED_ASSET,
        AccountCategory.INTANGIBLE_ASSET,
        AccountCategory.OTHER_ASSET,
    },
    AccountType.LIABILITY: {
        AccountCategory.CURRENT_LIABILITY,
        AccountCategory.NON_CURRENT_LIABILITY,
        AccountCategory.OTHER_LIABILITY,
    },
    AccountType.EQUITY: {
        AccountCategory.EQUITY,
    },
    AccountType.REVENUE: {
        AccountCategory.OPERATING_REVENUE,
        AccountCategory.OTHER_REVENUE,
    },
    AccountType.EXPENSE: {
        AccountCategory.COST_OF_SALES,
        AccountCategory.OPERATING_EXPENSE,
        AccountCategory.OTHER_EXPENSE,
        AccountCategory.TAX_EXPENSE,
    },
}


class FiscalYearStatus(models.TextChoices):
    OPEN = "open", "Open"
    CLOSED = "closed", "Closed"
    LOCKED = "locked", "Locked"


class PeriodStatus(models.TextChoices):
    """
    Keadaan satu periode akuntansi.

    Empat, bukan dua, dan yang membedakan ketiga keadaan tertutupnya
    adalah **siapa yang masih boleh menembusnya**:

    * `OPEN` — posting biasa.
    * `SOFT_CLOSED` — tutup buku operasional. Yang memegang
      `finance.can_post_soft_closed_period` masih boleh memposting;
      operator biasa tidak. Ini keadaan yang dipakai selama penyusunan
      laporan bulanan, saat jurnal penyesuaian masih mendarat sementara
      transaksi harian sudah harus berhenti.
    * `CLOSED` — tidak ada posting sama sekali. Bisa dibuka kembali.
    * `LOCKED` — sudah diaudit/dilaporkan ke luar. Membukanya kembali
      perlu jalur tersendiri yang tercatat, dan `reopen_reason` wajib
      diisi.
    """

    OPEN = "open", "Open"
    SOFT_CLOSED = "soft_closed", "Soft Closed"
    CLOSED = "closed", "Closed"
    LOCKED = "locked", "Locked"


# Periode yang menerima posting tanpa syarat tambahan.
POSTABLE_PERIOD_STATUSES = frozenset({PeriodStatus.OPEN})

# Periode yang menerima posting **hanya** untuk pemegang izin khusus.
RESTRICTED_PERIOD_STATUSES = frozenset({PeriodStatus.SOFT_CLOSED})


class JournalType(models.TextChoices):
    """
    Jenis jurnal — **penanda, bukan pengendali.**

    Tidak satu pun perilaku posting bercabang pada nilai di sini.
    Yang menentukan akun adalah `AccountingPolicy` + `AccountMapping`;
    yang menentukan boleh-tidaknya memposting adalah status periode dan
    izin. Jenis dipakai untuk menyaring, mengelompokkan di laporan, dan
    menjelaskan kepada manusia kenapa sebuah jurnal ada.

    Satu-satunya yang diperlakukan khusus adalah `REVERSAL`, dan itu
    pun bukan cabang perilaku: ia diisi `FinanceReversalService` supaya
    jurnal pembalik bisa dikenali di daftar, sementara aturan
    posting-nya sama persis dengan jurnal lain.
    """

    MANUAL = "manual", "Manual"
    AUTOMATIC = "automatic", "Automatic"
    ADJUSTMENT = "adjustment", "Adjustment"
    ACCRUAL = "accrual", "Accrual"
    REVERSAL = "reversal", "Reversal"
    RECURRING = "recurring", "Recurring"
    OPENING = "opening", "Opening"
    CLOSING = "closing", "Closing"
    INTERCOMPANY = "intercompany", "Intercompany"
    ALLOCATION = "allocation", "Allocation"


class JournalStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Pending Approval"
    APPROVED = "approved", "Approved"
    POSTED = "posted", "Posted"
    REJECTED = "rejected", "Rejected"
    CANCELLED = "cancelled", "Cancelled"
    REVERSED = "reversed", "Reversed"


# Jurnal yang isinya masih boleh disunting. Di luar daftar ini,
# `JournalService` menolak setiap perubahan baris maupun kepala
# dokumen — termasuk lewat PATCH yang diketik tangan.
EDITABLE_JOURNAL_STATUSES = frozenset({
    JournalStatus.DRAFT,
    JournalStatus.REJECTED,
})

# Jurnal yang sudah menjadi fakta akuntansi. Tidak pernah disunting,
# tidak pernah dihapus — koreksinya lewat pembalikan.
IMMUTABLE_JOURNAL_STATUSES = frozenset({
    JournalStatus.POSTED,
    JournalStatus.REVERSED,
})

# Yang benar-benar berdampak ke buku besar. Satu-satunya daftar yang
# dibaca Trial Balance dan Account Ledger.
LEDGER_JOURNAL_STATUSES = frozenset({
    JournalStatus.POSTED,
    JournalStatus.REVERSED,
})


class AccountingEventStatus(models.TextChoices):
    """
    Keadaan satu kejadian akuntansi yang dikirim modul lain.

    `SKIPPED` bukan kegagalan: ada kejadian yang memang tidak
    menghasilkan jurnal di sebuah tenant — komponen gaji yang
    kebijakannya tidak memetakan apa pun, misalnya. Membedakannya dari
    `FAILED` penting, kalau tidak layar pemantauan penuh baris merah
    yang tidak ada yang perlu memperbaikinya.
    """

    PENDING = "pending", "Pending"
    PROCESSING = "processing", "Processing"
    PROCESSED = "processed", "Processed"
    FAILED = "failed", "Failed"
    SKIPPED = "skipped", "Skipped"
    CANCELLED = "cancelled", "Cancelled"
    # PF-0G. Kejadian yang jurnalnya **belum** masuk buku besar lalu
    # digantikan kejadian koreksi. Payload, digest, penanda idempotensi,
    # dan relasi jurnalnya tetap utuh — yang berubah hanya perannya:
    # ia bukan lagi fakta akuntansi yang berlaku. Tidak pernah diproses
    # ulang dan tidak pernah menerbitkan jurnal kedua.
    SUPERSEDED = "superseded", "Superseded"


class DimensionDataType(models.TextChoices):
    """Bentuk nilai sebuah dimensi tambahan."""

    REFERENCE = "reference", "Reference"
    TEXT = "text", "Text"


class PostingSide(models.TextChoices):
    DEBIT = "debit", "Debit"
    CREDIT = "credit", "Credit"
