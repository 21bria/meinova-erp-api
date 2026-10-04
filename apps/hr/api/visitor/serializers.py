"""
Serializer Visitor Management.

Satu pola yang berulang di seluruh berkas ini dan gampang terlewat:
setiap kolom lookup yang muncul di tabel **wajib** punya pasangan
`<field>_name`. Generator FE memetakan kolom lookup ke nama itu, dan
serializer yang cuma `fields = "__all__"` tidak pernah mengirimnya —
hasilnya kolom "-" di semua baris, tanpa satu pun pesan error.
"""

from rest_framework import serializers

from apps.hr.api.constants import AUDIT_READ_ONLY_FIELDS
from apps.hr.api.visitor.services import INTERNAL_VISITOR_REJECTED
from apps.hr.models import (
    Employee,
    ExternalVisitor,
    VisitorPass,
    VisitorRequest,
    VisitorType,
)
from apps.workflow.models import ApprovalStatus
from apps.workflow.services import (
    WorkflowApprovalService,
    WorkflowService,
)


class ExternalVisitorSerializer(serializers.ModelSerializer):
    identity_type_label = serializers.CharField(
        source="get_identity_type_display",
        read_only=True,
    )

    gender_name = serializers.CharField(
        source="gender.name",
        read_only=True,
        default=None,
    )

    nationality_name = serializers.CharField(
        source="nationality.name",
        read_only=True,
        default=None,
    )

    city_name = serializers.CharField(
        source="city.name",
        read_only=True,
        default=None,
    )

    country_name = serializers.CharField(
        source="country.name",
        read_only=True,
        default=None,
    )

    # Terisi service dari deret hr/external_visitor. Read-only supaya
    # tidak ada yang mengetik nomor yang sudah dipakai tamu lain.
    visitor_number = serializers.CharField(read_only=True)

    # Properti model, bukan `SerializerMethodField`: export CSV membaca
    # instance dan bukan serializer, jadi kolom yang hanya ada di sini
    # akan kosong di seluruh baris CSV tanpa satu pun pesan.
    visit_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = ExternalVisitor
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "visitor_number",
            "identity_type_label",
            "gender_name",
            "nationality_name",
            "city_name",
            "country_name",
            "visit_count",
        ]


class VisitorPassSerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    request_number = serializers.CharField(
        source="request.document_number",
        read_only=True,
        default=None,
    )

    visitor_name = serializers.CharField(
        source="request.visitor_name",
        read_only=True,
        default=None,
    )

    visitor_type_label = serializers.CharField(
        source="request.get_visitor_type_display",
        read_only=True,
        default=None,
    )

    host_name = serializers.CharField(
        source="request.host_employee.full_name",
        read_only=True,
        default=None,
    )

    location_name = serializers.CharField(
        source="request.location.name",
        read_only=True,
        default=None,
    )

    visit_date = serializers.DateField(
        source="request.visit_start_date",
        read_only=True,
        default=None,
    )

    pass_number = serializers.CharField(read_only=True)

    # Diisi service saat kartu diterbitkan. Dibiarkan bisa ditulis
    # akan memungkinkan orang mengetik jam terbit yang tidak pernah
    # terjadi ke kartu yang dipegang orang lain.
    valid_from = serializers.DateField(required=False)
    valid_until = serializers.DateField(required=False)

    class Meta:
        model = VisitorPass
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "pass_number",
            "status_label",
            "request_number",
            "visitor_name",
            "visitor_type_label",
            "host_name",
            "location_name",
            "visit_date",
            "issued_at",
            "issued_by",
            "returned_at",
            "returned_by",
        ]


