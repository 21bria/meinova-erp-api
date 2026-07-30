from django.urls import path

from .views import AllowanceTemplatesLookupView


urlpatterns = [
    path(
        "",
        AllowanceTemplatesLookupView.as_view(),
        {
            "lookup_name": "allowance-templates",
        },
        name="allowance-templates-lookup-list",
    ),
    path(
        "<int:pk>/",
        AllowanceTemplatesLookupView.as_view(),
        {
            "lookup_name": "allowance-templates",
        },
        name="allowance-templates-lookup-detail",
    ),
]