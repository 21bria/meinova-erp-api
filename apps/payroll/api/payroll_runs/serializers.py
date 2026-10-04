from rest_framework import serializers

from apps.payroll.models import PayrollRun
from apps.workflow.models import ApprovalStatus
from apps.workflow.services import WorkflowApprovalService, WorkflowService


class PayrollRunSerializer(serializers.ModelSerializer):
    period_code = serializers.CharField(
        source="period.code", read_only=True, default=None,
    )
    period_name = serializers.CharField(
        source="period.name", read_only=True, default=None,
    )
    period_start_date = serializers.DateField(
        source="period.start_date", read_only=True, default=None,
    )
    period_end_date = serializers.DateField(
        source="period.end_date", read_only=True, default=None,
    )
    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )
    location_name = serializers.CharField(
        source="location.name", read_only=True, default=None,
    )
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=None,
    )

    error_count = serializers.SerializerMethodField()
    warning_count = serializers.SerializerMethodField()

    approval = serializers.SerializerMethodField()

    # Tiga pertanyaan yang berbeda, dan menjawabnya dengan satu field
    # adalah cara membuat salah satunya salah:
    #
    # - `can_edit`  — layar edit-nya masih boleh dibuka? Di situlah
    #   tombol prosesnya tinggal (Generate, Calculate, Submit,
    #   **Withdraw**, **Finalize**). Run yang menunggu persetujuan tidak
    #   bisa disunting isinya tapi tetap harus bisa ditarik kembali, dan
    #   run yang sudah disetujui justru baru di situ bisa difinalisasi
    # - `can_save`  — isian formulirnya masih boleh disimpan?
    # - `can_delete` — dokumennya masih boleh dibuang?
    #
    # Layar tidak menyimpulkannya sendiri dari `status`: daftarnya
    # tinggal di model, dan salinannya di frontend akan tertinggal
    # diam-diam begitu ada status baru.
    can_edit = serializers.SerializerMethodField()
    can_save = serializers.SerializerMethodField()

    # Aturan hapus **berbeda** dari aturan sunting, dan itu bukan
    # kelalaian: run Cancelled tidak bisa disunting tapi boleh dibuang,
    # sedangkan run Processing bisa disunting tapi tidak boleh hilang.
    # Menyatukan keduanya di satu field berarti salah satunya salah.
    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = PayrollRun
        fields = "__all__"
        read_only_fields = [
            "id",
            "company",
            "status",
            "employee_count",
            "total_earning",
            "total_deduction",
            "total_tax",
            "total_net",
            "validation_summary",
            "warnings_acknowledged",
            "acknowledged_at",
            "acknowledged_by",
            "calculated_at",
            "calculated_by",
            "submitted_at",
            "submitted_by",
            "approved_at",
            "approved_by",
            "finalized_at",
            "finalized_by",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "deleted_at",
            "deleted_by",
            "is_deleted",
        ]

    def get_can_edit(self, instance) -> bool:
        return not instance.is_locked

    def get_can_save(self, instance) -> bool:
        return instance.is_editable

    def get_can_delete(self, instance) -> bool:
        from apps.payroll.models import PayrollRunStatus

        return instance.status in (
            PayrollRunStatus.DRAFT,
            PayrollRunStatus.CANCELLED,
        )

    def get_error_count(self, obj) -> int:
        return len((obj.validation_summary or {}).get("errors", []))

    def get_warning_count(self, obj) -> int:
        return len((obj.validation_summary or {}).get("warnings", []))

    def get_approval(self, obj) -> dict | None:
        """
        Keadaan persetujuan run ini.

        Bentuknya sengaja sama dengan dokumen HR lain (`approval.can_act`
        dipakai `visible_when` tombol Approve di schema), supaya
        generator frontend tidak perlu mengenal payroll sebagai kasus
        khusus.
        """
        workflow = WorkflowService.history_for(
            document=obj,
            module="payroll",
            document_type="payroll_run",
        ).first()

        if workflow is None:
            return None

        user = getattr(self.context.get("request"), "user", None)

        rows = sorted(
            workflow.approvals.all(),
            key=lambda row: (row.sequence, row.pk),
        )

        current = next(
            (
                row
                for row in rows
                if row.status == ApprovalStatus.PENDING
                and row.step_id == workflow.current_step_id
            ),
            None,
        )

        def approver_name(row):
            if row.approver_employee_id:
                return row.approver_employee.full_name

            if row.approver_id:
                return row.approver.get_full_name() or row.approver.email

            return None

        return {
            "instance_id": workflow.pk,
            "status": workflow.status,
            "status_label": workflow.get_status_display(),
            "flow": workflow.definition.name,
            "submitted_at": workflow.submitted_at,
            "completed_at": workflow.completed_at,
            "can_act": (
                current is not None
                and WorkflowApprovalService.can_act(
                    approval=current, user=user,
                )
            ),
            "current_step": (
                {
                    "approval_id": current.pk,
                    "sequence": current.sequence,
                    "name": current.name,
                    "approver": approver_name(current),
                }
                if current is not None
                else None
            ),
            "steps": [
                {
                    "approval_id": row.pk,
                    "sequence": row.sequence,
                    "name": row.name,
                    "approver": approver_name(row),
                    "decision": row.status,
                    "decision_label": row.get_status_display(),
                    "decided_at": row.acted_at,
                    "notes": row.comment or row.assignment_reference,
                }
                for row in rows
            ],
        }
