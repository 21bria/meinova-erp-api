from rest_framework.routers import DefaultRouter

from .views import BpjsEnrollmentViewSet

router = DefaultRouter()
router.register("", BpjsEnrollmentViewSet, basename="bpjs-enrollment")

urlpatterns = router.urls
