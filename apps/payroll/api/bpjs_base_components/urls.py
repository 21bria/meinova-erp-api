from rest_framework.routers import DefaultRouter

from .views import BpjsBaseComponentViewSet

router = DefaultRouter()
router.register("", BpjsBaseComponentViewSet, basename="bpjs-base-component")

urlpatterns = router.urls
