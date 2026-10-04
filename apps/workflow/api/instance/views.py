from rest_framework.decorators import action

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet

from apps.workflow import selectors
from apps.workflow.services import WorkflowApprovalService

from .schema import INSTANCE_SCHEMA
from .serializers import WorkflowInstanceSerializer


class WorkflowInstanceViewSet(BaseMasterViewSet):
    """
    Daftar dokumen yang sedang berjalan.

    Mewarisi `BaseMasterViewSet` — bukan `GenericViewSet` polos —
    karena hanya turunan base itu yang ditemukan
    `framework_schema_view`, dan module yang tidak ketemu berarti tidak
    bisa digenerate di FE. Yang dimatikan cuma metode tulisnya.
    """

    serializer_class = WorkflowInstanceSerializer

    framework_module = "workflow/instances"
    schema = INSTANCE_SCHEMA

    # Dokumen masuk ke sini lewat tombol Submit di modulnya
    # masing-masing, tidak pernah diketik langsung. Membolehkan
    # pembuatan langsung berarti ada instance yang tidak menunjuk
    # dokumen mana pun, dan tidak ada yang bisa menutupnya.
    http_method_names = ["get", "head", "options"]

    search_fields = [
        "document_number",
        "document_label",
        "module",
        "document_type",
        "subject_employee__employee_number",
        "subject_employee__first_name",
        "subject_employee__last_name",
    ]

    filterset_fields = [
        "definition",
        "module",
        "document_type",
        "object_id",
        "status",
        "company",
        "branch",
        "location",
        "subject_employee",
        "submitted_by",
    ]

    ordering_fields = [
        "document_number",
        "status",
        "submitted_at",
        "completed_at",
        "created_at",
    ]

    ordering = ["-created_at"]

    def get_queryset(self):
        """
        Disaring ke yang berhak melihatnya, bukan seluruh tabel.

        Layar monitoring bukan papan pengumuman: `document_label`
        memuat jenis cutinya, dan "Cuti Melahirkan" milik orang lain
        bukan konsumsi satu kantor. Lihat `selectors.visible_instances`.
        """
        return selectors.visible_instances(self.request.user)

    @action(detail=False, methods=["get"], url_path="my-submissions")
    def my_submissions(self, request):
        """Dokumen yang saya ajukan — untuk kartu 'menunggu persetujuan'."""
        queryset = self.filter_queryset(
            self.get_queryset().filter(submitted_by=request.user),
        )

        page = self.paginate_queryset(queryset)

        if page is not None:
            return self.get_paginated_response(
                self.get_serializer(page, many=True).data,
            )

        return success_response(
            data=self.get_serializer(queryset, many=True).data,
            message="Pengajuan saya.",
        )

    @action(detail=True, methods=["get"])
    def trail(self, request, pk=None):
        """
        Seluruh kotak tanda tangan dokumen ini, urut.

        Dipisah dari detail supaya layar dokumen di modul mana pun bisa
        menariknya tanpa ikut membawa seluruh isi instance.
        """
        from apps.workflow.api.approval.serializers import (
            WorkflowApprovalSerializer,
        )

        instance = self.get_object()

        rows = WorkflowApprovalService.history_for(instance=instance)

        return success_response(
            data={
                "status": instance.status,
                "status_label": instance.get_status_display(),
                "current_step": (
                    instance.current_step.name
                    if instance.current_step_id
                    else None
                ),
                "approvals": WorkflowApprovalSerializer(
                    rows,
                    many=True,
                ).data,
            },
            message="Jejak persetujuan.",
        )
