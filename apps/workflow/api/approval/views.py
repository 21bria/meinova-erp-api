"""
Kotak masuk approval dan tiga tombolnya.

Sengaja satu endpoint untuk semua modul: approver tidak boleh harus
membuka layar Cuti untuk menyetujui cuti dan layar Travel Request untuk
menyetujui TR. Yang membedakan cuma `module`/`document_type` sebagai
filter.
"""

from django.core.exceptions import ValidationError
from django.db.models import Q

from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.core.pagination import StandardPagination
from apps.core.responses.api import success_response

from apps.workflow.models import WorkflowApproval
from apps.workflow.services import (
    WorkflowApprovalService,
    WorkflowService,
)

from .serializers import (
    ApprovalDecisionSerializer,
    WorkflowApprovalSerializer,
)


class WorkflowApprovalViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = WorkflowApprovalSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):
        """
        Baris yang boleh dilihat pemakai ini.

        Bukan seluruh tabel: kotak tanda tangan menyebut nama orang dan
        alasan penolakan, dan itu bukan konsumsi semua orang. Riwayat
        dokumen dibaca lewat endpoint dokumennya masing-masing, yang
        sudah punya penjagaannya sendiri.
        """
        user = self.request.user

        queryset = (
            WorkflowApproval.objects
            .select_related(
                "instance",
                "instance__definition",
                "instance__subject_employee",
                "step",
                "approver",
                "approver_employee",
                "acted_by",
            )
        )

        from apps.workflow import selectors

        if selectors.can_monitor_all(user):
            return queryset.order_by("-created_at")

        # `acted_by` ikut: delegate yang benar-benar menekan tombolnya
        # harus tetap bisa membuka kembali keputusan yang ia ambil,
        # walau surat kuasanya sudah lewat masa berlaku.
        return (
            queryset
            .filter(Q(approver=user) | Q(acted_by=user))
            .order_by("-created_at")
        )

    # ------------------------------------------------------------------
    # Kotak masuk
    # ------------------------------------------------------------------

    @action(detail=False, methods=["get"])
    def inbox(self, request):
        """
        Yang menunggu keputusan saya — termasuk yang dikuasakan kepada
        saya.

        Hanya baris di step terdepan: step #2 belum jadi urusan
        siapa-siapa selama step #1 belum diputuskan, dan menagihnya
        lebih awal membuat approver menyetujui sesuatu yang bisa saja
        ditolak di bawahnya.
        """
        queryset = WorkflowApprovalService.pending_for(
            request.user,
            module=request.query_params.get("module", ""),
            document_type=request.query_params.get("document_type", ""),
        )

        page = self.paginate_queryset(queryset)

        if page is not None:
            return self.get_paginated_response(
                self.get_serializer(page, many=True).data,
            )

        return success_response(
            data=self.get_serializer(queryset, many=True).data,
            message="Kotak masuk approval.",
        )

    @action(detail=False, methods=["get"])
    def summary(self, request):
        """Angka untuk lencana di sidebar dan kartu beranda."""
        from apps.workflow import selectors

        return success_response(
            data=selectors.summary_for(request.user),
            message="Ringkasan approval.",
        )

    # ------------------------------------------------------------------
    # Keputusan
    # ------------------------------------------------------------------

    def _decide(self, request, pk, handler, verb: str):
        approval = (
            WorkflowApproval.objects
            .select_related("instance", "step", "approver")
            .filter(pk=pk)
            .first()
        )

        if approval is None:
            raise ValidationError({"detail": "Baris tidak ditemukan."})

        right = WorkflowApprovalService.check_right(
            approval=approval,
            user=request.user,
        )

        if not right:
            raise ValidationError({"workflow": right.reason})

        payload = ApprovalDecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        instance = handler(
            instance=approval.instance,
            user=request.user,
            comment=payload.validated_data["comment"],
            on_complete=_module_callback(approval.instance),
        )

        approval.refresh_from_db()

        return success_response(
            data={
                "approval": self.get_serializer(approval).data,
                "instance_status": instance.status,
                "acted_as": right.reason,
            },
            message=f"Dokumen {verb}.",
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(
            request,
            pk,
            WorkflowService.approve,
            "disetujui",
        )

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(
            request,
            pk,
            WorkflowService.reject,
            "ditolak",
        )

    @action(detail=True, methods=["post"], url_path="return")
    def send_back(self, request, pk=None):
        return self._decide(
            request,
            pk,
            WorkflowService.send_back,
            "dikembalikan ke pengaju",
        )


def _module_callback(instance):
    """
    Callback milik modul pemilik dokumen.

    Engine tidak boleh menebak nama kolom status modul lain, jadi tiap
    modul mendaftarkan sendiri apa yang harus terjadi saat alurnya
    berhenti. Modul yang belum mendaftar tetap jalan — dokumennya cuma
    tidak ikut berpindah status, dan itu keadaan yang sah untuk modul
    yang memang hanya butuh jejak persetujuan.
    """
    from apps.workflow.registry import completion_handler

    return completion_handler(
        module=instance.module,
        document_type=instance.document_type,
    )
