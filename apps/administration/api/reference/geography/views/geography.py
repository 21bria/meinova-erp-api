"""
Lima tingkat wilayah, lima layar bertab.

**Bukan satu tabel yang mencampur seluruh tingkat.** Menggabungkannya
berarti satu kolom "level" plus satu kolom "parent" yang artinya berubah
per baris, dan pencarian yang mengembalikan provinsi, kabupaten, dan
kelurahan berjejer tanpa cara membedakannya. Tiap tingkat punya
tabel, pencarian, dan filternya sendiri.

Penyaringan berantai dipasang di **filter toolbar**, mengikuti hierarki:
memilih Province menyempitkan dropdown Kabupaten/Kota, memilih
Kabupaten/Kota menyempitkan Kecamatan, dan seterusnya. Dua hal yang
harus ada bersamaan untuk itu, dan yang lupa salah satunya gagal tanpa
suara:

* `lookup_params` pada schema — yang menyaring isi dropdown-nya;
* nama parameternya terdaftar di `filter_fields` lookup tujuan —
  parameter yang tidak terdaftar **diabaikan diam-diam**, dan dropdown
  tetap menampilkan seluruh tenant.

Ditambah `filterset_fields` di viewset: `filter=True` pada schema hanya
menampilkan filternya di UI. Tanpa pemetaan di sini, parameternya
diterima lalu diabaikan — dan hasil yang tidak menyempit tidak bisa
dibedakan dari data yang memang seperti itu.
"""

from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.reference.geography.serializers.geography import (
    CitySerializer,
    CountrySerializer,
    DistrictSerializer,
    ProvinceSerializer,
    VillageSerializer,
)
from apps.administration.api.reference.geography.services.geography_service import (
    CityService,
    CountryService,
    DistrictService,
    ProvinceService,
    VillageService,
)


LOOKUP_BASE = "/api/administration/references/geography/lookup"


def _endpoint(slug: str) -> str:
    return f"/api/administration/references/geography/{slug}/"


def _aid_field(order: int, example: str) -> dict:
    """
    Kolom kode wilayah, sama bentuknya di keempat tingkat.

    Read-only di form: `aid` adalah identitas baris saat import, dan
    mengubahnya lewat form berarti baris itu tidak lagi dikenali oleh
    berkas sumbernya — import berikutnya akan membuat duplikatnya.
    """

    return {
        "label": "Area ID",
        "form": True,
        "table": True,
        "filter": False,
        "display": True,
        "placeholder": f"e.g. {example}",
        "help_text": (
            "Kode wilayah Kemendagri. Diisi otomatis oleh import dan "
            "dipakai sebagai identitas baris — jangan diubah manual."
        ),
        "order": order,
    }


def _is_active_field() -> dict:
    return {
        "label": "Active",
        "form": True,
        "table": True,
        "filter": True,
        "placement": "quick",
        "order": 999,
    }


def country_schema(slug):
    return {
        "endpoint": _endpoint(slug),
        "ui": {
            "editor": "dialog",
            "size": "md",
            "columns": 2,
        },
        "fields": {
            "code": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. ID",
                "order": 10,
            },
            "name": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "Country name",
                "order": 20,
            },
            "phone_code": {
                "label": "Phone Code",
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. +62",
                "order": 30,
            },
            "currency_code": {
                "label": "Currency Code",
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. IDR",
                "order": 40,
            },
            "is_active": _is_active_field(),
        },
    }


def province_schema(slug):
    return {
        "endpoint": _endpoint(slug),
        "ui": {
            "editor": "dialog",
            "size": "md",
            "columns": 2,
        },
        "fields": {
            "country": {
                "label": "Country",
                "lookup_endpoint": f"{LOOKUP_BASE}/countries/",
                "display_key": "country_name",
                "filter": True,
                "placement": "quick",
                "order": 10,
            },
            "aid": _aid_field(15, "11"),
            "code": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. 11",
                "order": 20,
            },
            "name": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "Province name",
                "order": 30,
            },
            "is_active": _is_active_field(),
        },
    }


def city_schema(slug):
    return {
        "endpoint": _endpoint(slug),
        "ui": {
            "editor": "dialog",
            "size": "md",
            "columns": 2,
        },
        "fields": {
            "province": {
                "label": "Province",
                "lookup_endpoint": f"{LOOKUP_BASE}/provinces/",
                "display_key": "province_name",
                "filter": True,
                "placement": "quick",
                "order": 10,
            },
            "aid": _aid_field(15, "11.01"),
            "code": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. 11.01",
                "order": 20,
            },
            "name": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "Kabupaten/Kota name",
                "order": 30,
            },
            "is_active": _is_active_field(),
        },
    }


