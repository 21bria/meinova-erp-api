from rest_framework import serializers

from apps.assets.api.capabilities import (
    CapabilityFieldsMixin,
    movement_document_capabilities,
)

from apps.assets.models import AssetCondition, AssetReturn


class AssetReturnSerializer(CapabilityFieldsMixin, serializers.ModelSerializer):
    asset_code = serializers.CharField(source="asset.asset_code", read_only=True)
    asset_name = serializers.CharField(source="asset.name", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    source_location_name = serializers.CharField(
        source="source_location.name",
        read_only=True,
    )
    source_facility_name = serializers.CharField(
        source="source_facility.name",
        read_only=True,
        default=None,
    )
    source_employee_name = serializers.CharField(
        source="source_employee.__str__",
        read_only=True,
        default=None,
    )
    source_department_name = serializers.CharField(
        source="source_department.name",
        read_only=True,
        default=None,
    )
    source_pic_employee_name = serializers.CharField(
        source="source_pic_employee.__str__",
        read_only=True,
        default=None,
    )
    destination_location_name = serializers.CharField(
        source="destination_location.name",
        read_only=True,
    )
    destination_facility_name = serializers.CharField(
        source="destination_facility.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = AssetReturn

        # Eksplisit — asal, kolom sistem, penghapusan, dan custody tidak
        # pernah bisa ditulis lewat API.
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
            "source_custody_type",
            "source_location",
            "source_location_name",
            "source_facility",
            "source_facility_name",
            "source_employee",
            "source_employee_name",
            "source_department",
            "source_department_name",
            "source_pic_employee",
            "source_pic_employee_name",
            "destination_location",
            "destination_location_name",
            "destination_facility",
            "destination_facility_name",
            "reason",
            "notes",
            "return_date",
            "return_condition",
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
            "source_custody_type",
            "source_location",
            "source_facility",
            "source_employee",
            "source_department",
            "source_pic_employee",
            "return_date",
            "return_condition",
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

        # Pemesanan dan keunikan nomor dijaga service + constraint database.
        validators = []

    def record_capabilities(self, instance):
        # Tombol aksi di layar dokumen (ASSET-6): izin + sisi + status.
        return movement_document_capabilities(
            self.context.get("view"),
            instance,
            model_name="assetreturn",
        )


class NotesSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class CompleteReturnSerializer(serializers.Serializer):
    return_date = serializers.DateField(required=False, allow_null=True)
    # Wajib — kondisi saat kembali selalu diketahui (service menolak juga).
    condition = serializers.ChoiceField(choices=AssetCondition.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="")
