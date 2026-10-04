from django.urls import path

from .views import PayrollRunLookupView


urlpatterns = [
    path(
        "",
        PayrollRunLookupView.as_view(),
        name="payroll-run-lookup-list",
    ),
    path(
        "<int:pk>/",
        PayrollRunLookupView.as_view(),
        name="payroll-run-lookup-detail",
    ),
]
