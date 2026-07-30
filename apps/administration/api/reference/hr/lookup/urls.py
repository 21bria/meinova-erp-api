from django.urls import path

from .views import HRReferenceLookupView

urlpatterns = [
    path(
        "<str:lookup_name>/",
        HRReferenceLookupView.as_view(),
        name="lookup",
    ),
    path(
        "<str:lookup_name>/<int:pk>/",
        HRReferenceLookupView.as_view(),
        name="lookup-detail",
    ),
]