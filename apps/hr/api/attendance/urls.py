from rest_framework.routers import DefaultRouter

from .views import EmployeeAttendanceViewSet

router = DefaultRouter()

router.register(
    "attendance",
    EmployeeAttendanceViewSet,
    basename="attendance",
)

urlpatterns = router.urls