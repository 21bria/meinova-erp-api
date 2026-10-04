from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.administration.api.reference.organization.views import *

router = DefaultRouter()
router.register("company-types", CompanyTypeViewSet, basename="master-company-type")
router.register("branch-types", BranchTypeViewSet, basename="master-branch-type")
router.register("location-types", LocationTypeViewSet, basename="master-location-type")
router.register("facility-types", FacilityTypeViewSet, basename="master-facility-type")

urlpatterns = [
    path("lookup/",include( "apps.administration.api.reference.organization.lookup.urls" )),
    path("", include(router.urls)),
]