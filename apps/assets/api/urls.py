"""
Router tunggal Asset Management — `/api/assets/`.

Kontraknya: `docs/claude/assets.md`.
"""

from django.urls import include, path


urlpatterns = [
    # Lookup lebih dulu. Router DRF mendaftarkan `<pk>` yang serakah,
    # dan rute spesifik yang ditaruh sesudahnya akan tertelan — aturan
    # yang sama dengan `apps/finance/api/urls.py`.
    path("lookup/", include("apps.assets.api.lookup.urls")),

    path("", include("apps.assets.api.asset_category.urls")),
    path("", include("apps.assets.api.asset.urls")),
    path("", include("apps.assets.api.asset_assignment.urls")),
    path("", include("apps.assets.api.asset_return.urls")),
    path("", include("apps.assets.api.asset_transfer.urls")),
]
