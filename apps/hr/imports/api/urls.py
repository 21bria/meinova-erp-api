from django.urls import path

from .import_views import (
    AttendanceImportConfirmAPIView,
    AttendanceImportPreviewAPIView,
)
from .profile_views import (
    AttendanceImportProfileLookupViewSet,
)


profile_lookup_view = (
    AttendanceImportProfileLookupViewSet
    .as_view({
        "get": "list",
    })
)


urlpatterns = [
    path(
        "attendance/import-profiles/lookup/",
        profile_lookup_view,
        name="attendance-import-profile-lookup",
    ),

    path(
        "attendance/import/preview/",
        AttendanceImportPreviewAPIView.as_view(),
        name="attendance-import-preview",
    ),

    path(
        "attendance/import/confirm/",
        AttendanceImportConfirmAPIView.as_view(),
        name="attendance-import-confirm",
    ),
]