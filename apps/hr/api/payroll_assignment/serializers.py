from rest_framework import serializers

from apps.hr.models import PayrollAssignment


class PayrollAssignmentSerializer(
    serializers.ModelSerializer,
):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    payroll_group_name = serializers.CharField(
        source="payroll_group.name",
        read_only=True,
        default=None,
    )

    salary_grade_name = serializers.CharField(
        source="salary_grade.name",
        read_only=True,
        default=None,
    )

    salary_level_name = serializers.CharField(
        source="salary_level.name",
        read_only=True,
        default=None,
    )

    currency_code = serializers.CharField(
        source="currency.code",
        read_only=True,
        default=None,
    )

    currency_name = serializers.CharField(
        source="currency.name",
        read_only=True,
        default=None,
    )

    tax_status_name = serializers.CharField(
        source="tax_status.name",
        read_only=True,
        default=None,
    )

    overtime_group_name = serializers.CharField(
        source="overtime_group.name",
        read_only=True,
        default=None,
    )

    allowance_template_name = serializers.CharField(
        source="allowance_template.name",
        read_only=True,
        default=None,
    )

    deduction_template_name = serializers.CharField(
        source="deduction_template.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = PayrollAssignment
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
            "is_current",
        ]

    def validate(self, attrs):
        instance = self.instance

        effective_from = attrs.get(
            "effective_from",
            getattr(instance, "effective_from", None),
        )
        effective_to = attrs.get(
            "effective_to",
            getattr(instance, "effective_to", None),
        )

        salary_grade = attrs.get(
            "salary_grade",
            getattr(instance, "salary_grade", None),
        )
        salary_level = attrs.get(
            "salary_level",
            getattr(instance, "salary_level", None),
        )

        overtime_eligible = attrs.get(
            "overtime_eligible",
            getattr(instance, "overtime_eligible", False),
        )
        overtime_group = attrs.get(
            "overtime_group",
            getattr(instance, "overtime_group", None),
        )

        basic_salary = attrs.get(
            "basic_salary",
            getattr(instance, "basic_salary", None),
        )

        if (
            effective_from
            and effective_to
            and effective_to < effective_from
        ):
            raise serializers.ValidationError({
                "effective_to": (
                    "Effective To tidak boleh lebih awal "
                    "dari Effective From."
                ),
            })

        if (
            salary_grade
            and salary_level
            and hasattr(salary_level, "salary_grade_id")
            and salary_level.salary_grade_id
            != salary_grade.id
        ):
            raise serializers.ValidationError({
                "salary_level": (
                    "Salary Level harus berasal dari "
                    "Salary Grade yang dipilih."
                ),
            })

        if overtime_group and not overtime_eligible:
            raise serializers.ValidationError({
                "overtime_group": (
                    "Overtime Group hanya boleh dipilih "
                    "jika employee eligible overtime."
                ),
            })

        if basic_salary is not None and basic_salary < 0:
            raise serializers.ValidationError({
                "basic_salary": (
                    "Basic Salary tidak boleh bernilai negatif."
                ),
            })

        return attrs