from rest_framework.routers import DefaultRouter

from .views import AssetTransferViewSet


router = DefaultRouter()
router.register("transfers", AssetTransferViewSet, basename="asset-transfer")

urlpatterns = router.urls
