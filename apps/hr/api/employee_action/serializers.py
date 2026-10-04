"""
Serializer Employee Action.

Kolom `current_*` semuanya read-only turunan dari penempatan pegawai
sekarang — **tidak disalin ke dokumen**. Dua alasan: menyalinnya berarti
dua versi data yang sama dan yang satu diam-diam basi, dan nilai
"sebelum" yang sungguhan sudah punya tempatnya sendiri di
`values_before` yang dibekukan tepat sebelum perubahannya ditulis.

Jadi sebelum diterapkan, `current_*` menunjuk keadaan hari ini (itu yang
dibutuhkan approver saat membaca); sesudah diterapkan, `values_before`
yang menunjuk keadaan waktu itu (itu yang dibutuhkan riwayat).
"""

from rest_framework import serializers

from apps.hr.api.constants import AUDIT_READ_ONLY_FIELDS
from apps.hr.models import EmployeeAction
from apps.workflow.models import ApprovalStatus
from apps.workflow.services import WorkflowService


class EmployeeActionSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    employee_number = serializers.CharField(
        source="employee.employee_number",
        read_only=True,
    )

    action_type_label = serializers.CharField(
        source="get_action_type_display",
        read_only=True,
    )

    # Nama pengusul untuk kolom tabel dan dokumen tercetak. Tanpa ini
    # kolomnya mencari `requested_by_name` yang tidak ada dan tampil
    # "-" di semua baris.
    requested_by_name = serializers.CharField(
        source="requested_by.full_name",
        read_only=True,
        default=None,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    is_editable = serializers.BooleanField(read_only=True)
    is_applied = serializers.BooleanField(read_only=True)

    # ------------------------------------------------------------------
    # Nilai sekarang
    # ------------------------------------------------------------------

    current_employment_type_name = serializers.CharField(
        source="employee.employment.employment_type.name",
        read_only=True,
        default=None,
    )

    current_employment_status_name = serializers.CharField(
        source="employee.employment.employment_status.name",
        read_only=True,
        default=None,
    )

    current_employee_group_name = serializers.CharField(
        source="employee.employment.employee_group.name",
        read_only=True,
        default=None,
    )

    current_contract_type_name = serializers.CharField(
        source="employee.employment.contract_type.name",
        read_only=True,
        default=None,
    )

    current_contract_start = serializers.DateField(
        source="employee.employment.contract_start",
        read_only=True,
        default=None,
    )

    current_contract_end = serializers.DateField(
        source="employee.employment.contract_end",
        read_only=True,
        default=None,
    )

    current_probation_type_name = serializers.CharField(
        source="employee.employment.probation_type.name",
        read_only=True,
        default=None,
    )

    current_probation_start = serializers.DateField(
        source="employee.employment.probation_start",
        read_only=True,
        default=None,
    )

    current_probation_end = serializers.DateField(
        source="employee.employment.probation_end",
        read_only=True,
        default=None,
    )

    current_position_name = serializers.CharField(
        source="employee.organization.position.name",
        read_only=True,
        default=None,
    )

    current_department_name = serializers.CharField(
        source="employee.organization.department.name",
        read_only=True,
        default=None,
    )

    current_section_name = serializers.CharField(
        source="employee.organization.section.name",
        read_only=True,
        default=None,
    )

    current_location_name = serializers.CharField(
        source="employee.organization.location.name",
        read_only=True,
        default=None,
    )

    current_basic_salary = serializers.SerializerMethodField()

    # ------------------------------------------------------------------
    # Label nilai usulan
    # ------------------------------------------------------------------
    #
    # Generator FE memetakan kolom lookup ke `<field>_name` kalau
    # `display_key` kosong. Tanpa field di bawah, kolomnya tampil "-"
    # untuk semua baris tanpa satu pun pesan error.

    proposed_employment_type_name = serializers.CharField(
        source="proposed_employment_type.name",
        read_only=True,
        default=None,
    )

    proposed_employment_status_name = serializers.CharField(
        source="proposed_employment_status.name",
        read_only=True,
        default=None,
    )

    proposed_contract_type_name = serializers.CharField(
        source="proposed_contract_type.name",
        read_only=True,
        default=None,
    )

    proposed_probation_type_name = serializers.CharField(
        source="proposed_probation_type.name",
        read_only=True,
        default=None,
    )

    proposed_position_name = serializers.CharField(
        source="proposed_position.name",
        read_only=True,
        default=None,
    )

    proposed_reports_to_name = serializers.CharField(
        source="proposed_reports_to.full_name",
        read_only=True,
        default=None,
    )

    # Bentuknya sengaja disamakan dengan `approval` di Travel Request
    # dan `workflow` di Cuti supaya komponen jejak persetujuan di FE
    # dipakai ulang apa adanya.
    workflow = serializers.SerializerMethodField()

    class Meta:
        model = EmployeeAction
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "document_number",
            "status",
            "status_label",
            "action_type_label",
            "employee_name",
            "employee_number",
            "company",
            "branch",
            "location",
            "values_before",
            "values_after",
            "applied_at",
            "applied_by",
            "apply_error",
            "is_editable",
            "is_applied",
            "workflow",
        ]

    def get_current_basic_salary(self, obj) -> str | None:
        payroll = (
            obj.employee.payroll_assignments
            .filter(is_current=True, is_deleted=False)
            .first()
        )

        if payroll is None or payroll.basic_salary is None:
            return None

        return str(payroll.basic_salary)

    def get_workflow(self, obj) -> dict | None:
        """
        Keadaan persetujuan + kotak tanda tangan.

        Yang diambil pengajuan **terakhir**, bukan yang masih aktif:
        dokumen yang sudah disetujui tidak punya pengajuan aktif, dan
        justru itu yang harus terbaca di layar riwayat.
        """
        instance = WorkflowService.history_for(
            document=obj,
            module="hr",
            document_type="employee_action",
        ).first()

        if instance is None:
            return None

        rows = sorted(
            instance.approvals.all(),
            key=lambda row: (row.sequence, row.pk),
        )

        def approver_name(row):
            if row.approver_employee_id:
                return row.approver_employee.full_name

            if row.approver_id:
                return (
                    row.approver.get_full_name()
                    or row.approver.email
                )

            return None

        return {
            "instance_id": instance.pk,
            "status": instance.status,
            "status_label": instance.get_status_display(),
            "flow": instance.definition.name,
            "submitted_at": instance.submitted_at,
            "completed_at": instance.completed_at,
            "steps": [
                {
                    "sequence": row.sequence,
                    # Judul disalin ke barisnya sendiri saat pengajuan
                    # dibuat — kotak tanda tangan yang sudah tercetak
                    # tidak boleh berubah judulnya gara-gara step-nya
                    # dinamai ulang minggu depan.
                    "name": row.name,
                    "approver": approver_name(row),
                    "status": row.status,
                    "status_label": row.get_status_display(),
                    "is_pending": row.status == ApprovalStatus.PENDING,
                    "comment": row.comment,
                    "acted_at": row.acted_at,
                }
                for row in rows
            ],
        }
