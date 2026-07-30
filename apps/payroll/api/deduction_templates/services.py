from apps.payroll.models import DeductionTemplate


class DeductionTemplateService:
    @staticmethod
    def list():
        return DeductionTemplate.objects.order_by("code")