"""
Pemberitahuan alur persetujuan.

Sebelum ini engine approval **tidak pernah memberi tahu siapa pun**.
Approver tidak tahu ada dokumen di mejanya sampai ia kebetulan membuka
kotak masuk, dan pengaju tidak tahu dokumennya sudah diputuskan. Kotak
masuk yang tidak pernah ditagih adalah dokumen yang mengendap, dan itu
kegagalan yang paling mahal di sistem ini — bukan karena datanya salah,
tapi karena tidak ada yang merasa ditagih.

Dipisah dari `workflow_service.py` dengan sengaja: engine tidak boleh
tahu apa-apa soal template, penerima, atau kanal. Yang dipanggilnya
cuma tiga fungsi di berkas ini, dan masing-masing berhenti di
`notify()`.

**Tidak satu pun fungsi di sini boleh melempar.** Pengajuan cuti yang
gagal karena servernya tidak bisa mengirim email adalah kesalahan yang
jauh lebih besar daripada email yang tidak terkirim. `notify()` sendiri
sudah menelan seluruh kegagalannya di dalam savepoint; yang ditambahkan
di sini cuma penjagaan saat merakit konteksnya.
"""

from __future__ import annotations

import logging

from .models import ApprovalStatus
from .registry import document_url

logger = logging.getLogger(__name__)


def _context(instance, *, step=None, decided_by=None, comment: str = "") -> dict:
    """
    Konteks datar untuk template.

    Datar, bukan instance model — lihat lapis (2) di
    `apps/notifications/render.py`. Tanpa objek di konteks, template
    yang disunting admin tenant tidak punya apa pun untuk ditelusuri.
    """
    employee = instance.subject_employee

    total = instance.approvals.count()

    return {
        "document_label": instance.document_label or "",
        "document_number": instance.document_number or "",
        "document_type": instance.document_type or "",
        "employee_name": str(employee) if employee else "",
        "employee_number": getattr(employee, "employee_number", "") or "",
        "submitter_name": (
            instance.submitted_by.get_full_name()
            or instance.submitted_by.username
        )
        if instance.submitted_by_id
        else "",
        "workflow_name": (
            instance.definition.name if instance.definition_id else ""
        ),
        "step_name": getattr(step, "name", "") or "",
        "step_sequence": getattr(step, "sequence", "") or "",
        "step_total": total,
        "decided_by": (
            decided_by.get_full_name() or decided_by.username
        )
        if decided_by is not None
        else "",
        "comment": comment or "",
    }


def _preparers(instance) -> list:
    """
    Yang mengisi meja **pertama** alur — penyiap dokumennya.

    Bukan pengaju: di alur site pegawai yang mengajukan, tapi Admin
    Section (atau Admin Department kalau section-nya belum punya) yang
    menyiapkan isinya. Dialah yang akan dimintai perbaikan kalau
    dokumennya dikembalikan, dan yang harus tahu hasil akhirnya — kalau
    tidak, satu-satunya yang diberi tahu adalah orang yang tidak bisa
    memperbaikinya.

    Diambil dari baris keputusan, **bukan** dari konfigurasi step: yang
    dicari orangnya, dan orangnya sudah dibekukan saat pengajuan.
    Membaca ulang konfigurasi berarti surat hasil bisa mendarat di
    Admin Section yang baru dipindahkan minggu lalu.

    Baris SKIPPED ikut. Meja pertama yang dilewati karena pengisinya
    juga pengaju tetap dipegang orang yang sama — dan `merge()` di sisi
    notifikasi memang menyatukan penerima kembar.
    """
    rows = list(
        instance.approvals
        .select_related("approver")
        .filter(approver__isnull=False)
        .order_by("sequence", "id")
    )

    if not rows:
        return []

    first = rows[0].sequence

    return [row.approver for row in rows if row.sequence == first]


