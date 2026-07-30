from apps.administration.models import Division


class DivisionService:
    @staticmethod
    def list():
        return (
            Division.objects.select_related(
                "company",
                "site",
            )
            .order_by("name")
        )