"""
Penanda "sudah termasuk jatah tahun ini" dibuang.

Saldo awal punya satu arti sekarang: **saldo aktual pegawai pada tanggal
go-live**. Penanda per baris membuat angka yang sama berarti dua hal
berbeda tergantung siapa yang mengisi filenya, dengan bawaan yang justru
lebih jarang benar — dan enam bulan kemudian tidak ada cara tahu
keputusan mana yang diambil untuk sebuah baris.

Kolomnya di-drop, bukan dibiarkan menganggur: kolom yang tidak dibaca
siapa pun tapi masih bisa dicentang lewat API adalah kenop yang cepat
atau lambat dipakai orang, dan sesudah itu tidak berpengaruh apa-apa
tanpa satu pun pesan.

Akibatnya ke perhitungan ada di `0050` — baris yang tadinya penandanya
mati sekarang ikut memegang tahunnya, jadi jatah tahun itu tidak lagi
diterbitkan di atas saldo awalnya.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0048_post_existing_leave_opening_balances'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='leaveopeningbalance',
            name='replaces_entitlement',
        ),
    ]
