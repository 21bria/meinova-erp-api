"""
Buku besar dan neraca saldo — seluruhnya baca.

**Baris jurnal adalah satu-satunya sumber angka di sini.** Tidak ada
tabel saldo, tidak ada ringkasan yang disimpan, dan karena itu tidak
ada yang bisa menyimpang. Kalau nanti volumenya menuntut ringkasan, ia
harus tetap berupa turunan yang bisa dibangun ulang dari tabel ini —
dan pemanggilnya tidak perlu berubah, karena ia lewat dua service di
bawah ini.

**Seluruh penjumlahan terjadi di database.** Tidak satu baris jurnal
pun dimuat ke Python untuk dijumlahkan; yang dimuat hanya hasil
`GROUP BY`-nya, satu baris per akun. Itu bukan optimasi — pada tabel
berisi jutaan baris, menjumlahkan di Python berarti layar yang tidak
pernah selesai memuat.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import (
    Case,
    DecimalField,
    F,
    Q,
    Sum,
    Value,
    When,
    Window,
)
from django.db.models.functions import Coalesce

from apps.accounts.scoping import DataScopeService
from apps.finance.models import (
    BALANCE_SHEET_TYPES,
    ZERO,
    Account,
    AccountingPeriod,
    FiscalYear,
    JournalLine,
)


MONEY = DecimalField(max_digits=20, decimal_places=2)


def _zero() -> Value:
    return Value(ZERO, output_field=MONEY)


# Cakupan data untuk baris buku besar. Dimensi inti jadi kolom pada
# `JournalLine`, jadi petanya langsung — tidak ada satu pun join.
#
# **Dimensi tambahan sengaja tidak ada di sini.** Cakupan data disaring
# lewat unit organisasi, dan dimensi generik (project, customer) tidak
# pernah jadi batas keamanan — lihat catatan arsitektur di
# `apps/finance/models/dimension.py`.
LEDGER_SCOPE = {
    "company": "company",
    "branch": "branch",
    "location": "location",
    "division": "division",
    "department": "department",
    "section": "section",
    "cost_center": "cost_center",
    "own": None,
}


@dataclass(frozen=True)
class LedgerFilters:
    """
    Penyaring yang berlaku sama untuk Trial Balance dan Account Ledger.

    Satu bentuk untuk dua laporan, dan itu disengaja: tombol filter yang
    sama di dua layar harus berarti hal yang sama, dan dua penafsir
    filter yang terpisah adalah cara membuat drill-down dari Trial
    Balance ke Account Ledger mendarat pada angka yang berbeda.
    """

    company_id: int
    date_from: date | None = None
    date_to: date | None = None
    fiscal_year_id: int | None = None
    period_id: int | None = None
    account_id: int | None = None
    # Akar hierarki: seluruh akun di bawahnya ikut, lewat `path`.
    account_root_id: int | None = None
    account_type: str | None = None
    branch_id: int | None = None
    location_id: int | None = None
    division_id: int | None = None
    department_id: int | None = None
    section_id: int | None = None
    cost_center_id: int | None = None
    # `{kode dimensi: nilai}` untuk dimensi tambahan.
    dimensions: tuple[tuple[str, str], ...] = ()
    include_zero: bool = False


class LedgerQueryService:
    """Penyusun queryset dasar — dipakai kedua laporan."""

    @staticmethod
    def resolve_range(filters: LedgerFilters) -> tuple[date, date]:
        """
        Rentang tanggal efektif.

        Urutannya: periode > tahun buku > tanggal yang diketik. Periode
        menang karena ia yang paling spesifik, dan karena orang yang
        memilih "Agustus" lalu lupa mengosongkan tanggal dari filter
        sebelumnya bermaksud melihat Agustus.
        """
        if filters.period_id:
            period = (
                AccountingPeriod.objects
                .filter(pk=filters.period_id, is_deleted=False)
                .first()
            )

            if period is None:
                raise ValidationError({
                    "period": "Periode yang dipilih tidak ditemukan.",
                })

            return period.start_date, period.end_date

        if filters.fiscal_year_id:
            year = (
                FiscalYear.objects
                .filter(pk=filters.fiscal_year_id, is_deleted=False)
                .first()
            )

            if year is None:
                raise ValidationError({
                    "fiscal_year": "Tahun buku yang dipilih tidak ditemukan.",
                })

            return (
                filters.date_from or year.start_date,
                filters.date_to or year.end_date,
            )

        if filters.date_from and filters.date_to:
            if filters.date_to < filters.date_from:
                raise ValidationError({
                    "date_to": "Tanggal akhir sebelum tanggal mulai.",
                })

            return filters.date_from, filters.date_to

        raise ValidationError({
            "period": (
                "Pilih periode, tahun buku, atau rentang tanggal. "
                "Neraca saldo tanpa batas waktu menjumlahkan seluruh "
                "riwayat pembukuan dan tidak menjawab pertanyaan siapa "
                "pun."
            ),
        })

    @classmethod
    def base_queryset(cls, filters: LedgerFilters, *, user=None):
        """
        Baris buku besar yang boleh dilihat pemintanya, sebelum
        dibatasi tanggal.

        `is_posted=True` memakai indeks parsial `idx_fin_line_ledger` —
        baris draf tidak pernah ikut dijumlahkan dan tidak ikut
        membesarkan indeksnya.
        """
        queryset = JournalLine.objects.filter(
            is_deleted=False,
            is_posted=True,
            company_id=filters.company_id,
        )

        queryset = cls._apply_dimensions(queryset, filters)
        queryset = cls._apply_accounts(queryset, filters)

        return cls.apply_scope(queryset, user=user)

    @staticmethod
    def apply_scope(queryset, *, user=None):
        """
        Cakupan data, dipasang di satu tempat.

        Laporan tidak lewat `BaseMasterViewSet.filter_queryset()` — ia
        `APIView` — jadi tanpa panggilan ini seluruh angka buku besar
        terbuka untuk siapa pun yang bisa membuka layarnya. Pola yang
        sama dengan `HRDashboardService` dan laporan HR.
        """
        return DataScopeService.filter(
            queryset,
            {key: path for key, path in LEDGER_SCOPE.items() if path},
            user,
            required_permission="finance.view_journalline",
        )

    @staticmethod
    def _apply_dimensions(queryset, filters: LedgerFilters):
        for field in (
            "branch",
            "location",
            "division",
            "department",
            "section",
            "cost_center",
        ):
            value = getattr(filters, f"{field}_id")

            if value:
                queryset = queryset.filter(**{f"{field}_id": value})

        for code, value in filters.dimensions:
            if not value:
                continue

            # Dimensi tambahan disaring lewat relasi balik. Satu
            # `EXISTS` per dimensi, terindeks lewat
            # `idx_fin_dimval_code_value`.
            condition = Q(dimension_values__dimension_code=code)

            if str(value).isdigit():
                condition &= Q(dimension_values__value_id=int(value))
            else:
                condition &= Q(dimension_values__value_text=str(value))

            queryset = queryset.filter(condition)

        return queryset

    @staticmethod
    def _apply_accounts(queryset, filters: LedgerFilters):
        if filters.account_id:
            return queryset.filter(account_id=filters.account_id)

        if filters.account_root_id:
            root = (
                Account.objects
                .filter(pk=filters.account_root_id, is_deleted=False)
                .first()
            )

            if root is None:
                raise ValidationError({
                    "account_root": "Akun induk tidak ditemukan.",
                })

            # **Satu `LIKE` berprefiks, bukan rekursi.** Inilah gunanya
            # `Account.path` disimpan: "seluruh beban di bawah Beban
            # Usaha" jadi satu syarat terindeks, bukan satu query per
            # tingkat.
            queryset = queryset.filter(
                account__path__startswith=root.path or f"/{root.pk}/",
            )

        if filters.account_type:
            queryset = queryset.filter(
                account__account_type=filters.account_type,
            )

        return queryset


class TrialBalanceQueryService:
    """
    Neraca saldo.

    Saldo awal dihitung berbeda menurut golongan akun, dan itu bukan
    kerumitan yang bisa dihindari:

    * **Akun neraca** membawa saldonya sejak awal pembukuan. Kas per 1
      Agustus adalah kas yang ada sejak perusahaan berdiri.
    * **Akun laba rugi** selalu mulai dari nol di tiap tahun buku.
      Beban Januari tidak ikut terbawa ke saldo awal Agustus tahun
      berikutnya — kalau ikut, laba tahun ini jadi akumulasi seluruh
      sejarah.

    Menyamakan keduanya adalah kesalahan yang neraca saldonya **tetap
    seimbang** — debit dan kredit sama-sama salah dengan besar yang
    sama — jadi ia tidak pernah ketahuan dari total.
    """

    @classmethod
    def build(cls, filters: LedgerFilters, *, user=None) -> dict:
        start, end = LedgerQueryService.resolve_range(filters)

        base = LedgerQueryService.base_queryset(filters, user=user)

        movement = cls._aggregate(
            base.filter(posting_date__gte=start, posting_date__lte=end)
        )

        opening = cls._opening(
            base=base,
            filters=filters,
            start=start,
        )

        account_ids = set(movement) | set(opening)

        if not account_ids:
            return cls._empty(start, end)

        accounts = {
            account.pk: account
            for account in Account.objects.filter(pk__in=account_ids)
        }

        rows = []

        totals = {
            "beginning_debit": ZERO,
            "beginning_credit": ZERO,
            "debit": ZERO,
            "credit": ZERO,
            "ending_debit": ZERO,
            "ending_credit": ZERO,
        }

        for account_id in account_ids:
            account = accounts.get(account_id)

            if account is None:
                continue

            begin = opening.get(account_id, ZERO)
            period = movement.get(account_id, {"debit": ZERO, "credit": ZERO})

            debit = period["debit"]
            credit = period["credit"]

            # Saldo disimpan sebagai **selisih bertanda debit-positif**
            # sepanjang perhitungan, lalu baru dipecah jadi dua kolom di
            # akhir. Memecahnya lebih awal memaksa setiap penjumlahan
            # memutuskan sisi mana yang bertambah, dan akun kontra
            # membuat keputusan itu salah separuh waktu.
            ending = begin + debit - credit

            if not filters.include_zero and not any((begin, debit, credit, ending)):
                continue

            begin_debit, begin_credit = cls._split(begin)
            end_debit, end_credit = cls._split(ending)

            rows.append({
                "account_id": account_id,
                "account_code": account.code,
                "account_name": account.name,
                "account_type": account.account_type,
                "account_category": account.account_category,
                "normal_balance": account.effective_normal_balance,
                "level": account.level,
                "beginning_debit": begin_debit,
                "beginning_credit": begin_credit,
                "debit": debit,
                "credit": credit,
                "ending_debit": end_debit,
                "ending_credit": end_credit,
            })

            totals["beginning_debit"] += begin_debit
            totals["beginning_credit"] += begin_credit
            totals["debit"] += debit
            totals["credit"] += credit
            totals["ending_debit"] += end_debit
            totals["ending_credit"] += end_credit

        rows.sort(key=lambda row: row["account_code"])

        return {
            "date_from": start,
            "date_to": end,
            "rows": rows,
            "totals": totals,
            # Dihitung, bukan diasumsikan. Neraca saldo yang tidak
            # seimbang berarti ada yang salah di pembukuan atau di
            # laporan ini, dan layar harus mengatakannya — bukan
            # menampilkan dua angka berbeda berdampingan dan
            # membiarkan orang membandingkannya sendiri.
            #
            # **Yang diperiksa kolom mutasi, bukan saldo akhir**, dan
            # itu bukan kelalaian. Setiap jurnal seimbang dan seluruh
            # barisnya membawa tanggal posting kepala dokumennya, jadi
            # rentang tanggal apa pun memotong jurnal secara utuh —
            # debit dan kredit mutasi **selalu** sama. Kalau tidak,
            # ada yang rusak, dan itulah yang dilaporkan.
            #
            # Saldo awal dan saldo akhir tidak punya jaminan yang sama
            # selama belum ada jurnal tutup buku: perkiraan laba rugi
            # dipotong di awal tahun buku sementara lawan neracanya
            # terbawa sejak awal pembukuan, jadi selisihnya persis
            # sebesar laba tahun-tahun sebelumnya yang belum
            # dipindahkan ke ekuitas. Memeriksa kolom itu akan
            # melaporkan "tidak seimbang" pada pembukuan yang justru
            # benar — dan tutup buku memang belum dibangun (§33).
            "is_balanced": totals["debit"] == totals["credit"],
            "difference": totals["debit"] - totals["credit"],
        }

    @staticmethod
    def _empty(start, end) -> dict:
        zero_totals = {
            key: ZERO
            for key in (
                "beginning_debit", "beginning_credit",
                "debit", "credit",
                "ending_debit", "ending_credit",
            )
        }

        return {
            "date_from": start,
            "date_to": end,
            "rows": [],
            "totals": zero_totals,
            "is_balanced": True,
            "difference": ZERO,
        }

    @staticmethod
    def _aggregate(queryset) -> dict[int, dict]:
        """`GROUP BY account` di database — satu baris per akun."""
        rows = (
            queryset
            .values("account_id")
            .annotate(
                debit=Coalesce(Sum("base_debit"), _zero()),
                credit=Coalesce(Sum("base_credit"), _zero()),
            )
        )

        return {
            row["account_id"]: {
                "debit": row["debit"],
                "credit": row["credit"],
            }
            for row in rows
        }

    @classmethod
    def _opening(cls, *, base, filters: LedgerFilters, start: date) -> dict:
        """
        Saldo awal per akun, dua query — satu untuk tiap perlakuan.

        Dua, bukan satu dengan `CASE`: batas tanggalnya berbeda, dan
        satu query yang harus memakai dua batas sekaligus tidak bisa
        memanfaatkan indeks tanggal untuk keduanya.
        """
        balance_sheet = cls._balance_of(
            base.filter(
                posting_date__lt=start,
                account__account_type__in=list(BALANCE_SHEET_TYPES),
            )
        )

        year_start = cls._year_start(filters=filters, start=start)

        if year_start is None or year_start >= start:
            income = {}
        else:
            income = cls._balance_of(
                base.filter(
                    posting_date__gte=year_start,
                    posting_date__lt=start,
                )
                .exclude(account__account_type__in=list(BALANCE_SHEET_TYPES))
            )

        return {**balance_sheet, **income}

    @staticmethod
    def _balance_of(queryset) -> dict[int, Decimal]:
        rows = (
            queryset
            .values("account_id")
            .annotate(
                balance=Coalesce(Sum("base_debit"), _zero())
                - Coalesce(Sum("base_credit"), _zero()),
            )
        )

        return {row["account_id"]: row["balance"] for row in rows}

    @staticmethod
    def _year_start(*, filters: LedgerFilters, start: date) -> date | None:
        """
        Awal tahun buku yang memuat tanggal mulai laporan.

        Dicari dari tanggalnya, bukan dari filter tahun buku: orang
        boleh memilih rentang tanggal tanpa menyebut tahun buku sama
        sekali, dan saldo awal akun laba rugi tetap harus dipotong di
        awal tahun bukunya.
        """
        year = (
            FiscalYear.objects
            .filter(
                company_id=filters.company_id,
                is_deleted=False,
                start_date__lte=start,
                end_date__gte=start,
            )
            .order_by("start_date")
            .first()
        )

        return year.start_date if year else None

    @staticmethod
    def _split(balance: Decimal) -> tuple[Decimal, Decimal]:
        """Selisih bertanda jadi dua kolom penyajian."""
        if balance > 0:
            return balance, ZERO

        if balance < 0:
            return ZERO, -balance

        return ZERO, ZERO


class AccountLedgerQueryService:
    """
    Buku besar satu akun: saldo awal, lalu mutasinya baris per baris.

    Saldo berjalannya dihitung **window function di database**, bukan
    akumulasi di Python. Bedanya menentukan begitu daftarnya berhalaman:
    akumulasi di Python cuma tahu baris yang sedang dimuat, jadi saldo
    berjalan di halaman dua akan mulai dari nol lagi — angka yang
    terlihat masuk akal dan salah sama sekali.
    """

    @classmethod
    def build(
        cls,
        filters: LedgerFilters,
        *,
        user=None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict:
        if not filters.account_id:
            raise ValidationError({
                "account": "Pilih akun yang mau dilihat buku besarnya.",
            })

        account = (
            Account.objects
            .filter(pk=filters.account_id, is_deleted=False)
            .first()
        )

        if account is None:
            raise ValidationError({"account": "Akun tidak ditemukan."})

        start, end = LedgerQueryService.resolve_range(filters)

        base = LedgerQueryService.base_queryset(filters, user=user)

        opening = TrialBalanceQueryService._opening(
            base=base,
            filters=filters,
            start=start,
        ).get(account.pk, ZERO)

        window = (
            base
            .filter(posting_date__gte=start, posting_date__lte=end)
            .annotate(
                running=Window(
                    expression=Sum(F("base_debit") - F("base_credit")),
                    order_by=[
                        F("posting_date").asc(),
                        F("journal_id").asc(),
                        F("line_number").asc(),
                    ],
                ),
            )
            .select_related("journal", "account", "cost_center", "location")
            .order_by("posting_date", "journal_id", "line_number")
        )

        total = base.filter(
            posting_date__gte=start, posting_date__lte=end,
        ).count()

        rows = []

        for line in window[offset:offset + limit]:
            rows.append({
                "line_id": line.pk,
                "journal_id": line.journal_id,
                "journal_number": line.journal.journal_number,
                "journal_type": line.journal.journal_type,
                "posting_date": line.posting_date,
                "description": line.description or line.journal.description,
                "debit": line.base_debit,
                "credit": line.base_credit,
                # Saldo awal ditambahkan di sini, bukan di dalam window:
                # ia konstanta untuk seluruh daftar, dan menaruhnya di
                # SQL berarti mengirim satu angka yang sama berulang kali.
                "running_balance": opening + line.running,
                "location": line.location_id,
                "cost_center": line.cost_center_id,
                # Penelusuran balik ke dokumen sumbernya — separuh dari
                # syarat "traceable both directions".
                "source_module": line.journal.source_module,
                "source_type": line.journal.source_type,
                "source_id": line.journal.source_id,
            })

        movement = TrialBalanceQueryService._aggregate(
            base.filter(posting_date__gte=start, posting_date__lte=end)
        ).get(account.pk, {"debit": ZERO, "credit": ZERO})

        return {
            "account": {
                "id": account.pk,
                "code": account.code,
                "name": account.name,
                "account_type": account.account_type,
                "normal_balance": account.effective_normal_balance,
            },
            "date_from": start,
            "date_to": end,
            "beginning_balance": opening,
            "total_debit": movement["debit"],
            "total_credit": movement["credit"],
            "ending_balance": opening + movement["debit"] - movement["credit"],
            "count": total,
            "offset": offset,
            "limit": limit,
            "rows": rows,
        }
