"""
Serializer modul roster.

Satu aturan yang berulang di seluruh berkas ini: kolom yang **dihitung
backend** tidak boleh bisa ditulis dari form — nomor dokumen, status,
saldo, dan `credit_days` untuk konversi. Bukan kerapian: kolom status
yang bisa ditulis berarti siapa pun bisa menandai dokumennya sendiri
"Applied" tanpa satu pun meja menyetujuinya.
"""

from rest_framework import serializers

from apps.hr.api.constants import AUDIT_READ_ONLY_FIELDS
from apps.hr.models import (
    RosterAdjustment,
    RosterSetupLine,
    RosterSetupRequest,
    RotationCreditTransaction,
    RotationPeriod,
)
from apps.workflow.models import ApprovalStatus
from apps.workflow.services import WorkflowService


# ----------------------------------------------------------------------
# Bantuan bersama
# ----------------------------------------------------------------------


def approval_payload(document, *, module, document_type) -> dict | None:
    """
    Keadaan persetujuan dalam bentuk yang **sama persis** dengan Travel
    Request dan Cuti.

    Disamakan supaya komponen jejak persetujuan di frontend dipakai
    ulang apa adanya; kalau bentuknya berbeda sedikit saja, modul ini
    butuh komponennya sendiri yang harus dijaga tetap sama.
    """
    workflow = WorkflowService.history_for(
        document=document,
        module=module,
        document_type=document_type,
    ).first()

    if workflow is None:
        return None

    rows = sorted(
        workflow.approvals.all(),
        key=lambda row: (row.sequence, row.pk),
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
        "definition": getattr(workflow.definition, "code", None),
        "current_step": workflow.current_step_id,
        "steps": [
            {
                "sequence": row.sequence,
                "name": getattr(row.step, "name", None),
                "status": row.status,
                "approver": approver_name(row),
                "acted_at": row.acted_at,
                "comment": row.comment,
                "is_current": (
                    row.status == ApprovalStatus.PENDING
                    and row.step_id == workflow.current_step_id
                ),
            }
            for row in rows
        ],
    }


# ----------------------------------------------------------------------
# Segmen
# ----------------------------------------------------------------------


class RosterSegmentSerializer(serializers.ModelSerializer):
    """
    Baris jadwal untuk layar detail rencana.

    Read-only seluruhnya: segmen tidak pernah disunting di tempat, yang
    ada tutup-dan-ganti lewat versi. Menyediakan endpoint tulis di sini
    akan membuka jalur yang persis dilarang desainnya.
    """

    segment_type_label = serializers.CharField(
        source="get_segment_type_display",
        read_only=True,
    )

    version_from_no = serializers.IntegerField(
        source="version_from.version_no",
        read_only=True,
        default=None,
    )

    version_to_no = serializers.IntegerField(
        source="version_to.version_no",
        read_only=True,
        default=None,
    )

    shift_days = serializers.SerializerMethodField()

    class Meta:
        model = RotationPeriod
        fields = [
            "id",
            "sequence",
            "segment_type",
            "segment_type_label",
            "cycle_number",
            "start_date",
            "end_date",
            "total_days",
            "counts_as_roster_day",
            "planned_start_date",
            "planned_end_date",
            "shift_days",
            "is_locked",
            "version_from_no",
            "version_to_no",
            "status",
            "notes",
        ]

        read_only_fields = fields

    def get_shift_days(self, obj) -> int | None:
        """
        Selisih terhadap rencana semula. `None` kalau belum pernah
        digeser — nol dan "belum pernah" adalah dua keadaan berbeda.
        """
        if not obj.planned_start_date or not obj.start_date:
            return None

        return (obj.start_date - obj.planned_start_date).days


# ----------------------------------------------------------------------
# Setup
# ----------------------------------------------------------------------


class RosterSetupLineSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    employee_number = serializers.CharField(
        source="employee.employee_number",
        read_only=True,
    )

    roster_policy_code = serializers.CharField(
        source="roster_policy.code",
        read_only=True,
        default=None,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    # Boleh dikosongkan supaya service bisa mengisinya dari penempatan
    # pegawainya (`apply_defaults`). Dibiarkan `required` bawaan model,
    # DRF menolak lebih dulu dan jalur pengisian otomatis itu tidak
    # pernah kepakai.
    roster_policy = serializers.PrimaryKeyRelatedField(
        queryset=RosterSetupLine._meta.get_field(
            "roster_policy",
        ).related_model.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )

    current_cycle_start = serializers.DateField(required=False)

    class Meta:
        model = RosterSetupLine
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "employee_name",
            "employee_number",
            "roster_policy_code",
            "status_label",
            "status",
            "commit_error",
        ]


