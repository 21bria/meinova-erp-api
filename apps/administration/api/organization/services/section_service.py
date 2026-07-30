from apps.administration.models import Section


class SectionService:
    @staticmethod
    def list():
        return (
            Section.objects.select_related(
                "company",
                "site",
                "division",
                "department",
            )
            .order_by("name")
        )