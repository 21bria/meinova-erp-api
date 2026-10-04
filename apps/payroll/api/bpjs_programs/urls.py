from rest_framework.routers import DefaultRouter

from .views import BpjsProgramViewSet

router = DefaultRouter()
router.register("", BpjsProgramViewSet, basename="bpjs-program")

urlpatterns = router.urls
