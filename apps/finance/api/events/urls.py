from rest_framework.routers import DefaultRouter

from .views import AccountingEventViewSet


router = DefaultRouter()
router.register(
    "accounting-events",
    AccountingEventViewSet,
    basename="finance-accounting-event",
)

urlpatterns = router.urls
