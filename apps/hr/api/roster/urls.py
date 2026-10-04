from rest_framework.routers import DefaultRouter

from .views import (
    RosterAdjustmentViewSet,
    RosterSetupLineViewSet,
    RosterSetupViewSet,
    RotationCreditViewSet,
)


router = DefaultRouter()

router.register(
    "roster-setups",
    RosterSetupViewSet,
    basename="roster-setup",
)

router.register(
    "roster-setup-lines",
    RosterSetupLineViewSet,
    basename="roster-setup-line",
)

router.register(
    "roster-adjustments",
    RosterAdjustmentViewSet,
    basename="roster-adjustment",
)

router.register(
    "rotation-credits",
    RotationCreditViewSet,
    basename="rotation-credit",
)

urlpatterns = router.urls
