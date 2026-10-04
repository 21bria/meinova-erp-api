from rest_framework.routers import DefaultRouter

from .views import LeaveOpeningBalanceViewSet


router = DefaultRouter()

router.register(
    "leave-opening-balances",
    LeaveOpeningBalanceViewSet,
    basename="leave-opening-balance",
)

urlpatterns = router.urls
