from rest_framework.routers import DefaultRouter

from .views import AssetAssignmentViewSet


router = DefaultRouter()
router.register("assignments", AssetAssignmentViewSet, basename="asset-assignment")

urlpatterns = router.urls
