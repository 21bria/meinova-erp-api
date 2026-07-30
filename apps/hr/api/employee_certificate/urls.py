from rest_framework.routers import DefaultRouter

from .views import EmployeeCertificateViewSet


router = DefaultRouter()

router.register(
    "employee-certificates",
    EmployeeCertificateViewSet,
    basename="employee-certificate",
)

urlpatterns = router.urls