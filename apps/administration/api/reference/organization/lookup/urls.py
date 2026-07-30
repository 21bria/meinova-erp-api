from django.urls import path

from .views import OrganizationReferenceLookupView


urlpatterns = [
    path(
        "<str:lookup_name>/",
        OrganizationReferenceLookupView.as_view(),
        name="lookup",
    ),
    path(
        "<str:lookup_name>/<int:pk>/",
        OrganizationReferenceLookupView.as_view(),
        name="lookup-detail",
    ),
]