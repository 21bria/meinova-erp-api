"""
Menyambungkan dokumen HR ke engine approval generik.

Kotak masuk approval satu untuk semua modul, jadi saat approver menekan
Approve dari sana, engine perlu tahu apa yang harus terjadi pada
dokumennya. Engine tidak boleh menebak nama kolom status modul lain —
di sinilah HR mendaftarkan sendiri pemetaannya.

Di-import dari `HrConfig.ready()`. Kalau lupa, tombol Approve di kotak
masuk tetap jalan tapi status cuti/TR-nya **tidak ikut berpindah**, dan
gagalnya diam.
"""

from __future__ import annotations

import logging

from apps.workflow.registry import register_completion, register_route


logger = logging.getLogger(__name__)


# Rute halaman dokumen di frontend, dipakai tombol "Buka dokumen" di
# kotak masuk dan layar monitoring. Ditulis di sini, bukan ditebak
# engine: `leave_request` yang halamannya `/hr/leave/<id>` tidak bisa
# disimpulkan dari nama modulnya. Harus cocok dengan `app/pages/` di
# repo Nuxt — rute yang salah membuat tombolnya mendarat di 404.
register_route("hr", "leave_request", "/hr/leave/{id}/edit")
register_route("hr", "travel_request", "/hr/travel-requests/{id}")
register_route("hr", "employee_action", "/hr/employee-actions/{id}")
register_route("hr", "roster_setup", "/hr/roster-setups/{id}")
register_route("hr", "roster_adjustment", "/hr/roster-adjustments/{id}")
register_route("hr", "visitor_request", "/hr/visitor-requests/{id}")
register_route("hr", "business_trip", "/hr/business-trips/{id}")
register_route(
    "hr",
    "attendance_permission",
    "/hr/attendance-permissions/{id}",
)


def _document(instance, model):
    document = (
        model.objects
        .filter(pk=instance.object_id, is_deleted=False)
        .first()
    )

    if document is None:
        # Dokumen yang hilang setelah alurnya berjalan. Dicatat, bukan
        # dilempar: keputusan approver-nya sendiri sudah tersimpan, dan
        # menggagalkan transaksi di titik ini akan membatalkan
        # persetujuan yang sah gara-gara dokumen yang sudah tidak ada.
        logger.warning(
            "Workflow %s selesai tapi dokumen %s/%s #%s tidak ditemukan.",
            instance.pk,
            instance.module,
            instance.document_type,
            instance.object_id,
        )

    return document


@register_completion("hr", "leave_request")
def leave_completed(instance, status):
    from apps.hr.api.leave.services import EmployeeLeaveService
    from apps.hr.models import EmployeeLeave

    leave = _document(instance, EmployeeLeave)

    if leave is None:
        return None

    return EmployeeLeaveService.apply_workflow_status(
        instance=leave,
        status=status,
        user=instance.submitted_by,
    )


@register_completion("hr", "employee_action")
def employee_action_completed(instance, status):
    """
    Menutup dokumen perubahan kepegawaian.

    Yang membedakannya dari dua handler lain: di sini `on_workflow_done`
    juga **menerapkan** perubahannya ke data pegawai kalau alurnya
    selesai dengan APPROVED. Itu satu-satunya jalur yang mengubah
    kontrak, penempatan, atau gaji — dan ia idempotent, jadi callback
    yang kebetulan jalan dua kali tidak menerapkannya dua kali.
    """
    from apps.hr.api.employee_action.services import EmployeeActionService
    from apps.hr.models import EmployeeAction

    document = _document(instance, EmployeeAction)

    if document is None:
        return None

    return EmployeeActionService.on_workflow_done(
        instance=document,
        status=status,
        user=instance.submitted_by,
    )


