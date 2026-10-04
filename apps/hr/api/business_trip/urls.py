from rest_framework.routers import DefaultRouter

from .views import BusinessTripLegViewSet, BusinessTripViewSet


router = DefaultRouter()

router.register(
    "business-trips",
    BusinessTripViewSet,
    basename="business-trip",
)

router.register(
    "business-trip-legs",
    BusinessTripLegViewSet,
    basename="business-trip-leg",
)

urlpatterns = router.urls
