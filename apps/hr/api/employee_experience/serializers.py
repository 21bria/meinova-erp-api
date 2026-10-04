from rest_framework import serializers

from apps.hr.models import EmployeeExperience


class EmployeeExperienceSerializer(
    serializers.ModelSerializer,
):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    class Meta:
        model = EmployeeExperience
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

        is_current = attrs.get(
            "is_current",
            getattr(instance, "is_current", False),
        )

        last_salary = attrs.get(
            "last_salary",
            getattr(instance, "last_salary", None),
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

        if is_current and end_date:
            errors["end_date"] = (
                "End Date must be blank if the experience"
                "is still ongoing."
            )

        if (
            last_salary is not None
            and last_salary < 0
        ):
            errors["last_salary"] = (
                "Last Salary cannot be negative."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs