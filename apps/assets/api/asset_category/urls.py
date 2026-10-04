from rest_framework.routers import DefaultRouter

from .views import AssetCategoryViewSet


router = DefaultRouter()
router.register("categories", AssetCategoryViewSet, basename="asset-category")

urlpatterns = router.urls
