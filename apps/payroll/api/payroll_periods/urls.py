from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PayrollPeriodViewSet


router = DefaultRouter()
router.register("", PayrollPeriodViewSet, basename="payroll-period")


urlpatterns = [
    path(
        "lookup/",
        include("apps.payroll.api.payroll_periods.lookup.urls"),
    ),
    path("", include(router.urls)),
]
