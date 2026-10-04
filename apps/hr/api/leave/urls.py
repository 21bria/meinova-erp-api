from rest_framework.routers import DefaultRouter

from .views import EmployeeLeaveViewSet, LeaveBalanceViewSet


router = DefaultRouter()

router.register(
    "leaves",
    EmployeeLeaveViewSet,
    basename="employee-leave",
)

router.register(
    "leave-balances",
    LeaveBalanceViewSet,
    basename="leave-balance",
)

urlpatterns = router.urls
