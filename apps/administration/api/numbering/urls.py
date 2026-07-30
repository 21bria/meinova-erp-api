from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.administration.api.numbering.views.numbering import (
    NumberingSequenceViewSet,
    DocumentSeriesViewSet,
)

router = DefaultRouter()
router.register("sequences", NumberingSequenceViewSet, basename="numbering-sequence")
router.register("document-series", DocumentSeriesViewSet, basename="document-series")

urlpatterns = [
    path(
        "lookup/",
        include("apps.administration.api.numbering.lookup.urls"),
    ),
    path("", include(router.urls)),
]