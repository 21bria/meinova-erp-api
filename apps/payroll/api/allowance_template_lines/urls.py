from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AllowanceTemplateLineViewSet


router = DefaultRouter()
router.register(
    "",
    AllowanceTemplateLineViewSet,
    basename="allowance-template-line",
)


urlpatterns = [
    path(
        "lookup/",
        include("apps.payroll.api.allowance_template_lines.lookup.urls"),
    ),
    path("", include(router.urls)),
]
