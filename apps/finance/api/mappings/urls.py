from rest_framework.routers import DefaultRouter

from .views import AccountMappingViewSet


router = DefaultRouter()
router.register(
    "account-mappings",
    AccountMappingViewSet,
    basename="finance-account-mapping",
)

urlpatterns = router.urls
