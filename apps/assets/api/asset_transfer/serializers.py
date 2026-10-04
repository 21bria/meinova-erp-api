from rest_framework import serializers

from apps.assets.api.capabilities import (
    CapabilityFieldsMixin,
    movement_document_capabilities,
)

from apps.assets.models import AssetCondition, AssetTransfer


def _name(source):
    return serializers.CharField(source=source, read_only=True, default=None)


class AssetTransferSerializer(CapabilityFieldsMixin, serializers.ModelSerializer):
    asset_code = serializers.CharField(source="asset.asset_code", read_only=True)
    asset_name = serializers.CharField(source="asset.name", read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)

    source_location_name = _name("source_location.name")
    source_facility_name = _name("source_facility.name")
    source_employee_name = _name("source_employee.__str__")
    source_department_name = _name("source_department.name")
    source_pic_employee_name = _name("source_pic_employee.__str__")

    target_employee_name = _name("target_employee.__str__")
    target_department_name = _name("target_department.name")
    target_pic_employee_name = _name("target_pic_employee.__str__")
    target_location_name = _name("target_location.name")
    target_facility_name = _name("target_facility.name")
    employee_company_name = _name("employee_company.name")

    class Meta:
        model = AssetTransfer

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
            "target_custody_type",
            "target_employee",
            "target_employee_name",
            "target_department",
            "target_department_name",
            "target_pic_employee",
            "target_pic_employee_name",
            "target_location",
            "target_location_name",
            "target_facility",
            "target_facility_name",
            "employee_company",
            "employee_company_name",
            "employee_location",
            "employee_department",
            "is_cross_company",
            "cross_company_reason",
            "reason",
            "notes",
            "transfer_date",
            "transfer_condition",
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
            "employee_company",
            "employee_location",
            "employee_department",
            "is_cross_company",
            "transfer_date",
            "transfer_condition",
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
            model_name="assettransfer",
        )


class NotesSerializer(serializers.Serializer):
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class CompleteTransferSerializer(serializers.Serializer):
    transfer_date = serializers.DateField(required=False, allow_null=True)
    # Wajib — kondisi saat dipindahkan selalu diketahui (service juga menolak).
    condition = serializers.ChoiceField(choices=AssetCondition.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="")