def district_schema(slug):
    return {
        "endpoint": _endpoint(slug),
        "ui": {
            "editor": "dialog",
            "size": "md",
            "columns": 2,
        },
        "fields": {
            # Province bukan kolom model District — ia disaring lewat
            # `city__province`, dan ada di **dua** tempat: toolbar filter
            # dan form.
            #
            # Di toolbar, supaya rantai filternya bisa dimulai dari atas:
            # tanpa itu, menyaring 7.277 kecamatan berarti memilih dari
            # 514 kabupaten sekaligus.
            #
            # Di form ia **wajib** ada, dan itu bukan kenyamanan.
            # `depends_on` pada field Kabupaten/Kota di bawah menonaktifkan
            # field itu selama induknya kosong — dan induk yang tidak
            # pernah dirender tidak akan pernah terisi. Akibatnya field
            # Kabupaten/Kota terkunci selamanya, dan karena ia wajib,
            # Kecamatan tidak bisa dibuat dari layar mana pun. Gagalnya
            # diam: dropdown-nya tampil normal, cuma tidak bisa dibuka.
            #
            # `read_only: False` menimpa hasil introspeksi. Serializer
            # memang mengirimnya read-only — nilainya diabaikan saat
            # menyimpan, karena yang menentukan induk tetap `city` — tapi
            # generator membaca `read_only` sebagai "kunci field ini", dan
            # penyaring yang terkunci sama saja dengan tidak ada.
            "city__province": {
                "label": "Province",
                "type": "lookup",
                "lookup_endpoint": f"{LOOKUP_BASE}/provinces/",
                "form": True,
                "display": True,
                "read_only": False,
                "required": False,
                "table": False,
                "filter": True,
                "placement": "quick",
                "help_text": (
                    "Menyaring pilihan Kabupaten/Kota. Tidak disimpan — "
                    "induk yang tersimpan adalah Kabupaten/Kota."
                ),
                "order": 5,
            },
            "city": {
                "label": "Kabupaten/Kota",
                "lookup_endpoint": f"{LOOKUP_BASE}/cities/",
                "display_key": "city_name",
                "depends_on": ["city__province"],
                "lookup_params": {
                    "province_id": "$city__province",
                },
                "filter": True,
                "placement": "quick",
                "order": 10,
            },
            "aid": _aid_field(15, "11.01.01"),
            "code": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. 11.01.01",
                "order": 20,
            },
            "name": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "Kecamatan name",
                "order": 30,
            },
            "is_active": _is_active_field(),
        },
    }


def village_schema(slug):
    return {
        "endpoint": _endpoint(slug),
        "ui": {
            "editor": "dialog",
            "size": "md",
            "columns": 2,
        },
        "fields": {
            # Lihat catatan panjang `city__province` di `district_schema`
            # — alasannya sama persis, satu tingkat di bawahnya. Di sini
            # akibatnya lebih parah kalau dilewatkan: tanpa penyaring ini
            # yang membuat Kelurahan harus memilih satu dari 7.277
            # kecamatan sekaligus.
            "district__city": {
                "label": "Kabupaten/Kota",
                "type": "lookup",
                "lookup_endpoint": f"{LOOKUP_BASE}/cities/",
                "form": True,
                "display": True,
                "read_only": False,
                "required": False,
                "table": False,
                "filter": True,
                "placement": "quick",
                "help_text": (
                    "Menyaring pilihan Kecamatan. Tidak disimpan — induk "
                    "yang tersimpan adalah Kecamatan."
                ),
                "order": 5,
            },
            "district": {
                "label": "Kecamatan",
                "lookup_endpoint": f"{LOOKUP_BASE}/districts/",
                "display_key": "district_name",
                "depends_on": ["district__city"],
                "lookup_params": {
                    "city_id": "$district__city",
                },
                "filter": True,
                "placement": "quick",
                "order": 10,
            },
            "aid": _aid_field(15, "11.01.01.2002"),
            "code": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. 11.01.01.2002",
                "order": 20,
            },
            "name": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "Kelurahan/Desa name",
                "order": 30,
            },
            "is_active": _is_active_field(),
        },
    }


class CountryViewSet(BaseMasterViewSet):
    serializer_class = CountrySerializer
    service_class = CountryService

    ordering = ["name"]
    search_fields = ["code", "name", "phone_code", "currency_code"]
    filterset_fields = ["is_active"]
    framework_module = "references/geography/countries"
    schema = country_schema("countries")


class ProvinceViewSet(BaseMasterViewSet):
    serializer_class = ProvinceSerializer
    service_class = ProvinceService

    ordering = ["country__name", "name"]
    search_fields = ["code", "aid", "name", "country__name"]
    filterset_fields = ["country", "is_active"]
    framework_module = "references/geography/provinces"
    schema = province_schema("provinces")


class CityViewSet(BaseMasterViewSet):
    serializer_class = CitySerializer
    service_class = CityService

    ordering = ["province__country__name", "province__name", "name"]
    search_fields = [
        "code",
        "aid",
        "name",
        "province__name",
        "province__country__name",
    ]
    filterset_fields = [
        "province",
        "province__country",
        "is_active",
    ]
    framework_module = "references/geography/cities"
    schema = city_schema("cities")


class DistrictViewSet(BaseMasterViewSet):
    serializer_class = DistrictSerializer
    service_class = DistrictService

    ordering = ["city__province__name", "city__name", "name"]
    search_fields = [
        "code",
        "aid",
        "name",
        "city__name",
        "city__province__name",
    ]
    filterset_fields = [
        "city",
        "city__province",
        "is_active",
    ]
    framework_module = "references/geography/districts"
    schema = district_schema("districts")


class VillageViewSet(BaseMasterViewSet):
    serializer_class = VillageSerializer
    service_class = VillageService

    ordering = ["district__city__name", "district__name", "name"]
    search_fields = [
        "code",
        "aid",
        "name",
        "district__name",
        "district__city__name",
    ]
    filterset_fields = [
        "district",
        "district__city",
        "is_active",
    ]
    framework_module = "references/geography/villages"
    schema = village_schema("villages")
