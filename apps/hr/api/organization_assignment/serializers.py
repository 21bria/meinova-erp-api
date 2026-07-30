from rest_framework import serializers

from apps.hr.models import OrganizationAssignment


class OrganizationAssignmentSerializer(
    serializers.ModelSerializer,
):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    branch_name = serializers.CharField(
        source="branch.name",
        read_only=True,
        default=None,
    )

    site_name = serializers.CharField(
        source="site.name",
        read_only=True,
        default=None,
    )

    division_name = serializers.CharField(
        source="division.name",
        read_only=True,
        default=None,
    )

    department_name = serializers.CharField(
        source="department.name",
        read_only=True,
        default=None,
    )

    section_name = serializers.CharField(
        source="section.name",
        read_only=True,
        default=None,
    )

    position_name = serializers.CharField(
        source="position.name",
        read_only=True,
        default=None,
    )

    job_level_name = serializers.CharField(
        source="job_level.name",
        read_only=True,
        default=None,
    )

    job_grade_name = serializers.CharField(
        source="job_grade.name",
        read_only=True,
        default=None,
    )

    reports_to_name = serializers.CharField(
        source="reports_to.full_name",
        read_only=True,
        default=None,
    )

    cost_center_name = serializers.CharField(
        source="cost_center.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = OrganizationAssignment
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

        company = attrs.get(
            "company",
            getattr(instance, "company", None),
        )

        branch = attrs.get(
            "branch",
            getattr(instance, "branch", None),
        )

        site = attrs.get(
            "site",
            getattr(instance, "site", None),
        )

        division = attrs.get(
            "division",
            getattr(instance, "division", None),
        )

        department = attrs.get(
            "department",
            getattr(instance, "department", None),
        )

        section = attrs.get(
            "section",
            getattr(instance, "section", None),
        )

        position = attrs.get(
            "position",
            getattr(instance, "position", None),
        )

        reports_to = attrs.get(
            "reports_to",
            getattr(instance, "reports_to", None),
        )

        cost_center = attrs.get(
            "cost_center",
            getattr(instance, "cost_center", None),
        )

        errors = {}

        if (
            branch
            and company
            and branch.company_id != company.id
        ):
            errors["branch"] = (
                "Branch harus berasal dari company yang dipilih."
            )

        if (
            site
            and company
            and site.company_id != company.id
        ):
            errors["site"] = (
                "Site harus berasal dari company yang dipilih."
            )

        if (
            site
            and branch
            and site.branch_id
            and site.branch_id != branch.id
        ):
            errors["site"] = (
                "Site harus berasal dari branch yang dipilih."
            )

        if (
            division
            and company
            and division.company_id != company.id
        ):
            errors["division"] = (
                "Division harus berasal dari company yang dipilih."
            )

        if (
            division
            and site
            and division.site_id
            and division.site_id != site.id
        ):
            errors["division"] = (
                "Division harus berasal dari site yang dipilih."
            )

        if (
            department
            and company
            and department.company_id != company.id
        ):
            errors["department"] = (
                "Department harus berasal dari company yang dipilih."
            )

        if (
            department
            and division
            and department.division_id
            and department.division_id != division.id
        ):
            errors["department"] = (
                "Department harus berasal dari division yang dipilih."
            )

        if (
            section
            and company
            and section.company_id != company.id
        ):
            errors["section"] = (
                "Section harus berasal dari company yang dipilih."
            )

        if (
            section
            and department
            and section.department_id
            and section.department_id != department.id
        ):
            errors["section"] = (
                "Section harus berasal dari department yang dipilih."
            )

        if (
            position
            and company
            and position.company_id != company.id
        ):
            errors["position"] = (
                "Position harus berasal dari company yang dipilih."
            )

        if (
            position
            and section
            and position.section_id
            and position.section_id != section.id
        ):
            errors["position"] = (
                "Position harus berasal dari section yang dipilih."
            )

        if (
            reports_to
            and employee
            and reports_to.id == employee.id
        ):
            errors["reports_to"] = (
                "Employee tidak dapat melapor kepada dirinya sendiri."
            )

        if reports_to and company:
            try:
                supervisor_organization = reports_to.organization
            except OrganizationAssignment.DoesNotExist:
                supervisor_organization = None

            if (
                supervisor_organization
                and supervisor_organization.company_id
                != company.id
            ):
                errors["reports_to"] = (
                    "Reports To harus berasal dari company yang sama."
                )

        if (
            cost_center
            and company
            and cost_center.company_id != company.id
        ):
            errors["cost_center"] = (
                "Cost Center harus berasal dari company yang dipilih."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs