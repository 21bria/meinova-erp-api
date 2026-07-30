from django.db import models

from apps.core.models import BaseModel


class Country(BaseModel):
    code = models.CharField(max_length=5,unique=True)
    name = models.CharField(max_length=100)
    phone_code = models.CharField(max_length=10)
    currency_code = models.CharField(max_length=3)

    class Meta:
        db_table = "master_country"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Province(BaseModel):
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    country = models.ForeignKey(
        Country,
        on_delete=models.DO_NOTHING,
        related_name="provinces",
    )

    class Meta:
        db_table = "master_province"
        ordering = ["country","name"]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "country",
                    "code",
                ],
                name="uniq_master_province_country_code",
            ),
        ]

    def __str__(self):
        return f"{self.country.name} - {self.name}"


class City(BaseModel):
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    province = models.ForeignKey( Province,on_delete=models.DO_NOTHING,related_name="cities" )

    class Meta:
        db_table = "master_city"
        ordering = ["province","name"]
        
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "province",
                    "code",
                ],
                name="uniq_master_city_province_code",
            ),
        ]

    def __str__(self):
        return f"{self.province.name} - {self.name}"