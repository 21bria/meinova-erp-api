"""
Menuliskan efek izin ke baris presensi.

`permission_resolver.py` di sebelah menghitungnya tanpa menyentuh
database; berkas ini yang mencarikan bahannya dan menyimpan hasilnya.
Pemisahannya bukan gaya: perhitungan yang butuh query tidak bisa diuji
untuk dua puluh skenario tanpa membangun dua puluh tenant, dan hitungan
menit izin adalah bagian yang paling sering ditanyakan ulang.

Satu aturan yang tidak boleh dilanggar: **baris presensi tidak pernah
dibuat dari sini.** Yang menerbitkan baris tetap importir, mesin, atau
`AttendanceClosingService`. Izin hanya mengklasifikasikan baris yang
sudah ada — dan hari yang barisnya belum terbit akan mendapat
klasifikasinya begitu barisnya terbit, karena `EmployeeAttendance
Service.create()` memanggil resolver yang sama.
"""

from __future__ import annotations

from datetime import date as date_cls

from django.db import transaction

from apps.hr.api.attendance.permission_resolver import (
    AttendancePermissionResolver,
    PERMISSION_FIELDS,
    build_window,
)
from apps.hr.api.attendance.schedule import resolve_shift, shift_span
from apps.hr.models.attendance.permission import (
    AttendancePermission,
    AttendancePermissionStatus,
)


# Yang dibaca resolver: yang sudah disetujui (memaafkan) dan yang masih
# berjalan (menjelaskan kenapa belum dimaafkan). DRAFT sengaja tidak
# ikut — dokumen yang belum diajukan belum diketahui siapa pun, dan
# menampilkannya sebagai "menunggu izin" di layar atasan berarti
# menagih keputusan atas sesuatu yang belum sampai ke mejanya.
READABLE_STATUSES = [
    AttendancePermissionStatus.SUBMITTED,
    AttendancePermissionStatus.IN_REVIEW,
    AttendancePermissionStatus.APPROVED,
]


def permissions_for(employee, work_date: date_cls) -> list:
    return list(
        AttendancePermission.objects
        .filter(
            employee=employee,
            date=work_date,
            is_deleted=False,
            status__in=READABLE_STATUSES,
        )
        .order_by("id")
    )


def shift_window(employee, work_date: date_cls):
    """
    Jendela shift sebagai datetime naif, atau `(None, None)`.

    **Naif, bukan ber-timezone**, dan bukan `scheduled_window()`: yang
    dibandingkan resolver adalah jam dinding, dan `scheduled_window()`
    ikut menolak hari yang tidak terjadwal. Untuk izin, hari yang tidak
    terjadwal tetap perlu jendelanya — izin di hari libur ditolak
    validasi dengan pesan yang menyebutkannya, bukan dihitung diam-diam
    sebagai izin tanpa jam.
    """
    resolved = resolve_shift(employee, work_date)

    if resolved is None:
        return (None, None)

    start, end, crosses = resolved.as_times()

    return shift_span(work_date, start, end, crosses)


def compute_for(
    *,
    employee,
    work_date: date_cls,
    status,
    late_minutes,
    early_leave_minutes,
    check_in,
    check_out,
    permissions=None,
) -> dict:
    """
    Kelima kolom klasifikasi untuk satu hari.

    `permissions` boleh dioper pemanggil yang sudah membacanya (jalur
    perhitungan ulang sebulan) supaya tidak ada satu query per baris.
    """
    if permissions is None:
        permissions = permissions_for(employee, work_date)

    if not permissions:
        # Jalan pintas yang menyelamatkan jalur borongan. Baris presensi
        # dibuat ribuan sekaligus (importir, penutup hari), dan hampir
        # tidak satu pun punya izin — meresolusi shift untuk masing-
        # masing berarti beberapa query per baris demi jawaban yang
        # sudah pasti "tidak ada izin".
        #
        # Yang **tidak** dilewati perhitungan `permission_state`:
        # telat tanpa izin tetap harus terbaca `unauthorized`, dan
        # jawabannya tidak butuh jendela shift sama sekali.
        return AttendancePermissionResolver.compute(
            windows=[],
            status=status,
            late_minutes=late_minutes,
            early_leave_minutes=early_leave_minutes,
            check_in=check_in,
            check_out=check_out,
        )

    shift_start, shift_end = shift_window(employee, work_date)

    windows = [
        build_window(
            permission,
            shift_start=shift_start,
            shift_end=shift_end,
        )
        for permission in permissions
    ]

    return AttendancePermissionResolver.compute(
        windows=windows,
        status=status,
        late_minutes=late_minutes,
        early_leave_minutes=early_leave_minutes,
        check_in=check_in,
        check_out=check_out,
        shift_start=shift_start,
        shift_end=shift_end,
    )


class AttendancePermissionEffectService:
    @classmethod
    @transaction.atomic
    def recalculate(cls, *, employee, work_date: date_cls) -> int:
        """
        Hitung ulang klasifikasi satu hari. Mengembalikan jumlah baris
        yang benar-benar berubah.

        Angka itu yang dipakai pesan "presensi dihitung ulang" — nol
        berarti barisnya belum ada, dan itu keadaan yang sah (izin
        diajukan untuk tanggal yang mesinnya belum diimpor). Melaporkan
        "berhasil" untuk nol baris membuat orang menunggu perubahan yang
        tidak akan datang.
        """
        from apps.hr.models import EmployeeAttendance

        permissions = permissions_for(employee, work_date)

        rows = (
            EmployeeAttendance.objects
            .filter(
                employee=employee,
                work_date=work_date,
                is_deleted=False,
            )
        )

        changed = 0

        for row in rows:
            computed = compute_for(
                employee=employee,
                work_date=work_date,
                status=row.status,
                late_minutes=row.late_minutes,
                early_leave_minutes=row.early_leave_minutes,
                check_in=row.check_in,
                check_out=row.check_out,
                permissions=permissions,
            )

            dirty = [
                key
                for key in PERMISSION_FIELDS
                if getattr(row, key) != computed[key]
            ]

            if not dirty:
                continue

            for key in dirty:
                setattr(row, key, computed[key])

            row.save(update_fields=dirty + ["updated_at"])

            changed += 1

        return changed

    @classmethod
    def recalculate_for_permission(cls, *, permission) -> int:
        return cls.recalculate(
            employee=permission.employee,
            work_date=permission.date,
        )
