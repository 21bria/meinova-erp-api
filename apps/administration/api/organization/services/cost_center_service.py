from apps.administration.models import CostCenter


class CostCenterService:
    @staticmethod
    def list():
        return (
            CostCenter.objects.select_related(
                "company",
                "location",
            )
            .order_by("name")
        )