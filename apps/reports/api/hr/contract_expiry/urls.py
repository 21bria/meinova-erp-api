from django.urls import path

from .views import (
    ExpiryStatusLookupAPIView,
    HRContractExpiryAPIView,
    RenewalStatusLookupAPIView,
)


urlpatterns = [
    path(
        "contract-expiry/",
        HRContractExpiryAPIView.as_view(),
        name="hr-contract-expiry",
    ),
    path(
        "contract-expiry/ui-schema/",
        HRContractExpiryAPIView.as_schema_view(),
        name="hr-contract-expiry-ui-schema",
    ),
    # Isi dua dropdown yang tidak punya tabel master. Read-only.
    path(
        "contract-expiry/expiry-status/",
        ExpiryStatusLookupAPIView.as_view(),
        name="hr-contract-expiry-expiry-status",
    ),
    path(
        "contract-expiry/expiry-status/<int:pk>/",
        ExpiryStatusLookupAPIView.as_view(),
        name="hr-contract-expiry-expiry-status-detail",
    ),
    path(
        "contract-expiry/renewal-status/",
        RenewalStatusLookupAPIView.as_view(),
        name="hr-contract-expiry-renewal-status",
    ),
    path(
        "contract-expiry/renewal-status/<int:pk>/",
        RenewalStatusLookupAPIView.as_view(),
        name="hr-contract-expiry-renewal-status-detail",
    ),
]