@register_completion("hr", "roster_setup")
def roster_setup_completed(instance, status):
    """
    Menutup dokumen setup roster.

    Kalau disetujui, callback ini juga **menerbitkan** jadwalnya —
    satu rencana per baris, masing-masing langsung dikunci sebagai
    baseline. Kegagalan per baris tidak membatalkan persetujuan; yang
    gagal ditandai di barisnya sendiri dan diulang lewat
    `POST .../commit/`.
    """
    from apps.hr.api.roster.setup_service import RosterSetupService
    from apps.hr.models import RosterSetupRequest

    document = _document(instance, RosterSetupRequest)

    if document is None:
        return None

    return RosterSetupService.on_workflow_done(
        request=document,
        status=status,
        user=instance.submitted_by,
    )


@register_completion("hr", "roster_adjustment")
def roster_adjustment_completed(instance, status):
    from apps.hr.api.roster.adjustment_service import (
        RosterAdjustmentService,
    )
    from apps.hr.models import RosterAdjustment

    document = _document(instance, RosterAdjustment)

    if document is None:
        return None

    return RosterAdjustmentService.on_workflow_done(
        adjustment=document,
        status=status,
        user=instance.submitted_by,
    )


@register_completion("hr", "travel_request")
def travel_request_completed(instance, status):
    from apps.hr.api.travel_request.services import TravelRequestService
    from apps.hr.models import TravelRequest

    request = _document(instance, TravelRequest)

    if request is None:
        return None

    return TravelRequestService.on_workflow_done(
        request=request,
        status=status,
        user=instance.submitted_by,
    )


@register_completion("hr", "visitor_request")
def visitor_request_completed(instance, status):
    """
    Menutup dokumen kunjungan tamu.

    Yang membedakannya dari handler lain: tidak ada apa pun yang
    diterbitkan saat disetujui. Persetujuan hanya membuka pintu —
    check-in-nya dilakukan orang di pos jaga, dan itu tindakan
    tersendiri yang tanggalnya tidak bisa disimpulkan dari kapan
    approver menekan tombol.
    """
    from apps.hr.api.visitor.services import VisitorRequestService
    from apps.hr.models import VisitorRequest

    document = _document(instance, VisitorRequest)

    if document is None:
        return None

    return VisitorRequestService.on_workflow_done(
        request=document,
        status=status,
        user=instance.submitted_by,
    )


@register_completion("hr", "business_trip")
def business_trip_completed(instance, status):
    """
    Menutup dokumen Business Trip.

    Handler ini **satu-satunya** jalur hasil alur ke dokumennya: layar
    Business Trip dan kotak masuk generik sama-sama mengopernya sebagai
    `on_complete`, jadi keduanya berakhir di keadaan yang sama.
    """
    from apps.hr.api.business_trip.services import BusinessTripService
    from apps.hr.models import BusinessTrip

    document = _document(instance, BusinessTrip)

    if document is None:
        return None

    return BusinessTripService.on_workflow_done(
        trip=document,
        status=status,
        user=instance.submitted_by,
    )


@register_completion("hr", "attendance_permission")
def attendance_permission_completed(instance, status):
    """
    Menutup dokumen izin kehadiran.

    Yang membedakannya dari handler lain: keputusan approver **memicu
    perhitungan ulang presensi** pada tanggal izinnya, dan itu berlaku
    untuk penolakan juga — bukan hanya persetujuan. Izin yang ditolak
    harus mencabut badge "menunggu izin" yang sempat terbaca di layar
    presensi; membiarkannya membuat baris yang sudah diputuskan terlihat
    masih menggantung.

    Jam tap tidak disentuh sama sekali. Yang berubah hanya
    klasifikasinya.
    """
    from apps.hr.api.attendance_permission.services import (
        AttendancePermissionService,
    )
    from apps.hr.models import AttendancePermission

    document = _document(instance, AttendancePermission)

    if document is None:
        return None

    return AttendancePermissionService.on_workflow_done(
        permission=document,
        status=status,
        user=instance.submitted_by,
    )
