from django.urls import path

from .views import DeductionTemplatesLookupView


urlpatterns = [
    path(
        "",
        DeductionTemplatesLookupView.as_view(),
        {
            "lookup_name": "deduction-templates",
        },
        name="deduction-templates-lookup-list",
    ),
    path(
        "<int:pk>/",
        DeductionTemplatesLookupView.as_view(),
        {
            "lookup_name": "deduction-templates",
        },
        name="deduction-templates-lookup-detail",
    ),
]