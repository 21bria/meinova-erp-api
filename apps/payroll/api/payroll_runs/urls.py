from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PayrollRunViewSet


router = DefaultRouter()
router.register("", PayrollRunViewSet, basename="payroll-run")


urlpatterns = [
    path(
        "lookup/",
        include("apps.payroll.api.payroll_runs.lookup.urls"),
    ),
    path("", include(router.urls)),
]
