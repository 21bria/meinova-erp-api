from rest_framework.routers import DefaultRouter

from .views import (
    TravelArrangementViewSet,
    TravelRequestPurposeViewSet,
    TravelRequestViewSet,
)


router = DefaultRouter()

router.register(
    "travel-requests",
    TravelRequestViewSet,
    basename="travel-request",
)

router.register(
    "travel-request-purposes",
    TravelRequestPurposeViewSet,
    basename="travel-request-purpose",
)

router.register(
    "travel-arrangements",
    TravelArrangementViewSet,
    basename="travel-arrangement",
)

urlpatterns = router.urls
