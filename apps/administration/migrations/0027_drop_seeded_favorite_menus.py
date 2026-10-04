"""
Membuang pintasan beranda hasil seed lama.

`seed_favorite_menus` menuliskan lima baris `FavoriteMenu` untuk setiap
pengguna, dengan kode buatannya sendiri (`employee-master`, `attendance`,
…). Katalog pintasan sekarang tabel `Menu`, yang kodenya diturunkan dari
route (`hr.employees`, `hr.attendance`, …) — jadi baris lama itu tidak
menunjuk apa pun lagi.

Membiarkannya justru merusak: pembeda "belum pernah menyusun" adalah
**tidak adanya baris**, sehingga pengguna yang pernah kena seed akan
terbaca sebagai sudah menyusun, dan bagian Favorite Menus-nya kosong
tanpa satu pun pintasan bawaan.

Hard delete: ini preferensi tampilan, tidak ada jejak yang perlu
disimpan — dan `uniq_favorite_menu_user_code` tidak dikondisikan ke
`is_deleted`, jadi baris bertanda terhapus justru menghalangi
penyimpanan berikutnya.

Tidak ada yang hilang buat pengguna: kelimanya memang bawaan, dan
bawaannya sekarang muncul sendiri tanpa baris di database.
"""

from django.db import migrations


# Kode yang hanya bisa lahir dari seed. Baris di luar daftar ini
# dibiarkan — endpoint `POST` lama menerima kode bebas dari klien, dan
# menebak mana yang buatan orang bukan tugas migrasi.
SEEDED_CODES = [
    "employee-master",
    "attendance",
    "leave",
    "travel-request",
    "approval-inbox",

    # Sempat diseed lalu ditarik karena halamannya tidak pernah ada.
    "payroll-run",
    "purchase-request",
    "journal-entry",
]


def drop_seeded(apps, schema_editor):
    FavoriteMenu = apps.get_model("administration", "FavoriteMenu")

    FavoriteMenu.objects.filter(menu_code__in=SEEDED_CODES).delete()


def noop(apps, schema_editor):
    """
    Tidak dikembalikan.

    Isinya susunan bawaan yang sekarang diturunkan saat dibaca; menulis
    ulang barisnya saat rollback justru mengembalikan keadaan yang
    sedang diperbaiki.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("administration", "0026_roster_policy_cycle_pattern"),
    ]

    operations = [
        migrations.RunPython(drop_seeded, noop),
    ]
