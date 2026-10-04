from django.urls import path

from .views import RolePermissionSaveView, RolePermissionTreeView

urlpatterns = [
    path("tree/", RolePermissionTreeView.as_view(), name="role-permission-tree"),
    path("save/", RolePermissionSaveView.as_view(), name="role-permission-save"),
]
