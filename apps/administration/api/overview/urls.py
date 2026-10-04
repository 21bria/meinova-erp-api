from django.urls import path

from .views import AdministrationDashboardAPIView


urlpatterns = [
    path(
        "",
        AdministrationDashboardAPIView.as_view(),
        name="administration-dashboard",
    ),
    path(
        "ui-schema/",
        AdministrationDashboardAPIView.as_schema_view(),
        name="administration-dashboard-ui-schema",
    ),
]
