from django.urls import path

from .views import PayrollPolicyLookupView

urlpatterns = [
    path(
        "",
        PayrollPolicyLookupView.as_view(),
        {"lookup_name": "payroll-policies"},
        name="payroll-policies-lookup-list",
    ),
    path(
        "<int:pk>/",
        PayrollPolicyLookupView.as_view(),
        {"lookup_name": "payroll-policies"},
        name="payroll-policies-lookup-detail",
    ),
]
