"""
Kosakata metrik HR Period Summary.

Satu berkas, dan itu disengaja: nama metrik dipakai di **empat** tempat
— kartu KPI, chart, kolom tabel, dan parameter drill-down. Menulisnya
sebagai string lepas di masing-masing berarti "off_worked" di kolom
tabel dan "offworked" di endpoint rincian bisa berbeda tanpa satu pun
pesan error; yang muncul cuma rincian kosong untuk angka yang jelas
tidak nol.
"""

from __future__ import annotations


class Metric:
    """Nama metrik yang boleh muncul di kolom tabel dan drill-down."""

    SCHEDULED = "scheduled"
    PRESENT = "present"
    ABSENT = "absent"

    ANNUAL = "annual"
    SICK = "sick"
    OTHER_LEAVE = "other_leave"
    UNPAID = "unpaid"

    FIELD_BREAK = "field_break"

    OFF_WORKED = "off_worked"
    HOLIDAY_WORKED = "holiday_worked"

    LATE = "late"
    EARLY = "early"

    OT_REGULAR = "ot_regular"
    OT_OFF = "ot_off"
    OT_HOLIDAY = "ot_holiday"
    OT_TOTAL = "ot_total"


# Metrik cuti → kunci grup di baris pegawai. "Other Leave" **hanya
# pengelompokan laporan**: tidak ada LeaveType bernama itu, dan tipe
# aslinya tetap terbawa ke drill-down.
LEAVE_METRICS = (
    Metric.ANNUAL,
    Metric.SICK,
    Metric.OTHER_LEAVE,
    Metric.UNPAID,
)


# Kode LeaveType master (`apps/administration/seeds/reference/hr.py`)
# yang punya kolomnya sendiri di laporan. Kode di luar ketiganya jatuh
# ke "Other Leave" — termasuk kode buatan tenant, yang memang tidak bisa
# ditebak dari sini.
LEAVE_CODE_GROUPS = {
    "ANNUAL": Metric.ANNUAL,
    "SICK": Metric.SICK,
    "UNPAID": Metric.UNPAID,
}


def leave_group(code: str | None) -> str:
    return LEAVE_CODE_GROUPS.get((code or "").upper(), Metric.OTHER_LEAVE)


# Metrik yang nilainya **jam**, bukan cacahan hari. Dipakai serializer
# tabel dan drill-down untuk memilih satuan.
HOUR_METRICS = (
    Metric.OT_REGULAR,
    Metric.OT_OFF,
    Metric.OT_HOLIDAY,
    Metric.OT_TOTAL,
)


# Satuan **fakta** tiap metrik — kode stabil, bukan teks tampilan.
#
# "4x" dan "4h" adalah dua fakta berbeda: yang pertama berapa kali
# terjadi, yang kedua berapa lama. Late/Early tetap `occurrence` walau
# drill-down-nya juga membawa menit; durasinya fakta kedua yang
# dikirim terpisah, bukan pengganti angkanya.
class Unit:
    OCCURRENCE = "occurrence"
    DAY = "day"
    HOUR = "hour"
    MINUTE = "minute"


METRIC_UNITS = {
    Metric.SCHEDULED: Unit.DAY,
    Metric.PRESENT: Unit.DAY,
    Metric.ABSENT: Unit.DAY,
    Metric.ANNUAL: Unit.DAY,
    Metric.SICK: Unit.DAY,
    Metric.OTHER_LEAVE: Unit.DAY,
    Metric.UNPAID: Unit.DAY,
    Metric.FIELD_BREAK: Unit.DAY,
    Metric.OFF_WORKED: Unit.DAY,
    Metric.HOLIDAY_WORKED: Unit.DAY,
    Metric.LATE: Unit.OCCURRENCE,
    Metric.EARLY: Unit.OCCURRENCE,
    Metric.OT_REGULAR: Unit.HOUR,
    Metric.OT_OFF: Unit.HOUR,
    Metric.OT_HOLIDAY: Unit.HOUR,
    Metric.OT_TOTAL: Unit.HOUR,
}


# Metrik yang bisa ditelusuri ke sumbernya. Yang tidak terdaftar di sini
# ditolak endpoint rincian — daripada membalas daftar kosong yang
# terbaca seperti "memang tidak ada datanya".
DRILLDOWN_METRICS = (
    Metric.SCHEDULED,
    Metric.PRESENT,
    Metric.ABSENT,
    Metric.ANNUAL,
    Metric.SICK,
    Metric.OTHER_LEAVE,
    Metric.UNPAID,
    Metric.FIELD_BREAK,
    Metric.OFF_WORKED,
    Metric.HOLIDAY_WORKED,
    Metric.LATE,
    Metric.EARLY,
    Metric.OT_REGULAR,
    Metric.OT_OFF,
    Metric.OT_HOLIDAY,
    Metric.OT_TOTAL,
)


METRIC_LABELS = {
    Metric.SCHEDULED: "Scheduled",
    Metric.PRESENT: "Present",
    Metric.ABSENT: "Absent",
    Metric.ANNUAL: "Annual",
    Metric.SICK: "Sick",
    Metric.OTHER_LEAVE: "Other Leave",
    Metric.UNPAID: "Unpaid",
    Metric.FIELD_BREAK: "Field Break",
    Metric.OFF_WORKED: "Off Worked",
    Metric.HOLIDAY_WORKED: "Holiday Worked",
    Metric.LATE: "Late",
    Metric.EARLY: "Early",
    Metric.OT_REGULAR: "Regular OT",
    Metric.OT_OFF: "Off OT",
    Metric.OT_HOLIDAY: "Holiday OT",
    Metric.OT_TOTAL: "Total OT",
}


