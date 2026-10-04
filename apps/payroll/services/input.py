"""
Service Payroll Input.

Yang dijaga di sini cuma satu hal, dan itu yang paling mudah terlewat:
**input tidak boleh berubah setelah periodenya dikunci.** Tanpa itu,
angka yang sudah tercetak di slip bisa punya dokumen sumber yang isinya
berbeda, dan tidak ada satu pun laporan yang bisa menjelaskan selisihnya.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError

from apps.core.services.master import BaseMasterService
from apps.payroll.models import PayrollInput, PayrollInputStatus


class PayrollInputService(BaseMasterService):
    model = PayrollInput

    @classmethod
    def get_queryset(cls):
        return (
            super()
            .get_queryset()
            .select_related(
                "period",
                "employee",
                "allowance_line",
                "allowance_line__template",
                "deduction_line",
                "deduction_line__template",
            )
        )

    @staticmethod
    def assert_period_open(period) -> None:
        """
        Statusnya dibaca ulang dari database, bukan dari objek yang
        dioper pemanggil.

        Ditemukan lewat UAT penguncian: objek `PayrollPeriod` yang sudah
        lama dipegang pemanggil membawa status **lama**, jadi periode
        yang dikunci di antaranya tetap terbaca terbuka dan
        penyuntingan inputnya lolos. Jalur API kebetulan selamat —
        `get_object()` membaca barisnya baru setiap request — sehingga
        kebocorannya hanya muncul di jalur service, dan muncul **diam**:
        tidak ada error, angkanya saja yang berubah di belakang payroll
        yang slipnya sudah terbit.

        Satu query ringan per penulisan input adalah harga yang murah
        untuk menutupnya di semua jalur sekaligus.
        """
        if period is None:
            return

        from apps.payroll.models import PayrollPeriod, PayrollPeriodStatus

        locked = (
            PayrollPeriod.objects
            .filter(
                pk=period.pk,
                status=PayrollPeriodStatus.FINALIZED,
            )
            .exists()
        )

        if locked:
            raise ValidationError(
                {
                    "period": (
                        "Periode ini sudah Finalized. Input baru harus "
                        "masuk lewat periode berikutnya, atau lewat "
                        "payroll run bertipe Correction."
                    ),
                },
            )

    @classmethod
    def prepare_create_data(
        cls,
        *,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_period_open(data.get("period"))

        # Kode dan nama disalin dari master saat komponennya dipilih,
        # supaya laporan dan slip bisa mengelompokkan tanpa menembus
        # relasi — dan supaya baris tetap terbaca kalau baris master
        # yang dirujuknya kelak dinonaktifkan.
        line = data.get("allowance_line") or data.get("deduction_line")

        if line is not None:
            data.setdefault("code", line.code)
            data.setdefault("name", line.name)

        return data

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ) -> dict[str, Any]:
        cls.assert_period_open(instance.period)

        if instance.status == PayrollInputStatus.CANCELLED:
            raise ValidationError(
                {
                    "status": (
                        "Input yang sudah dibatalkan tidak bisa "
                        "diubah."
                    ),
                },
            )

        # Periode tidak boleh berpindah: nilainya sudah ikut terhitung
        # di run periode ini, dan memindahkannya membuat total run yang
        # sudah dihitung tidak lagi sama dengan jumlah inputnya.
        data.pop("period", None)

        return data

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs):
        cls.assert_period_open(instance.period)

        return super().before_soft_delete(instance=instance, user=user, **kwargs)
