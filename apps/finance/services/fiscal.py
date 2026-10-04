"""
Service tahun buku dan periode akuntansi.

`FiscalPeriodService` di bawah adalah penjaganya: satu tempat yang
menjawab "tanggal ini jatuh di periode mana" dan "periode itu menerima
posting atau tidak". Dua pertanyaan yang ditanyakan posting engine,
pembuatan jurnal, dan pemroses kejadian akuntansi — dan yang kalau
dijawab di tiga tempat akan berbeda pendapat cepat atau lambat.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.core.services.master import BaseMasterService
from apps.finance.services.authority import (
    ADD_PERIOD_PERMISSION,
    CHANGE_PERIOD_PERMISSION,
    assert_finance_action,
)
from apps.finance.models import (
    AccountingPeriod,
    FiscalYear,
    FiscalYearStatus,
    Journal,
    JournalStatus,
    PeriodStatus,
)


# Izin yang membuat seseorang boleh memposting ke periode
# `SOFT_CLOSED`. Izin Django biasa, jadi ia bisa dicentang di layar
# Roles seperti izin lain — bukan daftar kode role yang ditanam di kode.
POST_SOFT_CLOSED_PERMISSION = "finance.post_soft_closed_period"

# Izin membuka kembali periode yang sudah `LOCKED`.
REOPEN_LOCKED_PERMISSION = "finance.reopen_locked_period"


class FiscalYearService(BaseMasterService):
    model = FiscalYear

    @staticmethod
    def list():
        return (
            FiscalYear.objects
            .filter(is_deleted=False)
            .select_related("company")
            .order_by("company_id", "-start_date")
        )

    @classmethod
    def after_create(cls, *, instance, user=None, **kwargs):
        cls._sync_current(instance)

        return instance

    @classmethod
    def after_update(cls, *, instance, user=None, **kwargs):
        cls._sync_current(instance)

        return instance

    @staticmethod
    def _sync_current(year: FiscalYear) -> None:
        """
        Satu tahun berjalan per perusahaan.

        Dipadamkan di baris lain, bukan ditolak: menandai tahun buku
        baru sebagai yang berjalan adalah hal yang memang dilakukan
        orang tiap tahun, dan menuntutnya mematikan yang lama lebih dulu
        cuma membuat langkah biasa jadi dua langkah yang bisa lupa.
        """
        if not year.is_current:
            return

        (
            FiscalYear.objects
            .filter(company_id=year.company_id, is_current=True)
            .exclude(pk=year.pk)
            .update(is_current=False)
        )

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        used = Journal.objects.filter(
            fiscal_year=instance, is_deleted=False,
        ).count()

        if used:
            raise ValidationError({
                "fiscal_year": (
                    f"Tahun buku ini sudah dipakai {used} jurnal dan "
                    "tidak bisa dihapus."
                ),
            })

    # ------------------------------------------------------------------
    # Pembuatan periode
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def generate_periods(
        cls,
        *,
        fiscal_year: FiscalYear,
        count: int = 12,
        user=None,
    ) -> list[AccountingPeriod]:
        """
        Membuat periode secara merata sepanjang tahun buku.

        **Dua belas cuma nilai bawaan, bukan asumsi.** Perusahaan yang
        memakai empat periode kuartalan mengirim `count=4`, dan yang
        memakai tiga belas periode empat mingguan mengirim `count=13`.

        Untuk `count=12` pada tahun buku yang mulai di tanggal 1,
        batasnya jatuh persis di batas bulan kalender — itu yang
        dikehendaki hampir semua orang. Di luar itu, rentangnya dibagi
        rata dan sisa harinya jatuh ke periode terakhir; periode yang
        panjangnya berbeda beberapa hari tetap periode yang sah, dan
        menolak menghasilkannya memaksa orang mengetik dua belas baris
        tangan.
        """
        # FIN-B1/B2. `generate-periods/` adalah `@action` kustom —
        # `ModelPermission` tidak menjaganya — padahal ia menerbitkan
        # kalender akuntansi. Menagih izin membuat periode, dengan
        # cakupan perusahaan tahun bukunya dari izin itu.
        assert_finance_action(
            user=user,
            permission=ADD_PERIOD_PERMISSION,
            queryset=FiscalYear.objects.filter(pk=fiscal_year.pk),
            scope={"company": "company"},
            action="menyusun periode akuntansi",
        )

        if fiscal_year.periods.filter(is_deleted=False).exists():
            raise ValidationError({
                "fiscal_year": (
                    "Tahun buku ini sudah punya periode. Hapus dulu yang "
                    "ada kalau memang mau disusun ulang — periode yang "
                    "sudah dipakai jurnal tidak bisa dihapus."
                ),
            })

        if count < 1 or count > 24:
            raise ValidationError({
                "count": "Jumlah periode harus antara 1 dan 24.",
            })

        ranges = cls._period_ranges(fiscal_year, count)

        created: list[AccountingPeriod] = []

        for number, (start, end) in enumerate(ranges, start=1):
            created.append(
                AccountingPeriodService.create(
                    data={
                        "fiscal_year": fiscal_year,
                        "period_number": number,
                        "code": f"{fiscal_year.code}-{number:02d}",
                        "name": start.strftime("%B %Y"),
                        "start_date": start,
                        "end_date": end,
                        "status": PeriodStatus.OPEN,
                    },
                    user=user,
                )
            )

        return created

    @staticmethod
    def _period_ranges(
        fiscal_year: FiscalYear,
        count: int,
    ) -> list[tuple[date, date]]:
        start = fiscal_year.start_date
        end = fiscal_year.end_date

        # Jalur bulan kalender — yang dipakai hampir semua tenant.
        if count == 12 and start.day == 1:
            ranges: list[tuple[date, date]] = []

            year, month = start.year, start.month

            for _ in range(12):
                last = monthrange(year, month)[1]

                ranges.append((
                    date(year, month, 1),
                    min(date(year, month, last), end),
                ))

                month += 1

                if month > 12:
                    month = 1
                    year += 1

            return ranges

        total = (end - start).days + 1
        size = total // count

        if size < 1:
            raise ValidationError({
                "count": (
                    f"Tahun buku ini cuma {total} hari — tidak bisa "
                    f"dibagi jadi {count} periode."
                ),
            })

        ranges = []
        cursor = start

        for index in range(count):
            # Periode terakhir menyerap sisa pembagian, jadi tahun
            # bukunya tertutup rapat sampai hari terakhir. Membiarkan
            # sisanya di luar periode mana pun berarti ada tanggal yang
            # tidak bisa dibukukan sama sekali — dan tidak ada satu pun
            # pesan yang akan menyebutkannya.
            last = end if index == count - 1 else cursor + timedelta(days=size - 1)

            ranges.append((cursor, last))

            cursor = last + timedelta(days=1)

        return ranges


class AccountingPeriodService(BaseMasterService):
    model = AccountingPeriod

    @staticmethod
    def list():
        return (
            AccountingPeriod.objects
            .filter(is_deleted=False)
            .select_related("fiscal_year", "fiscal_year__company")
            .order_by("fiscal_year__start_date", "period_number")
        )

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        used = Journal.objects.filter(
            accounting_period=instance, is_deleted=False,
        ).count()

        if used:
            raise ValidationError({
                "accounting_period": (
                    f"Periode ini sudah dipakai {used} jurnal dan tidak "
                    "bisa dihapus."
                ),
            })

    # ------------------------------------------------------------------
    # Perpindahan status
    # ------------------------------------------------------------------

    # Perpindahan yang diizinkan. Ditulis sebagai peta, bukan sebagai
    # rangkaian `if`: daftar yang bisa dibaca sekali lihat adalah
    # daftar yang bisa diperiksa orang yang tidak menulisnya.
    TRANSITIONS = {
        PeriodStatus.OPEN: {PeriodStatus.SOFT_CLOSED, PeriodStatus.CLOSED},
        PeriodStatus.SOFT_CLOSED: {PeriodStatus.OPEN, PeriodStatus.CLOSED},
        PeriodStatus.CLOSED: {
            PeriodStatus.OPEN,
            PeriodStatus.SOFT_CLOSED,
            PeriodStatus.LOCKED,
        },
        # Dari LOCKED cuma bisa ke CLOSED, dan itu pun lewat
        # `reopen()` yang menuntut alasan dan izin tersendiri. Membuka
        # langsung ke OPEN dari keadaan terkunci berarti periode yang
        # sudah diaudit kembali menerima transaksi harian dalam satu
        # klik.
        PeriodStatus.LOCKED: {PeriodStatus.CLOSED},
    }

    STRICTNESS = {
        PeriodStatus.OPEN: 0,
        PeriodStatus.SOFT_CLOSED: 1,
        PeriodStatus.CLOSED: 2,
        PeriodStatus.LOCKED: 3,
    }

    @classmethod
    @transaction.atomic
    def change_status(
        cls,
        *,
        period: AccountingPeriod,
        status: str,
        user=None,
        reason: str = "",
    ) -> AccountingPeriod:
        # FIN-B1/B2. Menutup, mengunci, dan membuka periode mengubah
        # apa yang boleh masuk buku besar. Sebelum ini cukup "cakupan
        # company" — `change-status/` adalah `@action` kustom yang tidak
        # dijaga `ModelPermission`. Membuka kembali periode LOCKED tetap
        # menagih `reopen_locked_period` di atas ini.
        assert_finance_action(
            user=user,
            permission=CHANGE_PERIOD_PERMISSION,
            queryset=AccountingPeriod.objects.filter(pk=period.pk),
            scope={"company": "fiscal_year__company"},
            action="mengubah status periode akuntansi",
        )

        current = period.status

        if status == current:
            return period

        if status not in cls.TRANSITIONS.get(current, set()):
            raise ValidationError({
                "status": (
                    f"Periode '{period.code}' berstatus "
                    f"{period.get_status_display()} dan tidak bisa "
                    f"langsung dipindah ke "
                    f"{PeriodStatus(status).label}."
                ),
            })

        if current == PeriodStatus.LOCKED:
            cls._assert_may_reopen(user=user, period=period, reason=reason)

        now = timezone.now()

        data: dict = {"status": status}

        # Arahnya dibaca dari **urutan ketatnya**, bukan dari status
        # tujuannya saja. LOCKED → CLOSED berakhir di status "tertutup",
        # tapi tindakannya pembukaan kembali: periode yang sudah dikunci
        # auditor dilonggarkan. Menilainya dari tujuan saja mencatatnya
        # sebagai penutupan dan membuang alasan yang barusan diwajibkan
        # `_assert_may_reopen` — tepat jejak yang diminta §5.
        closing = cls.STRICTNESS[status] > cls.STRICTNESS[current]

        if closing:
            data["closed_at"] = now
            data["closed_by"] = user
        else:
            # Membuka kembali. Jejaknya ditulis di sini dan **tidak**
            # menghapus jejak penutupan sebelumnya: pertanyaan yang
            # ditanyakan auditor adalah "ditutup kapan, lalu dibuka lagi
            # kapan dan kenapa", dan menghapus yang pertama membuang
            # separuh jawabannya.
            data["reopened_at"] = now
            data["reopened_by"] = user
            data["reopen_reason"] = reason

        return cls.update(instance=period, data=data, user=user)

    @classmethod
    def _assert_may_reopen(cls, *, user, period, reason: str) -> None:
        if not reason.strip():
            raise ValidationError({
                "reason": (
                    f"Periode '{period.code}' sudah dikunci. Sebutkan "
                    "alasan pembukaannya — tanpa itu tidak ada yang bisa "
                    "menjelaskan kenapa angka yang sudah dilaporkan "
                    "berubah."
                ),
            })

        if user is None:
            # Jalur sistem (seed, perintah manajemen) memang berjalan
            # tanpa orang. Dilewati sengaja, sama seperti
            # `assert_employee_allowed` di modul HR.
            return

        if user.is_superuser or user.has_perm(REOPEN_LOCKED_PERMISSION):
            return

        raise ValidationError({
            "status": (
                f"Periode '{period.code}' terkunci. Membukanya kembali "
                "perlu wewenang 'Reopen locked accounting period'."
            ),
        })


class FiscalPeriodService:
    """
    Penjaga kalender akuntansi.

    Satu-satunya tempat yang menjawab dua pertanyaan di bawah. Posting
    engine, pembuatan jurnal, dan pemroses kejadian semuanya lewat sini
    — bukan masing-masing menyaring `AccountingPeriod` sendiri.
    """

    @staticmethod
    def resolve(*, company, posting_date: date) -> AccountingPeriod:
        """
        Periode yang memuat tanggal ini, atau penolakan yang menyebut
        sebabnya.

        Kegagalannya dipisah jadi dua kalimat yang berbeda, dan itu
        bukan kemewahan: "tahun bukunya belum dibuat" dan "tahun
        bukunya ada tapi periodenya belum disusun" menuntut dua tindakan
        yang berbeda dari orang yang membacanya.
        """
        period = (
            AccountingPeriod.objects
            .select_related("fiscal_year")
            .filter(
                is_deleted=False,
                fiscal_year__company=company,
                fiscal_year__is_deleted=False,
                start_date__lte=posting_date,
                end_date__gte=posting_date,
            )
            .order_by("start_date")
            .first()
        )

        if period is not None:
            return period

        year_exists = FiscalYear.objects.filter(
            company=company,
            is_deleted=False,
            start_date__lte=posting_date,
            end_date__gte=posting_date,
        ).exists()

        if year_exists:
            raise ValidationError({
                "posting_date": (
                    f"Tahun buku yang memuat {posting_date} sudah ada, "
                    "tapi periodenya belum disusun. Buka Fiscal Years "
                    "lalu jalankan Generate Periods."
                ),
            })

        raise ValidationError({
            "posting_date": (
                f"Belum ada tahun buku yang memuat {posting_date} untuk "
                "perusahaan ini. Buat tahun bukunya lebih dulu di "
                "Finance → Setup → Fiscal Years."
            ),
        })

    @staticmethod
    def assert_postable(
        *,
        period: AccountingPeriod,
        user=None,
        action: str = "diposting",
    ) -> None:
        """
        Menolak posting ke periode yang tidak menerimanya.

        `SOFT_CLOSED` adalah satu-satunya keadaan yang bergantung pada
        siapa yang meminta, dan itulah gunanya keadaan itu ada: tutup
        buku operasional menghentikan transaksi harian tanpa
        menghentikan jurnal penyesuaian yang justru sedang dikerjakan.
        """
        status = period.status

        if status == PeriodStatus.OPEN:
            return

        if status == PeriodStatus.SOFT_CLOSED:
            if user is None:
                return

            if user.is_superuser or user.has_perm(POST_SOFT_CLOSED_PERMISSION):
                return

            raise ValidationError({
                "accounting_period": (
                    f"Periode '{period.code}' sudah ditutup sementara "
                    "(soft closed). Hanya yang punya wewenang "
                    "'Post to soft-closed accounting period' yang masih "
                    f"bisa {action} ke periode ini."
                ),
            })

        label = PeriodStatus(status).label

        raise ValidationError({
            "accounting_period": (
                f"Periode '{period.code}' berstatus {label} — tidak ada "
                f"dokumen yang bisa {action} ke sana. Buka kembali "
                "periodenya dari Finance → Setup → Accounting Periods."
            ),
        })

    @staticmethod
    def assert_year_open(*, fiscal_year: FiscalYear) -> None:
        if fiscal_year.status == FiscalYearStatus.OPEN:
            return

        raise ValidationError({
            "fiscal_year": (
                f"Tahun buku '{fiscal_year.code}' berstatus "
                f"{fiscal_year.get_status_display()}."
            ),
        })

    @classmethod
    def open_period_for(cls, *, company, posting_date: date, user=None):
        """Gabungan `resolve` + kedua penjagaannya — jalur yang dipakai posting."""
        period = cls.resolve(company=company, posting_date=posting_date)

        cls.assert_year_open(fiscal_year=period.fiscal_year)
        cls.assert_postable(period=period, user=user)

        return period

    @staticmethod
    def has_posted_journals(period: AccountingPeriod) -> bool:
        return Journal.objects.filter(
            accounting_period=period,
            status=JournalStatus.POSTED,
            is_deleted=False,
        ).exists()
