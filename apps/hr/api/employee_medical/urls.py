from rest_framework.routers import DefaultRouter

from .views import EmployeeMedicalEventViewSet


router = DefaultRouter()

router.register(
    "employee-medical-events",
    EmployeeMedicalEventViewSet,
    basename="employee-medical-event",
)

urlpatterns = router.urls