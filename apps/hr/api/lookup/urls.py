from django.urls import path

from .views import HRLookupView

urlpatterns = [
    path(
        "<str:lookup_name>/",
        HRLookupView.as_view(),
        name="hr-lookup",
    ),
    path(
        "<str:lookup_name>/<int:pk>/",
        HRLookupView.as_view(),
        name="hr-lookup-detail",
    ),
]
