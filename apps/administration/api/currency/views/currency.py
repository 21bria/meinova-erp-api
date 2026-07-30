from rest_framework.permissions import IsAuthenticated
from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.currency.serializers.currency import (
    CurrencySerializer,
    ExchangeRateSerializer,
)
from apps.administration.api.currency.services.currency_service import (
    CurrencyService,
    ExchangeRateService,
)


class CurrencyViewSet(BaseMasterViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = CurrencySerializer
    service_class = CurrencyService
    framework_module = "administration/currency"
    schema_type = "crud"

    schema = {
        "title": "Currency",
        "description": "Manage currencies used throughout the system.",
    }


class ExchangeRateViewSet(BaseMasterViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = ExchangeRateSerializer
    service_class = ExchangeRateService
    framework_module = "administration/currency/exchange-rate"
    schema_type = "crud"

    schema = {
        "title": "Exchange Rate",
        "description": "Manage currency exchange rates.",
    }