from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.administration.api.audit.views.audit import AuditTrailViewSet

router = DefaultRouter()
router.register("trails", AuditTrailViewSet, basename="audit-trail")

urlpatterns = [
    path("", include(router.urls)),
]