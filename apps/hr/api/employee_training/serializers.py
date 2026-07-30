from rest_framework import serializers

from apps.hr.models import EmployeeTraining


class EmployeeTrainingSerializer(
    serializers.ModelSerializer,
):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    training_category_name = serializers.CharField(
        source="training_category.name",
        read_only=True,
        default=None,
    )

    provider_name = serializers.CharField(
        source="provider.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = EmployeeTraining
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

        expiry_date = attrs.get(
            "expiry_date",
            getattr(instance, "expiry_date", None),
        )

        duration_hours = attrs.get(
            "duration_hours",
            getattr(instance, "duration_hours", None),
        )

        score = attrs.get(
            "score",
            getattr(instance, "score", None),
        )

        errors = {}

        if (
            start_date
            and end_date
            and end_date < start_date
        ):
            errors["end_date"] = (
                "End Date tidak boleh lebih awal "
                "dari Start Date."
            )

        if (
            end_date
            and expiry_date
            and expiry_date < end_date
        ):
            errors["expiry_date"] = (
                "Expiry Date tidak boleh lebih awal "
                "dari End Date."
            )

        if (
            duration_hours is not None
            and duration_hours < 0
        ):
            errors["duration_hours"] = (
                "Duration Hours tidak boleh negatif."
            )

        if score is not None and score < 0:
            errors["score"] = (
                "Score tidak boleh negatif."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs