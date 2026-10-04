from rest_framework.routers import DefaultRouter

from .views import FiscalYearViewSet


router = DefaultRouter()
router.register(
    "fiscal-years", FiscalYearViewSet, basename="finance-fiscal-year",
)

urlpatterns = router.urls
