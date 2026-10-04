from rest_framework.routers import DefaultRouter

from .views import AssetReturnViewSet


router = DefaultRouter()
router.register("returns", AssetReturnViewSet, basename="asset-return")

urlpatterns = router.urls
