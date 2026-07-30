from apps.administration.models import Currency, ExchangeRate


class CurrencyService:
    @staticmethod
    def list():
        return Currency.objects.order_by("code")


class ExchangeRateService:
    @staticmethod
    def list():
        return ExchangeRate.objects.select_related(
            "from_currency",
            "to_currency",
        ).order_by("-rate_date")