from django.urls import path

from .views import SalaryGradeLookupView


urlpatterns = [
    path(
        "",
        SalaryGradeLookupView.as_view(),
        name="salary-grade-lookup-list",
    ),
    path(
        "<int:pk>/",
        SalaryGradeLookupView.as_view(),
        name="salary-grade-lookup-detail",
    ),
]