from django.urls import path

from .views import MenuPermissionSaveView, MenuPermissionTreeView, MyMenuAccessView

urlpatterns = [
    path("tree/", MenuPermissionTreeView.as_view(), name="menu-permission-tree"),
    path("save/", MenuPermissionSaveView.as_view(), name="menu-permission-save"),
    path("my/", MyMenuAccessView.as_view(), name="menu-permission-my"),
]
