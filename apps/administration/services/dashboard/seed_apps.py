"""
Menuliskan susunan aplikasi bawaan ke tiap pengguna.

**Daftarnya tidak lagi ditulis di sini.** Sebelumnya berkas ini memuat
salinannya sendiri — sembilan aplikasi, empat di antaranya
(`manufacturing`, `crm`, `reports`, dan `assets`) tidak punya halaman di
Nuxt sama sekali, jadi kartunya mendarat di 404. Sekarang satu-satunya
sumbernya `apps/administration/api/dashboard/catalog.py`, yang juga
dipakai endpoint katalog dan susunan bawaan; dua daftar untuk barang
yang sama pasti berbeda pada akhirnya, dan bedanya baru ketahuan saat
ada yang mengklik kartu yang salah.

Perlu diketahui: **seed ini tidak wajib lagi.** Pengguna yang belum
pernah menyusun sendiri sudah mendapat susunan bawaan langsung dari
katalog tanpa satu baris pun di database. Perintahnya dipertahankan
untuk memaksakan susunan awal ke akun yang sudah ada — mis. setelah
katalognya berubah.
"""

from django.contrib.auth import get_user_model

from apps.administration.api.dashboard.catalog import DEFAULT_CODES
from apps.administration.api.dashboard.services.favorite_app_service import (
    FavoriteAppService,
)


User = get_user_model()


def seed_favorite_apps():
    seeded = 0

    for user in User.objects.all():
        FavoriteAppService.set_favorites(user, DEFAULT_CODES)

        seeded += 1

    return {
        "users": seeded,
        "apps": len(DEFAULT_CODES),
    }
