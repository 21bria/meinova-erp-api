"""
Serializer wilayah.

Tiap tingkat mengirim **nama induknya** sebagai kolom turunan
(`province_name`, `city_name`, …). Itu bukan kerapian: generator kolom
di frontend memetakan field lookup ke `<field>_name`, dan serializer yang
cuma `fields = "__all__"` tidak pernah mengirimnya — kolomnya tampil "-"
di semua baris tanpa satu pun pesan error. Tabel Kabupaten/Kota sudah
kena persis itu: kolom Province kosong di seluruh 514 barisnya.

Kolom `*_aid` ikut dikirim supaya penelusuran "kenapa kecamatan ini
duduk di kabupaten itu" bisa dijawab dari layar, tanpa membuka database.
"""

from rest_framework import serializers

from apps.administration.models import (
    City,
    Country,
    District,
    Province,
    Village,
)


class CountrySerializer(serializers.ModelSerializer):
    class Meta:
        model = Country
        fields = "__all__"


class ProvinceSerializer(serializers.ModelSerializer):
    country_name = serializers.CharField(
        source="country.name",
        read_only=True,
    )

    class Meta:
        model = Province
        fields = "__all__"


class CitySerializer(serializers.ModelSerializer):
    province_name = serializers.CharField(
        source="province.name",
        read_only=True,
    )
    province_aid = serializers.CharField(
        source="province.aid",
        read_only=True,
    )
    country_name = serializers.CharField(
        source="province.country.name",
        read_only=True,
    )

    class Meta:
        model = City
        fields = "__all__"


class DistrictSerializer(serializers.ModelSerializer):
    city_name = serializers.CharField(
        source="city.name",
        read_only=True,
    )
    # Induk-dari-induk, dikirim sebagai id.
    #
    # Ini yang mengisi penyaring "Province" di form saat sebuah baris
    # dibuka untuk disunting. Tanpa itu penyaringnya kosong, dan field
    # Kabupaten/Kota yang bergantung padanya ikut terkunci — jadi
    # Kecamatan yang sudah tersimpan tidak bisa dipindah ke kabupaten
    # lain dari layar mana pun.
    #
    # `city.province_id`, bukan `city.province`: `select_related("city")`
    # sudah membawa kolomnya, jadi tidak ada query tambahan per baris.
    city__province = serializers.IntegerField(
        source="city.province_id",
        read_only=True,
    )
    city_aid = serializers.CharField(
        source="city.aid",
        read_only=True,
    )
    province_name = serializers.CharField(
        source="city.province.name",
        read_only=True,
    )

    class Meta:
        model = District
        fields = "__all__"


class VillageSerializer(serializers.ModelSerializer):
    district_name = serializers.CharField(
        source="district.name",
        read_only=True,
    )
    # Lihat catatan `city__province` di DistrictSerializer — alasannya
    # sama persis, satu tingkat di bawahnya.
    district__city = serializers.IntegerField(
        source="district.city_id",
        read_only=True,
    )
    district_aid = serializers.CharField(
        source="district.aid",
        read_only=True,
    )
    city_name = serializers.CharField(
        source="district.city.name",
        read_only=True,
    )
    province_name = serializers.CharField(
        source="district.city.province.name",
        read_only=True,
    )

    class Meta:
        model = Village
        fields = "__all__"
