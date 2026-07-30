from apps.administration.models import Site

class SiteService:
    @staticmethod
    def list():
        return (
            Site.objects.select_related(
                "company",
                "branch",
                "site_type",
                "country",
                "province",
                "city",
            )
            .order_by("name")
        )