class RosterSetupSerializer(serializers.ModelSerializer):
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

    department_name = serializers.CharField(
        source="department.name",
        read_only=True,
        default=None,
    )

    section_name = serializers.CharField(
        source="section.name",
        read_only=True,
        default=None,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    line_count = serializers.SerializerMethodField()
    committed_count = serializers.SerializerMethodField()

    workflow = serializers.SerializerMethodField()

    class Meta:
        model = RosterSetupRequest
        fields = "__all__"

        extra_kwargs = {
            # Boleh dikosongkan supaya `apply_scope_defaults` sempat
            # mengisinya dari cakupan pembuatnya. Kalau dibiarkan
            # `required` bawaan model, DRF menolak request lebih dulu
            # dan jalur pengisian otomatis itu tidak pernah kepakai —
            # jebakan yang sama dengan `start_date` di SiteRotation.
            #
            # Yang cakupannya luas tetap wajib menyebutkannya:
            # `full_clean()` yang menolak, dengan pesan per field.
            "location": {"required": False},
        }

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "company_name",
            "location_name",
            "department_name",
            "section_name",
            "status_label",
            "line_count",
            "committed_count",
            "workflow",
            "committed_at",
            "commit_error",
            "submitted_at",
            "submitted_by",
            # Berpindah lewat alur persetujuan, bukan lewat form.
            "status",
        ]

    def get_line_count(self, obj) -> int:
        return len(
            [line for line in obj.lines.all() if not line.is_deleted],
        )

    def get_committed_count(self, obj) -> int:
        return len(
            [
                line
                for line in obj.lines.all()
                if not line.is_deleted and line.status == "committed"
            ],
        )

    def get_workflow(self, obj) -> dict | None:
        return approval_payload(
            obj,
            module="hr",
            document_type="roster_setup",
        )


# ----------------------------------------------------------------------
# Penyesuaian
# ----------------------------------------------------------------------


class RosterAdjustmentSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
        default=None,
    )

    employee_number = serializers.CharField(
        source="employee.employee_number",
        read_only=True,
        default=None,
    )

    plan_label = serializers.CharField(
        source="plan.__str__",
        read_only=True,
        default=None,
    )

    adjustment_kind_label = serializers.CharField(
        source="get_adjustment_kind_display",
        read_only=True,
    )

    credit_impact_label = serializers.CharField(
        source="get_credit_impact_display",
        read_only=True,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    credit_balance = serializers.SerializerMethodField()

    workflow = serializers.SerializerMethodField()

    # Diisi service dari rencananya; menuliskannya lewat form hanya
    # akan ditimpa, dan yang lebih buruk: dokumen bisa menunjuk pegawai
    # yang bukan pemilik jadwalnya.
    employee = serializers.PrimaryKeyRelatedField(
        read_only=True,
    )

    class Meta:
        model = RosterAdjustment
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "employee_name",
            "employee_number",
            "plan_label",
            "adjustment_kind_label",
            "credit_impact_label",
            "status_label",
            "credit_balance",
            "workflow",
            "applied_at",
            "apply_error",
            "resulting_version",
            "submitted_at",
            "submitted_by",
            "status",
        ]

    def get_credit_balance(self, obj) -> str | None:
        from apps.hr.api.roster.credit_service import RotationCreditService

        if obj.employee_id is None:
            return None

        return str(RotationCreditService.balance_for(obj.employee).balance)

    def get_workflow(self, obj) -> dict | None:
        return approval_payload(
            obj,
            module="hr",
            document_type="roster_adjustment",
        )


# ----------------------------------------------------------------------
# Rotation credit
# ----------------------------------------------------------------------


class RotationCreditSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    employee_number = serializers.CharField(
        source="employee.employee_number",
        read_only=True,
    )

    entry_type_label = serializers.CharField(
        source="get_entry_type_display",
        read_only=True,
    )

    signed_days = serializers.DecimalField(
        max_digits=8,
        decimal_places=2,
        read_only=True,
    )

    source_label = serializers.SerializerMethodField()
    reversed_by_label = serializers.SerializerMethodField()

    class Meta:
        model = RotationCreditTransaction
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "employee_name",
            "employee_number",
            "entry_type_label",
            "signed_days",
            "source_label",
            "reversed_by_label",
            "transaction_date",
            "remainder_days",
            "conversion_ratio",
            # Pembalikan dibuat lewat action `reverse/`, bukan dengan
            # mengetik pk di form — tanpa itu tidak ada yang memeriksa
            # bahwa transaksinya belum pernah dibalikkan.
            "reverses",
        ]

    def get_source_label(self, obj) -> str | None:
        if not obj.source_type:
            return None

        return f"{obj.source_type} #{obj.source_id}" if obj.source_id else (
            obj.source_type
        )

    def get_reversed_by_label(self, obj) -> str | None:
        reversal = next(
            (
                row
                for row in obj.reversed_by.all()
                if not row.is_deleted
            ),
            None,
        )

        if reversal is None:
            return None

        return f"#{reversal.pk} ({reversal.effective_date})"


class RotationCreditBalanceSerializer(serializers.Serializer):
    """Rekap saldo, dibaca dari cache yang dihitung ulang dari ledger."""

    employee = serializers.IntegerField(source="employee_id")
    employee_number = serializers.CharField(
        source="employee.employee_number",
    )
    employee_name = serializers.CharField(source="employee.full_name")

    earned = serializers.DecimalField(max_digits=8, decimal_places=2)
    used = serializers.DecimalField(max_digits=8, decimal_places=2)
    adjustment = serializers.DecimalField(max_digits=8, decimal_places=2)
    expired = serializers.DecimalField(max_digits=8, decimal_places=2)
    balance = serializers.DecimalField(max_digits=8, decimal_places=2)

    carried_excess_days = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
    )

    last_transaction_at = serializers.DateTimeField(allow_null=True)
