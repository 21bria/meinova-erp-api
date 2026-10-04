"""
Pemberitahuan Travel Request di luar jalur persetujuan.

Yang lewat approval sudah ditangani `apps/workflow/notifications.py` —
empat event generik yang berlaku untuk dokumen apa pun. Dua di berkas
ini kejadian yang **tidak punya tombol setuju**: jadwalnya jadi pasti,
dan hari berangkatnya mendekat.

Pembedanya bukan kerapian. "Dokumen Anda disetujui" dan "tiket Anda
sudah pasti, berangkat 14 September dari Gebe" menjawab dua pertanyaan
berbeda, dan yang kedua yang benar-benar dibutuhkan orang yang harus
mengemas barang.
"""

from __future__ import annotations

import logging

from apps.hr.models import TravelDirection


logger = logging.getLogger(__name__)


def _route(request) -> tuple[str, str]:
    """
    Titik awal dan titik akhir perjalanan.

    Diambil dari etape **pertama arah keluar** dan **terakhir arah
    masuk**, bukan dari kolom di dokumen induknya — rutenya bersambung
    dan berbeda per orang karena Point of Hire-nya berbeda, dan
    dokumennya sendiri memang tidak menyimpan ringkasannya.

    Kosong kalau etapenya belum diisi. Itu keadaan yang sah: TR bisa
    disetujui sebelum tiketnya dibeli.

    Related name-nya `travels`, bukan `arrangements`. Dulu tertulis
    yang kedua dan seluruh badan fungsi ini dibungkus
    `except Exception: return "", ""` — jadi `AttributeError`-nya
    ditelan dan setiap surat terkirim tanpa asal dan tujuan, persis dua
    keterangan yang jadi alasan pemberitahuan ini dipisah dari
    pemberitahuan approval generik. Penjaganya sekarang dilepas: kedua
    pemanggil sudah membungkusnya dengan `logger.exception`, jadi
    kesalahan sejenis berikutnya berbunyi alih-alih menghasilkan surat
    yang setengah kosong.
    """
    legs = list(
        request.travels
        .filter(is_deleted=False)
        .order_by("direction", "sequence")
    )

    outbound = [
        leg
        for leg in legs
        if leg.direction == TravelDirection.OUTBOUND
    ]

    inbound = [
        leg
        for leg in legs
        if leg.direction == TravelDirection.INBOUND
    ]

    origin = outbound[0].origin if outbound else ""
    destination = outbound[-1].destination if outbound else ""

    if not origin and inbound:
        origin = inbound[0].origin

    return origin or "", destination or ""


def _context(request, *, days_left=None) -> dict:
    origin, destination = _route(request)

    departure = request.departure_date

    return {
        "document_number": request.document_number or "",
        "employee_name": request.employee.full_name if request.employee_id else "",
        "employee_number": (
            request.employee.employee_number if request.employee_id else ""
        ),
        # Etape pertama arah keluar, bukan awal blok off — lihat
        # `TravelRequest.departure_date`. Surat yang menyebut tanggal
        # libur sebagai tanggal berangkat membuat orang mengemas
        # terlambat.
        "departure_date": (
            departure.strftime("%d %B %Y") if departure else ""
        ),
        "return_date": (
            request.end_date.strftime("%d %B %Y") if request.end_date else ""
        ),
        "origin": origin,
        "destination": destination,
        "days_left": "" if days_left is None else days_left,
    }


def notify_issued(request) -> None:
    """
    Jadwal perjalanan sudah pasti.

    Dipanggil dari `on_workflow_done` saat statusnya APPROVED — titik
    yang sama dengan penerbitan catatan cutinya. Sengaja **bukan** di
    tengah alur: tiket yang terlanjur dikabarkan lalu ditolak KTT adalah
    pemberitahuan yang harus ditarik kembali, dan tidak ada cara menarik
    email.
    """
    from apps.notifications import notify

    try:
        notify(
            event="hr.travel_request_issued",
            context=_context(request),
            subject_employee=request.employee,
            company=request.company,
            module="hr",
            object_type="travel-request-issued",
            object_id=request.pk,
            link=f"/hr/travel-requests/{request.pk}",
            dedup_key=f"hr.travel_request_issued:{request.pk}",
            tone="success",
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Pemberitahuan penerbitan TR %s gagal dirakit.",
            getattr(request, "pk", None),
        )


def notify_departure(request, *, days_left: int) -> None:
    """
    Pengingat H-N keberangkatan.

    `days_left` ikut jadi kunci dedup: pengingat H-7 tidak boleh ditolak
    sebagai duplikat pengingat H-14, karena yang mendesak justru yang
    belakangan.
    """
    from apps.notifications import notify

    try:
        notify(
            event="hr.travel_departure_reminder",
            context=_context(request, days_left=days_left),
            subject_employee=request.employee,
            company=request.company,
            module="hr",
            object_type="travel-request-departure",
            object_id=request.pk,
            link=f"/hr/travel-requests/{request.pk}",
            dedup_key=(
                f"hr.travel_departure_reminder:{request.pk}:{days_left}"
            ),
            tone="info",
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Pengingat keberangkatan TR %s gagal dirakit.",
            getattr(request, "pk", None),
        )
