"""
Kotak masuk approval dan hak memutuskan.

Dipisah dari `WorkflowService` karena dua hal ini yang dipanggil paling
sering dan dari paling banyak tempat: setiap layar dokumen menanyakan
"boleh tidak saya menekan tombol ini", dan halaman beranda menanyakan
"apa saja yang menunggu saya".
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import F

from apps.workflow.models import (
    ApprovalStatus,
    InstanceStatus,
    WorkflowApproval,
)
from apps.workflow.services.delegation_service import (
    WorkflowDelegationService,
)


@dataclass(frozen=True)
class ActingRight:
    """
    Hasil pemeriksaan hak: boleh atau tidak, dan atas dasar apa.

    `delegation` terisi kalau haknya datang dari surat kuasa — itu yang
    nanti disimpan di `WorkflowApproval.acted_via_delegation`, supaya
    "kenapa yang tanda tangan bukan atasannya" ada jawabannya.
    """

    allowed: bool
    delegation: object | None = None
    reason: str = ""

    def __bool__(self) -> bool:
        return self.allowed


class WorkflowApprovalService:
    # ------------------------------------------------------------------
    # Hak memutuskan
    # ------------------------------------------------------------------

    @staticmethod
    def check_right(*, approval: WorkflowApproval, user) -> ActingRight:
        """
        Apakah `user` boleh memutuskan baris ini.

        Tiga jalan: approver-nya sendiri, pemegang surat kuasa, atau
        superuser. Superuser ikut supaya tenant yang datanya belum
        lengkap tetap bisa menjalankan alurnya — tanpa itu, satu
        `reports_to` yang kosong mengunci dokumen dan tidak ada jalan
        keluar selain lewat shell.
        """
        if user is None or not getattr(user, "is_authenticated", False):
            return ActingRight(False, reason="Belum masuk.")

        if approval.status != ApprovalStatus.PENDING:
            return ActingRight(
                False,
                reason=(
                    f"Baris ini sudah "
                    f"{approval.get_status_display().lower()}."
                ),
            )

        if approval.approver_id == user.pk:
            return ActingRight(True, reason="Approver dokumen ini.")

        delegation = WorkflowDelegationService.delegation_between(
            approver=approval.approver,
            actor=user,
            module=approval.instance.module,
            document_type=approval.instance.document_type,
        )

        if delegation is not None:
            return ActingRight(
                True,
                delegation=delegation,
                reason=(
                    f"Surat kuasa dari {delegation.delegator} "
                    f"({delegation.starts_at:%d/%m/%Y} – "
                    f"{delegation.ends_at:%d/%m/%Y})."
                ),
            )

        # Sengaja diperiksa paling akhir: superuser yang juga approver
        # atau delegate harus tercatat sebagai itu, bukan sebagai
        # "dilewati sebagai superuser".
        if user.is_superuser:
            return ActingRight(True, reason="Dijalankan sebagai superuser.")

        return ActingRight(
            False,
            reason=(
                f"Baris ini menunggu keputusan "
                f"{approval.approver or '—'}."
            ),
        )

    @classmethod
    def can_act(cls, *, approval: WorkflowApproval, user) -> bool:
        return bool(cls.check_right(approval=approval, user=user))

    # ------------------------------------------------------------------
    # Kotak masuk
    # ------------------------------------------------------------------

    @staticmethod
    def base_queryset():
        return (
            WorkflowApproval.objects
            .filter(
                status=ApprovalStatus.PENDING,
                instance__status=InstanceStatus.PENDING,
            )
            # Hanya baris di step yang sedang ditunggu. Step #2 belum
            # jadi urusan siapa-siapa selama step #1 belum diputuskan —
            # dan menagihnya lebih awal membuat approver menyetujui
            # sesuatu yang bisa saja ditolak di bawahnya.
            .filter(step_id=F("instance__current_step"))
            .select_related(
                "instance",
                "instance__definition",
                "instance__subject_employee",
                "step",
                "approver",
                "approver_employee",
            )
            .order_by("instance__submitted_at", "sequence")
        )

    @classmethod
    def pending_for(cls, user, *, module: str = "", document_type: str = ""):
        """
        Baris yang menunggu keputusan `user` — miliknya sendiri maupun
        yang dikuasakan kepadanya.

        Superuser sengaja **tidak** melihat seluruh kotak masuk tenant.
        Boleh memutuskan saat dibutuhkan (lihat `check_right`) bukan
        berarti harus ditagih setiap dokumen milik semua orang.
        """
        if user is None or not getattr(user, "is_authenticated", False):
            return WorkflowApproval.objects.none()

        owners = [user] + WorkflowDelegationService.delegators_for(
            delegate=user,
            module=module,
            document_type=document_type,
        )

        queryset = cls.base_queryset().filter(approver__in=owners)

        if module:
            queryset = queryset.filter(instance__module=module)

        if document_type:
            queryset = queryset.filter(
                instance__document_type=document_type,
            )

        return queryset

    @classmethod
    def history_for(cls, *, instance):
        """Seluruh baris keputusan satu dokumen, urut kotak tanda tangan."""
        return (
            instance.approvals
            .select_related(
                "step",
                "approver",
                "approver_employee",
                "acted_by",
                "acted_via_delegation",
                "acted_via_delegation__delegator",
            )
            .order_by("sequence", "id")
        )
