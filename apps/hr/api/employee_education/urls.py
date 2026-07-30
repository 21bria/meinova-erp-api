from rest_framework.routers import DefaultRouter

from .views import EmployeeEducationViewSet


router = DefaultRouter()

router.register(
    "employee-educations",
    EmployeeEducationViewSet,
    basename="employee-education",
)

urlpatterns = router.urls