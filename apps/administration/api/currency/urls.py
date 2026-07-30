from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.administration.api.currency.views.currency import (
    CurrencyViewSet,
    ExchangeRateViewSet,
)

router = DefaultRouter()
router.register("currencies", CurrencyViewSet, basename="currency")
router.register("exchange-rates", ExchangeRateViewSet, basename="exchange-rate")

urlpatterns = [
    path( "lookup/",include("apps.administration.api.currency.lookup.urls")),
    path("", include(router.urls)),
]