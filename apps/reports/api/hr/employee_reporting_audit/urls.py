from django.urls import path

from .views import (
    HREmployeeReportingAuditAPIView,
    ReportingStatusLookupAPIView,
)


urlpatterns = [
    path(
        "employee-reporting-audit/",
        HREmployeeReportingAuditAPIView.as_view(),
        name="hr-employee-reporting-audit",
    ),
    path(
        "employee-reporting-audit/ui-schema/",
        HREmployeeReportingAuditAPIView.as_schema_view(),
        name="hr-employee-reporting-audit-ui-schema",
    ),
    # Isi dropdown "Reporting Status". Dua pilihan tetap, read-only.
    path(
        "employee-reporting-audit/reporting-status/",
        ReportingStatusLookupAPIView.as_view(),
        name="hr-employee-reporting-audit-reporting-status",
    ),
    path(
        "employee-reporting-audit/reporting-status/<int:pk>/",
        ReportingStatusLookupAPIView.as_view(),
        name="hr-employee-reporting-audit-reporting-status-detail",
    ),
]
