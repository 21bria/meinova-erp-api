from django.urls import path,include
from rest_framework.routers import DefaultRouter

from .views import SalaryLevelViewSet

router = DefaultRouter()
router.register(
    "",
    SalaryLevelViewSet,
    basename="salary-level",
)


urlpatterns = [
    path(
        "lookup/",
        include("apps.payroll.api.salary_levels.lookup.urls"),
    ),
    path(
        "",
        include(router.urls),
    ),
]