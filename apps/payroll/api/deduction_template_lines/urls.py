from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import DeductionTemplateLineViewSet


router = DefaultRouter()
router.register(
    "",
    DeductionTemplateLineViewSet,
    basename="deduction-template-line",
)


urlpatterns = [
    path(
        "lookup/",
        include("apps.payroll.api.deduction_template_lines.lookup.urls"),
    ),
    path("", include(router.urls)),
]
