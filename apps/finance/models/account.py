"""
Bagan akun (Chart of Accounts).

Hirarkis, dan **susunannya tidak ditentukan kode mana pun**. Tidak ada
kode akun bawaan, tidak ada nama perkiraan yang diharuskan, tidak ada
tingkat yang diwajibkan. Tambang yang memerlukan "Beban Pengupasan
Lapisan Penutup" dan jasa keamanan yang memerlukan "Beban Seragam
Anggota" sama-sama menuliskannya sendiri; yang dijaga sistem cuma
aturan pembukuannya — akun grup tidak menerima jurnal, anak tidak boleh
jadi leluhur induknya, dan kode tidak boleh kembar dalam satu
perusahaan.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .choices import (
    CATEGORIES_BY_TYPE,
    DEFAULT_NORMAL_BALANCE,
    AccountCategory,
    AccountType,
    NormalBalance,
)


# Pagar terhadap data yang sudah terlanjur berputar di database.
# Penelusuran ke atas tanpa batas pada rantai A→B→A tidak melaporkan
# datanya yang salah, ia kehabisan memori. Pola yang sama dengan
# `MAX_REPORTING_DEPTH` di `apps/hr/reporting_line.py`.
MAX_ACCOUNT_DEPTH = 12


class Account(BaseModel):
    """
    Satu perkiraan dalam bagan akun sebuah perusahaan.

    Dua sifat yang memisahkan perkiraan pembukuan dari sekadar baris
    master, dan keduanya dijaga di `clean()`:

    * **Akun grup tidak menerima jurnal.** "Aset Lancar" adalah judul,
      bukan tempat uang. Memposting ke sana membuat saldo anak-anaknya
      dan saldo induknya sama-sama benar sendiri-sendiri tapi tidak
      pernah cocok saat dijumlahkan.
    * **Akun yang punya anak otomatis jadi grup.** Kalau tidak, sebuah
      perkiraan bisa punya saldo sendiri *dan* saldo anak-anaknya, dan
      neraca menjumlahkannya dua kali.
    """

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="finance_accounts",
    )

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)

    # PROTECT, bukan SET_NULL. Menghapus "Aset Lancar" dengan SET_NULL
    # akan melempar Kas, Bank, dan Piutang ke akar tanpa satu pun pesan
    # — bagan akunnya tetap terlihat wajar, cuma susunannya bukan lagi
    # yang disusun siapa pun. Soft delete induk yang masih punya anak
    # ditolak `AccountService`.
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="children",
    )

    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices,
    )

    account_category = models.CharField(
        max_length=30,
        choices=AccountCategory.choices,
        blank=True,
        default="",
    )

    normal_balance = models.CharField(
        max_length=10,
        choices=NormalBalance.choices,
        blank=True,
        help_text=(
            "Kosongkan untuk mengikuti golongan akun. Diisi sendiri "
            "hanya untuk akun kontra — akumulasi penyusutan pada "
            "golongan Asset, misalnya."
        ),
    )

    # ------------------------------------------------------------------
    # Perilaku
    # ------------------------------------------------------------------

    posting_allowed = models.BooleanField(
        default=True,
        help_text=(
            "Mati = akun grup/judul. Akun yang punya anak selalu jadi "
            "grup, apa pun isi kolom ini."
        ),
    )

    control_account = models.BooleanField(
        default=False,
        help_text=(
            "Saldonya dikendalikan buku pembantu (piutang, utang, aset "
            "tetap). Jurnal manual ke akun semacam ini membuat buku "
            "besar dan buku pembantu berselisih."
        ),
    )

    reconciliation_required = models.BooleanField(
        default=False,
        help_text="Mutasinya harus direkonsiliasi (kas, bank, kliring).",
    )

    default_currency = models.ForeignKey(
        "administration.Currency",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="finance_accounts",
        help_text=(
            "Kosong = menerima mata uang apa pun. Diisi = akun ini "
            "hanya menerima jurnal bermata uang itu (rekening bank "
            "valas)."
        ),
    )

    sort_order = models.PositiveIntegerField(default=0)

    metadata = models.JSONField(default=dict, blank=True)

    # ------------------------------------------------------------------
    # Turunan — ditulis mesin, tidak pernah diketik orang
    # ------------------------------------------------------------------
    #
    # Keduanya **diturunkan dari `parent`** dan ditulis ulang
    # `AccountService` setiap kali induk berubah, plus bisa dibangun
    # ulang kapan saja lewat `manage.py tenant_command
    # rebuild_finance_account_tree`. Disimpan karena tanpanya
    # "seluruh beban di bawah Beban Usaha" berarti rekursi di Python
    # untuk setiap baris laporan; dengan `path` ia jadi satu
    # `startswith` yang terindeks.
    #
    # Bentuknya `/12/57/193/` — id, bukan kode. Kode boleh diganti
    # tenant, dan jalur yang berubah arti saat seseorang merapikan
    # penomoran adalah cara membuat laporan diam-diam salah.

    path = models.CharField(
        max_length=255,
        blank=True,
        default="",
        db_index=True,
    )

    level = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "finance_account"

        ordering = ["company_id", "code"]

        constraints = [
            # Dikondisikan ke `is_deleted`: tanpa itu kode akun yang
            # sudah dihapus terkunci selamanya, dan perusahaan yang
            # salah ketik satu kode kehilangan kode itu untuk selamanya.
            models.UniqueConstraint(
                fields=["company", "code"],
                condition=Q(is_deleted=False),
                name="uniq_active_finance_account_code",
            ),
        ]

        indexes = [
            # Daftar bagan akun per perusahaan, urut kode — bentuk
            # query layar Chart of Accounts dan seluruh laporan.
            models.Index(
                fields=["company", "code"],
                name="idx_fin_account_company_code",
            ),
            # Penyusun laporan keuangan menyaring per golongan.
            models.Index(
                fields=["company", "account_type"],
                name="idx_fin_account_company_type",
            ),
            models.Index(
                fields=["parent"],
                name="idx_fin_account_parent",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    # ------------------------------------------------------------------
    # Turunan
    # ------------------------------------------------------------------

    @property
    def effective_normal_balance(self) -> str:
        """Saldo normal yang berlaku: yang ditulis, atau bawaan golongan."""
        if self.normal_balance:
            return self.normal_balance

        return DEFAULT_NORMAL_BALANCE.get(
            self.account_type,
            NormalBalance.DEBIT,
        )

    @property
    def is_group(self) -> bool:
        return not self.posting_allowed

    def ancestors(self) -> list[int]:
        """Id leluhur dari akar ke induk langsung, dibaca dari `path`."""
        return [
            int(part)
            for part in self.path.strip("/").split("/")
            if part
        ][:-1]

    def build_path(self) -> str:
        """
        Jalur materialisasi untuk baris ini.

        Dibaca dari `parent.path`, bukan ditelusuri ulang ke atas: induk
        selalu sudah punya jalurnya sendiri, dan menelusuri berarti satu
        query per tingkat untuk setiap baris yang disimpan.
        """
        if self.parent_id is None:
            return f"/{self.pk}/"

        parent_path = self.parent.path or ""

        if not parent_path:
            # Induk yang jalurnya belum terisi — baris peninggalan
            # sebelum kolom ini ada, atau tenant yang belum di-rebuild.
            # Dirakit di tempat supaya satu baris yang tertinggal tidak
            # merusak jalur seluruh cabangnya.
            parent_path = self.parent.build_path()

        return f"{parent_path}{self.pk}/"

    # ------------------------------------------------------------------
    # Validasi
    # ------------------------------------------------------------------

    def clean(self):
        super().clean()

        errors: dict[str, str] = {}

        if self.code:
            self.code = self.code.strip()

        if self.account_type and self.account_category:
            allowed = CATEGORIES_BY_TYPE.get(self.account_type, set())

            if self.account_category not in allowed:
                errors["account_category"] = (
                    f"Kategori '{self.get_account_category_display()}' "
                    f"tidak berlaku untuk golongan "
                    f"'{self.get_account_type_display()}'."
                )

        self._clean_parent(errors)

        if errors:
            raise ValidationError(errors)

    def _clean_parent(self, errors: dict) -> None:
        parent = self.parent

        if parent is None:
            return

        if parent.pk == self.pk:
            errors["parent"] = "Akun tidak bisa menjadi induk dirinya sendiri."

            return

        if parent.company_id != self.company_id:
            errors["parent"] = (
                "Induk harus berada di perusahaan yang sama. Bagan akun "
                "tidak pernah melintasi badan usaha — yang melintasi "
                "adalah jurnal antarperusahaan, dan itu dokumen, bukan "
                "susunan perkiraan."
            )

            return

        if parent.is_deleted:
            errors["parent"] = "Induk yang dipilih sudah dihapus."

            return

        # Induk otomatis jadi grup. Diperiksa di sini supaya
        # penolakannya menyebut induknya, bukan supaya diam-diam
        # diubah: mengubah `posting_allowed` induk dari jalur anak
        # berarti satu simpanan mengubah baris yang tidak sedang dibuka
        # siapa pun.
        if parent.posting_allowed:
            errors["parent"] = (
                f"Akun '{parent.code} — {parent.name}' masih berstatus "
                "akun posting. Matikan dulu 'Posting Allowed' pada akun "
                "itu sebelum memberinya anak — satu akun tidak boleh "
                "punya saldo sendiri sekaligus saldo anak-anaknya."
            )

            return

        if self.account_type and parent.account_type != self.account_type:
            errors["parent"] = (
                f"Induk bergolongan "
                f"'{parent.get_account_type_display()}', sementara akun "
                f"ini '{self.get_account_type_display()}'. Satu cabang "
                "bagan akun harus satu golongan, kalau tidak jumlah "
                "cabangnya tidak berarti apa-apa."
            )

            return

        self._assert_no_cycle(parent, errors)

    def _assert_no_cycle(self, parent, errors: dict) -> None:
        """
        Menolak rantai yang berputar.

        Ditelusuri lewat FK, **bukan** lewat `path`: saat induk baru
        sedang dipilih, `path` yang tersimpan masih menggambarkan
        susunan lama, dan memeriksanya akan meloloskan justru
        perpindahan yang membentuk lingkaran.
        """
        if self.pk is None:
            return

        seen = {self.pk}
        current = parent
        depth = 0

        while current is not None:
            if current.pk in seen:
                errors["parent"] = (
                    "Susunan ini membentuk lingkaran — akun yang "
                    "dipilih berada di bawah akun ini."
                )

                return

            seen.add(current.pk)

            depth += 1

            if depth > MAX_ACCOUNT_DEPTH:
                errors["parent"] = (
                    f"Susunan bagan akun melebihi {MAX_ACCOUNT_DEPTH} "
                    "tingkat. Periksa apakah ada rantai induk yang "
                    "berputar."
                )

                return

            current = current.parent
