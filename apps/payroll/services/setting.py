"""
Kebijakan penggajian per perusahaan, dan cara membacanya.

Dua kebijakan tinggal di sini, dan keduanya dibaca lewat objek yang
**berbeda**: prorata gaji pokok (Business Decision #1) lewat
`ProrationPolicy`, potongan ketidakhadiran (Business Decision #2) lewat
`AttendancePolicy`. Satu dataclass gemuk berisi keduanya akan membuat
mesin hitung menerima kebijakan prorata di tempat yang seharusnya cuma
tahu soal potongan — dan pemisahan itu justru inti keputusan #2.

Yang dijaga service ini tetap dua hal yang sama: kebijakan dibaca lewat
satu pintu, dan perusahaan yang belum memilih tidak diam-diam dianggap
sudah memilih.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.core.services.master import BaseMasterService
from apps.payroll.models import (
    DEFAULT_PRORATION_METHOD,
    PayrollProrationMethod,
    PayrollSetting,
)


@dataclass(frozen=True)
class ProrationPolicy:
    """
    Kebijakan yang berlaku untuk satu run, sudah jadi nilai.

    `is_default` menandai perusahaan yang **belum punya baris
    `PayrollSetting`**. Bedanya penting: metodenya sama dengan yang
    dipakai sebelum kebijakan ini ada, tapi asalnya bukan keputusan
    siapa pun — dan run-nya membawa temuan yang menyebut itu.
    """

    method: str
    prorate_on_join: bool
    prorate_on_termination: bool
    is_default: bool

    @property
    def method_label(self) -> str:
        return PayrollProrationMethod(self.method).label


DEFAULT_POLICY = ProrationPolicy(
    method=DEFAULT_PRORATION_METHOD,
    prorate_on_join=True,
    prorate_on_termination=True,
    is_default=True,
)


@dataclass(frozen=True)
class AttendancePolicy:
    """
    Kebijakan potongan ketidakhadiran, sudah jadi nilai.

    `method` boleh **kosong**, dan kosong bukan kelalaian: itu keadaan
    perusahaan yang belum memilih apa pun. Pembaginya lalu diambil dari
    `PayrollPeriod.divisor_days` — persis perilaku engine sebelum
    kebijakan ini ada, jadi menambah layar konfigurasi tidak menggeser
    satu rupiah pun pada payroll yang sudah berjalan. Yang membedakan
    "belum memilih" dari "memilih Calendar Days" adalah `is_default`,
    dan run-nya membawa temuan yang menyebutnya.
    """

    method: str
    deduct_absence: bool
    deduct_unpaid_leave: bool
    is_default: bool

    @property
    def method_label(self) -> str:
        if not self.method:
            return "Pembagi hari periode"

        return PayrollProrationMethod(self.method).label


DEFAULT_ATTENDANCE_POLICY = AttendancePolicy(
    method="",
    deduct_absence=True,
    deduct_unpaid_leave=True,
    is_default=True,
)


class PayrollSettingService(BaseMasterService):
    model = PayrollSetting

    @classmethod
    def get_queryset(cls):
        return super().get_queryset().select_related("company")

    @classmethod
    def resolve_policy(cls, *, company) -> ProrationPolicy:
        """
        Kebijakan prorata perusahaan ini, atau bawaan kalau belum ada.

        Dipanggil **sekali per run**, bukan per pegawai: kebijakannya
        milik perusahaan, dan membacanya ulang untuk tiap baris berarti
        ratusan query yang jawabannya sama.
        """
        if company is None:
            return DEFAULT_POLICY

        row = (
            cls.get_queryset()
            .filter(company=company, is_active=True)
            .first()
        )

        if row is None:
            return DEFAULT_POLICY

        return ProrationPolicy(
            method=row.proration_method,
            prorate_on_join=row.prorate_on_join,
            prorate_on_termination=row.prorate_on_termination,
            is_default=False,
        )

    @classmethod
    def resolve_attendance_policy(cls, *, company) -> AttendancePolicy:
        """
        Kebijakan potongan ketidakhadiran perusahaan ini.

        Sama seperti `resolve_policy`: dipanggil **sekali per run**.
        Barisnya sama, tapi objek yang keluar berbeda — yang membaca
        potongan tidak perlu tahu apa pun tentang prorata, dan
        sebaliknya.

        Perusahaan yang punya baris `PayrollSetting` tapi belum mengisi
        metodenya tetap `is_default=True`: yang menentukan bukan ada
        tidaknya baris, melainkan ada tidaknya **keputusan**.
        """
        if company is None:
            return DEFAULT_ATTENDANCE_POLICY

        row = (
            cls.get_queryset()
            .filter(company=company, is_active=True)
            .first()
        )

        if row is None:
            return DEFAULT_ATTENDANCE_POLICY

        return AttendancePolicy(
            method=row.attendance_deduction_method,
            deduct_absence=row.deduct_absence,
            deduct_unpaid_leave=row.deduct_unpaid_leave,
            is_default=not row.attendance_deduction_method,
        )
