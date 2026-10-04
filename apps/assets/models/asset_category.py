from django.db import models

from apps.core.models.base_reference import BaseReference


class AssetCategory(BaseReference):
    """
    Klasifikasi **operasional** aset — Laptop, Radio/HT, Light Vehicle.

    Master data, bukan enum: daftar kategori milik tenant, dan tidak ada
    satu baris kode pun yang boleh mencocokkan kode kategori untuk
    memutuskan perilaku.

    **Berlaku untuk seluruh tenant, tanpa company.** "Laptop" di MMN dan
    "Laptop" di MIN adalah kategori yang sama; yang berbeda per company
    adalah asetnya (`Asset.company`) dan — kelak — pemetaan akunnya di
    Finance. Memberi kategori kolom company akan memaksa tiap company
    menduplikasi daftar yang sama, dan Entitlement Policy lintas company
    jadi tidak bisa menyebut satu kategori.

    **Tidak membawa satu pun atribut akuntansi** — akun, masa manfaat,
    metode penyusutan, ambang kapitalisasi. Kategori ini dipakai juga
    untuk barang yang tidak pernah dikapitalisasi; klasifikasi akuntansi
    milik tahap Fixed Asset Accounting. Kontraknya:
    `docs/claude/assets.md` §5.
    """

    # Dibaca saat aset diaktifkan: aset berkategori ini tidak bisa
    # aktif tanpa serial number. Tidak berlaku surut — aset yang sudah
    # aktif tidak menjadi tidak sah ketika saklarnya dinyalakan.
    requires_serial_number = models.BooleanField(default=False)

    # Jenis custody pemakaian yang diizinkan — data, bukan nama kategori.
    # Dua saklar, bukan satu pilihan: HT dan GPS boleh dipegang pegawai
    # **maupun** unit, dan satu field pilihan-tunggal membuat itu tidak
    # bisa dinyatakan. STORAGE selalu boleh (keadaan internal pemilik).
    # Bawaannya keduanya hidup: belum dikonfigurasi = tidak membatasi.
    allow_employee_custody = models.BooleanField(default=True)
    allow_organization_custody = models.BooleanField(default=True)

    class Meta(BaseReference.Meta):
        db_table = "assets_asset_category"
        verbose_name = "Asset Category"
        verbose_name_plural = "Asset Categories"

        constraints = [
            *BaseReference.Meta.constraints,
            # Kategori yang tidak bisa dipakai sama sekali bukan
            # konfigurasi, itu salah ketik.
            models.CheckConstraint(
                condition=(
                    models.Q(allow_employee_custody=True)
                    | models.Q(allow_organization_custody=True)
                ),
                name="ck_assets_category_some_custody",
            ),
        ]
