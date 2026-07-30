# apps/administration/seeds/geography.py

COUNTRIES = [
    {
        "code": "ID",
        "name": "Indonesia",
        "phone_code": "+62",
        "currency_code": "IDR",
    },
    {
        "code": "SG",
        "name": "Singapore",
        "phone_code": "+65",
        "currency_code": "SGD",
    },
    {
        "code": "MY",
        "name": "Malaysia",
        "phone_code": "+60",
        "currency_code": "MYR",
    },
]

PROVINCES = [
    ("ID", "DKI", "DKI Jakarta"),
    ("ID", "JB", "Jawa Barat"),
    ("ID", "JT", "Jawa Tengah"),
    ("ID", "JI", "Jawa Timur"),
    ("ID", "BA", "Bali"),
]

CITIES = [
    ("DKI", "JKT", "Jakarta"),
    ("DKI", "JUS", "Jakarta Utara"),
    ("DKI", "JTM", "Jakarta Timur"),
    ("DKI", "JSL", "Jakarta Selatan"),
    ("DKI", "JBR", "Jakarta Barat"),

    ("JB", "BDG", "Bandung"),
    ("JB", "BKS", "Bekasi"),
    ("JB", "DPK", "Depok"),
    ("JB", "BGR", "Bogor"),

    ("JT", "SMG", "Semarang"),
    ("JT", "SLO", "Surakarta"),
    ("JT", "TGL", "Tegal"),

    ("JI", "SBY", "Surabaya"),
    ("JI", "MLG", "Malang"),
    ("JI", "KDR", "Kediri"),

    ("BA", "DPS", "Denpasar"),
]

from apps.administration.models import (
    Country,
    Province,
    City,
)

from .base import seed_reference


def seed_geography():
    # Country
    seed_reference(Country, COUNTRIES)

    # Province
    for country_code, code, name in PROVINCES:
        country = Country.objects.get(code=country_code)

        Province.objects.update_or_create(
            code=code,
            defaults={
                "country": country,
                "name": name,
                "is_active": True,
            },
        )

    # City
    for province_code, code, name in CITIES:
        province = Province.objects.get(code=province_code)

        City.objects.update_or_create(
            code=code,
            defaults={
                "province": province,
                "name": name,
                "is_active": True,
            },
        )