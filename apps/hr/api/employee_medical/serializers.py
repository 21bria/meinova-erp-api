from rest_framework import serializers

from apps.hr.models import EmployeeMedicalEvent
from apps.uploads.api.serializers import UploadedFileSerializer
from apps.uploads.models import UploadedFile


class EmployeeMedicalEventSerializer(
    serializers.ModelSerializer,
):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    medical_type_label = serializers.CharField(
        source="get_medical_type_display",
        read_only=True,
    )

    fitness_status_label = serializers.CharField(
        source="get_fitness_status_display",
        read_only=True,
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
        model = EmployeeMedicalEvent
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
            "medical_type_label",
            "fitness_status_label",
            "uploaded_file_detail",
        ]

    def validate(self, attrs):
        instance = self.instance

        event_date = attrs.get(
            "event_date",
            getattr(
                instance,
                "event_date",
                None,
            ),
        )

        next_due_date = attrs.get(
            "next_due_date",
            getattr(
                instance,
                "next_due_date",
                None,
            ),
        )

        fitness_status = attrs.get(
            "fitness_status",
            getattr(
                instance,
                "fitness_status",
                EmployeeMedicalEvent
                .FitnessStatus
                .NOT_APPLICABLE,
            ),
        )

        restriction_notes = attrs.get(
            "restriction_notes",
            getattr(
                instance,
                "restriction_notes",
                "",
            ),
        )

        errors = {}

        if (
            event_date
            and next_due_date
            and next_due_date < event_date
        ):
            errors["next_due_date"] = (
                "The next due date cannot be earlier "
                "than the event date."
            )

        if (
            fitness_status
            == EmployeeMedicalEvent
            .FitnessStatus
            .FIT_WITH_RESTRICTION
            and not str(
                restriction_notes or "",
            ).strip()
        ):
            errors["restriction_notes"] = (
                "Restriction Notes must be filled in "
                "if the status is Fit With Restrictions."
            )

        if errors:
            raise serializers.ValidationError(
                errors,
            )

        return attrs