from rest_framework.routers import DefaultRouter

from .views import EmployeeFamilyViewSet


router = DefaultRouter()

router.register(
    "employee-families",
    EmployeeFamilyViewSet,
    basename="employee-family",
)

urlpatterns = router.urls