from django.urls import path

from apps.administration.api.dashboard.views import (
    AppCatalogAPIView,
    DashboardSummaryAPIView,
    FavoriteAppAPIView,
    FavoriteMenuAPIView,
    MenuCatalogAPIView,
    UserDashboardLayoutAPIView,
)

urlpatterns = [
    path("summary/", DashboardSummaryAPIView.as_view(), name="dashboard-summary"),
    path("layout/", UserDashboardLayoutAPIView.as_view(), name="dashboard-layout"),

    # Katalog + susunan pilihan, dua pasang dengan bentuk yang sama:
    # `GET .../<x>-catalog/` memberi seluruh pilihan beserta penanda mana
    # yang sedang dipakai, `PUT .../favorite-<x>/` menyimpan susunannya
    # sekaligus. Satu request memberi kedua keadaan, jadi masuk mode
    # Customize tidak menembak API lagi.
    path("apps/", AppCatalogAPIView.as_view(), name="dashboard-app-catalog"),
    path("favorite-apps/", FavoriteAppAPIView.as_view(), name="dashboard-favorite-apps"),

    path("menu-catalog/", MenuCatalogAPIView.as_view(), name="dashboard-menu-catalog"),
    path("favorite-menus/", FavoriteMenuAPIView.as_view(), name="dashboard-favorite-menus"),
]
