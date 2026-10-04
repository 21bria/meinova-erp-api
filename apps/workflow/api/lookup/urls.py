from django.urls import path

from .views import WorkflowLookupView


urlpatterns = [
    path(
        "<str:lookup_name>/",
        WorkflowLookupView.as_view(),
        name="workflow-lookup",
    ),
    path(
        "<str:lookup_name>/<int:pk>/",
        WorkflowLookupView.as_view(),
        name="workflow-lookup-detail",
    ),
]
