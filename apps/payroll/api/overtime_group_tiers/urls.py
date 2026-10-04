from rest_framework.routers import DefaultRouter

from .views import OvertimeGroupTierViewSet

router = DefaultRouter()
router.register("", OvertimeGroupTierViewSet, basename="overtime-group-tier")

urlpatterns = router.urls
