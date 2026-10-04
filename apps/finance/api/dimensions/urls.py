from rest_framework.routers import DefaultRouter

from .views import AccountingDimensionViewSet


router = DefaultRouter()
router.register(
    "accounting-dimensions",
    AccountingDimensionViewSet,
    basename="finance-accounting-dimension",
)

urlpatterns = router.urls
