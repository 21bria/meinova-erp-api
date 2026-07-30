from rest_framework import serializers

from apps.hr.models import EmployeeMedicalEvent


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
        ]

    def validate(self, attrs):
        instance = self.instance

        event_date = attrs.get(
            "event_date",
            getattr(instance, "event_date", None),
        )

        next_due_date = attrs.get(
            "next_due_date",
            getattr(instance, "next_due_date", None),
        )

        fitness_status = attrs.get(
            "fitness_status",
            getattr(
                instance,
                "fitness_status",
                EmployeeMedicalEvent.FitnessStatus.NOT_APPLICABLE,
            ),
        )

        restriction_notes = attrs.get(
            "restriction_notes",
            getattr(instance, "restriction_notes", ""),
        )

        errors = {}

        if (
            event_date
            and next_due_date
            and next_due_date < event_date
        ):
            errors["next_due_date"] = (
                "Next Due Date tidak boleh lebih awal "
                "dari Event Date."
            )

        if (
            fitness_status
            == EmployeeMedicalEvent.FitnessStatus.FIT_WITH_RESTRICTION
            and not str(restriction_notes or "").strip()
        ):
            errors["restriction_notes"] = (
                "Restriction Notes wajib diisi jika status "
                "Fit With Restriction."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs