from rest_framework import serializers

from apps.hr.models import EmploymentAssignment


class EmploymentAssignmentSerializer(
    serializers.ModelSerializer,
):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    employment_status_name = serializers.CharField(
        source="employment_status.name",
        read_only=True,
        default=None,
    )

    employment_type_name = serializers.CharField(
        source="employment_type.name",
        read_only=True,
        default=None,
    )

    employee_group_name = serializers.CharField(
        source="employee_group.name",
        read_only=True,
        default=None,
    )

    contract_type_name = serializers.CharField(
        source="contract_type.name",
        read_only=True,
        default=None,
    )

    probation_type_name = serializers.CharField(
        source="probation_type.name",
        read_only=True,
        default=None,
    )

    termination_reason_name = serializers.CharField(
        source="termination_reason.name",
        read_only=True,
        default=None,
    )

    work_schedule_name = serializers.CharField(
        source="work_schedule.name",
        read_only=True,
        default=None,
    )

    working_calendar_name = serializers.CharField(
        source="working_calendar.name",
        read_only=True,
        default=None,
    )

    shift_name = serializers.CharField(
        source="shift.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = EmploymentAssignment
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

        join_date = attrs.get(
            "join_date",
            getattr(instance, "join_date", None),
        )

        employment_effective_date = attrs.get(
            "employment_effective_date",
            getattr(
                instance,
                "employment_effective_date",
                None,
            ),
        )

        confirmation_date = attrs.get(
            "confirmation_date",
            getattr(instance, "confirmation_date", None),
        )

        probation_type = attrs.get(
            "probation_type",
            getattr(instance, "probation_type", None),
        )

        probation_start = attrs.get(
            "probation_start",
            getattr(instance, "probation_start", None),
        )

        probation_end = attrs.get(
            "probation_end",
            getattr(instance, "probation_end", None),
        )

        contract_type = attrs.get(
            "contract_type",
            getattr(instance, "contract_type", None),
        )

        contract_start = attrs.get(
            "contract_start",
            getattr(instance, "contract_start", None),
        )

        contract_end = attrs.get(
            "contract_end",
            getattr(instance, "contract_end", None),
        )

        termination_date = attrs.get(
            "termination_date",
            getattr(instance, "termination_date", None),
        )

        termination_reason = attrs.get(
            "termination_reason",
            getattr(instance, "termination_reason", None),
        )

        retirement_date = attrs.get(
            "retirement_date",
            getattr(instance, "retirement_date", None),
        )

        errors: dict[str, str] = {}

        if (
            employment_effective_date
            and join_date
            and employment_effective_date < join_date
        ):
            errors["employment_effective_date"] = (
                "Employment Effective Date tidak boleh "
                "lebih awal dari Join Date."
            )

        if (
            confirmation_date
            and join_date
            and confirmation_date < join_date
        ):
            errors["confirmation_date"] = (
                "Confirmation Date tidak boleh lebih awal "
                "dari Join Date."
            )

        if probation_start and not probation_end:
            errors["probation_end"] = (
                "Probation End wajib diisi."
            )

        if probation_end and not probation_start:
            errors["probation_start"] = (
                "Probation Start wajib diisi."
            )

        if (
            probation_start
            and probation_end
            and probation_end < probation_start
        ):
            errors["probation_end"] = (
                "Probation End tidak boleh lebih awal "
                "dari Probation Start."
            )

        if (
            probation_type
            and (
                not probation_start
                or not probation_end
            )
        ):
            errors["probation_type"] = (
                "Probation Start dan Probation End "
                "wajib diisi jika Probation Type dipilih."
            )

        if contract_start and not contract_end:
            errors["contract_end"] = (
                "Contract End wajib diisi."
            )

        if contract_end and not contract_start:
            errors["contract_start"] = (
                "Contract Start wajib diisi."
            )

        if (
            contract_start
            and contract_end
            and contract_end < contract_start
        ):
            errors["contract_end"] = (
                "Contract End tidak boleh lebih awal "
                "dari Contract Start."
            )

        if (
            (
                contract_start
                or contract_end
            )
            and not contract_type
        ):
            errors["contract_type"] = (
                "Contract Type wajib dipilih jika "
                "Contract Start atau Contract End diisi."
            )

        if (
            termination_date
            and join_date
            and termination_date < join_date
        ):
            errors["termination_date"] = (
                "Termination Date tidak boleh lebih awal "
                "dari Join Date."
            )

        if termination_reason and not termination_date:
            errors["termination_date"] = (
                "Termination Date wajib diisi jika "
                "Termination Reason dipilih."
            )

        if termination_date and not termination_reason:
            errors["termination_reason"] = (
                "Termination Reason wajib diisi jika "
                "Termination Date diisi."
            )

        if (
            retirement_date
            and join_date
            and retirement_date < join_date
        ):
            errors["retirement_date"] = (
                "Retirement Date tidak boleh lebih awal "
                "dari Join Date."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs