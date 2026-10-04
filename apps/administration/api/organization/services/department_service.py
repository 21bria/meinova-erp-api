from apps.administration.models import Department


class DepartmentService:
    @staticmethod
    def list():
        return (
            Department.objects.select_related(
                "company",
                "location",
                "division",
            )
            .order_by("name")
        )