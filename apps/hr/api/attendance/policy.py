"""
Membaca `AttendancePolicy` lalu menurunkan angka-angka kehadiran.

Dipisah dari service karena dipanggil tiga tempat: saat baris presensi
dibuat, saat disunting, dan saat seluruh bulan dihitung ulang setelah
aturannya diubah. Perhitungannya **fungsi murni** — masukkan jadwal,
jam tap, dan aturannya, keluar angka. Tidak ada query di dalamnya, jadi
menghitung ulang seribu baris tidak berarti seribu pencarian policy.

Yang diputuskan di sini
-----------------------
* status `late` atau `present`
* `late_minutes`, `early_leave_minutes`, `overtime_minutes`
* `worked_minutes`

Yang **tidak** disentuh: `check_in` dan `check_out`. Jam tap adalah
fakta, dan toleransi tidak boleh mengubahnya — kalau jamnya ikut
digeser, tidak ada lagi cara menjawab "jam berapa sebenarnya dia
datang".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from apps.administration.models import AttendancePolicy
from apps.hr.models.attendance.choices import AttendanceStatus


# Status yang memang bukan hasil tap: cuti, libur, hari off, dan
# ketidakhadiran. Menghitung ulang keterlambatannya tidak masuk akal —
# tidak ada jam masuk untuk dibandingkan.
NON_COMPUTED_STATUSES = {
    AttendanceStatus.ABSENT,
    AttendanceStatus.LEAVE,
    AttendanceStatus.SICK,
    AttendanceStatus.PERMIT,
    AttendanceStatus.HOLIDAY,
    AttendanceStatus.DAY_OFF,
}


@dataclass(frozen=True)
class AttendanceRules:
    """
    Bentuk siap-hitung dari sebuah `AttendancePolicy`.

    Dipakai supaya pemanggil tidak perlu memegang instance model —
    perintah hitung-ulang me-resolve policy sekali per pegawai lalu
    memakai ulang aturannya untuk seluruh barisnya.
    """

    late_tolerance_minutes: int = 0
    late_counts_from_tolerance: bool = True
    early_leave_tolerance_minutes: int = 0
    overtime_threshold_minutes: int = 30
    overtime_rounding_minutes: int = 0
    break_minutes: int = 60

    # Nol = aturannya mati. Bawaan ini yang membuat tenant yang sudah
    # berjalan tidak tiba-tiba mulai menandai orang.
    late_leave_threshold_minutes: int = 0
    early_leave_leave_threshold_minutes: int = 0
    leave_deduction_days: Decimal = Decimal("0")

    @classmethod
    def from_policy(cls, policy: AttendancePolicy | None) -> "AttendanceRules":
        if policy is None:
            # Tanpa policy = tanpa kelonggaran, bukan tanpa
            # perhitungan. Tenant yang belum mengisi masternya tetap
            # mendapat angka yang benar, cuma tanpa toleransi.
            return cls()

        return cls(
            late_tolerance_minutes=policy.late_tolerance_minutes,
            late_counts_from_tolerance=policy.late_counts_from_tolerance,
            early_leave_tolerance_minutes=(
                policy.early_leave_tolerance_minutes
            ),
            overtime_threshold_minutes=policy.overtime_threshold_minutes,
            overtime_rounding_minutes=policy.overtime_rounding_minutes,
            break_minutes=policy.break_minutes,
            late_leave_threshold_minutes=(
                policy.late_leave_threshold_minutes
            ),
            early_leave_leave_threshold_minutes=(
                policy.early_leave_leave_threshold_minutes
            ),
            leave_deduction_days=(
                policy.leave_deduction_days or Decimal("0")
            ),
        )


class AttendancePolicyResolver:
    @staticmethod
    def match(employee) -> AttendancePolicy | None:
        """
        Aturan paling khusus yang cocok untuk pegawai ini.

        Dipilih lewat skor `specificity`, bukan urutan baris — berapa
        menit seseorang boleh terlambat tidak boleh bergantung pada
        nomor id di database.
        """
        organization = getattr(employee, "organization", None)
        employment = getattr(employee, "employment", None)

        company_id = getattr(organization, "company_id", None)
        location_id = getattr(organization, "location_id", None)
        group_id = getattr(employment, "employee_group_id", None)

        candidates = AttendancePolicy.objects.filter(
            is_deleted=False,
            is_active=True,
        )

        matched = [
            policy
            for policy in candidates
            # Aturan yang menyebut sasaran tertentu hanya berlaku untuk
            # sasaran itu; yang mengosongkannya berlaku untuk semua.
            if (not policy.company_id or policy.company_id == company_id)
            and (not policy.location_id or policy.location_id == location_id)
            and (
                not policy.employee_group_id
                or policy.employee_group_id == group_id
            )
        ]

        if not matched:
            return None

        return max(matched, key=lambda policy: policy.specificity)

    @classmethod
    def rules_for(cls, employee) -> AttendanceRules:
        return AttendanceRules.from_policy(cls.match(employee))

    # ------------------------------------------------------------------
    # Perhitungan
    # ------------------------------------------------------------------

    @staticmethod
    def _minutes(start: datetime, end: datetime) -> int:
        return int((end - start).total_seconds() // 60)

    @classmethod
    def compute(
        cls,
        *,
        rules: AttendanceRules,
        scheduled_check_in: datetime | None,
        scheduled_check_out: datetime | None,
        check_in: datetime | None,
        check_out: datetime | None,
        status: str | None = None,
        break_minutes: int | None = None,
    ) -> dict:
        """
        Angka kehadiran menurut aturannya. Kunci yang tidak bisa
        dihitung tidak dikembalikan sama sekali — pemanggil menimpa
        payload dengan hasil ini, dan mengembalikan nol untuk hal yang
        tidak diketahui berarti menimpa angka yang mungkin sudah benar.
        """
        if status and str(status) in NON_COMPUTED_STATUSES:
            return {}

        result: dict = {}

        break_total = (
            rules.break_minutes
            if break_minutes is None
            else break_minutes
        )

        # Selisih mentahnya dipegang di luar kedua cabang: ambang
        # "dianggap ambil cuti" dinilai terhadap **jam jadwal**, bukan
        # terhadap menit telat yang sudah dipotong toleransi. Kalau
        # dinilai terhadap yang sudah dipotong, mengubah toleransi dari
        # 1 menit jadi 15 diam-diam menggeser ambang dua jamnya juga.
        raw_late = None
        raw_early = None

        # ------------------------------------------------------------------
        # Terlambat
        # ------------------------------------------------------------------
        if scheduled_check_in and check_in:
            raw_late = max(0, cls._minutes(scheduled_check_in, check_in))

            if raw_late <= rules.late_tolerance_minutes:
                late = 0
            elif rules.late_counts_from_tolerance:
                late = raw_late - rules.late_tolerance_minutes
            else:
                late = raw_late

            result["late_minutes"] = late

            # Status hanya disentuh untuk baris yang memang hasil tap.
            # Yang sedang cuti atau libur sudah keluar lebih dulu di
            # atas.
            result["status"] = (
                AttendanceStatus.LATE
                if late
                else AttendanceStatus.PRESENT
            )

        # ------------------------------------------------------------------
        # Pulang cepat & lembur
        # ------------------------------------------------------------------
        if scheduled_check_out and check_out:
            early = max(0, cls._minutes(check_out, scheduled_check_out))

            raw_early = early

            result["early_leave_minutes"] = (
                0
                if early <= rules.early_leave_tolerance_minutes
                else early - rules.early_leave_tolerance_minutes
            )

            over = max(0, cls._minutes(scheduled_check_out, check_out))

            if over < rules.overtime_threshold_minutes:
                over = 0
            elif rules.overtime_rounding_minutes:
                over -= over % rules.overtime_rounding_minutes

            result["overtime_minutes"] = over

        # ------------------------------------------------------------------
        # Seharusnya mengambil cuti
        #
        # **Penanda, bukan eksekusi** — lihat `EmployeeAttendance
        # .leave_required_days`. Yang dihasilkan di sini cuma angka dan
        # sebabnya; yang memotong saldo tetap dokumen cuti yang
        # diajukan dan disetujui.
        # ------------------------------------------------------------------
        over_late = bool(
            rules.late_leave_threshold_minutes
            and raw_late is not None
            and raw_late > rules.late_leave_threshold_minutes
        )

        over_early = bool(
            rules.early_leave_leave_threshold_minutes
            and raw_early is not None
            and raw_early > rules.early_leave_leave_threshold_minutes
        )

        # Ditulis hanya kalau ada sisi yang benar-benar bisa dinilai.
        # Baris tanpa jadwal, atau yang tap pulangnya belum masuk, tidak
        # boleh dibersihkan jadi nol — pemanggil menimpa payload dengan
        # hasil ini, dan menulis nol untuk hal yang belum diketahui akan
        # menghapus penanda yang mungkin sudah benar.
        if raw_late is not None or raw_early is not None:
            if over_late and over_early:
                reason = "both"
            elif over_late:
                reason = "late"
            elif over_early:
                reason = "early_leave"
            else:
                reason = ""

            # Sekali sehari, bukan dua kali. Orang yang datang telat
            # **dan** pulang cepat tetap kehilangan satu potongan yang
            # sama — menjumlahkannya berarti satu hari kerja bisa
            # memotong cuti lebih dari satu hari, dan angka itu tidak
            # bisa dijelaskan ke siapa pun.
            result["leave_required_days"] = (
                rules.leave_deduction_days
                if reason
                else Decimal("0")
            )

            result["leave_required_reason"] = reason

        # ------------------------------------------------------------------
        # Jam kerja bersih
        # ------------------------------------------------------------------
        if check_in and check_out:
            result["break_minutes"] = break_total

            result["worked_minutes"] = max(
                0,
                cls._minutes(check_in, check_out) - break_total,
            )

        return result
