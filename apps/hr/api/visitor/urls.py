from rest_framework.routers import DefaultRouter

from .views import (
    ExternalVisitorViewSet,
    VisitorPassViewSet,
    VisitorRequestViewSet,
)


router = DefaultRouter()

router.register(
    "external-visitors",
    ExternalVisitorViewSet,
    basename="external-visitor",
)

router.register(
    "visitor-requests",
    VisitorRequestViewSet,
    basename="visitor-request",
)

router.register(
    "visitor-passes",
    VisitorPassViewSet,
    basename="visitor-pass",
)

urlpatterns = router.urls
