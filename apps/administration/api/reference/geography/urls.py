from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.administration.api.reference.geography.views.geography import (
    CityViewSet,
    CountryViewSet,
    DistrictViewSet,
    ProvinceViewSet,
    VillageViewSet,
)

router = DefaultRouter()
router.register("countries", CountryViewSet, basename="master-country")
router.register("provinces", ProvinceViewSet, basename="master-province")
router.register("cities", CityViewSet, basename="master-city")
router.register("districts", DistrictViewSet, basename="master-district")
router.register("villages", VillageViewSet, basename="master-village")

urlpatterns = [
    path("lookup/",include("apps.administration.api.reference.geography.lookup.urls")),
    path("", include(router.urls)),
]
