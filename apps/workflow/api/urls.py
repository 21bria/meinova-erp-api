from django.urls import include, path


urlpatterns = [
    # Rute path-tetap harus di atas router viewset supaya tidak
    # tertelan rute `<str:pk>` milik router.
    path("lookup/", include("apps.workflow.api.lookup.urls")),

    path("", include("apps.workflow.api.definition.urls")),
    path("", include("apps.workflow.api.step.urls")),
    path("", include("apps.workflow.api.instance.urls")),
    path("", include("apps.workflow.api.approval.urls")),
    path("", include("apps.workflow.api.delegation.urls")),
]