def _link(instance) -> str:
    """
    Rute dokumen di frontend, kalau modulnya sudah mendaftarkannya.

    Belum terdaftar = string kosong, dan emailnya terkirim tanpa tombol.
    Menebak rutenya jauh lebih buruk: tombol yang tampak berfungsi lalu
    mendarat di 404 membuat penerimanya menyangka dokumennya hilang.
    """
    return (
        document_url(
            module=instance.module,
            document_type=instance.document_type,
            object_id=instance.object_id,
        )
        or ""
    )


def notify_pending(instance, *, step=None) -> None:
    """
    Menagih approver di tahap yang sedang berjalan.

    Penerimanya diambil dari baris keputusan yang **masih PENDING di
    tahap berjalan** — bukan seluruh approver dokumen. Menagih tahap
    berikutnya lebih awal membuat orang menyetujui sesuatu yang bisa
    saja ditolak di bawahnya, dan itu aturan yang sudah dipegang
    `WorkflowApprovalService.pending_for`.
    """
    from apps.notifications import notify

    try:
        step = step or instance.current_step

        if step is None:
            return

        rows = list(
            instance.approvals
            .select_related("approver")
            .filter(step=step, status=ApprovalStatus.PENDING)
        )

        approvers = [row.approver for row in rows if row.approver_id]

        if not approvers:
            return

        notify(
            event="workflow.pending_approval",
            context=_context(instance, step=step),
            subject_employee=instance.subject_employee,
            submitter=instance.submitted_by,
            pending_approvers=approvers,
            company=instance.company,
            module=instance.module,
            object_type=f"{instance.module}-{instance.document_type}",
            object_id=instance.object_id,
            link=_link(instance),
            # Tahapnya ikut jadi kunci: satu dokumen melewati beberapa
            # meja, dan tanpa nomor tahap surat untuk meja kedua ditolak
            # sebagai duplikat surat meja pertama.
            dedup_key=(
                f"workflow.pending_approval:{instance.pk}:{step.pk}"
            ),
            tone="warning",
        )
    except Exception:  # noqa: BLE001 - lihat docstring modul
        logger.exception(
            "Pemberitahuan approval untuk instance %s gagal dirakit.",
            getattr(instance, "pk", None),
        )


def notify_outcome(instance, status, *, decided_by=None, comment: str = "") -> None:
    """
    Memberi tahu pengaju bahwa dokumennya sudah diputuskan.

    `CANCELLED` sengaja **tidak** punya event. Yang membatalkan adalah
    pengajunya sendiri, dan memberitahunya tentang tindakan yang baru
    saja ia lakukan cuma menambah satu surat yang tidak menyampaikan apa
    pun. Kalau nanti pembatalan bisa dilakukan orang lain, di situlah
    event-nya ditambahkan.
    """
    from apps.notifications import notify

    events = {
        "approved": "workflow.approved",
        "rejected": "workflow.rejected",
        "returned": "workflow.returned",
    }

    event = events.get(str(status))

    if event is None:
        return

    try:
        step = None

        # Tahap tempat keputusannya diambil — bukan `current_step`, yang
        # sudah dikosongkan `_close()` saat dokumennya ditutup.
        last = (
            instance.approvals
            .select_related("step")
            .exclude(acted_at=None)
            .order_by("-acted_at", "-id")
            .first()
        )

        if last is not None:
            step = last.step

        notify(
            event=event,
            context=_context(
                instance,
                step=step,
                decided_by=decided_by,
                comment=comment,
            ),
            subject_employee=instance.subject_employee,
            submitter=instance.submitted_by,
            preparers=_preparers(instance),
            company=instance.company,
            module=instance.module,
            object_type=f"{instance.module}-{instance.document_type}",
            object_id=instance.object_id,
            link=_link(instance),
            # Tanpa nomor percobaan: dokumen yang dikembalikan lalu
            # diajukan ulang menghasilkan instance baru, jadi pk-nya
            # sudah membedakan.
            dedup_key=f"{event}:{instance.pk}",
            tone="success" if event == "workflow.approved" else "warning",
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "Pemberitahuan hasil alur untuk instance %s gagal dirakit.",
            getattr(instance, "pk", None),
        )
