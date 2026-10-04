"""
Mempertemukan izin yang disetujui dengan angka presensi hari itu.

Dipisah dari `AttendancePolicyResolver` karena menjawab pertanyaan yang
berbeda. Yang di sana membaca **aturan perusahaan** dan hasilnya fungsi
murni atas jadwal + jam tap. Yang di sini membaca **dokumen yang
disetujui orang**, jadi ia butuh baris izin — dan menyatukan keduanya
berarti perhitungan menit yang tadinya nol query jadi satu query per
baris presensi.

Yang diputuskan di sini
-----------------------
* `excused_late_minutes` — berapa menit keterlambatan yang dimaafkan
* `excused_early_leave_minutes` — idem untuk pulang cepat
* `permission_minutes` — izin keluar sementara
* `is_excused_absence` — tidak masuk dengan izin
* `permission_state` — penanda untuk layar

Yang **tidak** disentuh: `late_minutes`, `early_leave_minutes`,
`check_in`, `check_out`, dan `status`. Izin tidak mengubah fakta; ia
menjelaskannya. Baris presensi yang dihitung ulang tanpa satu pun
dokumen izin karena itu kembali ke nol di kelima kolom di atas —
dan itu benar: izin yang dibatalkan harus benar-benar berhenti berlaku.

Bagian yang di luar izin
------------------------
Izin "boleh datang sampai 10:00" yang dipakai datang 10:30 memaafkan
**dua jam pertama saja**. Yang dihitung karena itu bukan "seluruh telat
kalau ada izin", melainkan selisih antara jam tap dan batas izinnya:

    di luar izin  = max(0, tap − batas izin)
    dimaafkan     = max(0, late_minutes − di luar izin)

Ditulis dalam bentuk itu, bukan `min(late_minutes, panjang jendela
izin)`, supaya toleransi keterlambatan tetap jatuh pada bagian yang
memang dimaafkan. Dengan toleransi 15 menit dan tap 10:30, `min(...)`
menghasilkan 120 menit dimaafkan dan 15 menit tanpa izin — padahal yang
benar-benar di luar izin cuma 30 menit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_cls, datetime, time, timedelta

from apps.hr.models.attendance.choices import AttendanceStatus
from apps.hr.models.attendance.permission import (
    AttendancePermissionType,
    PERMISSION_EFFECTIVE_STATUSES,
    PERMISSION_PENDING_STATUSES,
)


# Kunci yang ditulis resolver ini. Dikumpulkan sebagai konstanta karena
# dipakai dua kali: sebagai `update_fields` saat menyimpan, dan sebagai
# himpunan yang harus dinolkan saat tidak ada izin sama sekali. Dua
# daftar terpisah adalah cara paling pelan untuk membuat pembatalan izin
# meninggalkan satu kolom yang tidak ikut bersih.
PERMISSION_FIELDS = (
    "excused_late_minutes",
    "excused_early_leave_minutes",
    "permission_minutes",
    "is_excused_absence",
    "permission_state",
)


EMPTY = {
    "excused_late_minutes": 0,
    "excused_early_leave_minutes": 0,
    "permission_minutes": 0,
    "is_excused_absence": False,
    "permission_state": "",
}


@dataclass(frozen=True)
class PermissionWindow:
    """
    Satu izin, sudah jadi jendela waktu **naif** (jam dinding).

    Naif dan bukan ber-timezone karena pembandingnya juga jam dinding:
    `shift_span()` menghasilkan datetime naif, dan mencampur keduanya
    di satu perbandingan adalah cara termudah menghasilkan selisih tujuh
    jam yang tidak ada yang mencarinya.
    """

    permission_id: int
    permission_type: str
    status: str
    start: datetime | None
    end: datetime | None
    document_number: str = ""

    @property
    def is_effective(self) -> bool:
        return self.status in PERMISSION_EFFECTIVE_STATUSES

    @property
    def is_pending(self) -> bool:
        return self.status in PERMISSION_PENDING_STATUSES

    @property
    def minutes(self) -> int:
        if self.start is None or self.end is None:
            return 0

        return max(0, int((self.end - self.start).total_seconds() // 60))


def anchor_time(
    value: time,
    *,
    work_date: date_cls,
    shift_start: datetime | None,
    shift_end: datetime | None,
) -> datetime:
    """
    Jam dinding → datetime, ditambatkan ke **jendela shift**, bukan ke
    tanggal kalendernya.

    Inilah yang membuat shift malam bekerja. Shift 20:00–05:00 tanggal
    10 September yang izin keluarnya 23:30–01:00 punya satu jam yang
    jatuh di tanggal 10 dan satu lagi di tanggal 11 — dan tidak ada
    satu pun kolom di dokumennya yang menyebutkan itu, karena memang
    tidak boleh: yang diketik pengaju adalah jam, dan tanggal yang
    benar adalah kesimpulan dari jadwalnya.

    Tanpa jendela shift (jadwal belum tersusun) jatuh ke tanggal
    dokumennya apa adanya — perkiraan terbaik yang tersedia, dan
    menandainya lebih jauh dari itu berarti menebak.
    """
    candidate = datetime.combine(work_date, value)

    if shift_start is None or shift_end is None:
        return candidate

    if candidate < shift_start:
        # Jam yang jatuh sebelum shift dimulai berarti sudah lewat
        # tengah malam — selama pergeserannya benar-benar mendarat di
        # dalam jendela. Kalau tidak, ia memang di luar shift, dan yang
        # menolaknya validasi di service, bukan pergeseran diam-diam
        # di sini.
        shifted = candidate + timedelta(days=1)

        if shifted <= shift_end:
            return shifted

    return candidate


def build_window(
    permission,
    *,
    shift_start: datetime | None,
    shift_end: datetime | None,
) -> PermissionWindow:
    """
    Dokumen izin → jendela waktu, sesuai bentuk tiap tipenya.

    * `LATE_ARRIVAL`  — dari awal shift sampai batas yang diizinkan
    * `EARLY_LEAVE`   — dari jam yang diizinkan sampai akhir shift
    * `TEMPORARY_OUT` — jendela yang diketik apa adanya
    * `FULL_DAY`      — seluruh shift; tanpa jadwal jendelanya kosong
      dan yang tersisa cuma penandanya
    """
    work_date = permission.date
    kind = permission.permission_type

    start = end = None

    if kind == AttendancePermissionType.LATE_ARRIVAL:
        start = shift_start

        if permission.end_time is not None:
            end = anchor_time(
                permission.end_time,
                work_date=work_date,
                shift_start=shift_start,
                shift_end=shift_end,
            )

    elif kind == AttendancePermissionType.EARLY_LEAVE:
        end = shift_end

        if permission.start_time is not None:
            start = anchor_time(
                permission.start_time,
                work_date=work_date,
                shift_start=shift_start,
                shift_end=shift_end,
            )

    elif kind == AttendancePermissionType.TEMPORARY_OUT:
        if permission.start_time is not None:
            start = anchor_time(
                permission.start_time,
                work_date=work_date,
                shift_start=shift_start,
                shift_end=shift_end,
            )

        if permission.end_time is not None:
            end = anchor_time(
                permission.end_time,
                work_date=work_date,
                shift_start=shift_start,
                shift_end=shift_end,
            )

            # Jendela yang berakhir sebelum ia dimulai selalu berarti
            # lewat tengah malam — dan itu tetap benar untuk pegawai
            # yang jadwalnya belum tersusun, di mana penambatan di atas
            # tidak punya jendela untuk dibandingkan.
            if start is not None and end <= start:
                end += timedelta(days=1)

    else:  # FULL_DAY
        start = shift_start
        end = shift_end

    return PermissionWindow(
        permission_id=permission.pk,
        permission_type=kind,
        status=permission.status,
        start=start,
        end=end,
        document_number=getattr(permission, "document_number", "") or "",
    )


def _naive(value: datetime | None) -> datetime | None:
    """
    Jam dinding dari sebuah datetime, ber-timezone atau tidak.

    `EmployeeAttendance` menyimpan tap sebagai datetime ber-timezone;
    jendela izin dibentuk dari jam yang diketik orang. Membandingkan
    keduanya apa adanya melempar `TypeError`, dan mengonversi salah
    satunya ke UTC menggeser tengah malam ke tempat yang tidak
    diinginkan siapa pun. Yang dipakai jam dindingnya — sama seperti
    `shift_span()`.
    """
    if value is None:
        return None

    if value.tzinfo is None:
        return value

    from apps.hr.api.attendance.schedule import WALL_CLOCK_TZ

    return value.astimezone(WALL_CLOCK_TZ).replace(tzinfo=None)


class AttendancePermissionResolver:
    @staticmethod
    def compute(
        *,
        windows: list[PermissionWindow],
        status: str | None,
        late_minutes: int,
        early_leave_minutes: int,
        check_in: datetime | None,
        check_out: datetime | None,
        shift_start: datetime | None = None,
        shift_end: datetime | None = None,
    ) -> dict:
        """
        Klasifikasi hari itu. Fungsi murni — tidak menyentuh database.

        `windows` sudah memuat izin yang **belum** disetujui juga:
        keduanya dibutuhkan, yang satu untuk memaafkan dan yang satu
        untuk menjelaskan kenapa barisnya belum dimaafkan. Yang
        memaafkan hanya `is_effective`.
        """
        result = dict(EMPTY)

        # **Tidak ada jalan pintas untuk `windows` kosong**, dan itu
        # bukan kelalaian. Empat kolom angkanya memang kembali ke nol
        # — termasuk baris yang izinnya baru saja dibatalkan, jalur
        # yang paling penting benar — tapi `permission_state` yang
        # kelima justru punya jawaban di sini: telat tanpa satu pun
        # dokumen izin adalah `unauthorized`, bukan "tidak ada
        # pengecualian". Kalau ia dikosongkan, daftar kerja HR
        # ("saring pengecualian tanpa izin") memuat nol baris di
        # tenant yang belum satu pun pegawainya mengajukan izin —
        # persis daftar yang paling perlu dibaca.
        check_in = _naive(check_in)
        check_out = _naive(check_out)

        late_minutes = int(late_minutes or 0)
        early_leave_minutes = int(early_leave_minutes or 0)

        effective = [w for w in windows if w.is_effective]
        pending = [w for w in windows if w.is_pending]

        excused_late = 0
        excused_early = 0
        permission_minutes = 0
        excused_absence = False

        for window in effective:
            kind = window.permission_type

            if kind == AttendancePermissionType.LATE_ARRIVAL:
                excused_late = max(
                    excused_late,
                    _excused_late(
                        window=window,
                        check_in=check_in,
                        late_minutes=late_minutes,
                    ),
                )

            elif kind == AttendancePermissionType.EARLY_LEAVE:
                excused_early = max(
                    excused_early,
                    _excused_early(
                        window=window,
                        check_out=check_out,
                        early_leave_minutes=early_leave_minutes,
                    ),
                )

            elif kind == AttendancePermissionType.TEMPORARY_OUT:
                # Dijumlahkan, bukan diambil yang terbesar: dua izin
                # keluar di hari yang sama adalah dua ketidakhadiran
                # yang berbeda. Yang tumpang tindih sudah ditolak
                # service sebelum sampai ke sini.
                permission_minutes += _clip(window, shift_start, shift_end)

            else:  # FULL_DAY
                excused_absence = True

                # Seharian pergi berarti seluruh telat dan pulang
                # cepatnya ikut termaafkan. Kombinasi ini tidak lazim —
                # izin sehari yang tetap ada tapnya — tapi ia terjadi:
                # orang yang izin lalu tetap mampir menandatangani
                # sesuatu.
                excused_late = max(excused_late, late_minutes)
                excused_early = max(excused_early, early_leave_minutes)

        result["excused_late_minutes"] = min(excused_late, late_minutes)
        result["excused_early_leave_minutes"] = min(
            excused_early, early_leave_minutes,
        )
        result["permission_minutes"] = permission_minutes
        result["is_excused_absence"] = bool(
            excused_absence and status == AttendanceStatus.ABSENT
        )

        result["permission_state"] = _state(
            effective=effective,
            pending=pending,
            late_minutes=late_minutes,
            early_leave_minutes=early_leave_minutes,
            excused_late=result["excused_late_minutes"],
            excused_early=result["excused_early_leave_minutes"],
            excused_absence=result["is_excused_absence"],
            status=status,
        )

        return result


def _clip(
    window: PermissionWindow,
    shift_start: datetime | None,
    shift_end: datetime | None,
) -> int:
    """
    Menit izin yang benar-benar jatuh di dalam jam kerja.

    Izin 16:00–18:00 untuk shift yang selesai 17:00 adalah satu jam
    ketidakhadiran, bukan dua — dan payroll yang menerima dua akan
    memotong waktu yang memang bukan jam kerjanya.
    """
    if window.start is None or window.end is None:
        return 0

    start = window.start
    end = window.end

    if shift_start is not None:
        start = max(start, shift_start)

    if shift_end is not None:
        end = min(end, shift_end)

    return max(0, int((end - start).total_seconds() // 60))


def _excused_late(
    *,
    window: PermissionWindow,
    check_in: datetime | None,
    late_minutes: int,
) -> int:
    if late_minutes <= 0:
        return 0

    if window.end is None:
        # Batas izinnya tidak diketahui — tidak ada dasar untuk
        # memaafkan sebagian, dan memaafkan seluruhnya berarti
        # dokumen tanpa jam jadi surat sakti. Model sudah mewajibkan
        # `end_time` untuk tipe ini; jaring ini untuk baris lama.
        return 0

    if check_in is None:
        # Izin datang terlambat yang tapnya tidak pernah masuk. Tidak
        # ada keterlambatan untuk dimaafkan — yang ada ketidakhadiran,
        # dan itu bukan yang diizinkan dokumen ini.
        return 0

    beyond = max(0, int((check_in - window.end).total_seconds() // 60))

    return max(0, late_minutes - beyond)


def _excused_early(
    *,
    window: PermissionWindow,
    check_out: datetime | None,
    early_leave_minutes: int,
) -> int:
    if early_leave_minutes <= 0:
        return 0

    if window.start is None or check_out is None:
        return 0

    # Pulang **sebelum** jam yang diizinkan: selisihnya yang tidak
    # dimaafkan. Pulang sesudahnya menghasilkan nol, jadi seluruh
    # pulang cepatnya termaafkan.
    beyond = max(0, int((window.start - check_out).total_seconds() // 60))

    return max(0, early_leave_minutes - beyond)


def _state(
    *,
    effective,
    pending,
    late_minutes: int,
    early_leave_minutes: int,
    excused_late: int,
    excused_early: int,
    excused_absence: bool,
    status: str | None,
) -> str:
    """
    Satu kata untuk layar. Urutannya: yang tertutup penuh, yang
    tertutup sebagian, yang masih menunggu, lalu yang memang tanpa
    izin.

    `pending` sengaja **di bawah** `partial`: baris yang sebagian sudah
    dimaafkan izin yang disetujui tidak boleh terbaca "menunggu" hanya
    karena ada izin kedua yang belum diputuskan.
    """
    exceptions = (
        late_minutes > 0
        or early_leave_minutes > 0
        or status == AttendanceStatus.ABSENT
    )

    if effective:
        covered = (
            excused_late >= late_minutes
            and excused_early >= early_leave_minutes
            and (status != AttendanceStatus.ABSENT or excused_absence)
        )

        if covered:
            return "excused"

        return "partial"

    if pending:
        return "pending"

    # Sisanya: dokumen izinnya ada tapi tidak satu pun berlaku —
    # ditolak atau dibatalkan. Barisnya kembali jadi pengecualian tanpa
    # izin, dan itu memang yang harus terbaca.
    return "unauthorized" if exceptions else ""
