from django.urls import path

from .views import TaxStatusLookupView


urlpatterns = [
    path(
        "",
        TaxStatusLookupView.as_view(),
        {
            "lookup_name": "tax-statuses",
        },
        name="tax-statuses-lookup-list",
    ),
    path(
        "<int:pk>/",
        TaxStatusLookupView.as_view(),
        {
            "lookup_name": "tax-statuses",
        },
        name="tax-statuses-lookup-detail",
    ),
]