from rest_framework.routers import DefaultRouter

from .views import AttendancePermissionViewSet


router = DefaultRouter()

router.register(
    "attendance-permissions",
    AttendancePermissionViewSet,
    basename="attendance-permission",
)

urlpatterns = router.urls
