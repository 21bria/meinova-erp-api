from rest_framework.routers import DefaultRouter

from .views import (
    RotationPeriodViewSet,
    SiteRotationViewSet,
)


router = DefaultRouter()

router.register(
    "site-rotations",
    SiteRotationViewSet,
    basename="site-rotation",
)

router.register(
    "rotation-periods",
    RotationPeriodViewSet,
    basename="rotation-period",
)

urlpatterns = router.urls
