from apps.administration.models import Company

class CompanyService:
    @staticmethod
    def list():
        return (
            Company.objects.select_related(
                "parent",
                "company_type",
                "country",
                "province",
                "city",
            )
            .order_by("name")
        )