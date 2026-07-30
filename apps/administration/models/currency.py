from django.db import models

from apps.core.models.base import BaseModel


class Currency(BaseModel):
    code = models.CharField(max_length=3, unique=True)
    name = models.CharField(max_length=100)
    symbol = models.CharField(max_length=10)

    decimal_places = models.PositiveSmallIntegerField(default=2)

    is_base_currency = models.BooleanField(default=False)

    class Meta:
        db_table = "master_currency"
        ordering = ["code"]

    def __str__(self):
        return self.code


class ExchangeRate(BaseModel):
    class RateType(models.TextChoices):
        SPOT = "SPOT", "Spot"
        BUY = "BUY", "Buy"
        SELL = "SELL", "Sell"
        AVERAGE = "AVERAGE", "Average"

    from_currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name="rates_from",
    )

    to_currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name="rates_to",
    )

    rate_type = models.CharField(
        max_length=20,
        choices=RateType.choices,
        default=RateType.SPOT,
    )

    rate = models.DecimalField(
        max_digits=20,
        decimal_places=6,
    )

    rate_date = models.DateField()

    class Meta:
        db_table = "master_exchange_rate"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "from_currency",
                    "to_currency",
                    "rate_type",
                    "rate_date",
                ],
                name="uniq_exchange_rate",
            ),
        ]
        ordering = ["-rate_date"]

    def __str__(self):
        return (
            f"{self.from_currency.code} → "
            f"{self.to_currency.code} "
            f"({self.rate_date})"
        )