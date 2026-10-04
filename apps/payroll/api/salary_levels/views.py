from apps.framework.views.master import BaseMasterViewSet

from .serializers import SalaryLevelSerializer
from .services import SalaryLevelService


class SalaryLevelViewSet(BaseMasterViewSet):
    serializer_class = SalaryLevelSerializer
    service_class = SalaryLevelService

    framework_module = "payroll/salary-levels"
    schema_type = "crud"

    ordering = [
        "salary_grade__code",
        "code",
    ]

    search_fields = [
        "salary_grade__code",
        "salary_grade__name",
        "code",
        "name",
    ]

    filterset_fields = [
        "salary_grade",
        "is_active",
    ]

    ordering_fields = [
        "salary_grade__code",
        "salary_grade__name",
        "code",
        "name",
        "sequence",
        "minimum_salary",
        "maximum_salary",
        "is_active",
        "created_at",
    ]

    schema = {
        "endpoint": "/api/payroll/salary-levels/",
        "ui": {
            "editor": "dialog",
            "size": "lg",
        },
        "fields": {
            "salary_grade": {
                "lookup_endpoint": "/api/payroll/salary-grades/lookup/",
                "placement": "quick",
                "label": "Salary Grade",
                "required": True,
                "order": 10,
            },
            "code": {
                "label": "Level Code",
                "placeholder": "e.g. A1",
                "order": 20,
            },
            "name": {
                "label": "Level Name",
                "placeholder": "e.g. Junior Level",
                "order": 30,
            },
            "sequence": {
                "label": "Sequence",
                "placeholder": "e.g. 1",
                "order": 40,
            },
            "minimum_salary": {
                "label": "Minimum Salary",
                "placeholder": "e.g. 5000000",
                "order": 50,
            },
            "maximum_salary": {
                "label": "Maximum Salary",
                "placeholder": "e.g. 7500000",
                "order": 60,
            },
            "description": {
                "label": "Description",
                "widget": "textarea",
                "rows": 3,
                "layout": "full",
                "table": False,
                "order": 70,
            },
            "is_active": {
                "label": "Active",
                "placement": "quick",
                "order": 999,
            },
        },
    }