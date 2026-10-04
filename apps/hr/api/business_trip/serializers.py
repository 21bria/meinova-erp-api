from __future__ import annotations

from rest_framework import serializers

from apps.hr.api.constants import AUDIT_READ_ONLY_FIELDS
from apps.hr.models import BusinessTrip, BusinessTripLeg, Employee
from apps.uploads.api.attach import guard_attachment
from apps.uploads.api.serializers import UploadedFileSerializer
from apps.uploads.models import UploadedFile
from apps.workflow.models import ApprovalStatus
from apps.workflow.services import WorkflowApprovalService, WorkflowService

from .overlap import trip_dates


# Kolom yang ditulis service dan hanya dibaca klien. Status dan jejak
# waktunya berpindah **hanya** lewat aksi — kalau kolomnya bisa dikirim
# form, siapa pun yang menembak API langsung bisa menulis `approved`.
SERVICE_OWNED_FIELDS = [
    "document_number",
    "requester",
    "company",
    "branch",
    "location",
    "division",
    "department",
    "section",
    "position",
    "cost_center",
    "status",
    "submitted_at",
    "approved_at",
    "rejected_at",
    "departed_at",
    "completed_at",
    "cancelled_at",
    "cancelled_by",
    "cancellation_reason",
    "actual_departure_datetime",
    "actual_return_datetime",
]


def _name(source: str):
    return serializers.CharField(source=source, read_only=True, default=None)


class BusinessTripLegSerializer(serializers.ModelSerializer):
    direction_label = serializers.CharField(
        source="get_direction_display",
        read_only=True,
    )

    transport_mode_name = _name("transport_mode.name")
    accommodation_type_name = _name("accommodation_type.name")

    class Meta:
        model = BusinessTripLeg
        fields = "__all__"
        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "direction_label",
            "transport_mode_name",
            "accommodation_type_name",
        ]


class BusinessTripSerializer(serializers.ModelSerializer):
    # Kosong = diisi service dari akun yang mengetik (pegawai mengajukan
    # untuk dirinya sendiri). Wajib `required=False`: kalau tidak, DRF
    # menolak sebelum service sempat mengisinya.
    employee = serializers.PrimaryKeyRelatedField(
        queryset=Employee.objects.filter(is_deleted=False),
        required=False,
    )

    supersedes = serializers.PrimaryKeyRelatedField(
        queryset=BusinessTrip.objects.filter(is_deleted=False),
        required=False,
        allow_null=True,
    )

    attachment = serializers.PrimaryKeyRelatedField(
        queryset=UploadedFile.objects.active(),
        required=False,
        allow_null=True,
    )

    attachment_detail = UploadedFileSerializer(
        source="attachment",
        read_only=True,
    )

    employee_name = _name("employee.full_name")
    employee_number = _name("employee.employee_number")
    requester_name = _name("requester.full_name")

    company_name = _name("company.name")
    branch_name = _name("branch.name")
    location_name = _name("location.name")
    division_name = _name("division.name")
    department_name = _name("department.name")
    section_name = _name("section.name")
    position_name = _name("position.name")
    cost_center_name = _name("cost_center.name")

    origin_location_name = _name("origin_location.name")
    destination_location_name = _name("destination_location.name")
    destination_city_name = _name("destination_city.name")
    destination_country_name = _name("destination_country.name")

    supersedes_number = _name("supersedes.document_number")

    # Satu teks tujuan untuk kolom daftar (BT-5) — lokasi perusahaan,
    # atau kota/negara, plus keterangan bebas.
    destination_summary = serializers.SerializerMethodField()

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    purpose_category_label = serializers.CharField(
        source="get_purpose_category_display",
        read_only=True,
    )

    destination_type_label = serializers.CharField(
        source="get_destination_type_display",
        read_only=True,
    )

    supersede_type_label = serializers.CharField(
        source="get_supersede_type_display",
        read_only=True,
    )

    is_editable = serializers.BooleanField(read_only=True)

    departure_date = serializers.SerializerMethodField()
    return_date = serializers.SerializerMethodField()

    # Blok detail — tidak dihitung di daftar (lihat `_is_detail`).
    legs = serializers.SerializerMethodField()
    approval = serializers.SerializerMethodField()
    superseded_by = serializers.SerializerMethodField()

    class Meta:
        model = BusinessTrip
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + SERVICE_OWNED_FIELDS

        # Diisi service (hari ini, jam dinding) kalau tidak dikirim —
        # tanpa ini DRF menolak sebelum service sempat mengisinya.
        extra_kwargs = {"request_date": {"required": False}}

    @property
    def _is_detail(self) -> bool:
        return self.parent is None

    def get_destination_summary(self, obj) -> str:
        place = (
            getattr(obj.destination_location, "name", None)
            or ", ".join(
                value
                for value in (
                    getattr(obj.destination_city, "name", None),
                    getattr(obj.destination_country, "name", None),
                )
                if value
            )
        )

        parts = [part for part in (place, obj.destination_detail) if part]

        return " — ".join(parts)

    def get_departure_date(self, obj):
        if obj.departure_datetime is None or obj.return_datetime is None:
            return None

        return trip_dates(obj)[0]

    def get_return_date(self, obj):
        if obj.departure_datetime is None or obj.return_datetime is None:
            return None

        return trip_dates(obj)[1]

    def get_legs(self, obj):
        if not self._is_detail or obj.pk is None:
            return None

        return BusinessTripLegSerializer(
            obj.legs.filter(is_deleted=False).order_by("sequence", "id"),
            many=True,
        ).data

    def get_superseded_by(self, obj):
        if not self._is_detail or obj.pk is None:
            return None

        return [
            {
                "id": row.pk,
                "document_number": row.document_number,
                "supersede_type": row.supersede_type,
                "status": row.status,
            }
            for row in obj.superseded_by.filter(is_deleted=False).order_by("id")
        ]

    def get_approval(self, obj) -> dict | None:
        """Bentuknya sama dengan `approval` di Attendance Permission."""
        if not self._is_detail or obj.pk is None:
            return None

        workflow = WorkflowService.history_for(
            document=obj,
            module="hr",
            document_type="business_trip",
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
                }
                for row in rows
            ],
        }

    def validate(self, attrs):
        # Lampiran: aktif, milik yang menempel, belum dipakai dokumen
        # lain — aturan `FileAccessService`, sama dengan Cuti dan Izin.
        guard_attachment(self, "attachment", attrs)

        return attrs
