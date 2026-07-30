from django.urls import path

from .views import CurrencyLookupView

urlpatterns = [
    path(
        "<str:lookup_name>/",
        CurrencyLookupView.as_view(),
        name="lookup",
    ),
    path(
        "<str:lookup_name>/<int:pk>/",
        CurrencyLookupView.as_view(),
        name="lookup-detail",
    ),
]