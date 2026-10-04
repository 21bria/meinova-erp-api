"""
Mengisi `scope` untuk baris Work Calendar dan Holiday yang sudah ada.

**Tidak mengubah perilaku satu baris pun.** Yang dilakukan cuma
menyatakan cakupan yang selama ini tersirat dari kolom yang terisi:
baris yang menyebut location adalah LOCATION, sisanya COMPANY. Tidak
ada baris yang dinaikkan jadi GLOBAL di sini — menaikkannya berarti
kalender satu perusahaan mendadak berlaku untuk seluruh tenant, dan
itu keputusan yang harus dibaca orang lebih dulu.

Penggabungan duplikat yang sesungguhnya (`OFFICE-2026` × 3 perusahaan
→ satu baris GLOBAL) ada di command terpisah:

    python manage.py collapse_calendar_duplicates --dry-run

Dipisah dengan sengaja. Migration berjalan otomatis saat deploy, dan
penggabungan itu **mengubah hari kerja** bagi siapa pun yang datanya
ternyata tidak seidentik yang terlihat. Yang mengubah hari kerja harus
dijalankan orang yang sudah membaca laporan selisihnya, bukan oleh
`migrate`.
"""

from django.db import migrations


def backfill(apps, schema_editor):
    WorkCalendar = apps.get_model("administration", "WorkCalendar")
    Holiday = apps.get_model("administration", "Holiday")

    for model in (WorkCalendar, Holiday):
        # Yang menyebut lokasi memang selalu berarti "hanya di lokasi
        # ini" — itu satu-satunya arti kolom itu sebelum ada `scope`.
        model.objects.filter(location__isnull=False).update(
            scope="LOCATION",
        )

        model.objects.filter(location__isnull=True).update(
            scope="COMPANY",
        )


def unbackfill(apps, schema_editor):
    # `scope` ikut hilang saat migration sebelumnya dibalik; tidak ada
    # yang perlu dikembalikan di sini.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("administration", "0040_holidaycompany_and_more"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
