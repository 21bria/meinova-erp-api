from django.urls import path

from .views import MenuPermissionTreeView, MenuPermissionSaveView

urlpatterns = [
    path("tree/", MenuPermissionTreeView.as_view(), name="menu-permission-tree"),
    path("save/", MenuPermissionSaveView.as_view(), name="menu-permission-save"),
]