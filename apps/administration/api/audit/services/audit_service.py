from apps.administration.models import AuditTrail


class AuditTrailService:
    @staticmethod
    def list():
        return AuditTrail.objects.select_related(
            "company",
            "site",
            "user",
        ).order_by("-created_at")