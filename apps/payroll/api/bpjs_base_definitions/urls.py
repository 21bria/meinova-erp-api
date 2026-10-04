from rest_framework.routers import DefaultRouter

from .views import BpjsBaseDefinitionViewSet

router = DefaultRouter()
router.register("", BpjsBaseDefinitionViewSet, basename="bpjs-base-definition")

urlpatterns = router.urls