# ----------------------------------------------------------------------
# Metrik → proses HR (Feature Applicability)
# ----------------------------------------------------------------------
#
# Yang memutuskan pegawai mana yang **boleh dihitung** sebuah metrik
# bukan laporan ini, tapi `EmployeeGroup` lewat Feature Applicability.
# Yang ditulis di sini cuma pemetaannya: metrik ini mewakili proses yang
# mana.
#
# **Satu flag untuk seluruh laporan adalah jawaban yang salah.** Pegawai
# yang tidak diabsen tapi tetap punya cuti harus hilang dari kolom
# Scheduled/Present/Absent dan tetap ada di kolom cuti; memakai satu
# penanda membuat keduanya jatuh bersama, dan angka yang hilang itu
# tidak meninggalkan jejak apa pun di layar.

from apps.hr.applicability import HRFeature


METRIC_FEATURES = {
    # Kehadiran — termasuk turunannya (telat, pulang cepat) dan hari
    # kerja di luar jadwal, yang dua-duanya lahir dari baris presensi.
    Metric.SCHEDULED: HRFeature.ATTENDANCE,
    Metric.PRESENT: HRFeature.ATTENDANCE,
    Metric.ABSENT: HRFeature.ATTENDANCE,
    Metric.LATE: HRFeature.ATTENDANCE,
    Metric.EARLY: HRFeature.ATTENDANCE,
    Metric.OFF_WORKED: HRFeature.ATTENDANCE,
    Metric.HOLIDAY_WORKED: HRFeature.ATTENDANCE,

    # Cuti — keempat kelompok laporan membaca penanda yang sama, karena
    # keempatnya satu proses. Yang membedakannya cuma `LeaveType`.
    Metric.ANNUAL: HRFeature.LEAVE,
    Metric.SICK: HRFeature.LEAVE,
    Metric.OTHER_LEAVE: HRFeature.LEAVE,
    Metric.UNPAID: HRFeature.LEAVE,

    # Blok off roster. Punya penandanya sendiri, **bukan** menumpang
    # `leave`: `RotationPurpose` memisahkan keduanya justru karena field
    # break tidak memotong saldo apa pun.
    Metric.FIELD_BREAK: HRFeature.FIELD_BREAK,

    Metric.OT_REGULAR: HRFeature.OVERTIME,
    Metric.OT_OFF: HRFeature.OVERTIME,
    Metric.OT_HOLIDAY: HRFeature.OVERTIME,
    Metric.OT_TOTAL: HRFeature.OVERTIME,
}


# Proses yang **diwakili** laporan ini. Dipakai menentukan populasinya:
# pegawai yang keempatnya dimatikan tidak punya satu pun angka untuk
# disumbangkan, jadi ia tidak menghasilkan baris dan tidak masuk
# Headcount.
#
# Roster dan Shift sengaja **tidak** ikut. Keduanya memang proses HR,
# tapi laporan ini tidak punya satu pun metrik yang melaporkannya —
# memasukkannya berarti pegawai yang cuma punya Roster tetap terbit
# sebagai baris nol, persis masalah yang sedang ditutup. Field Break
# yang lahir dari roster punya penandanya sendiri dan sudah terwakili.
REPORT_FEATURES = (
    HRFeature.ATTENDANCE,
    HRFeature.LEAVE,
    HRFeature.OVERTIME,
    HRFeature.FIELD_BREAK,
)


def metric_feature(metric: str):
    """
    Proses yang diwakili sebuah metrik, atau `None` kalau metriknya
    tidak bergantung pada Feature Applicability.

    `None` berarti "hitung untuk siapa pun yang ada di populasi" — bukan
    "tidak berlaku untuk siapa pun".
    """
    return METRIC_FEATURES.get(metric)


# ----------------------------------------------------------------------
# Jenis hari
# ----------------------------------------------------------------------
#
# Satu resolver untuk kehadiran **dan** lembur. Dua salinan aturan
# "hari ini terjadwal atau tidak" adalah persis cara Off Worked dan Off
# OT diam-diam menghitung hari yang berbeda untuk tanggal yang sama.


class DayType:
    SCHEDULED = "scheduled"
    HOLIDAY = "holiday"
    OFF = "off"


def day_type(day, scheduled_days, holidays) -> str:
    """
    Terjadwal **lebih dulu**, baru libur.

    Urutannya menentukan, dan bukan selera. Pegawai roster tetap bekerja
    saat blok kerjanya jatuh di tanggal merah — rosternya sendiri yang
    jadi kalender (`LeaveDayCalculator.count_working_days`). Kalau libur
    diperiksa lebih dulu, tanggal merah di tengah blok kerja berpindah
    dari Present ke Holiday Worked, dan Scheduled tidak lagi sama dengan
    Present + Absent + Leave.

    Untuk pegawai kantor pertanyaannya tidak pernah muncul: hari libur
    memang sudah dibuang dari hari terjadwalnya.
    """
    if day in scheduled_days:
        return DayType.SCHEDULED

    if day in holidays:
        return DayType.HOLIDAY

    return DayType.OFF
