from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import SalaryGradeViewSet


router = DefaultRouter()

router.register(
    "",
    SalaryGradeViewSet,
    basename="salary-grade",
)

urlpatterns = [
    path(
        "lookup/",
        include("apps.payroll.api.salary_grades.lookup.urls"),
    ),
    path(
        "",
        include(router.urls),
    ),
]