from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PayrollRunEmployeeViewSet


router = DefaultRouter()
router.register(
    "", PayrollRunEmployeeViewSet, basename="payroll-run-employee",
)


urlpatterns = [path("", include(router.urls))]
