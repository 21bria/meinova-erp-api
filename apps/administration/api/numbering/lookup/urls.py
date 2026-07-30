from django.urls import path

from apps.framework.lookup import BaseLookupView

urlpatterns = [
    path(
        "<str:lookup_name>/",
        BaseLookupView.as_view(),
        name="lookup",
    ),
    path(
        "<str:lookup_name>/<int:pk>/",
        BaseLookupView.as_view(),
        name="lookup-detail",
    ),
]