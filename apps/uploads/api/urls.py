from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.uploads.api.views import UploadedFileViewSet


app_name = "uploads"

router = DefaultRouter()
router.register(
    "",
    UploadedFileViewSet,
    basename="uploaded-file",
)

urlpatterns = [
    path("", include(router.urls)),
]