"""
Baris saldo awal yang sudah ada tetap berlaku.

Kolom `status` lahir dengan bawaan DRAFT, dan itu benar untuk baris
yang dibuat sesudah ini — import harus lewat Review dulu. Tapi bawaan
yang sama diterapkan ke baris **yang sudah ada**, dan baris-baris itu
sudah lama menyumbang angkanya ke kartu cuti orang: membiarkannya DRAFT
akan mengosongkan `opening_balance` seluruh tenant pada perhitungan
ulang berikutnya, tanpa satu pun pesan dan tanpa ada yang mengubah
datanya.

Jadi yang sudah ada ditandai POSTED. `posted_at` diisi dari
`created_at`-nya sendiri, bukan dari waktu migrasi dijalankan — yang
membaca jejaknya mencari kapan angka itu mulai berlaku, dan tanggal
migrasi tidak menjawab apa pun.
"""

from django.db import migrations


def post_existing(apps, schema_editor):
    model = apps.get_model("hr", "LeaveOpeningBalance")

    for row in model.objects.all().iterator():
        model.objects.filter(pk=row.pk).update(
            status="posted",
            posted_at=row.created_at,
            posted_by_id=row.created_by_id,
        )


def unpost(apps, schema_editor):
    model = apps.get_model("hr", "LeaveOpeningBalance")

    model.objects.all().update(
        status="draft",
        posted_at=None,
        posted_by=None,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("hr", "0047_leaveopeningbalance_posted_at_and_more"),
    ]

    operations = [
        migrations.RunPython(post_existing, unpost),
    ]
