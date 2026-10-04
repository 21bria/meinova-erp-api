"""
Query siap pakai untuk layar-layar workflow.

Dipisah dari service supaya viewset tidak menyusun `select_related`
sendiri-sendiri: daftar dokumen dan kotak masuk sama-sama menembus
empat relasi, dan yang lupa satu di antaranya menambah query per baris
tanpa ada yang menyadarinya sampai datanya banyak.
"""

from __future__ import annotations

from django.conf import settings
from django.db.models import Count, Q

from apps.workflow.models import (
    ApprovalStatus,
    InstanceStatus,
    WorkflowDefinition,
    WorkflowInstance,
)


# Role yang boleh memantau seluruh dokumen tenant. Dipisah ke settings,
# bukan ditanam di kode, supaya tenant yang menamai role-nya berbeda
# tidak perlu menunggu rilis. Kosongkan untuk mematikan pengecualian
# ini sama sekali.
MONITOR_ROLE_CODES = getattr(
    settings,
    "WORKFLOW_MONITOR_ROLES",
    ["HR-ADMIN", "HR-MANAGER"],
)


def definitions():
    return (
        WorkflowDefinition.objects
        .filter(is_deleted=False)
        .select_related("company", "branch", "location", "employee_group")
        .annotate(
            step_count=Count(
                "steps",
                filter=Q(steps__is_deleted=False),
                distinct=True,
            ),
        )
    )


def instances():
    return (
        WorkflowInstance.objects
        .select_related(
            "definition",
            "current_step",
            "subject_employee",
            "company",
            "branch",
            "location",
            "submitted_by",
        )
        .prefetch_related(
            "approvals__step",
            "approvals__approver",
            "approvals__approver_employee",
            "approvals__acted_by",
        )
    )


def instances_for_document(*, module: str, document_type: str, object_id):
    return instances().filter(
        module=module,
        document_type=document_type,
        object_id=str(object_id),
    )


# ----------------------------------------------------------------------
# Visibilitas
# ----------------------------------------------------------------------


