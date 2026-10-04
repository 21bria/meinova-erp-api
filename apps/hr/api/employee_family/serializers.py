from django.utils import timezone
from rest_framework import serializers

from apps.hr.models import EmployeeFamily


class EmployeeFamilySerializer(
    serializers.ModelSerializer,
):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    relationship_name = serializers.CharField(
        source="relationship.name",
        read_only=True,
        default=None,
    )

    gender_name = serializers.CharField(
        source="gender.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = EmployeeFamily
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

        employee = attrs.get(
            "employee",
            getattr(instance, "employee", None),
        )

        relationship = attrs.get(
            "relationship",
            getattr(instance, "relationship", None),
        )

        name = attrs.get(
            "name",
            getattr(instance, "name", None),
        )

        birth_date = attrs.get(
            "birth_date",
            getattr(instance, "birth_date", None),
        )

        errors = {}

        normalized_name = str(
            name or "",
        ).strip()

        if not normalized_name:
            errors["name"] = (
                "Name is required."
            )

        if (
            birth_date
            and birth_date > timezone.localdate()
        ):
            errors["birth_date"] = (
                "Birth Date cannot be in the future."
            )

        if (
            employee
            and relationship
            and normalized_name
        ):
            queryset = EmployeeFamily.objects.filter(
                employee=employee,
                relationship=relationship,
                name__iexact=normalized_name,
                is_deleted=False,
            )

            if instance:
                queryset = queryset.exclude(
                    pk=instance.pk,
                )

            if queryset.exists():
                errors["name"] = (
                    "This family member already exists "
                    "for this employee."
                )

        if errors:
            raise serializers.ValidationError(
                errors,
            )

        attrs["name"] = normalized_name

        return attrs