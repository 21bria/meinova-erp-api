from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PayrollGroupViewSet


router = DefaultRouter()
router.register(
    "",
    PayrollGroupViewSet,
    basename="payroll-group",
)

urlpatterns = [
    path(
        "lookup/",
        include("apps.payroll.api.payroll_groups.lookup.urls"),
    ),
    path(
        "",
        include(router.urls),
    ),
]