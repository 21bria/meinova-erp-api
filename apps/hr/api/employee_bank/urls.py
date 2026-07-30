from rest_framework.routers import DefaultRouter

from .views import EmployeeBankAccountViewSet


router = DefaultRouter()

router.register(
    "employee-bank-accounts",
    EmployeeBankAccountViewSet,
    basename="employee-bank-account",
)

urlpatterns = router.urls