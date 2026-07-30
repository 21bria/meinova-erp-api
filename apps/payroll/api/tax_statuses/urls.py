from django.urls import path,include
from rest_framework.routers import DefaultRouter

from .views import TaxStatusViewSet

router = DefaultRouter()
router.register(
    "",
    TaxStatusViewSet,
    basename="tax-status",
)

urlpatterns = [
    path(
        "lookup/",
        include("apps.payroll.api.tax_statuses.lookup.urls"),
    ),
    path(
        "",
        include(router.urls),
    ),
]