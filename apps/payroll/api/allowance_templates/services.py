from apps.payroll.models import AllowanceTemplate


class AllowanceTemplateService:
    @staticmethod
    def list():
        return AllowanceTemplate.objects.order_by("code")