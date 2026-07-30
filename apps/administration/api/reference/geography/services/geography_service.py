from apps.administration.models import Country, Province, City


class CountryService:
    @staticmethod
    def list():
        return Country.objects.order_by("name")


class ProvinceService:
    @staticmethod
    def list():
        return Province.objects.select_related("country").order_by("name")


class CityService:
    @staticmethod
    def list():
        return City.objects.select_related("province", "province__country").order_by("name")