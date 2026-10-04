"""
Resolusi kebijakan perhitungan payroll.

**Satu pintu, tiga lapis, urutan yang tetap:**

    1. `PayrollPolicy` yang dibawa `PayrollAssignment` yang berlaku
    2. `PayrollSetting` perusahaan
    3. perilaku teknis sebelum kebijakan apa pun ada — beserta temuan
       WARNING yang menyebut bahwa itu yang sedang dipakai

Lapis ketiga bukan bawaan yang dipilih siapa pun; ia yang menjaga
payroll yang sudah berjalan tidak bergeser angkanya hanya karena tabel
baru lahir. Yang membedakannya dari keputusan yang kebetulan sama
adalah temuannya, bukan angkanya.

Kosong = ikut lapis di atasnya, **bukan** "matikan". Itu yang membuat
sebuah kebijakan bisa dibuat untuk satu perbedaan saja — "sama seperti
perusahaan, kecuali potongannya pakai hari kerja" — tanpa menyalin
ulang seluruh keputusan perusahaan, dan yang membuat perubahan di
tingkat perusahaan tetap menetes ke bawah.

Hasilnya `ResolvedPolicy`: nilai jadi, tidak bisa berubah, dan yang
masuk ke `CalculationInput`. Mesin hitung tidak pernah melihat
`PayrollPolicy` maupun `PayrollSetting` — ia menerima angka dan saklar
yang sudah selesai diperdebatkan.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from apps.core.services.master import BaseMasterService
from apps.payroll.models import (
    PayrollDailyRateMethod,
    PayrollPayBasis,
    PayrollPolicy,
    PayrollPolicyToggle,
)
from apps.payroll.services.setting import AttendancePolicy, ProrationPolicy

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class ResolvedPolicy:
    """
    Kebijakan satu pegawai untuk satu run, sudah jadi nilai.

    Dibentuk sekali per assignment dan dipakai apa adanya. Yang
    membacanya tidak perlu tahu nilai mana datang dari kebijakan
    kelompok dan mana dari perusahaan — kecuali untuk dicetak di
    layar, dan itu yang dijawab `label`.
    """

    pay_basis: str
    proration: ProrationPolicy
    attendance: AttendancePolicy

    daily_rate_method: str = ""
    daily_rate_divisor: Decimal | None = None
    pay_paid_leave: bool | None = None

    policy_id: int | None = None
    policy_code: str = ""
    policy_name: str = ""

    @property
    def is_daily(self) -> bool:
        return self.pay_basis == PayrollPayBasis.DAILY

    @property
    def label(self) -> str:
        """
        Sumber kebijakan, sebagai kalimat.

        Pegawai tanpa kebijakan kelompok **tidak** dibiarkan kosong di
        layar: sel kosong terbaca seperti data yang gagal termuat,
        sementara yang sebenarnya terjadi adalah ia mengikuti default
        perusahaan — dan itu jawaban yang sah.
        """
        if self.policy_id is None:
            return "Default perusahaan"

        return f"{self.policy_code} - {self.policy_name}".strip(" -")

    @property
    def pay_basis_label(self) -> str:
        return PayrollPayBasis(self.pay_basis).label


class PayrollPolicyService(BaseMasterService):
    model = PayrollPolicy

    @classmethod
    def get_queryset(cls):
        return super().get_queryset().select_related("company")

    # ------------------------------------------------------------------

    @classmethod
    def resolve(
        cls,
        *,
        policy,
        company_proration: ProrationPolicy,
        company_attendance: AttendancePolicy,
    ) -> ResolvedPolicy:
        """
        Gabungkan kebijakan kelompok di atas default perusahaan.

        `policy` boleh `None` — itu keadaan yang paling lazim, dan
        hasilnya persis kebijakan perusahaan apa adanya. Kebijakan
        perusahaan sendiri sudah dibaca **sekali per run** oleh
        pemanggil; fungsi ini tidak menyentuh database sama sekali,
        jadi memanggilnya untuk lima ratus pegawai tetap nol query.
        """
        if policy is None or not policy.is_active:
            # Kebijakan yang dinonaktifkan tidak diam-diam tetap
            # berlaku, tapi juga tidak menghapus pegawainya dari run —
            # ia jatuh ke default perusahaan dan validasi yang
            # menyebutnya.
            return ResolvedPolicy(
                pay_basis=PayrollPayBasis.MONTHLY,
                proration=company_proration,
                attendance=company_attendance,
            )

        proration = ProrationPolicy(
            method=policy.proration_method or company_proration.method,
            prorate_on_join=cls._pick(
                policy.prorate_on_join, company_proration.prorate_on_join,
            ),
            prorate_on_termination=cls._pick(
                policy.prorate_on_termination,
                company_proration.prorate_on_termination,
            ),
            # `is_default` tetap milik perusahaan: yang ditanyakannya
            # "sudah ada yang memutuskan metodenya?", dan kebijakan
            # kelompok yang mengisi metodenya sendiri berarti sudah.
            is_default=(
                company_proration.is_default
                and not policy.proration_method
            ),
        )

        attendance = AttendancePolicy(
            method=(
                policy.attendance_deduction_method
                or company_attendance.method
            ),
            deduct_absence=cls._pick(
                policy.deduct_absence, company_attendance.deduct_absence,
            ),
            deduct_unpaid_leave=cls._pick(
                policy.deduct_unpaid_leave,
                company_attendance.deduct_unpaid_leave,
            ),
            is_default=(
                company_attendance.is_default
                and not policy.attendance_deduction_method
            ),
        )

        return ResolvedPolicy(
            pay_basis=policy.pay_basis or PayrollPayBasis.MONTHLY,
            proration=proration,
            attendance=attendance,
            daily_rate_method=policy.daily_rate_method,
            daily_rate_divisor=policy.daily_rate_divisor,
            pay_paid_leave=policy.pays_paid_leave,
            policy_id=policy.pk,
            policy_code=policy.code,
            policy_name=policy.name,
        )

    @staticmethod
    def _pick(value, fallback):
        """
        Saklar tiga keadaan → boolean.

        Ditulis sebagai fungsi bernama karena `value or fallback` di
        sini salah, dan salahnya senyap: kebijakan yang dengan sengaja
        **mematikan** prorata akan diam-diam menyalakannya kembali dari
        perusahaan, dan tidak ada satu layar pun yang menunjukkannya.
        """
        if value == PayrollPolicyToggle.ON:
            return True

        if value == PayrollPolicyToggle.OFF:
            return False

        return fallback

    # ------------------------------------------------------------------

    @classmethod
    def daily_rate(cls, *, resolved: ResolvedPolicy, basic_salary, assignment_rate):
        """
        Upah sehari pegawai harian. Mengembalikan `(tarif, keterangan)`.

        Keterangannya **ekspresi** kalau tarifnya ada (`3000000 / 26`,
        supaya hitungan tangan HR menghasilkan angka yang persis sama),
        dan **alasan** kalau tarifnya nol. Dua arti untuk satu nilai,
        dibedakan oleh tarifnya sendiri.

        Tarif nol berarti belum bisa dihitung — pemanggil yang
        menerbitkan temuannya. Yang **tidak** dilakukan di sini:
        menebak tarif dari angka mana pun yang kebetulan ada. Upah
        sehari yang salah tidak menghasilkan error, ia menghasilkan
        orang yang dibayar keliru selama berbulan-bulan.

        Gaji yang dipakai gaji sebulan **penuh**, bukan yang sudah
        diprorata. Pegawai harian memang tidak diprorata, tapi
        urutannya tetap ditulis di sini supaya tidak ada yang
        memasangnya belakangan — persis alasan yang sama dengan upah
        per jam lembur.
        """
        if resolved.daily_rate_method == PayrollDailyRateMethod.ASSIGNMENT_RATE:
            # Tanpa ekspresi: tarifnya angka utuh yang ditulis orang,
            # jadi keterangan perhitungan cukup menyebut tarifnya.
            return Decimal(assignment_rate or 0), ""

        if resolved.daily_rate_method == PayrollDailyRateMethod.FROM_MONTHLY:
            divisor = Decimal(resolved.daily_rate_divisor or 0)
            monthly = Decimal(basic_salary or 0)

            if divisor <= ZERO:
                return ZERO, "pembagi upah harian belum diisi"

            # Dibiarkan tidak dibulatkan. Pembulatannya sekali saja, di
            # mesin hitung, sesudah dikali jumlah hari — 3.000.000 / 26
            # dibulatkan lebih dulu lalu dikali 26 menghasilkan
            # 2.999.997,74.
            return monthly / divisor, f"{monthly} / {divisor}"

        return ZERO, "cara upah harian belum ditentukan"
