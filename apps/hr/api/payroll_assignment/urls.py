from rest_framework.routers import DefaultRouter

from .views import PayrollAssignmentViewSet


router = DefaultRouter()

router.register(
    "payroll-assignments",
    PayrollAssignmentViewSet,
    basename="payroll-assignment",
)

urlpatterns = router.urls