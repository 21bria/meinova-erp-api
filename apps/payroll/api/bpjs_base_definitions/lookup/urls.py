from django.urls import path

from .views import BpjsBaseDefinitionLookupView

urlpatterns = [
    path(
        "",
        BpjsBaseDefinitionLookupView.as_view(),
        {"lookup_name": "bpjs-base-definitions"},
        name="bpjs-base-definitions-lookup-list",
    ),
    path(
        "<int:pk>/",
        BpjsBaseDefinitionLookupView.as_view(),
        {"lookup_name": "bpjs-base-definitions"},
        name="bpjs-base-definitions-lookup-detail",
    ),
]
