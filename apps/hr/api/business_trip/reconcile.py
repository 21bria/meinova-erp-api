"""
Merapikan presensi saat izin perjalanan menyusut — BT-3 (kontrak §10.6).

Dipanggil sesudah perjalanan **dibatalkan** atau **diselesaikan lebih
awal**, di dalam transaksi yang sama dengan perpindahan statusnya:
kalau rekonsiliasi ditolak, perpindahan statusnya ikut batal.

Yang disentuh hanya baris yang **dimiliki** perjalanan itu:
`business_trip=trip`, `source=SYSTEM`, status `business_trip`, tanpa jam
masuk/keluar — kesimpulan penutup hari, bukan fakta. Baris seperti itu
pada tanggal yang tidak lagi diizinkan dihapus (soft delete) lalu
penutup hari dijalankan ulang untuk tanggal-tanggal itu, sehingga
cuti/alpa ditulis dengan aturan biasa.

* Baris yang punya tap fisik **tidak pernah** dihapus; hanya FK
  perjalanannya yang dilepas.
* Tanggal di periode payroll FINALIZED tidak pernah diubah: aksinya
  ditolak (semantik `assert_period_open`), gaji yang sudah dibayar tidak
  bergeser diam-diam.
* Dijalankan dua kali tidak mengubah apa pun.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.hr.api.business_trip.coverage import covered_dates


def reconcile_attendance(trip, *, user=None) -> dict:
    from apps.hr.api.attendance.closing import AttendanceClosingService
    from apps.hr.api.attendance_permission.services import (
        AttendancePermissionService,
    )
    from apps.hr.models import EmployeeAttendance
    from apps.hr.models.attendance.choices import (
        AttendanceSource,
        AttendanceStatus,
    )

    still_covered = covered_dates(trip)

    rows = list(
        EmployeeAttendance.objects
        .select_for_update()
        .filter(business_trip=trip, is_deleted=False)
        .exclude(work_date__in=still_covered)
    )

    owned = [
        row
        for row in rows
        if row.source == AttendanceSource.SYSTEM
        and row.status == AttendanceStatus.BUSINESS_TRIP
        and row.check_in is None
        and row.check_out is None
    ]
    context_only = [row for row in rows if row not in owned]

    for row in owned:
        try:
            AttendancePermissionService.assert_period_open(
                employee=trip.employee,
                work_date=row.work_date,
            )
        except ValidationError as error:
            raise ValidationError(
                {
                    "status": (
                        f"Presensi {row.work_date} sudah dipakai payroll "
                        "yang dikunci, jadi izin perjalanannya tidak bisa "
                        "dicabut dari sini. "
                        + " ".join(
                            message
                            for messages in error.message_dict.values()
                            for message in messages
                        )
                    ),
                },
            ) from error

    now = timezone.now()

    for row in owned:
        row.is_deleted = True
        row.deleted_at = now
        row.deleted_by = user
        row.save(update_fields=["is_deleted", "deleted_at", "deleted_by"])

    for row in context_only:
        row.business_trip = None
        row.save(update_fields=["business_trip", "updated_at"])

    reclosed = None

    if owned:
        until = AttendanceClosingService.default_until()
        dates = sorted(row.work_date for row in owned if row.work_date <= until)

        if dates:
            reclosed = AttendanceClosingService.close(
                start=dates[0],
                end=dates[-1],
                employees=[trip.employee_id],
                user=user,
            )

    return {
        "revoked": len(owned),
        "detached": len(context_only),
        "reclosed": reclosed,
    }
