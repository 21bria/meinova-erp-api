from django.urls import path

from .views import DataPermissionTreeView, DataPermissionSaveView

urlpatterns = [
    path("tree/", DataPermissionTreeView.as_view(), name="data-permission-tree"),
    path("save/", DataPermissionSaveView.as_view(), name="data-permission-save"),
]