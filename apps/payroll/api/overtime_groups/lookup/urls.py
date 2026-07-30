from django.urls import path

from .views import OvertimeGroupLookupView


urlpatterns = [
    path(
        "",
        OvertimeGroupLookupView.as_view(),
        {
            "lookup_name": "overtime-groups",
        },
        name="overtime-groups-lookup-list",
    ),
    path(
        "<int:pk>/",
        OvertimeGroupLookupView.as_view(),
        {
            "lookup_name": "overtime-groups",
        },
        name="overtime-groups-lookup-detail",
    ),
]