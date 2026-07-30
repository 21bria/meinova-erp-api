from rest_framework.routers import DefaultRouter

from .views import EmployeeTrainingViewSet


router = DefaultRouter()

router.register(
    "employee-trainings",
    EmployeeTrainingViewSet,
    basename="employee-training",
)

urlpatterns = router.urls