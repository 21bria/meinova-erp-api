"""
Kelompok artikel panduan — "Getting Started", "Cuti & Absensi", dst.

Sengaja **satu tingkat**, tanpa sub-kategori. Panduan yang bersarang
dua tingkat memaksa pembacanya membuka dua pintu sebelum sampai ke
kalimat yang dicarinya, dan tidak ada satu pun help center yang
membaik karena itu. Kalau sebuah kategori sudah terlalu panjang,
pecah jadi dua kategori — bukan jadi induk dan anak.
"""

from django.db import models

from apps.core.models.base_reference import BaseReference


class HelpCategory(BaseReference):
    """
    Satu kelompok panduan di sidebar Help Center.

    Turunan `BaseReference`, jadi sudah membawa `code` (unik per
    tenant, dikondisikan ke `is_deleted`), `name`, `description`, dan
    `sort_order`.
    """

    icon = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text=(
            "Nama ikon bergaya Nuxt UI, mis. `i-lucide-rocket`. "
            "Nama yang tidak dikenal jatuh ke ikon bawaan tanpa error."
        ),
    )

    # Dipakai menyaring panduan yang relevan dengan modul yang sedang
    # dibuka pengguna (tombol Help kontekstual). Dikosongkan = panduan
    # umum yang tidak menempel ke modul mana pun.
    module = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text=(
            "Modul yang dijelaskan kategori ini (`hr`, `payroll`, "
            "`administration`). Dikosongkan = panduan umum."
        ),
    )

    is_published = models.BooleanField(
        default=True,
        help_text=(
            "Dimatikan: kategori beserta seluruh artikelnya hilang "
            "dari Help Center, tapi tetap bisa disunting di sini."
        ),
    )

    # `class Meta(BaseReference.Meta)`, bukan `class Meta:` polos —
    # tanpa pewarisan itu constraint unik `code` dan `ordering`-nya
    # tidak ikut terbawa.
    class Meta(BaseReference.Meta):
        verbose_name = "Help Category"
        verbose_name_plural = "Help Categories"

    def __str__(self) -> str:
        return self.name
