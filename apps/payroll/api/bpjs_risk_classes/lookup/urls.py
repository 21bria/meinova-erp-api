from django.urls import path

from .views import BpjsRiskClassLookupView

urlpatterns = [
    path(
        "",
        BpjsRiskClassLookupView.as_view(),
        {"lookup_name": "bpjs-risk-classes"},
        name="bpjs-risk-classes-lookup-list",
    ),
    path(
        "<int:pk>/",
        BpjsRiskClassLookupView.as_view(),
        {"lookup_name": "bpjs-risk-classes"},
        name="bpjs-risk-classes-lookup-detail",
    ),
]
