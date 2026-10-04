from django.urls import include, path


urlpatterns = [
    # Lookup lebih dulu. Router DRF mendaftarkan `<pk>` yang serakah,
    # dan rute spesifik yang ditaruh sesudahnya akan tertelan — aturan
    # yang sama sudah berlaku di `apps/hr/api/urls.py`.
    path("lookup/", include("apps.finance.api.lookup.urls")),

    # Laporan. Juga sebelum router, karena `reports/` bukan resource.
    path("reports/", include("apps.finance.api.reports.urls")),

    # Setup
    path("", include("apps.finance.api.accounts.urls")),
    path("", include("apps.finance.api.fiscal_years.urls")),
    path("", include("apps.finance.api.periods.urls")),
    path("", include("apps.finance.api.dimensions.urls")),

    # General Ledger
    path("", include("apps.finance.api.journals.urls")),

    # Lapisan integrasi
    path("", include("apps.finance.api.events.urls")),
    path("", include("apps.finance.api.policies.urls")),
    path("", include("apps.finance.api.mappings.urls")),
]
