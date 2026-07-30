from apps.administration.models import Branch

class BranchService:
    @staticmethod
    def list():
        return (
            Branch.objects.select_related(
                "company",
                "country",
                "province",
                "city",
            )
            .order_by("name")
        )