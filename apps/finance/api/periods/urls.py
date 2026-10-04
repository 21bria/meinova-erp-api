from rest_framework.routers import DefaultRouter

from .views import AccountingPeriodViewSet


router = DefaultRouter()
router.register(
    "accounting-periods",
    AccountingPeriodViewSet,
    basename="finance-accounting-period",
)

urlpatterns = router.urls
