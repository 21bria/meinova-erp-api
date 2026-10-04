from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class Country(BaseModel):
    code = models.CharField(max_length=5)
    name = models.CharField(max_length=100)
    phone_code = models.CharField(max_length=10)
    currency_code = models.CharField(max_length=3)

    class Meta:
        db_table = "master_country"
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_administration_country_code",
            ),
        ]

    def __str__(self):
        return self.name


class Province(BaseModel):
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    aid = models.CharField(
        max_length=20,
        blank=True,
        default="",
        db_index=True,
        verbose_name="Area ID",
        help_text=(
            "Kode wilayah Kemendagri, disimpan persis seperti di sumber "
            "(mis. '11'). Ini identitas baris saat import — jangan "
            "diubah jadi angka, leading zero-nya bermakna."
        ),
    )
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
            # Dikondisikan ke `is_deleted` **dan** ke aid yang terisi.
            # Yang kedua wajib: baris lama hasil seed peragaan tidak
            # punya aid, dan tanpa syarat itu baris kedua yang aid-nya
            # kosong langsung ditolak constraint.
            models.UniqueConstraint(
                fields=["aid"],
                condition=Q(is_deleted=False) & ~Q(aid=""),
                name="uniq_active_administration_province_aid",
            ),
        ]

    def __str__(self):
        return f"{self.country.name} - {self.name}"


class City(BaseModel):
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    aid = models.CharField(
        max_length=20,
        blank=True,
        default="",
        db_index=True,
        verbose_name="Area ID",
        help_text=(
            "Kode wilayah Kemendagri, disimpan persis seperti di sumber "
            "(mis. '11.01'). Awalannya yang menentukan induk — bukan "
            "namanya."
        ),
    )
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
            models.UniqueConstraint(
                fields=["aid"],
                condition=Q(is_deleted=False) & ~Q(aid=""),
                name="uniq_active_administration_city_aid",
            ),
        ]

    def __str__(self):
        return f"{self.province.name} - {self.name}"


class District(BaseModel):
    """
    Kecamatan.

    Dipisah dari `City` sebagai model tersendiri, bukan kolom level di
    satu tabel datar: FK berjenjang itulah yang membuat penyaringan
    berantai di dropdown dan tabel bisa dijalankan database, dan yang
    membuat "kecamatan ini milik kabupaten mana" tidak pernah bergantung
    pada kemiripan nama.
    """

    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    aid = models.CharField(
        max_length=20,
        blank=True,
        default="",
        db_index=True,
        verbose_name="Area ID",
        help_text=(
            "Kode wilayah Kemendagri, disimpan persis seperti di sumber "
            "(mis. '11.01.01')."
        ),
    )
    city = models.ForeignKey(
        City,
        on_delete=models.PROTECT,
        related_name="districts",
    )

    class Meta:
        db_table = "master_district"
        ordering = ["city", "name"]
        verbose_name = "District"
        verbose_name_plural = "Districts"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "city",
                    "code",
                ],
                condition=Q(is_deleted=False),
                name="uniq_active_administration_district_city_code",
            ),
            models.UniqueConstraint(
                fields=["aid"],
                condition=Q(is_deleted=False) & ~Q(aid=""),
                name="uniq_active_administration_district_aid",
            ),
        ]

    def __str__(self):
        return f"{self.city.name} - {self.name}"


class Village(BaseModel):
    """
    Kelurahan/Desa — level terakhir, dan yang jumlahnya puluhan ribu.

    Karena itu `aid` dan FK induknya berindeks: seluruh jalur yang
    memakai tabel ini (import, dropdown berantai, pencarian) menyaring
    lewat salah satu dari keduanya.
    """

    code = models.CharField(max_length=20)
    name = models.CharField(max_length=150)
    aid = models.CharField(
        max_length=20,
        blank=True,
        default="",
        db_index=True,
        verbose_name="Area ID",
        help_text=(
            "Kode wilayah Kemendagri, disimpan persis seperti di sumber "
            "(mis. '11.01.01.2002')."
        ),
    )
    district = models.ForeignKey(
        District,
        on_delete=models.PROTECT,
        related_name="villages",
    )

    class Meta:
        db_table = "master_village"
        ordering = ["district", "name"]
        verbose_name = "Village"
        verbose_name_plural = "Villages"

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "district",
                    "code",
                ],
                condition=Q(is_deleted=False),
                name="uniq_active_administration_village_district_code",
            ),
            models.UniqueConstraint(
                fields=["aid"],
                condition=Q(is_deleted=False) & ~Q(aid=""),
                name="uniq_active_administration_village_aid",
            ),
        ]

    def __str__(self):
        return f"{self.district.name} - {self.name}"