from rest_framework.routers import DefaultRouter

from .views import EmployeeOvertimeViewSet


router = DefaultRouter()

router.register(
    "overtimes",
    EmployeeOvertimeViewSet,
    basename="employee-overtime",
)

urlpatterns = router.urls
