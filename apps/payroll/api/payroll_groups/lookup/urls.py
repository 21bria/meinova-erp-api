from django.urls import path

from .views import PayrollGroupLookupView


urlpatterns = [
    path(
        "",
        PayrollGroupLookupView.as_view(),
        {
            "lookup_name": "payroll-groups",
        },
        name="payroll-groups-lookup-list",
    ),
    path(
        "<int:pk>/",
        PayrollGroupLookupView.as_view(),
        {
            "lookup_name": "payroll-groups",
        },
        name="payroll-groups-lookup-detail",
    ),
]