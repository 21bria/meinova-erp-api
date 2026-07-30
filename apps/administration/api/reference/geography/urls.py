from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.administration.api.reference.geography.views.geography import (
    CountryViewSet,
    ProvinceViewSet,
    CityViewSet,
)

router = DefaultRouter()
router.register("countries", CountryViewSet, basename="master-country")
router.register("provinces", ProvinceViewSet, basename="master-province")
router.register("cities", CityViewSet, basename="master-city")

urlpatterns = [
    path("lookup/",include("apps.administration.api.reference.geography.lookup.urls")),
    path("", include(router.urls)),
]