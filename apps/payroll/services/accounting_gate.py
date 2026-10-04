"""
Gerbang akuntansi Finalize — satu tempat, gagal tertutup.

Di sinilah dua dunia bertemu, dan sengaja **bukan** di
`accounting.py`: normalisasi (PF-0C) adalah milik Payroll seutuhnya dan
tidak boleh mengenal Finance sama sekali, sementara gerbang ini memang
perlu membaca konfigurasi akuntansi. Memisahkannya membuat penjagaan
"normalizer tidak mengimpor Finance" bisa ditegakkan sebuah test,
bukan sekadar disepakati.

Yang dilakukan gerbang ini persis dua hal:

1. Menyusun payload akuntansi dari fakta payroll yang sudah dihitung
   (`PayrollAccountingService`), sehingga komponen yang tidak punya
   makna akuntansi menghentikan Finalize, bukan diam-diam jatuh ke
   kategori lain-lain.
2. Membandingkan mata uang payload dengan mata uang buku besar yang
   dinyatakan Finance.

Yang **tidak** dilakukannya, dan tidak boleh ditambahkan di sini:
menerbitkan kejadian akuntansi, membuat jurnal, menentukan akun, atau
menyentuh buku besar. Semua itu PF-0E dan sesudahnya.

**Periode akuntansi sengaja tidak menghalangi Finalize.** Kalender
Finance yang belum disusun adalah keadaan konfigurasi, dan payroll yang
angkanya sudah benar tidak boleh gagal dikunci karena Finance belum
membuka bulannya. Keadaan itu dibaca dan dilaporkan sebagai konteks
(`period_problem`), lalu ditagih pada tahap penerbitan jurnal — di situ
kegagalannya bisa diulang tanpa menyentuh payroll-nya.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.payroll.services.accounting import (
    PayrollAccountingError,
    PayrollAccountingService,
)


@dataclass(frozen=True)
class AccountingGateResult:
    """Hasil gerbang: payload yang sah beserta konteks konfigurasinya."""

    payload: dict
    currency: str
    base_currency: str
    period_code: str
    period_status: str
    period_problem: str

    @property
    def digest(self) -> str:
        return self.payload["digest"]


class PayrollAccountingGate:
    """Syarat akuntansi yang harus benar sebelum sebuah run dikunci."""

    @classmethod
    def evaluate(cls, *, run) -> AccountingGateResult:
        """
        Payload akuntansi run ini, atau penolakan yang menyebut sebabnya.

        Dipanggil **setelah** `PayrollValidationService` — temuan
        payroll biasa (assignment hilang, baris belum dihitung, net pay
        negatif) harus muncul lebih dulu, karena itu yang bisa
        diperbaiki orang yang menjalankan payroll.
        """
        payload = PayrollAccountingService.build_payload(run=run)

        config = cls._configuration(run=run)

        if not config.has_base_currency:
            raise PayrollAccountingError(
                (
                    "Mata uang buku besar belum ditetapkan. Tandai satu "
                    "mata uang sebagai mata uang dasar di Administration "
                    "→ Currency sebelum payroll dikunci."
                ),
                code="finance_base_currency_missing",
            )

        currency = payload["currency"]

        if currency != config.base_currency_code:
            # Tidak ada konversi, dan tidak ada kurs yang diasumsikan.
            # Payroll dalam mata uang selain mata uang buku adalah
            # pekerjaan tersendiri yang belum dibangun.
            raise PayrollAccountingError(
                (
                    f"Payroll run ini bermata uang {currency}, sementara "
                    f"buku besar berjalan dalam {config.base_currency_code}. "
                    "Akuntansi payroll lintas mata uang belum didukung."
                ),
                code="accounting_currency_not_base",
            )

        return AccountingGateResult(
            payload=payload,
            currency=currency,
            base_currency=config.base_currency_code,
            period_code=config.period_code,
            period_status=config.period_status,
            period_problem=config.period_problem,
        )

    @staticmethod
    def _configuration(*, run):
        """
        Konfigurasi akuntansi milik company run ini.

        Impor di dalam fungsi, bukan di kepala berkas: Payroll menyentuh
        Finance **hanya** lewat satu pintu baca ini, dan impor yang
        tinggal di sini membuat itu terbaca di tempat ia terjadi.
        """
        from apps.finance.services.integration import (
            FinanceAccountingConfigService,
        )

        return FinanceAccountingConfigService.configuration_for(
            company=run.company,
            # Tanggal pengakuan beban payroll: akhir periode, bukan
            # tanggal pembayaran maupun tanggal run dibuat (PF-0B §7).
            on_date=run.period.end_date,
        )
