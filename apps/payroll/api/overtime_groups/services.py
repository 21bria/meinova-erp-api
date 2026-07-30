from apps.payroll.models import OvertimeGroup


class OvertimeGroupService:
    @staticmethod
    def list():
        return OvertimeGroup.objects.order_by("code")
