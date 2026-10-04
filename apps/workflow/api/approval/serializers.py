from rest_framework import serializers

from apps.workflow.labels import (
    APPROVAL_STATUS_LABELS,
    ASSIGNMENT_TYPE_LABELS,
    label_for,
)
from apps.workflow.models import WorkflowApproval


class WorkflowApprovalSerializer(serializers.ModelSerializer):
    """
    Satu kotak tanda tangan.

    Dipakai dua tempat sekaligus: baris di kotak masuk approver, dan
    baris riwayat di dalam dokumen. Bentuknya sengaja sama supaya
    formulir tercetak dan layar tidak pernah menampilkan susunan yang
    berbeda untuk data yang sama.
    """

    step_name = serializers.CharField(
        source="step.name",
        read_only=True,
        default=None,
    )

    status_label = serializers.SerializerMethodField()

    assignment_type_label = serializers.SerializerMethodField()

    def get_status_label(self, obj) -> str:
        return label_for(APPROVAL_STATUS_LABELS, obj.status)

    def get_assignment_type_label(self, obj) -> str:
        return label_for(ASSIGNMENT_TYPE_LABELS, obj.assignment_type)

    approver_name = serializers.SerializerMethodField()

    approver_number = serializers.CharField(
        source="approver_employee.employee_number",
        read_only=True,
        default=None,
    )

    acted_by_name = serializers.SerializerMethodField()

    delegated_from = serializers.SerializerMethodField()

    # Konteks dokumen supaya kotak masuk bisa berdiri sendiri tanpa
    # menembak satu request per baris ke modul asalnya.
    document_number = serializers.CharField(
        source="instance.document_number",
        read_only=True,
        default="",
    )

    document_label = serializers.CharField(
        source="instance.document_label",
        read_only=True,
        default="",
    )

    module = serializers.CharField(
        source="instance.module",
        read_only=True,
    )

    document_type = serializers.CharField(
        source="instance.document_type",
        read_only=True,
    )

    object_id = serializers.CharField(
        source="instance.object_id",
        read_only=True,
    )

    subject_name = serializers.SerializerMethodField()

    # Cuplikan nilai dokumen yang dibekukan saat pengajuan.
    #
    # **Generik, bukan milik satu modul.** Isinya ditentukan modul
    # asalnya lewat `context=` pada `WorkflowService.submit`, dan engine
    # tidak pernah menafsirkannya. Tanpa ini, peringatan yang sudah
    # susah payah dibekukan modul Cuti (`needs_review`, `rule_messages`)
    # tidak pernah sampai ke meja yang harus membacanya — approver
    # memutuskan tanpa tahu dokumen itu ditandai perlu diperiksa, dan
    # tidak ada satu pun tanda di layarnya.
    #
    # Namanya `document_context`, bukan `context`: `context` sudah
    # dipakai DRF sebagai atribut serializer, dan menimpanya membuat
    # `self.context` menunjuk baris database.
    document_context = serializers.JSONField(
        source="instance.context",
        read_only=True,
        default=dict,
    )

    submitted_at = serializers.DateTimeField(
        source="instance.submitted_at",
        read_only=True,
    )

    class Meta:
        model = WorkflowApproval
        fields = [
            "id",
            "instance",
            "step",
            "step_name",
            "name",
            "sequence",
            "status",
            "status_label",
            "is_required",
            "approver",
            "approver_name",
            "approver_number",
            "acted_by",
            "acted_by_name",
            "delegated_from",
            "comment",
            "acted_at",
            "assignment_type",
            "assignment_type_label",
            "assignment_reference",
            "document_number",
            "document_label",
            "module",
            "document_type",
            "object_id",
            "subject_name",
            "document_context",
            "submitted_at",
            "created_at",
        ]

        read_only_fields = fields

    def get_approver_name(self, obj) -> str | None:
        if obj.approver_employee_id:
            return obj.approver_employee.full_name

        if obj.approver_id:
            return obj.approver.get_full_name() or obj.approver.email

        return None

    def get_acted_by_name(self, obj) -> str | None:
        if not obj.acted_by_id:
            return None

        return obj.acted_by.get_full_name() or obj.acted_by.email

    def get_delegated_from(self, obj) -> str | None:
        """
        Nama atasan yang diwakili. Hanya terisi kalau keputusannya
        memang diambil delegate — yang menandatangani atas nama orang
        lain harus terbaca di formulir, bukan disamarkan.
        """
        if not obj.was_delegated:
            return None

        return self.get_approver_name(obj)

    def get_subject_name(self, obj) -> str | None:
        employee = obj.instance.subject_employee

        return employee.full_name if employee else None


class ApprovalDecisionSerializer(serializers.Serializer):
    """Isian tombol Approve / Reject / Return."""

    comment = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
