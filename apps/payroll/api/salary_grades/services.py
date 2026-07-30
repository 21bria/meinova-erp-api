from apps.payroll.models import SalaryGrade


class SalaryGradeService:
    @staticmethod
    def list():
        return SalaryGrade.objects.order_by("code")  