from rest_framework import serializers

from apps.workflow.api.approval.serializers import (
    WorkflowApprovalSerializer,
)
from apps.workflow.labels import INSTANCE_STATUS_LABELS, label_for
from apps.workflow.models import WorkflowInstance


class WorkflowInstanceSerializer(serializers.ModelSerializer):
    definition_code = serializers.CharField(
        source="definition.code",
        read_only=True,
    )

    definition_name = serializers.CharField(
        source="definition.name",
        read_only=True,
    )

    status_label = serializers.SerializerMethodField()

    def get_status_label(self, obj) -> str:
        return label_for(INSTANCE_STATUS_LABELS, obj.status)

    current_step_name = serializers.CharField(
        source="current_step.name",
        read_only=True,
        default=None,
    )

    subject_name = serializers.CharField(
        source="subject_employee.full_name",
        read_only=True,
        default=None,
    )

    subject_number = serializers.CharField(
        source="subject_employee.employee_number",
        read_only=True,
        default=None,
    )

    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    location_name = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )

    submitted_by_name = serializers.SerializerMethodField()

    approvals = WorkflowApprovalSerializer(many=True, read_only=True)

    # Turunan yang dibaca layar monitoring: sudah sampai kotak ke
    # berapa, sedang di meja siapa, dan apakah tombol Approve boleh
    # tampil untuk yang sedang membukanya.
    progress = serializers.SerializerMethodField()

    waiting_for = serializers.SerializerMethodField()

    document_url = serializers.SerializerMethodField()

    can_act = serializers.SerializerMethodField()

    class Meta:
        model = WorkflowInstance
        fields = "__all__"

        read_only_fields = [
            field.name
            for field in WorkflowInstance._meta.fields
        ] + [
            "definition_code",
            "definition_name",
            "status_label",
            "current_step_name",
            "subject_name",
            "subject_number",
            "company_name",
            "location_name",
            "submitted_by_name",
            "approvals",
            "progress",
            "waiting_for",
            "document_url",
            "can_act",
        ]

    def get_submitted_by_name(self, obj) -> str | None:
        if not obj.submitted_by_id:
            return None

        return obj.submitted_by.get_full_name() or obj.submitted_by.email

    def get_progress(self, obj) -> dict:
        """
        Sudah berapa kotak tanda tangan yang selesai.

        `percent` dihitung dari **semua** baris, termasuk yang SKIPPED —
        step yang dilewati memang tidak perlu ditunggu siapa pun, jadi
        menghitungnya sebagai "belum selesai" membuat dokumen yang
        sebenarnya tinggal satu meja lagi terlihat baru separuh jalan.

        Dokumen yang sudah berhenti selalu 100%: alurnya memang tidak
        akan bergerak lagi, dan bar setengah penuh pada dokumen yang
        ditolak membuat orang mengira masih ada yang harus menekan
        tombol.
        """
        from apps.workflow.models import ApprovalStatus, InstanceStatus

        rows = list(obj.approvals.all())

        total = len(rows)

        decided = sum(
            1
            for row in rows
            if row.status != ApprovalStatus.PENDING
        )

        approved = sum(
            1
            for row in rows
            if row.status == ApprovalStatus.APPROVED
        )

        if obj.status in (
            InstanceStatus.DRAFT,
            InstanceStatus.PENDING,
        ):
            percent = round(decided / total * 100) if total else 0
        else:
            percent = 100

        return {
            "total": total,
            "decided": decided,
            "approved": approved,
            "skipped": sum(
                1
                for row in rows
                if row.status == ApprovalStatus.SKIPPED
            ),
            "percent": percent,
        }

    def get_waiting_for(self, obj) -> dict | None:
        """
        Sedang menunggu siapa, di kotak yang mana, sejak kapan.

        Ini isi tooltip di layar monitoring — "sudah tiga hari di meja
        Budi" adalah satu-satunya angka yang membuat orang menagih.
        `since` diambil dari keputusan terakhir sebelum baris ini, bukan
        dari tanggal pengajuan: dokumen yang sudah lewat dua meja baru
        mendarat di meja ketiga kemarin, dan menghitungnya sejak
        pengajuan menyalahkan orang yang salah.
        """
        from apps.workflow.models import ApprovalStatus

        if obj.current_step_id is None:
            return None

        rows = sorted(
            obj.approvals.all(),
            key=lambda row: (row.sequence, row.pk),
        )

        pending = [
            row
            for row in rows
            if row.step_id == obj.current_step_id
            and row.status == ApprovalStatus.PENDING
        ]

        if not pending:
            return None

        decided_at = [
            row.acted_at
            for row in rows
            if row.acted_at is not None
            and row.sequence < pending[0].sequence
        ]

        since = max(decided_at) if decided_at else obj.submitted_at

        def name(row):
            if row.approver_employee_id:
                return row.approver_employee.full_name

            if row.approver_id:
                return row.approver.get_full_name() or row.approver.email

            return None

        return {
            "step": pending[0].name,
            "sequence": pending[0].sequence,
            "approvers": [
                name(row)
                for row in pending
                if name(row)
            ],
            "since": since,
        }

    def get_document_url(self, obj) -> str | None:
        """
        Rute halaman dokumen aslinya di frontend.

        None kalau modulnya belum mendaftar rute — frontend cukup tidak
        menampilkan tombolnya. Lihat `apps/workflow/registry.py`.
        """
        from apps.workflow.registry import document_url

        return document_url(
            module=obj.module,
            document_type=obj.document_type,
            object_id=obj.object_id,
        )

    def get_can_act(self, obj) -> bool:
        from apps.workflow.services import WorkflowApprovalService

        request = self.context.get("request")

        if request is None:
            return False

        return any(
            WorkflowApprovalService.can_act(
                approval=approval,
                user=request.user,
            )
            for approval in obj.pending_approvals
        )
