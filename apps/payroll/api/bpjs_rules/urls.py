from rest_framework.routers import DefaultRouter

from .views import BpjsRuleViewSet

router = DefaultRouter()
router.register("", BpjsRuleViewSet, basename="bpjs-rule")

urlpatterns = router.urls
