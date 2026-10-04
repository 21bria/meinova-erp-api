from django.urls import path

from .import_views import (
    ImportConfirmAPIView,
    ImportPreviewAPIView,
    ImportTemplateAPIView,
)
from .profile_views import ImportProfileLookupViewSet
from .views import (
    ImportJobDeleteAPIView,
    ImportJobDetailAPIView,
    ImportJobErrorListAPIView,
    ImportJobErrorReportAPIView,
    ImportJobListAPIView,
)


app_name = "imports"


profile_lookup_view = ImportProfileLookupViewSet.as_view({
    "get": "list",
})


urlpatterns = [
    # ------------------------------------------------------------------
    # Job tracking
    # ------------------------------------------------------------------
    path(
        "jobs/",
        ImportJobListAPIView.as_view(),
        name="job-list",
    ),

    path(
        "jobs/<uuid:public_id>/",
        ImportJobDetailAPIView.as_view(),
        name="job-detail",
    ),

    path(
        "jobs/<uuid:public_id>/errors/",
        ImportJobErrorListAPIView.as_view(),
        name="job-errors",
    ),

    path(
        "jobs/<uuid:public_id>/error-report/",
        ImportJobErrorReportAPIView.as_view(),
        name="job-error-report",
    ),

    path(
        "jobs/<uuid:public_id>/delete/",
        ImportJobDeleteAPIView.as_view(),
        name="job-delete",
    ),

    # ------------------------------------------------------------------
    # Profile lookup
    # ------------------------------------------------------------------
    path(
        "profiles/lookup/",
        profile_lookup_view,
        name="profile-lookup",
    ),

    # ------------------------------------------------------------------
    # Import generik per module.
    # Harus paling akhir: <path:module> ikut menangkap garis miring.
    # ------------------------------------------------------------------
    path(
        "<path:module>/preview/",
        ImportPreviewAPIView.as_view(),
        name="module-preview",
    ),

    path(
        "<path:module>/confirm/",
        ImportConfirmAPIView.as_view(),
        name="module-confirm",
    ),

    path(
        "<path:module>/template/",
        ImportTemplateAPIView.as_view(),
        name="module-template",
    ),
]