class VisitorRequestSerializer(serializers.ModelSerializer):
    # ------------------------------------------------------------------
    # Label
    # ------------------------------------------------------------------

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    visitor_type_label = serializers.CharField(
        source="get_visitor_type_display",
        read_only=True,
    )

    arrival_status_label = serializers.CharField(
        source="get_arrival_status_display",
        read_only=True,
    )

    # ------------------------------------------------------------------
    # Tamu — satu pasang kolom untuk dua sumber
    # ------------------------------------------------------------------
    #
    # Tabel daftar tidak boleh punya dua kolom nama tamu yang salah
    # satunya selalu kosong. Jadi nama, perusahaan, dan kontaknya
    # diturunkan dari sumber yang sesuai jenis kunjungannya, dan
    # layarnya cukup membaca satu kunci.

    visitor_name = serializers.CharField(read_only=True)
    visitor_organization = serializers.CharField(read_only=True)

    visitor_identity = serializers.SerializerMethodField()
    visitor_contact = serializers.SerializerMethodField()

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

    employee_department = serializers.CharField(
        source="employee.organization.department.name",
        read_only=True,
        default=None,
    )

    employee_position = serializers.CharField(
        source="employee.organization.position.name",
        read_only=True,
        default=None,
    )

    employee_location = serializers.CharField(
        source="employee.organization.location.name",
        read_only=True,
        default=None,
    )

    external_visitor_name = serializers.CharField(
        source="external_visitor.full_name",
        read_only=True,
        default=None,
    )

    external_visitor_number = serializers.CharField(
        source="external_visitor.visitor_number",
        read_only=True,
        default=None,
    )

    external_visitor_organization = serializers.CharField(
        source="external_visitor.organization_name",
        read_only=True,
        default=None,
    )

    # ------------------------------------------------------------------
    # Pemohon & tuan rumah
    # ------------------------------------------------------------------

    requester_name = serializers.CharField(
        source="requester.full_name",
        read_only=True,
        default=None,
    )

    requester_department = serializers.CharField(
        source="requester.organization.department.name",
        read_only=True,
        default=None,
    )

    host_name = serializers.CharField(
        source="host_employee.full_name",
        read_only=True,
        default=None,
    )

    host_department = serializers.CharField(
        source="host_employee.organization.department.name",
        read_only=True,
        default=None,
    )

    host_position = serializers.CharField(
        source="host_employee.organization.position.name",
        read_only=True,
        default=None,
    )

    host_contact = serializers.SerializerMethodField()

    # ------------------------------------------------------------------
    # Relasi lain
    # ------------------------------------------------------------------

    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    branch_name = serializers.CharField(
        source="branch.name",
        read_only=True,
        default=None,
    )

    location_name = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )

    visit_purpose_name = serializers.CharField(
        source="visit_purpose.name",
        read_only=True,
        default=None,
    )

    visit_type_name = serializers.CharField(
        source="visit_type.name",
        read_only=True,
        default=None,
    )

    transport_mode_name = serializers.CharField(
        source="transport_mode.name",
        read_only=True,
        default=None,
    )

    accommodation_type_name = serializers.CharField(
        source="accommodation_type.name",
        read_only=True,
        default=None,
    )

    checked_in_by_name = serializers.SerializerMethodField()
    checked_out_by_name = serializers.SerializerMethodField()

    expected_duration_days = serializers.IntegerField(read_only=True)

    # Boleh dikosongkan supaya service bisa mengisinya dari penempatan
    # pemohon. Kalau dibiarkan `required` bawaan model, DRF menolak
    # lebih dulu dan jalur pengisian otomatisnya tidak pernah kepakai.
    request_date = serializers.DateField(required=False)

    # Dikosongkan = diisi service dari akun yang mengetik. Wajib
    # `required=False` di sini: kalau dibiarkan required bawaan model,
    # DRF menolak sebelum service sempat jalan, dan pengisian
    # otomatisnya tidak pernah kepakai. Jebakan yang sama dengan
    # `location` di Roster Setup.
    requester = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.filter(is_deleted=False),
        required=False,
    )

    current_pass = serializers.SerializerMethodField()
    pass_count = serializers.SerializerMethodField()

    approval = serializers.SerializerMethodField()

    class Meta:
        model = VisitorRequest
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "document_number",
            "status_label",
            "visitor_type_label",
            "arrival_status_label",
            "visitor_name",
            "visitor_organization",
            "visitor_identity",
            "visitor_contact",
            "employee_name",
            "employee_number",
            "employee_department",
            "employee_position",
            "employee_location",
            "external_visitor_name",
            "external_visitor_number",
            "external_visitor_organization",
            "requester_name",
            "requester_department",
            "host_name",
            "host_department",
            "host_position",
            "host_contact",
            "company_name",
            "branch_name",
            "location_name",
            "visit_purpose_name",
            "visit_type_name",
            "transport_mode_name",
            "accommodation_type_name",
            "checked_in_by_name",
            "checked_out_by_name",
            "expected_duration_days",
            "current_pass",
            "pass_count",
            "approval",

            # Berpindah lewat tombol Submit/Approve/Check-in, bukan
            # lewat form. Dibiarkan bisa ditulis akan memungkinkan
            # orang menandai kunjungannya sendiri "Approved" lalu
            # check-in tanpa satu pun tanda tangan.
            "status",
            "arrival_status",
            "checked_in_at",
            "checked_in_by",
            "checked_out_at",
            "checked_out_by",
        ]

    # ------------------------------------------------------------------
    # Turunan
    # ------------------------------------------------------------------

    def get_visitor_identity(self, obj) -> str | None:
        if obj.visitor_type == VisitorType.INTERNAL:
            return obj.employee.employee_number if obj.employee_id else None

        if not obj.external_visitor_id:
            return None

        visitor = obj.external_visitor

        return (
            f"{visitor.get_identity_type_display()} "
            f"{visitor.identity_number}".strip()
            if visitor.identity_number
            else None
        )

    def get_visitor_contact(self, obj) -> str | None:
        if obj.visitor_type == VisitorType.INTERNAL:
            if not obj.employee_id:
                return None

            employee = obj.employee

            return employee.mobile or employee.phone or employee.work_email or None

        if not obj.external_visitor_id:
            return None

        visitor = obj.external_visitor

        return visitor.mobile or visitor.phone or visitor.email or None

    def get_host_contact(self, obj) -> str | None:
        if not obj.host_employee_id:
            return None

        host = obj.host_employee

        return host.mobile or host.phone or host.work_email or None

    def _user_name(self, user) -> str | None:
        if user is None:
            return None

        return user.get_full_name() or user.username

    def get_checked_in_by_name(self, obj) -> str | None:
        return self._user_name(obj.checked_in_by)

    def get_checked_out_by_name(self, obj) -> str | None:
        return self._user_name(obj.checked_out_by)

    def _passes(self, obj) -> list:
        return [row for row in obj.passes.all() if not row.is_deleted]

    def get_pass_count(self, obj) -> int:
        return len(self._passes(obj))

    def get_current_pass(self, obj) -> dict | None:
        """
        Kartu yang sedang dipegang tamunya.

        Disaring di Python dari hasil prefetch, bukan lewat query per
        baris — daftar kunjungan lazim seratus baris, dan satu query
        per baris membuat layarnya terasa rusak tanpa ada yang bisa
        menunjuk sebabnya.
        """
        current = next(
            (row for row in self._passes(obj) if row.is_open),
            None,
        )

        if current is None:
            return None

        return {
            "id": current.pk,
            "pass_number": current.pass_number,
            "valid_from": current.valid_from,
            "valid_until": current.valid_until,
            "issued_at": current.issued_at,
        }

    def get_approval(self, obj) -> dict | None:
        """
        Keadaan persetujuan + baris tanda tangan.

        Bentuknya **sengaja sama persis** dengan `approval` di Travel
        Request dan `workflow` di Cuti: komponen jejak persetujuan di
        frontend dipakai ulang apa adanya, dan bentuk yang berbeda
        sedikit berarti satu komponen lagi yang harus dijaga tetap sama.

        Yang diambil pengajuan **terakhir**, bukan yang aktif saja:
        dokumen yang sudah disetujui tidak punya pengajuan aktif, tapi
        justru itu yang harus tercetak di kaki formulir.
        """
        workflow = WorkflowService.history_for(
            document=obj,
            module="hr",
            document_type="visitor_request",
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
            # Dihitung, bukan ditebak dari status: menunggu persetujuan
            # orang lain dan menunggu persetujuan Anda sendiri terlihat
            # sama dari kolom status.
            "can_act": (
                current is not None
                and WorkflowApprovalService.can_act(
                    approval=current,
                    user=user,
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
                    "acted_by": (
                        (row.acted_by.get_full_name() or row.acted_by.email)
                        if row.was_delegated
                        else None
                    ),
                }
                for row in rows
            ],
        }

    # ------------------------------------------------------------------
    # Validasi
    # ------------------------------------------------------------------

    def validate(self, attrs):
        """
        BR-01…BR-03 dinilai di sini supaya pesannya menempel di kolom
        yang salah, bukan muncul sebagai error dokumen.

        `full_clean()` tetap memeriksa hal yang sama — ini bukan
        penggantinya. Yang dijaga di sini urutannya: `clean_fields()`
        berjalan lebih dulu dan pesan bawaannya ("This field cannot be
        null") muncul sebagai error pertama, dan itu yang ditampilkan
        form.
        """
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        errors = {}

        visitor_type = resolved("visitor_type")

        # BT-2A: pesan yang sama dengan service (sumber aturannya).
        if visitor_type == VisitorType.INTERNAL:
            errors["visitor_type"] = INTERNAL_VISITOR_REJECTED

        elif visitor_type == VisitorType.EXTERNAL:
            if resolved("external_visitor") is None:
                errors["external_visitor"] = (
                    "External Visitor wajib dipilih. Buat dulu datanya "
                    "di Visitor Master kalau tamunya belum terdaftar."
                )

        start = resolved("visit_start_date")
        end = resolved("visit_end_date")

        if start and end and end < start:
            errors["visit_end_date"] = (
                "Visit End tidak boleh lebih awal dari Visit Start."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
