from rest_framework.routers import DefaultRouter

from .views import AccountViewSet


router = DefaultRouter()
router.register("accounts", AccountViewSet, basename="finance-account")

urlpatterns = router.urls