def can_monitor_all(user) -> bool:
    """
    Apakah `user` boleh memantau seluruh dokumen tenant.

    Superuser dan pemegang role pemantau. Sengaja lewat role, bukan
    lewat "apakah dia pernah jadi approver": bagian HR harus bisa
    menjawab "pengajuan si A sudah sampai mana" tanpa harus ikut
    menandatanganinya lebih dulu.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False

    if user.is_superuser:
        return True

    if not MONITOR_ROLE_CODES:
        return False

    return user.roles.filter(
        code__in=MONITOR_ROLE_CODES,
        is_deleted=False,
    ).exists()


def visible_instances(user):
    """
    Dokumen yang boleh dilihat `user`.

    Layar monitoring bukan papan pengumuman: `document_label` memuat
    jenis cutinya — "Cuti Melahirkan", "Cuti Duka" — dan itu bukan
    konsumsi satu kantor. Yang boleh melihat hanya orang yang memang
    terlibat:

    * yang mengajukannya,
    * yang jadi subjeknya (pegawai yang dokumennya diajukan HR),
    * yang pernah kebagian kotak tanda tangan — termasuk yang sudah
      lewat gilirannya, karena dia berhak tahu keputusan akhir dokumen
      yang ikut ia setujui,

    plus pemegang role pemantau dan superuser yang melihat semuanya.
    """
    queryset = instances()

    if user is None or not getattr(user, "is_authenticated", False):
        return queryset.none()

    if can_monitor_all(user):
        return queryset

    return queryset.filter(
        Q(submitted_by=user)
        | Q(subject_employee__user=user)
        | Q(approvals__approver=user)
        # Delegate ikut melihat dokumen yang keputusannya benar-benar
        # ia ambil. Bukan lewat surat kuasanya — kuasa yang sudah lewat
        # masa berlakunya tidak boleh menghapus jejak dokumen yang
        # pernah ia tandatangani.
        | Q(approvals__acted_by=user),
    ).distinct()


def participant_object_ids(user, *, module: str, document_type: str):
    """
    `object_id` dokumen satu modul yang `user`-nya ikut sebagai **peserta
    alur** — pemegang meja, penerima kuasanya, atau yang benar-benar
    menekan tombolnya.

    Ada karena kotak masuk dan dokumennya dijaga dua lapis yang berbeda.
    Kotak masuk menagih approver lewat `WorkflowApproval`; dokumennya
    disaring cakupan data, yang cuma mengenal organisasi dan
    "milik sendiri". Atasan langsung bercakupan `own` karena itu
    ditagih menyetujui dokumen yang tidak bisa ia buka — dan yang
    muncul di layarnya bukan "Anda tidak berhak", melainkan
    "No EmployeeLeave matches the given query.", yang terbaca seperti
    dokumennya hilang.

    Yang dikembalikan **id dokumennya**, bukan queryset dokumen: engine
    tidak mengenal model modul mana pun (lihat `registry`), dan yang
    tahu cara menyusun querysetnya adalah viewset modulnya sendiri.

    Tiga keputusan yang disengaja:

    1. **Seluruh baris, bukan cuma yang masih PENDING.** Approver yang
       sudah menandatangani harus tetap bisa membuka yang ia
       tandatangani; akses yang hilang begitu tombol ditekan membuat
       orang menyimpan tangkapan layar sebagai gantinya.
    2. **Penerima kuasa ikut**, lewat `delegators_for` yang sama dengan
       `WorkflowApprovalService.pending_for`. Kalau dua daftar itu
       berbeda, ada baris yang tampil di kotak masuk seseorang lalu
       menolak dibuka — persis bug yang sedang ditutup ini, cuma
       pindah tempat.
    3. **Yang pernah memutuskan lewat kuasa tetap terhitung**
       (`acted_by`). Kuasa yang habis masa berlakunya tidak boleh
       menghapus jejak dokumen yang sudah ia tandatangani.

    Ini **penambah**, bukan pengganti: cakupan data tetap berlaku, dan
    yang bukan peserta alur tidak mendapat satu baris pun dari sini.
    """
    from apps.workflow.models import WorkflowApproval
    from apps.workflow.services import WorkflowDelegationService

    if user is None or not getattr(user, "is_authenticated", False):
        return []

    owners = [user] + WorkflowDelegationService.delegators_for(
        delegate=user,
        module=module,
        document_type=document_type,
    )

    return list(
        WorkflowApproval.objects
        .filter(
            instance__module=module,
            instance__document_type=document_type,
        )
        .filter(Q(approver__in=owners) | Q(acted_by=user))
        .values_list("instance__object_id", flat=True)
        .distinct()
    )


def summary_for(user):
    """
    Angka untuk kartu beranda: berapa yang menunggu saya, berapa yang
    saya ajukan dan masih berjalan.
    """
    from apps.workflow.services import WorkflowApprovalService

    from apps.workflow.permissions import can_configure

    if user is None or not getattr(user, "is_authenticated", False):
        return {
            "waiting_for_me": 0,
            "my_open_submissions": 0,
            "can_configure": False,
            "can_monitor_all": False,
        }

    return {
        # Dipakai frontend untuk menyembunyikan menu Configuration.
        # Bukan pengganti penjagaan di endpoint — menu yang disembunyikan
        # tetap bisa dilewati dengan menembak API langsung — melainkan
        # supaya orang tidak disodori layar yang pasti menolaknya.
        "can_configure": can_configure(user),
        "can_monitor_all": can_monitor_all(user),
        "waiting_for_me": WorkflowApprovalService.pending_for(user).count(),
        "my_open_submissions": (
            WorkflowInstance.objects
            .filter(
                submitted_by=user,
                status__in=[
                    InstanceStatus.PENDING,
                    InstanceStatus.RETURNED,
                ],
            )
            .count()
        ),
    }


def decided_count(instance) -> int:
    return (
        instance.approvals
        .exclude(status=ApprovalStatus.PENDING)
        .count()
    )
