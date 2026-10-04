"""
Dokumen HR peragaan manajemen — perencana, HR-DEMO-3.

Berkas ini **tidak menulis apa pun**; tidak satu pun service penulis
diimpor di sini. Yang mengeksekusi `hr_demo_documents_apply.py`.

Apa yang direncanakan
---------------------
Tiga jenis dokumen yang **menjelaskan** pengecualian presensi yang sudah
ada, bukan yang membuatnya hilang:

* **Cuti** — hari tidak hadir yang punya dasar.
* **Izin Kehadiran** — telat, pulang cepat, keluar sementara, atau tidak
  masuk sehari yang sudah disetujui atasan.
* **Lembur** — jam yang dicatat sebagai transaksi, bukan sekadar bukti.

Tiga batas yang tidak boleh kabur
---------------------------------
**Bukti lembur ≠ transaksi lembur ≠ lembur dibayar.** Yang pertama
dihitung presensi dari jam tap. Yang kedua dokumen yang diketik orang.
Yang ketiga baris di slip gaji. Tidak ada satu pun jalur yang mengubah
salah satunya jadi yang berikutnya secara otomatis.

**Cuti tidak menulis ulang presensi.** Baris yang sudah terbit sebagai
mangkir tetap mangkir; yang berubah pembacaannya di lapisan fakta
payroll. Satu-satunya cara sebuah hari terbit sebagai `leave` adalah
penutup hari yang menemukannya **belum punya baris** sementara cutinya
sudah disetujui.

**Izin tidak memaafkan jam tap.** `late_minutes` tetap angka menurut
mesin. Yang ditulis izin cuma berapa bagiannya yang dimaafkan.

Yang **tidak** dilakukan fase ini: menyelesaikan seluruh pengecualian.
28 dari 35 hari mangkir tetap tanpa keterangan, 527 dari 534
pengecualian tetap tanpa izin, dan 266 dari 272 baris berbukti lembur
tetap tanpa transaksi. Data peragaan yang semua orangnya sempurna tidak
bisa dipakai memperagakan apa pun.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal

from apps.hr.api.attendance.permission_effect import shift_window
from apps.hr.api.attendance.permission_resolver import (
    AttendancePermissionResolver,
    build_window,
)
from apps.hr.models import (
    Employee,
    EmployeeAttendance,
    LeaveBalance,
)
from apps.hr.models.attendance.permission import (
    AttendancePermission,
    AttendancePermissionStatus,
    AttendancePermissionType,
)
from apps.hr.models.leave import LeaveStatus


WINDOW_START = date(2026, 7, 25)
WINDOW_END = date(2026, 9, 25)

TRIAL_PREFIX = "TRL"

# Penanda dokumen milik fase ini. Dipakai dua arah: membongkar miliknya
# sendiri saat dijalankan ulang, dan **tidak** menyentuh dokumen yang
# diketik orang di tanggal yang sama.
MARKER = "HRDEMO3"


# ======================================================================
# Konfigurasi kanonik yang dibutuhkan fase ini
# ======================================================================
#
# Semuanya **master**, bukan perilaku yang ditanam di seed. Yang
# membacanya `PayrollPermissionRuleService` dan mesin hitung payroll —
# dan keduanya akan membacanya dengan cara yang sama untuk tenant klien.

PERMISSION_RULES = [
    # (permission_type, treatment, unpaid_over_minutes)
    ("late_arrival", "paid", 0),
    ("early_leave", "paid", 0),
    ("temporary_out", "unpaid", 60),
    ("full_day", "information_only", 0),
]

OVERTIME_GROUP_CODE = "SHIFT"
OVERTIME_TIER_BASIS = "daily"

# Rentang **jam lembur kumulatif**, bukan jam dinding. Batas atas
# kosong = tingkat teratas.
OVERTIME_TIERS = [
    # (sequence, hour_from, hour_to, multiplier)
    (1, Decimal("0.00"), Decimal("2.00"), Decimal("1.50")),
    (2, Decimal("2.00"), None, Decimal("2.00")),
]

# Kelompok lembur hanya dipasang ke pegawai yang **sudah dinyatakan
# berhak lembur** di Payroll Assignment. Lokasi site saja tidak cukup:
# manajer site pun berkantor di site, dan mereka memang tidak berhak.
OVERTIME_GROUP_EMPLOYEES = (
    "LOK001", "LOK002", "LOK003", "LOK004", "LOK005",
    "LOK006", "LOK007", "LOK008",
    "SGA002", "SGA003", "SGA006", "SGA007", "SGA008",
    "SGA009", "SGA010",
)


# ======================================================================
# Skenario Cuti
# ======================================================================
#
# Seluruh tanggal adalah hari **mangkir yang benar-benar ada** di
# dataset HR-DEMO-2. Yang dipatok bukan angkanya melainkan ceritanya:
# tiap baris menjawab satu pertanyaan manajemen yang berbeda.

@dataclass(frozen=True)
class LeaveScenario:
    key: str
    employee_number: str
    leave_type: str
    start: date
    end: date
    target: str
    reason: str
    story: str
    is_half_day: bool = False


LEAVE_SCENARIOS = [
    LeaveScenario(
        "L1", "HO004", "UNPAID", date(2026, 9, 4), date(2026, 9, 7),
        LeaveStatus.APPROVED,
        "Keperluan keluarga; belum genap setahun masa kerja, jadi "
        "diambil tanpa upah.",
        "cuti berjenjang tanpa upah — dua hari kerja, akhir pekan di "
        "tengahnya tidak dihitung; sumber Bukti A dan Bukti B",
    ),
    LeaveScenario(
        "L2", "HO008", "SICK", date(2026, 8, 25), date(2026, 8, 25),
        LeaveStatus.APPROVED,
        "Sakit, tidak masuk satu hari.",
        "cuti yang tidak memotong saldo dan tidak menuntut lampiran",
    ),
    LeaveScenario(
        "L3", "HO001", "ANNUAL", date(2026, 8, 28), date(2026, 8, 28),
        LeaveStatus.APPROVED,
        "Cuti tahunan satu hari.",
        "disetujui lewat alur — saldo tahunan berkurang satu hari",
    ),
    LeaveScenario(
        "L4", "LOK002", "ANNUAL", date(2026, 7, 29), date(2026, 7, 29),
        LeaveStatus.REJECTED,
        "Cuti tahunan satu hari.",
        "ditolak atasan langsung di rantai enam meja site — hari "
        "mangkirnya tetap tanpa keterangan",
    ),
    LeaveScenario(
        "L5", "HO005", "ANNUAL", date(2026, 9, 24), date(2026, 9, 24),
        LeaveStatus.CANCELLED,
        "Cuti tahunan yang dicatat lalu dibatalkan.",
        "saldo yang sudah terpotong kembali utuh saat catatannya "
        "dibatalkan",
    ),
    LeaveScenario(
        "L6", "LOK002", "ANNUAL", date(2026, 8, 10), date(2026, 8, 10),
        LeaveStatus.SUBMITTED,
        "Cuti tahunan satu hari.",
        "masih berjalan di rantai enam meja site — belum memotong "
        "apa pun",
    ),
    LeaveScenario(
        "L7", "HO002", "ANNUAL", date(2026, 9, 22), date(2026, 9, 22),
        LeaveStatus.DRAFT,
        "Rencana cuti tahunan, belum diajukan.",
        "draf yang belum sampai ke meja siapa pun",
    ),
    LeaveScenario(
        "L8", "HO003", "ANNUAL", date(2026, 9, 10), date(2026, 9, 10),
        LeaveStatus.RECORDED,
        "Cuti yang sudah disetujui di luar sistem, dicatat HR.",
        "jalur pencatatan — tanpa alur, tapi tetap memotong saldo",
    ),
    LeaveScenario(
        "L9", "HO008", "ANNUAL", date(2026, 9, 18), date(2026, 9, 18),
        LeaveStatus.APPROVED,
        "Cuti setengah hari.",
        "setengah hari memotong setengah hari saldo",
        is_half_day=True,
    ),
]


# Hari mangkir yang dipilih untuk Bukti B: barisnya dibongkar lalu
# diterbitkan ulang penutup hari, supaya perilaku penutup yang **sadar
# cuti** bisa dilihat, bukan cuma dijelaskan.
#
# Dipilih dari L1 karena cutinya disetujui lewat alur penuh — bukan
# dicatat — jadi yang dibuktikan benar-benar rantai lengkapnya.
PROOF_B = {"employee_number": "HO004", "work_date": date(2026, 9, 7)}

# Hari mangkir pasangan Bukti A: cuti yang sama, tanggal yang lain.
# Barisnya **tidak** disentuh sama sekali.
PROOF_A = {"employee_number": "HO004", "work_date": date(2026, 9, 4)}


# ======================================================================
# Skenario Izin Kehadiran
# ======================================================================


@dataclass(frozen=True)
class PermissionScenario:
    key: str
    employee_number: str
    work_date: date
    permission_type: str
    start_time: time | None
    end_time: time | None
    reason: str
    story: str
    target: str = AttendancePermissionStatus.APPROVED


PERMISSION_SCENARIOS = [
    PermissionScenario(
        "P1", "HO003", date(2026, 7, 30),
        AttendancePermissionType.LATE_ARRIVAL, None, time(10, 20),
        "Mengantar anak ke sekolah baru; sudah dikabarkan pagi itu.",
        "telat tipis yang dimaafkan seluruhnya",
    ),
    PermissionScenario(
        "P2", "HO001", date(2026, 9, 2),
        AttendancePermissionType.LATE_ARRIVAL, None, time(12, 0),
        "Rapat eksternal pagi di kantor klien.",
        "izin yang menutup sebagian — sisanya tetap tanpa izin",
    ),
    PermissionScenario(
        "P3a", "HO006", date(2026, 8, 21),
        AttendancePermissionType.LATE_ARRIVAL, None, time(10, 45),
        "Kontrol kesehatan rutin pagi.",
        "sisi telat dari satu hari yang punya dua pengecualian",
    ),
    PermissionScenario(
        "P3b", "HO006", date(2026, 8, 21),
        AttendancePermissionType.EARLY_LEAVE, time(17, 15), None,
        "Menjemput keluarga di bandara.",
        "sisi pulang cepat dari hari yang sama",
    ),
    PermissionScenario(
        "P4", "SGA003", date(2026, 8, 31),
        AttendancePermissionType.LATE_ARRIVAL, None, time(23, 10),
        "Serah terima alat dari shift sebelumnya molor.",
        "izin pada shift malam yang jam pulangnya menyeberang tengah "
        "malam",
    ),
    PermissionScenario(
        "P5", "HO002", date(2026, 8, 19),
        AttendancePermissionType.TEMPORARY_OUT, time(14, 0), time(15, 30),
        "Mengurus dokumen kependudukan di kelurahan.",
        "keluar sementara — menit izin tercatat, pulang cepatnya tetap "
        "tanpa izin",
    ),
    PermissionScenario(
        "P6", "HO008", date(2026, 9, 22),
        AttendancePermissionType.FULL_DAY, None, None,
        "Mendampingi keluarga berobat ke Ternate.",
        "tidak masuk sehari dengan izin — tanpa dokumen cuti, dan "
        "baris presensinya tetap apa adanya",
    ),
]


# ======================================================================
# Skenario Lembur
# ======================================================================
#
# **Tidak ada alur persetujuan lembur di sistem ini.** Status terkuat
# yang benar-benar ada `RECORDED`, dan itu yang dipakai. Nilai
# `SUBMITTED`/`APPROVED` memang ada di enum, tapi tidak ada satu baris
# kode pun yang menulisnya — enum yang memuat sebuah nama tidak
# membuktikan prosesnya ada.


@dataclass(frozen=True)
class OvertimeScenario:
    key: str
    employee_number: str
    work_date: date
    start_time: time
    end_time: time
    status: str
    is_paid: bool
    reason: str
    story: str


OVERTIME_SCENARIOS = [
    OvertimeScenario(
        "O1", "LOK001", date(2026, 7, 31), time(7, 0), time(7, 30),
        "recorded", True,
        "Serah terima shift molor.",
        "di bawah tingkat pertama — seluruhnya 1,5x",
    ),
    OvertimeScenario(
        "O2", "SGA006", date(2026, 9, 6), time(15, 0), time(17, 3),
        "recorded", True,
        "Perbaikan conveyor sebelum shift berikutnya masuk.",
        "melewati batas dua jam — dua tingkat dalam satu hari",
    ),
    OvertimeScenario(
        "O3", "LOK004", date(2026, 9, 23), time(7, 0), time(9, 27),
        "recorded", True,
        "Menunggu pengganti shift malam yang terlambat.",
        "lembur sesudah shift malam — jam dindingnya jatuh di tanggal "
        "berikutnya, hari kerjanya tetap tanggal semula",
    ),
    OvertimeScenario(
        "O4", "LOK002", date(2026, 8, 4), time(23, 0), time(1, 27),
        "recorded", False,
        "Diganti libur pengganti, tidak dibayar.",
        "lembur yang tercatat tapi tidak dibayar — tetap masuk rekap "
        "jam kerja, tidak masuk gaji",
    ),
    OvertimeScenario(
        "O5", "SGA003", date(2026, 7, 25), time(7, 0), time(9, 26),
        "cancelled", True,
        "Dibatalkan: jamnya sudah tercakup penyesuaian roster.",
        "dibatalkan — payroll tidak membacanya walau ditandai dibayar",
    ),
    OvertimeScenario(
        "O6a", "SGA008", date(2026, 8, 30), time(15, 0), time(16, 0),
        "recorded", True,
        "Menyelesaikan pengelasan.",
        "catatan pertama di tanggal yang sama",
    ),
    OvertimeScenario(
        "O6b", "SGA008", date(2026, 8, 30), time(16, 0), time(17, 26),
        "recorded", True,
        "Melanjutkan sampai unit bisa dijalankan.",
        "catatan kedua di tanggal yang sama — payroll menjumlahkannya "
        "jadi satu hari lembur sebelum menyusun tingkat",
    ),
]


# ======================================================================
# Hasil perencanaan
# ======================================================================


@dataclass
class Plan:
    start: date = WINDOW_START
    end: date = WINDOW_END
    leave: list = field(default_factory=list)
    permission: list = field(default_factory=list)
    overtime: list = field(default_factory=list)
    config: dict = field(default_factory=dict)
    blockers: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    @property
    def is_blocked(self) -> bool:
        return bool(self.blockers)


def _employee(number: str):
    return (
        Employee.objects
        .select_related(
            "user",
            "organization__company",
            "organization__location",
            "employment__employee_group",
            "employment__roster_crew__work_schedule",
            "employment__working_calendar",
            "employment__shift",
        )
        .filter(employee_number=number, is_deleted=False)
        .first()
    )


def _attendance(employee, work_date: date):
    return (
        EmployeeAttendance.objects
        .filter(employee=employee, work_date=work_date, is_deleted=False)
        .first()
    )


def _balance(employee, leave_type_code: str, year: int):
    return (
        LeaveBalance.objects
        .filter(
            employee=employee,
            leave_type__code=leave_type_code,
            year=year,
            is_deleted=False,
        )
        .first()
    )


def build(*, schema: str) -> Plan:
    """Rencana lengkap fase 3. **Tidak menulis apa pun.**"""
    plan = Plan()

    if schema == "public":
        plan.blockers.append(
            "Schema `public` tidak memuat data bisnis tenant.",
        )

        return plan

    from apps.administration.models.references.hr import LeaveType
    from apps.administration.models.references.leave_policy import LeavePolicy
    from apps.hr.models import PayrollAssignment
    from apps.payroll.models import (
        OvertimeGroup,
        OvertimeGroupTier,
        PayrollPermissionRule,
    )

    # ------------------------------------------------------------------
    # Konfigurasi
    # ------------------------------------------------------------------

    group = (
        OvertimeGroup.objects
        .filter(code=OVERTIME_GROUP_CODE, is_deleted=False)
        .first()
    )

    if group is None:
        plan.blockers.append(
            f"Overtime Group kanonik '{OVERTIME_GROUP_CODE}' tidak ada.",
        )
    else:
        existing_tiers = list(
            group.tiers.filter(is_deleted=False)
            .values_list("sequence", "hour_from", "hour_to", "multiplier")
        )

        plan.config["overtime_group"] = {
            "code": group.code,
            "tier_basis_before": group.tier_basis,
            "tier_basis_after": OVERTIME_TIER_BASIS,
            "tiers_before": existing_tiers,
            "tiers_after": [
                (seq, str(lo), str(hi) if hi is not None else None, str(mul))
                for seq, lo, hi, mul in OVERTIME_TIERS
            ],
        }

    assignments = {
        row.employee.employee_number: row
        for row in (
            PayrollAssignment.objects
            .filter(
                is_deleted=False,
                employee__employee_number__in=OVERTIME_GROUP_EMPLOYEES,
            )
            .select_related("employee", "overtime_group")
        )
    }

    missing = sorted(set(OVERTIME_GROUP_EMPLOYEES) - set(assignments))

    if missing:
        plan.blockers.append(
            f"Payroll Assignment tidak ada untuk: {', '.join(missing)}.",
        )

    not_eligible = sorted(
        number
        for number, row in assignments.items()
        if not row.overtime_eligible
    )

    if not_eligible:
        plan.blockers.append(
            "Bukan pegawai berhak lembur, tapi masuk daftar kelompok: "
            f"{', '.join(not_eligible)}. Kelayakan tidak boleh "
            "disimpulkan dari lokasi.",
        )

    plan.config["overtime_assignments"] = {
        number: getattr(row.overtime_group, "code", None)
        for number, row in sorted(assignments.items())
    }

    plan.config["permission_rules_before"] = list(
        PayrollPermissionRule.objects
        .filter(is_deleted=False)
        .values_list("permission_type", "treatment", "unpaid_over_minutes")
    )

    plan.config["permission_rules_after"] = PERMISSION_RULES

    # Silsilah uji tidak boleh ikut ke mana pun.
    trial_group = (
        OvertimeGroupTier.objects
        .filter(is_deleted=False, group__code__startswith=TRIAL_PREFIX)
        .count()
    )

    plan.notes.append(
        f"Tingkat lembur milik silsilah uji: {trial_group} baris — "
        f"tidak dibaca, tidak disalin, tidak diubah.",
    )

    # ------------------------------------------------------------------
    # Cuti
    # ------------------------------------------------------------------

    types = {
        row.code: row
        for row in LeaveType.objects.filter(is_deleted=False)
    }

    policies = {
        row.leave_type.code: row
        for row in (
            LeavePolicy.objects
            .filter(is_deleted=False, is_active=True)
            .select_related("leave_type")
        )
        if row.leave_type_id
    }

    for scenario in LEAVE_SCENARIOS:
        employee = _employee(scenario.employee_number)

        if employee is None:
            plan.blockers.append(
                f"{scenario.key}: pegawai {scenario.employee_number} "
                f"tidak ada.",
            )

            continue

        if scenario.employee_number.startswith(TRIAL_PREFIX):
            plan.blockers.append(
                f"{scenario.key}: silsilah uji tidak boleh dipakai.",
            )

            continue

        leave_type = types.get(scenario.leave_type)
        policy = policies.get(scenario.leave_type)

        if leave_type is None:
            plan.blockers.append(
                f"{scenario.key}: jenis cuti {scenario.leave_type} "
                f"tidak ada.",
            )

            continue

        rows = []
        current = scenario.start

        while current <= scenario.end:
            row = _attendance(employee, current)

            rows.append((current, getattr(row, "status", None)))

            current = date.fromordinal(current.toordinal() + 1)

        uses_balance = bool(policy and policy.uses_balance)

        balance = (
            _balance(employee, scenario.leave_type, scenario.start.year)
            if uses_balance
            else None
        )

        days = Decimal("0.5") if scenario.is_half_day else Decimal(
            (scenario.end - scenario.start).days + 1,
        )

        plan.leave.append({
            "key": scenario.key,
            "employee": scenario.employee_number,
            "actor": getattr(employee.user, "username", None),
            "type": scenario.leave_type,
            "uses_balance": uses_balance,
            "start": scenario.start,
            "end": scenario.end,
            "half_day": scenario.is_half_day,
            "days": days,
            "target": scenario.target,
            "story": scenario.story,
            "attendance_before": rows,
            "balance_before": (
                balance.remaining if balance is not None else None
            ),
            "balance_expected": (
                balance.remaining - days
                if balance is not None
                and scenario.target in (
                    LeaveStatus.APPROVED, LeaveStatus.RECORDED,
                )
                else (balance.remaining if balance is not None else None)
            ),
        })

    # ------------------------------------------------------------------
    # Izin Kehadiran
    # ------------------------------------------------------------------

    for scenario in PERMISSION_SCENARIOS:
        employee = _employee(scenario.employee_number)

        if employee is None:
            plan.blockers.append(
                f"{scenario.key}: pegawai {scenario.employee_number} "
                f"tidak ada.",
            )

            continue

        row = _attendance(employee, scenario.work_date)

        if row is None:
            plan.blockers.append(
                f"{scenario.key}: tidak ada baris presensi "
                f"{scenario.employee_number} {scenario.work_date}.",
            )

            continue

        expected = _predict_permission(
            employee=employee,
            row=row,
            scenarios=[
                other
                for other in PERMISSION_SCENARIOS
                if other.employee_number == scenario.employee_number
                and other.work_date == scenario.work_date
            ],
        )

        plan.permission.append({
            "key": scenario.key,
            "employee": scenario.employee_number,
            "actor": getattr(employee.user, "username", None),
            "date": scenario.work_date,
            "type": scenario.permission_type,
            "start_time": scenario.start_time,
            "end_time": scenario.end_time,
            "story": scenario.story,
            "before": {
                "status": row.status,
                "check_in": row.check_in,
                "check_out": row.check_out,
                "late_minutes": row.late_minutes,
                "early_leave_minutes": row.early_leave_minutes,
                "excused_late_minutes": row.excused_late_minutes,
                "excused_early_leave_minutes": (
                    row.excused_early_leave_minutes
                ),
                "permission_minutes": row.permission_minutes,
                "is_excused_absence": row.is_excused_absence,
                "permission_state": row.permission_state,
            },
            "expected": expected,
        })

    # ------------------------------------------------------------------
    # Lembur
    # ------------------------------------------------------------------

    for scenario in OVERTIME_SCENARIOS:
        employee = _employee(scenario.employee_number)

        if employee is None:
            plan.blockers.append(
                f"{scenario.key}: pegawai {scenario.employee_number} "
                f"tidak ada.",
            )

            continue

        if scenario.employee_number not in OVERTIME_GROUP_EMPLOYEES:
            plan.blockers.append(
                f"{scenario.key}: {scenario.employee_number} bukan "
                f"pegawai berkelompok lembur kanonik.",
            )

            continue

        row = _attendance(employee, scenario.work_date)

        minutes = _duration(scenario.start_time, scenario.end_time)

        plan.overtime.append({
            "key": scenario.key,
            "employee": scenario.employee_number,
            "date": scenario.work_date,
            "start": scenario.start_time,
            "end": scenario.end_time,
            "minutes": minutes,
            "hours": (Decimal(minutes) / Decimal("60")).quantize(
                Decimal("0.01"),
            ),
            "status": scenario.status,
            "is_paid": scenario.is_paid,
            "story": scenario.story,
            "evidence_minutes": getattr(row, "overtime_minutes", None),
            "counted_by_payroll": (
                scenario.is_paid and scenario.status == "recorded"
            ),
        })

    return plan


def _duration(start: time, end: time) -> int:
    from datetime import datetime, timedelta

    base = datetime(2000, 1, 1)

    begin = datetime.combine(base, start)
    finish = datetime.combine(base, end)

    if finish <= begin:
        finish += timedelta(days=1)

    return int((finish - begin).total_seconds() // 60)


def _predict_permission(*, employee, row, scenarios) -> dict:
    """
    Nilai yang **akan** ditulis resolver, dihitung tanpa menyimpan apa
    pun.

    Dokumen probe-nya tidak pernah disimpan dan tidak pernah
    divalidasi — yang dipakai cuma bentuk jendelanya. Memprediksi
    dengan rumus terpisah berarti laporan kering memakai aritmetika
    yang bukan aritmetika mesinnya.
    """
    shift_start, shift_end = shift_window(employee, row.work_date)

    windows = [
        build_window(
            AttendancePermission(
                employee=employee,
                date=scenario.work_date,
                permission_type=scenario.permission_type,
                start_time=scenario.start_time,
                end_time=scenario.end_time,
                status=AttendancePermissionStatus.APPROVED,
            ),
            shift_start=shift_start,
            shift_end=shift_end,
        )
        for scenario in scenarios
    ]

    return AttendancePermissionResolver.compute(
        windows=windows,
        status=row.status,
        late_minutes=row.late_minutes,
        early_leave_minutes=row.early_leave_minutes,
        check_in=row.check_in,
        check_out=row.check_out,
        shift_start=shift_start,
        shift_end=shift_end,
    )
