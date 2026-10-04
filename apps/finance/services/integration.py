"""
Kontrak baca Finance untuk modul sumber — **hanya membaca**.

Modul lain (Payroll hari ini, Inventory nanti) perlu tahu beberapa hal
tentang konfigurasi akuntansi sebelum mereka boleh menyatakan sebuah
dokumen final: mata uang buku besar yang berlaku, dan apakah kalender
akuntansinya sudah menjangkau tanggal dokumen itu. Tanpa satu pintu,
tiap modul akan mengimpor model Finance sendiri-sendiri — dan aturan
"mata uang buku diambil dari master, bukan diketik" akan hidup di lima
tempat yang cepat atau lambat berbeda.

Batasnya tegas, dan itu yang membuat berkas ini aman di tengah
pembekuan Finance:

* **Tidak menulis apa pun.** Tidak ada `create`, `update`, `save`, atau
  `delete` di sini, dan tidak satu pun service penulis dipanggil.
* **Tidak melempar.** Konfigurasi yang belum ada dilaporkan sebagai
  nilai kosong, bukan sebagai error — yang memutuskan apakah keadaan itu
  cukup untuk melanjutkan adalah modul sumbernya, bukan Finance.
* **Tidak menentukan akun.** Pemetaan semantik → akun tetap milik
  `AccountingPolicy` + `AccountMapping`, dan tidak disentuh di sini.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.core.exceptions import ValidationError

from apps.finance.models import PeriodStatus
from apps.finance.services.fiscal import FiscalPeriodService


@dataclass(frozen=True)
class AccountingConfiguration:
    """Keadaan konfigurasi akuntansi yang relevan bagi modul sumber."""

    company_id: int | None

    # Mata uang buku besar tenant ini, dibaca dengan aturan yang sama
    # persis dengan `JournalService._apply_currency()`.
    base_currency_id: int | None = None
    base_currency_code: str = ""

    # Kalender akuntansi pada tanggal yang ditanyakan. Kosong berarti
    # belum disusun — **bukan** berarti tertutup.
    fiscal_year_code: str = ""
    period_code: str = ""
    period_status: str = ""

    # Alasan kalendernya tidak bisa dipakai, dalam kalimat Finance
    # sendiri. Kosong kalau periodenya ketemu.
    period_problem: str = ""

    @property
    def has_base_currency(self) -> bool:
        return bool(self.base_currency_code)

    @property
    def has_period(self) -> bool:
        return bool(self.period_code)

    @property
    def period_is_open(self) -> bool:
        return self.period_status == PeriodStatus.OPEN


class FinanceAccountingConfigService:
    """Pembacaan konfigurasi akuntansi, untuk modul di luar Finance."""

    @staticmethod
    def base_currency():
        """
        Mata uang buku besar tenant ini, atau `None`.

        Aturannya **tidak ditulis ulang**: `JournalService` memilih baris
        bertanda `is_base_currency` dengan pk terkecil, dan yang di sini
        harus memilih baris yang sama. Kalau tidak, sebuah modul bisa
        menyatakan dokumennya sah dalam mata uang yang justru ditolak
        saat jurnalnya terbit.
        """
        from apps.administration.models import Currency

        return (
            Currency.objects
            .filter(is_base_currency=True, is_deleted=False)
            .order_by("pk")
            .first()
        )

    @classmethod
    def configuration_for(
        cls,
        *,
        company,
        on_date: date | None = None,
    ) -> AccountingConfiguration:
        """
        Konfigurasi akuntansi satu perusahaan pada satu tanggal.

        `on_date` boleh kosong kalau penanya cuma butuh mata uang.
        Kalender yang belum disusun dilaporkan lewat `period_problem`,
        tidak dilempar — modul sumber yang menentukan apakah itu
        menghalanginya.
        """
        currency = cls.base_currency()

        fiscal_year_code = ""
        period_code = ""
        period_status = ""
        period_problem = ""

        if on_date is not None and company is not None:
            try:
                period = FiscalPeriodService.resolve(
                    company=company,
                    posting_date=on_date,
                )
            except ValidationError as error:
                period_problem = "; ".join(error.messages)[:500]
            else:
                fiscal_year_code = period.fiscal_year.code
                period_code = period.code
                period_status = period.status

        return AccountingConfiguration(
            company_id=getattr(company, "pk", None),
            base_currency_id=getattr(currency, "pk", None),
            base_currency_code=(getattr(currency, "code", "") or "").strip().upper(),
            fiscal_year_code=fiscal_year_code,
            period_code=period_code,
            period_status=period_status,
            period_problem=period_problem,
        )
