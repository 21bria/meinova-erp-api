from rest_framework.routers import DefaultRouter

from .views import EmployeeExperienceViewSet


router = DefaultRouter()

router.register(
    "employee-experiences",
    EmployeeExperienceViewSet,
    basename="employee-experience",
)

urlpatterns = router.urls