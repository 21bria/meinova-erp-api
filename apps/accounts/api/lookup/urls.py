from django.urls import path

from .views import AccountLookupView


urlpatterns = [
    path(
        "<str:lookup_name>/",
        AccountLookupView.as_view(),
        name="lookup",
    ),
    path(
        "<str:lookup_name>/<int:pk>/",
        AccountLookupView.as_view(),
        name="lookup-detail",
    ),
]