from django.urls import path

from .views import SalaryLevelLookupView


urlpatterns = [
    path(
        "",
        SalaryLevelLookupView.as_view(),
        {
            "lookup_name": "salary-levels",
        },
        name="salary-levels-lookup-list",
    ),
    path(
        "<int:pk>/",
        SalaryLevelLookupView.as_view(),
        {
            "lookup_name": "salary-levels",
        },
        name="salary-levels-lookup-detail",
    ),
]