from django.urls import path

from .views import PayrollDashboardAPIView


urlpatterns = [
    path(
        "dashboard/",
        PayrollDashboardAPIView.as_view(),
        name="payroll-dashboard",
    ),
    path(
        "dashboard/ui-schema/",
        PayrollDashboardAPIView.as_schema_view(),
        name="payroll-dashboard-ui-schema",
    ),
]
