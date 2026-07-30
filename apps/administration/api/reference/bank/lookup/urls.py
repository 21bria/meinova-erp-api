from django.urls import path

from .views import BankReferenceLookupView


urlpatterns = [
    path(
        "<str:lookup_name>/",
        BankReferenceLookupView.as_view(),
        name="lookup",
    ),
    path(
        "<str:lookup_name>/<int:pk>/",
        BankReferenceLookupView.as_view(),
        name="lookup-detail",
    ),
]