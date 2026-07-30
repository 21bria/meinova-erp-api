from apps.administration.models import Position


class PositionService:
    @staticmethod
    def list():
        return (
            Position.objects.select_related(
                "company",
                "branch",
                "site",
                "division",
                "department",
                "section",
                "job_category",
                "job_level",
                "reports_to",
            )
            .order_by("name")
        )