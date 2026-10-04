from rest_framework.routers import DefaultRouter

from .views import EmployeeActionViewSet


router = DefaultRouter()

router.register(
    "employee-actions",
    EmployeeActionViewSet,
    basename="employee-action",
)

urlpatterns = router.urls
