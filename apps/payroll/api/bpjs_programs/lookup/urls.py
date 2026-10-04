from django.urls import path

from .views import BpjsProgramLookupView

urlpatterns = [
    path(
        "",
        BpjsProgramLookupView.as_view(),
        {"lookup_name": "bpjs-programs"},
        name="bpjs-programs-lookup-list",
    ),
    path(
        "<int:pk>/",
        BpjsProgramLookupView.as_view(),
        {"lookup_name": "bpjs-programs"},
        name="bpjs-programs-lookup-detail",
    ),
]
