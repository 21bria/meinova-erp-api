# services.py
from apps.payroll.models import PayrollGroup


class PayrollGroupService:
    @staticmethod
    def list():
        return PayrollGroup.objects.all().order_by("name")