# apps/hr/api/employee_document/serializers.py

from rest_framework import serializers

from apps.hr.models import EmployeeDocument


class EmployeeDocumentSerializer(
    serializers.ModelSerializer,
):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    document_type_name = serializers.CharField(
        source="document_type.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = EmployeeDocument
        fields = "__all__"

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "deleted_at",
            "deleted_by",
            "is_deleted",
        ]

    def validate(self, attrs):
        instance = self.instance

        issue_date = attrs.get(
            "issue_date",
            getattr(instance, "issue_date", None),
        )

        expiry_date = attrs.get(
            "expiry_date",
            getattr(instance, "expiry_date", None),
        )

        if (
            issue_date
            and expiry_date
            and expiry_date < issue_date
        ):
            raise serializers.ValidationError({
                "expiry_date": (
                    "Expiry Date tidak boleh lebih awal "
                    "dari Issue Date."
                ),
            })

        return attrs