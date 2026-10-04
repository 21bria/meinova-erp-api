"""
Service wilayah.

Sebelumnya keempatnya kelas polos dengan satu `list()` statis, dan itu
membawa dua akibat yang tidak terlihat di layar:

* **Baris terhapus tetap tampil.** `list()` tidak menyaring
  `is_deleted`, jadi yang dihapus lewat tombol Delete muncul lagi di
  daftar berikutnya — terbaca seperti penghapusan yang gagal tersimpan.
* **`perform_soft_delete()` tidak punya `soft_delete()` untuk
  dipanggil**, jadi jalur hapusnya jatuh ke penandaan langsung tanpa
  hook dan tanpa jejak audit.

Turunan `BaseMasterService` menutup keduanya sekaligus. `list()` tetap
wajib ditulis di sini: `BaseMasterViewSet` merakit querysetnya lewat
`service_class.list()`, dan `BaseMasterService` — berbeda dari
`BaseReferenceService` — memang tidak menyediakannya.
"""

from apps.administration.models import (
    City,
    Country,
    District,
    Province,
    Village,
)
from apps.core.services.master import BaseMasterService


class CountryService(BaseMasterService):
    model = Country

    @classmethod
    def list(cls):
        return cls.get_queryset().order_by("name")


class ProvinceService(BaseMasterService):
    model = Province

    @classmethod
    def list(cls):
        return (
            cls.get_queryset()
            .select_related("country")
            .order_by("name")
        )


class CityService(BaseMasterService):
    model = City

    @classmethod
    def list(cls):
        return (
            cls.get_queryset()
            .select_related(
                "province",
                "province__country",
            )
            .order_by("name")
        )


class DistrictService(BaseMasterService):
    model = District

    @classmethod
    def list(cls):
        return (
            cls.get_queryset()
            .select_related(
                "city",
                "city__province",
            )
            .order_by("name")
        )


class VillageService(BaseMasterService):
    model = Village

    @classmethod
    def list(cls):
        # Tiga tingkat induk ikut di-`select_related` karena serializer
        # memang mengirim ketiganya. Tanpa itu satu halaman berisi 20
        # kelurahan menembak 60 query tambahan — dan tabelnya berisi
        # puluhan ribu baris, jadi setiap halaman membayarnya lagi.
        return (
            cls.get_queryset()
            .select_related(
                "district",
                "district__city",
                "district__city__province",
            )
            .order_by("name")
        )
