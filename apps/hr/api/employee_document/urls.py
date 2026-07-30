# apps/hr/api/employee_document/urls.py

from rest_framework.routers import DefaultRouter

from .views import EmployeeDocumentViewSet


router = DefaultRouter()

router.register(
    "employee-documents",
    EmployeeDocumentViewSet,
    basename="employee-document",
)

urlpatterns = router.urls