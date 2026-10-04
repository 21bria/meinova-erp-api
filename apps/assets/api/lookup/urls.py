from django.urls import path

from .views import AssetsLookupView


urlpatterns = [
    path(
        "<str:lookup_name>/",
        AssetsLookupView.as_view(),
        name="assets-lookup",
    ),
    path(
        "<str:lookup_name>/<int:pk>/",
        AssetsLookupView.as_view(),
        name="assets-lookup-detail",
    ),
]
