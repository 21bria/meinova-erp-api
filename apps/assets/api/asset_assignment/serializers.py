from rest_framework import serializers

from apps.assets.api.capabilities import (
    CapabilityFieldsMixin,
    movement_document_capabilities,
)

from apps.assets.models import AssetAssignment, AssetCondition


class AssetAssignmentSerializer(CapabilityFieldsMixin, serializers.ModelSerializer):
    asset_code = serializers.CharField(source="asset.asset_code", read_only=True)
    asset_name = serializers.CharField(source="asset.name", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    source_location_name = serializers.CharField(
        source="source_location.name",
        read_only=True,
    )
    employee_name = serializers.CharField(
        source="employee.__str__",
        read_only=True,
        default=None,
    )
    department_name = serializers.CharField(
        source="department.name",
        read_only=True,
        default=None,
    )
    pic_employee_name = serializers.CharField(
        source="pic_employee.__str__",
        read_only=True,
        default=None,
    )
    location_name = serializers.CharField(source="location.name", read_only=True)
    facility_name = serializers.CharField(
        source="facility.name",
        read_only=True,
        default=None,
    )
    employee_company_name = serializers.CharField(
        source="employee_company.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = AssetAssignment

        # Eksplisit — kolom sistem, penghapusan, dan custody tidak pernah
        # bisa ditulis lewat API.
        fields = [
            "id",
            "document_number",
            "status",
            "company",
            "company_name",
            "asset",
            "asset_code",
            "asset_name",
            "source_custody",
            "source_location",
            "source_location_name",
            "target_custody_type",
            "employee",
            "employee_name",
            "department",
            "department_name",
            "pic_employee",
            "pic_employee_name",
            "location",
            "location_name",
            "facility",
            "facility_name",
            "employee_company",
            "employee_company_name",
            "employee_location",
            "employee_department",
            "is_cross_company",
            "cross_company_reason",
            "purpose",
            "notes",
            "handover_date",
            "handover_condition",
            "resulting_custody",
            "submitted_at",
            "approved_at",
            "rejected_at",
            "cancelled_at",
            "completed_at",
            "completed_by",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "document_number",
            "status",
            "company",
            "source_custody",
            "source_location",
            "employee_company",
            "employee_location",
            "employee_department",
            "is_cross_company",
            "handover_date",
            "handover_condition",
            "resulting_custody",
            "submitted_at",
            "approved_at",
            "rejected_at",
            "cancelled_at",
            "completed_at",
            "completed_by",
            "created_at",
            "updated_at",
        ]

        # Keunikan dan pemesanan dijaga service + constraint database.
        validators = []

    def record_capabilities(self, instance):
        # Tombol aksi di layar dokumen (ASSET-6): izin + sisi + status.
        return movement_document_capabilities(
            self.context.get("view"),
            instance,
            model_name="assetassignment",
        )


class NotesSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class CompleteSerializer(serializers.Serializer):
    handover_date = serializers.DateField(required=False, allow_null=True)
    condition = serializers.ChoiceField(
        choices=AssetCondition.choices,
        required=False,
        allow_blank=True,
        default="",
    )
    note = serializers.CharField(required=False, allow_blank=True, default="")
