from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PayrollPolicyViewSet

router = DefaultRouter()
router.register("", PayrollPolicyViewSet, basename="payroll-policy")

urlpatterns = [
    path(
        "lookup/",
        include("apps.payroll.api.payroll_policies.lookup.urls"),
    ),
    path("", include(router.urls)),
]
