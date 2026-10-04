from django.urls import path

from .views import PayrollPeriodLookupView


urlpatterns = [
    path(
        "",
        PayrollPeriodLookupView.as_view(),
        name="payroll-period-lookup-list",
    ),
    path(
        "<int:pk>/",
        PayrollPeriodLookupView.as_view(),
        name="payroll-period-lookup-detail",
    ),
]
