from django.urls import path,include
from rest_framework.routers import DefaultRouter

from .views import DeductionTemplateViewSet

router = DefaultRouter()
router.register(
    "",
    DeductionTemplateViewSet,
    basename="deduction-template",
)

urlpatterns = [
    path(
        "lookup/",
        include("apps.payroll.api.deduction_templates.lookup.urls"),
    ),
    path(
        "",
        include(router.urls),
    ),
]