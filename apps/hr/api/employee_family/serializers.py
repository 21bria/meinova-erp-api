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