from rest_framework import serializers

from apps.hr.models import EmployeeEducation


class EmployeeEducationSerializer(
    serializers.ModelSerializer,
):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    education_name = serializers.CharField(
        source="education.name",
        read_only=True,
        default=None,
    )

    degree_name = serializers.CharField(
        source="degree.name",
        read_only=True,
        default=None,
    )

    study_field_name = serializers.CharField(
        source="study_field.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = EmployeeEducation
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

        start_date = attrs.get(
            "start_date",
            getattr(instance, "start_date", None),
        )

        end_date = attrs.get(
            "end_date",
            getattr(instance, "end_date", None),
        )

        gpa = attrs.get(
            "gpa",
            getattr(instance, "gpa", None),
        )

        errors = {}

        if (
            start_date
            and end_date
            and end_date < start_date
        ):
            errors["end_date"] = (
              "End Date cannot be earlier" 
              "from Start Date."
            )

        if (
            gpa is not None
            and not (
                0 <= gpa <= 4
            )
        ):
            errors["gpa"] = (
               "GPA must be between 0.00 and 4.00."
            )

        if errors:
            raise serializers.ValidationError(
                errors,
            )

        return attrs