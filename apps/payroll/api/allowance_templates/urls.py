from django.urls import path,include
from rest_framework.routers import DefaultRouter

from .views import AllowanceTemplateViewSet

router = DefaultRouter()
router.register(
    "",
    AllowanceTemplateViewSet,
    basename="allowance-template",
)

urlpatterns = [
    path(
        "lookup/",
        include("apps.payroll.api.allowance_templates.lookup.urls"),
    ),
    path(
        "",
        include(router.urls),
    ),
]
