from rest_framework import serializers

from apps.hr.models import EmployeeDocument
from apps.uploads.api.serializers import UploadedFileSerializer
from apps.uploads.models import UploadedFile


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

    uploaded_file = serializers.PrimaryKeyRelatedField(
        queryset=UploadedFile.objects.active(),
        required=False,
        allow_null=True,
    )

    uploaded_file_detail = UploadedFileSerializer(
        source="uploaded_file",
        read_only=True,
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
            "employee_name",
            "document_type_name",
            "uploaded_file_detail",
        ]

    def validate(self, attrs):
        instance = self.instance

        issue_date = attrs.get(
            "issue_date",
            getattr(
                instance,
                "issue_date",
                None,
            ),
        )

        expiry_date = attrs.get(
            "expiry_date",
            getattr(
                instance,
                "expiry_date",
                None,
            ),
        )

        is_required = attrs.get(
            "is_required",
            getattr(
                instance,
                "is_required",
                False,
            ),
        )

        current_uploaded_file = getattr(
            instance,
            "uploaded_file",
            None,
        )

        uploaded_file = attrs.get(
            "uploaded_file",
            current_uploaded_file,
        )

        errors = {}

        if (
            issue_date
            and expiry_date
            and expiry_date < issue_date
        ):
            errors["expiry_date"] = (
                "Expiry Date cannot be earlier "
                "than Issue Date."
            )

        if is_required and not uploaded_file:
            errors["uploaded_file"] = (
                "Attachment is required."
            )

        if errors:
            raise serializers.ValidationError(
                errors,
            )

        return attrs