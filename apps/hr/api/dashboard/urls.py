from django.urls import path

from .views import HRDashboardAPIView


urlpatterns = [
    path(
        "dashboard/",
        HRDashboardAPIView.as_view(),
        name="hr-dashboard",
    ),
    path(
        "dashboard/ui-schema/",
        HRDashboardAPIView.as_schema_view(),
        name="hr-dashboard-ui-schema",
    ),
]
