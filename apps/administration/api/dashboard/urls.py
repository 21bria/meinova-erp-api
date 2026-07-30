from django.urls import path

from apps.administration.api.dashboard.views import (
    DashboardWidgetListAPIView,
    UserDashboardLayoutAPIView,
    FavoriteAppAPIView,
    FavoriteMenuAPIView,
)

urlpatterns = [
    path("widgets/", DashboardWidgetListAPIView.as_view(), name="dashboard-widgets"),
    path("layout/", UserDashboardLayoutAPIView.as_view(), name="dashboard-layout"),
    path("favorite-apps/", FavoriteAppAPIView.as_view(), name="dashboard-favorite-apps"),
    path("favorite-menus/", FavoriteMenuAPIView.as_view(), name="dashboard-favorite-menus"),
]