"""
Data uji Visitor Management.

Empat test case dari spesifikasi, dan masing-masing berhenti di keadaan
yang berbeda — supaya tiap tombol di layar punya dokumen yang
memperlihatkannya, bukan supaya datanya banyak:

* **TC-1 External, selesai penuh** — tamu vendor ke HO, diajukan →
  disetujui → check-in → check-out → COMPLETED. Ini yang membuktikan
  seluruh rantainya jalan.
* **TC-2 External, menunggu persetujuan** — tombol Approve/Reject punya
  dokumen untuk ditekan.
* **TC-3 External + travel + akomodasi, sudah disetujui, belum datang**
  — tombol Check In punya dokumen, dan conditional field-nya punya
  contoh yang isinya lengkap.
* **TC-4 External ke site, draft** — tombol Submit punya dokumen.

Sejak BT-2A tidak ada lagi skenario tamu internal: pegawai yang
berkunjung ke lokasi lain memakai Business Trip, dan service menolak
Visitor Request internal.

Dokumennya dibuat lewat **service dan kotak masuk yang sama dengan
pengguna**, bukan `objects.create`: kalau ada yang salah di rantai
persetujuan atau di penomoran, seed ini yang lebih dulu berhenti —
bukan orang pertama yang mencobanya besok pagi.

Pemilik cast tetap `seed_demo_workforce`; di sini pegawainya hanya
**dicari**. Yang belum ada dilaporkan kurang, bukan dibuatkan diam-diam
— pegawai karangan di tengah data uji orang lain adalah persis cara dua
seed mulai saling menimpa.

Aman diulang: dokumen bertanda `MARKER` dan tamu ber-`VISITOR_MARKER`
dibuang lebih dulu, **hard delete**. Baris bertanda terhapus tetap
menempati kunci uniknya (nomor identitas tamu) dan justru menggagalkan
pembangunan ulang.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.administration.models import (
    AccommodationType,
    TransportMode,
    VisitPurpose,
    VisitType,
)
from apps.hr.api.visitor.services import (
    ExternalVisitorService,
    VisitorRequestService,
)
from apps.hr.models import (
    Employee,
    ExternalVisitor,
    VisitorPass,
    VisitorRequest,
    VisitorRequestStatus,
    VisitorType,
)
from apps.workflow.models import InstanceStatus, WorkflowInstance
from apps.workflow.services import WorkflowApprovalService


MARKER = "[demo-visitor]"

# Ditulis di kolom catatan tamu, bukan di namanya: nama tamu tercetak
# di kartu dan di layar pos jaga, dan penanda teknis di sana membuat
# data peragaan tidak bisa dipakai memperagakan apa pun.
VISITOR_MARKER = "[demo-visitor-master]"

MODULE = "hr"
DOCUMENT_TYPE = "visitor_request"


# ----------------------------------------------------------------------
# Pencarian
# ----------------------------------------------------------------------

def _employee(number: str) -> Employee | None:
    return (
        Employee.objects
        .filter(employee_number=number, is_deleted=False)
        .select_related("user", "organization", "employment")
        .first()
    )


def _first_employee(*numbers: str) -> Employee | None:
    for number in numbers:
        found = _employee(number)

        if found is not None:
            return found

    return None


def _reference(model, *codes):
    """
    Baris master pertama yang ketemu dari daftar kode.

    Berjenjang, bukan satu kode yang ditebak: master tiap tenant
    dinamai sendiri, dan seed yang berhenti karena "SITE-VISIT" tidak
    ada di master klien lebih merepotkan daripada seed yang memakai
    baris pertama yang tersedia.
    """
    for code in codes:
        found = model.objects.filter(code=code, is_deleted=False).first()

        if found is not None:
            return found

    return model.objects.filter(is_deleted=False).order_by("sort_order").first()


# ----------------------------------------------------------------------
# Pembersihan
# ----------------------------------------------------------------------

def _purge() -> dict:
    """
    Membuang data uji lama supaya seed bisa dijalankan ulang.

    Urutannya: pengajuan workflow dulu (ia menunjuk dokumen lewat
    string `object_id` tanpa integritas referensial, jadi tidak ikut
    terhapus sendiri dan akan menahan pengajuan berikutnya lewat
    constraint "satu dokumen satu pengajuan berjalan"), lalu kartu,
    lalu dokumennya, terakhir masternya.
    """
    requests = VisitorRequest.objects.filter(remarks__contains=MARKER)

    request_ids = [str(pk) for pk in requests.values_list("pk", flat=True)]

    removed_flows = 0

    if request_ids:
        # Langsung ke model, bukan lewat `WorkflowService.history_for`:
        # helper itu menerima satu dokumen, sedangkan yang dibuang di
        # sini pengajuan milik beberapa dokumen sekaligus.
        instances = WorkflowInstance.objects.filter(
            module=MODULE,
            document_type=DOCUMENT_TYPE,
            object_id__in=request_ids,
        )

        removed_flows = instances.count()

        instances.delete()

    removed_passes = VisitorPass.objects.filter(
        request_id__in=requests.values_list("pk", flat=True),
    ).delete()[0]

    removed_requests = requests.delete()[0]

    removed_visitors = ExternalVisitor.objects.filter(
        notes__contains=VISITOR_MARKER,
    ).delete()[0]

    return {
        "flows": removed_flows,
        "passes": removed_passes,
        "requests": removed_requests,
        "visitors": removed_visitors,
    }


# ----------------------------------------------------------------------
# Alur
# ----------------------------------------------------------------------

def _approve_all(request: VisitorRequest, log, limit=None) -> None:
    """
    Menjalankan alurnya sampai berhenti, satu keputusan per putaran.

    Approver diambil dari baris yang sedang ditunggu lalu **diperiksa
    lewat kotak masuknya** sebelum tombolnya ditekan — itu jalur yang
    dilewati pengguna sungguhan, jadi penyaringan kotak masuk yang
    salah menghentikan seed ini alih-alih lolos diam-diam.
    """
    instance = VisitorRequestService.workflow_for(request)

    if instance is None:
        log("      ! Tidak ada pengajuan berjalan.")

        return

    taken = 0

    for _ in range(8):
        if limit is not None and taken >= limit:
            return

        instance.refresh_from_db()

        if instance.status != InstanceStatus.PENDING:
            return

        pending = instance.pending_approvals.select_related(
            "approver",
            "approver_employee",
        ).first()

        if pending is None or pending.approver_id is None:
            log(
                "      ! Baris berjalan tidak punya approver berakun — "
                "alur berhenti."
            )

            return

        actor = pending.approver

        in_inbox = (
            WorkflowApprovalService.pending_for(
                actor,
                module=MODULE,
                document_type=DOCUMENT_TYPE,
            )
            .filter(pk=pending.pk)
            .exists()
        )

        if not in_inbox:
            log(
                f"      ! Baris #{pending.sequence} tidak muncul di kotak "
                f"masuk {actor.email} — alur berhenti."
            )

            return

        name = (
            pending.approver_employee.full_name
            if pending.approver_employee_id
            else actor.email
        )

        # Lewat service modulnya, bukan `WorkflowService.approve`
        # langsung: itu jalur yang dipakai tombol Approve di layar
        # Visitor Request, dan ia yang memindahkan status dokumen ke
        # UNDER_REVIEW saat masih ada meja di depan.
        VisitorRequestService.decide(
            request=request,
            approved=True,
            user=actor,
            notes=f"Disetujui oleh {name}.",
        )

        taken += 1

        log(f"      ✓ {pending.name} disetujui {name}")


# ----------------------------------------------------------------------
# Skenario
# ----------------------------------------------------------------------

def _visitors() -> list[dict]:
    """
    Tamu luar data uji.

    Nomor identitasnya berawalan `TEST-` supaya tidak pernah
    bertabrakan dengan nomor KTP sungguhan saat file klien diimpor,
    dan supaya barisnya bisa dikenali sekilas di layar.
    """
    return [
        {
            "full_name": "John Doe",
            "identity_number": "TEST-KTP-001",
            "organization_name": "ABC Company",
            "position": "Sales Manager",
            "email": "john@example.test",
            "mobile": "0800000001",
        },
        {
            "full_name": "Siti Rahayu",
            "identity_number": "TEST-KTP-002",
            "organization_name": "PT Mitra Inspeksi Nusantara",
            "position": "Lead Auditor",
            "email": "siti@example.test",
            "mobile": "0800000002",
        },
        {
            "full_name": "Hendra Wijaya",
            "identity_number": "TEST-KTP-003",
            "organization_name": "CV Teknik Sejahtera",
            "position": "Service Engineer",
            "email": "hendra@example.test",
            "mobile": "0800000003",
        },
    ]


@transaction.atomic
def run(*, log=print) -> dict:
    today = timezone.localdate()

    removed = _purge()

    log(
        f"  Data uji lama dibuang: {removed['requests']} dokumen, "
        f"{removed['passes']} kartu, {removed['visitors']} tamu, "
        f"{removed['flows']} pengajuan."
    )

    missing: list[str] = []
    skipped: list[str] = []

    # ------------------------------------------------------------------
    # Cast
    # ------------------------------------------------------------------
    #
    # Nomor pegawai data uji: HO* kantor pusat, SGA* site Sagea.
    # Dicari berjenjang supaya seed ini tidak ikut rusak kalau
    # `seed_demo_workforce` menggeser nomornya.

    ho_requester = _first_employee("HO002", "HO001", "HO003")
    ho_host = _first_employee("HO003", "HO004", "HO001")
    site_host = _first_employee("SGA001", "SGA002", "SGA003")

    for label, employee in (
        ("pemohon HO", ho_requester),
        ("tuan rumah HO", ho_host),
        ("tuan rumah site", site_host),
    ):
        if employee is None:
            missing.append(label)

    if missing:
        return {
            "visitors": 0,
            "requests": 0,
            "completed": 0,
            "submitted": 0,
            "approved": 0,
            "drafts": 0,
            "removed": removed,
            "missing": missing,
            "skipped": skipped,
        }

    actor = ho_requester.user

    # ------------------------------------------------------------------
    # Master referensi
    # ------------------------------------------------------------------

    purpose_meeting = _reference(VisitPurpose, "MEETING")
    purpose_site = _reference(VisitPurpose, "SITE-VISIT", "MEETING")
    purpose_audit = _reference(VisitPurpose, "AUDIT", "INSPECTION")
    purpose_service = _reference(VisitPurpose, "MAINTENANCE", "VENDOR")

    type_official = _reference(VisitType, "OFFICIAL")
    type_vendor = _reference(VisitType, "VENDOR")

    if purpose_meeting is None:
        skipped.append(
            "Master Visit Purpose kosong — jalankan "
            "seed_administration --only=hr-reference."
        )

        return {
            "visitors": 0,
            "requests": 0,
            "completed": 0,
            "submitted": 0,
            "approved": 0,
            "drafts": 0,
            "removed": removed,
            "missing": missing,
            "skipped": skipped,
        }

    transport_flight = _reference(TransportMode, "FLIGHT")
    accommodation_hotel = _reference(AccommodationType, "HOTEL", "GUESTHOUSE")

    # ------------------------------------------------------------------
    # Master tamu
    # ------------------------------------------------------------------

    created_visitors = []

    for payload in _visitors():
        visitor = ExternalVisitorService.create(
            data={**payload, "notes": VISITOR_MARKER},
            user=actor,
        )

        created_visitors.append(visitor)

        log(f"  Tamu {visitor.visitor_number} — {visitor.full_name}")

    john, siti, hendra = created_visitors

    counters = {
        "completed": 0,
        "submitted": 0,
        "approved": 0,
        "drafts": 0,
    }

    requests: list[VisitorRequest] = []

    def build(*, label: str, data: dict) -> VisitorRequest | None:
        try:
            document = VisitorRequestService.create(
                data={**data, "remarks": f"{data.get('remarks', '')} {MARKER}".strip()},
                user=actor,
            )
        except Exception as error:  # noqa: BLE001
            # Satu skenario yang gagal tidak boleh menghentikan
            # tiga lainnya — dan alasannya harus terbaca, bukan
            # hilang sebagai traceback di tengah keluaran seed.
            skipped.append(f"{label}: {error}")

            return None

        requests.append(document)

        log(f"  {label}: {document.document_number}")

        return document

    # ---- TC-1: external, dijalani sampai selesai ---------------------

    tc1 = build(
        label="TC-1 External (selesai penuh)",
        data={
            "requester": ho_requester,
            "visitor_type": VisitorType.EXTERNAL,
            "external_visitor": john,
            "visit_purpose": purpose_meeting,
            "visit_type": type_vendor,
            "host_employee": ho_host,
            "visit_start_date": today - timedelta(days=2),
            "visit_start_time": "09:00",
            "visit_end_date": today - timedelta(days=2),
            "visit_end_time": "16:00",
            "number_of_visitors": 1,
            "remarks": "Rapat evaluasi kontrak dengan vendor di kantor pusat.",
        },
    )

    if tc1 is not None:
        VisitorRequestService.submit(request=tc1, user=actor)

        _approve_all(tc1, log)

        tc1.refresh_from_db()

        if tc1.status == VisitorRequestStatus.APPROVED:
            VisitorRequestService.check_in(
                request=tc1,
                user=actor,
                gate="Lobby HO",
                remarks="Kartu tamu diserahkan.",
            )

            VisitorRequestService.check_out(
                request=tc1,
                user=actor,
                remarks="Kartu dikembalikan.",
            )

            counters["completed"] += 1

            log("      ✓ Check-in dan check-out selesai.")
        else:
            skipped.append(
                f"TC-1 berhenti di status {tc1.get_status_display()} — "
                "check-in tidak dijalankan."
            )

    # ---- TC-2: external, menunggu persetujuan ------------------------

    tc2 = build(
        label="TC-2 External (menunggu persetujuan)",
        data={
            "requester": ho_requester,
            "visitor_type": VisitorType.EXTERNAL,
            "external_visitor": john,
            "visit_purpose": purpose_site,
            "visit_type": type_vendor,
            "host_employee": ho_host,
            "visit_start_date": today + timedelta(days=3),
            "visit_start_time": "10:00",
            "visit_end_date": today + timedelta(days=3),
            "visit_end_time": "15:00",
            "number_of_visitors": 2,
            "remarks": "Presentasi produk untuk tim procurement.",
        },
    )

    if tc2 is not None:
        VisitorRequestService.submit(request=tc2, user=actor)

        counters["submitted"] += 1

        log("      → menunggu meja pertama.")

    # ---- TC-3: external + travel + akomodasi, disetujui --------------

    tc3 = build(
        label="TC-3 External + Travel + Accommodation (disetujui)",
        data={
            "requester": ho_requester,
            "visitor_type": VisitorType.EXTERNAL,
            "external_visitor": siti,
            "visit_purpose": purpose_audit,
            "visit_type": type_official,
            "host_employee": site_host,
            "location": getattr(site_host.organization, "location", None),
            "visit_start_date": today + timedelta(days=5),
            "visit_start_time": "08:00",
            "visit_end_date": today + timedelta(days=8),
            "visit_end_time": "17:00",
            "number_of_visitors": 3,
            "remarks": "Audit sistem manajemen K3 tahunan di site.",

            "travel_required": True,
            "travel_from": "Jakarta",
            "travel_to": "Site Sagea",
            "departure_date": today + timedelta(days=4),
            "departure_time": "06:30",
            "return_date": today + timedelta(days=9),
            "return_time": "13:00",
            "transport_mode": transport_flight,
            "ticket_required": True,
            "ticket_number": "GA-642 / TEST-TKT-001",

            "accommodation_required": True,
            "accommodation_type": accommodation_hotel,
            "accommodation_name": "Guest House Site Sagea",
            "accommodation_checkin": today + timedelta(days=5),
            "accommodation_checkout": today + timedelta(days=8),

            "pickup_required": True,
            "pickup_point": "Bandara Sorong",
            "dropoff_point": "Bandara Sorong",
            "vehicle_required": True,
            "driver_required": True,
            "travel_remarks": "Rombongan 3 orang, perlu 1 kendaraan.",
        },
    )

    if tc3 is not None:
        VisitorRequestService.submit(request=tc3, user=actor)

        _approve_all(tc3, log)

        tc3.refresh_from_db()

        if tc3.status == VisitorRequestStatus.APPROVED:
            counters["approved"] += 1

            log("      → disetujui, menunggu kedatangan.")
        else:
            skipped.append(
                f"TC-3 berhenti di status {tc3.get_status_display()}."
            )

    # ---- TC-4: external ke site, draft -------------------------------

    tc4 = build(
        label="TC-4 External ke site (draft)",
        data={
            "requester": ho_requester,
            "visitor_type": VisitorType.EXTERNAL,
            "external_visitor": siti,
            "visit_purpose": purpose_site,
            "visit_type": type_official,
            "host_employee": site_host,
            "location": getattr(site_host.organization, "location", None),
            "visit_start_date": today + timedelta(days=14),
            "visit_start_time": "07:00",
            "visit_end_date": today + timedelta(days=16),
            "visit_end_time": "17:00",
            "number_of_visitors": 1,
            "remarks": "Inspeksi lanjutan ke site, belum diajukan.",
        },
    )

    if tc4 is not None:
        counters["drafts"] += 1

        log("      → draft, tombol Submit siap dicoba.")

    # ---- Tamu ketiga sengaja tanpa dokumen ---------------------------
    #
    # Hendra terdaftar di master tapi belum pernah diundang: itu yang
    # membuktikan pencarian tamu bekerja untuk orang yang **belum**
    # punya riwayat kunjungan, keadaan yang justru paling sering
    # ditemui saat fiturnya dipakai sungguhan.

    return {
        "visitors": len(created_visitors),
        "requests": len(requests),
        **counters,
        "removed": removed,
        "missing": missing,
        "skipped": skipped,
    }
