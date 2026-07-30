from rest_framework.routers import DefaultRouter

from apps.hr.api.employee.views.employee import EmployeeViewSet


router = DefaultRouter()
router.register(
    "employees",EmployeeViewSet,basename="employee"
)

urlpatterns = router.urls