from rest_framework import serializers

from apps.payroll.models import SalaryLevel


class SalaryLevelSerializer(serializers.ModelSerializer):
    salary_grade_name = serializers.CharField(
        source="salary_grade.name",
        read_only=True,
    )

    class Meta:
        model = SalaryLevel
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