from rest_framework.routers import DefaultRouter

from .views import BpjsRiskClassViewSet

router = DefaultRouter()
router.register("", BpjsRiskClassViewSet, basename="bpjs-risk-class")

urlpatterns = router.urls
