"""
Service kategori aset.

Disusun dari dua kelas dasar yang sudah ada, bukan ditulis ulang:

* `BaseReferenceService` — normalisasi `code` (trim + huruf besar),
  trim `name`, keunikan kode tanpa membedakan huruf di antara baris
  yang belum dihapus, dan `list()` yang dipakai `BaseMasterViewSet`;
* `BaseMasterService` — `soft_delete()`/`restore()` beserta jejak
  auditnya. Tanpa ini `perform_soft_delete()` jatuh ke penandaan
  langsung tanpa hook dan tanpa audit.

Urutannya penting: `BaseReferenceService` di depan supaya normalisasinya
jalan lebih dulu, lalu `super()` meneruskan ke hook `BaseMasterService`.
"""

from django.core.exceptions import ValidationError

from apps.assets.models import Asset, AssetCategory
from apps.core.services import (
    BaseMasterService,
    BaseReferenceService,
)


class AssetCategoryService(BaseReferenceService, BaseMasterService):
    model = AssetCategory

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        # Aset yang belum dihapus tetap menunjuk kategorinya (FK
        # PROTECT hanya menjaga hard delete). Menghapus kategori yang
        # masih dipakai membuat aset itu berkategori "tidak ada" di
        # setiap layar dan laporan.
        in_use = Asset.objects.filter(
            category=instance,
            is_deleted=False,
        ).count()

        if in_use:
            raise ValidationError({
                "category": (
                    f"Kategori ini masih dipakai {in_use} aset. Pindahkan "
                    "atau hapus aset DRAFT-nya dulu, atau nonaktifkan "
                    "kategorinya."
                ),
            })
