from apps.payroll.models import SalaryLevel


class SalaryLevelService:
    @staticmethod
    def list():
        return (
            SalaryLevel.objects
            .select_related("salary_grade")
            .order_by(
                "salary_grade__name",
                "code",
            )
        )