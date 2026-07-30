from django.urls import path,include
from rest_framework.routers import DefaultRouter

from .views import OvertimeGroupViewSet

router = DefaultRouter()
router.register(
    "",
    OvertimeGroupViewSet,
    basename="overtime-group",
)

urlpatterns = [
    path(
        "lookup/",
        include("apps.payroll.api.overtime_groups.lookup.urls"),
    ),
    path(
        "",
        include(router.urls),
    ),
]