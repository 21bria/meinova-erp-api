from django.urls import path

from .views import GeographyReferenceLookupView

urlpatterns = [
    path(
        "<str:lookup_name>/",
        GeographyReferenceLookupView.as_view(),
        name="lookup",
    ),
    path(
        "<str:lookup_name>/<int:pk>/",
        GeographyReferenceLookupView.as_view(),
        name="lookup-detail",
    ),
]