from apps.administration.models import Location

class LocationService:
    @staticmethod
    def list():
        return (
            Location.objects.select_related(
                "company",
                "branch",
                "location_type",
                "country",
                "province",
                "city",
            )
            .order_by("name")
        )