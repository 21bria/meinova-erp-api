from apps.payroll.models import TaxStatus


class TaxStatusService:
    @staticmethod
    def list():
        return TaxStatus.objects.order_by("code")