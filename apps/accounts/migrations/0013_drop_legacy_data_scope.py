"""
Gelombang C — skema cakupan lama dihapus.

Yang dibuang di sini bukan fitur melainkan **jalur kedua**. Sampai
Stage 4H ada dua tempat yang bisa menjawab "baris mana yang boleh
dilihat orang ini": konfigurasi cakupan pada `Role` dan kewenangan pada
`RoleAssignment`. Dua sumber kebenaran untuk satu pertanyaan keamanan
adalah bentuk yang paling mudah salah dibaca, dan yang lama gagal ke
arah yang salah: `explicit` tanpa satu pun baris berarti **tanpa
batasan**, jadi daftar yang lupa diisi membuka seluruh tenant.

Sejak Stage 4H tidak ada satu pun kode runtime yang membacanya —
dibuktikan dari SQL yang benar-benar dijalankan, bukan dari daftar
import. Yang tersisa kolom dan tabel yang tidak menahan apa pun, dan
justru itu yang berbahaya: skema yang terlihat seperti kebijakan tapi
tidak menentukan apa pun akan dibaca sebagai kebijakan oleh orang
berikutnya.

**Tidak bisa dibalik, dan itu jujur.** `RemoveField`/`DeleteModel`
punya balikan bawaan yang membuat kolom dan tabelnya kembali — kosong.
Isinya tidak bisa dikembalikan, jadi memutar balik migration ini
memulihkan bentuknya tanpa memulihkan artinya. Yang memulihkan akses
kalau ada yang salah bukan balikan ini melainkan cadangan database
sebelum penerapan; lihat runbook penerapan.

**Prasyarat yang harus dijalankan di tiap database sebelum ini
diterapkan** — termasuk produksi:

    manage.py audit_authority_hygiene

Tiap tenant harus bersih. Penugasan yang kewenangannya belum dinyatakan
tidak akan kehilangan akses karena migration ini (runtime sudah
menutupnya sejak 4G), tapi sesudah tabel lamanya hilang, kewenangan itu
tidak bisa lagi diturunkan dari mana pun — satu-satunya jalan
menyatakannya lewat layar Kewenangan.

Migration 0011 dan 0012 tetap menyebut `RoleDataPermission` lewat
`apps.get_model()`. Itu model **historis**, yang hidup di state
migration masing-masing dan tidak terpengaruh penghapusan di sini —
bukan ketergantungan pada kode aplikasi. Keduanya dibekukan di Stage 4J
persis supaya penghapusan ini tidak menggagalkan pembuatan tenant baru,
yang memutar ulang seluruh rantai.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0012_close_blank_assignment_authority'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='roledatapermission',
            name='uniq_accounts_role_data_permission',
        ),
        migrations.RemoveConstraint(
            model_name='userdatapermission',
            name='uniq_accounts_user_data_permission',
        ),
        migrations.RemoveField(
            model_name='role',
            name='data_scope_level',
        ),
        migrations.RemoveField(
            model_name='role',
            name='data_scope_mode',
        ),
        migrations.RemoveField(
            model_name='userdatapermission',
            name='created_by',
        ),
        migrations.RemoveField(
            model_name='userdatapermission',
            name='deleted_by',
        ),
        migrations.RemoveField(
            model_name='userdatapermission',
            name='updated_by',
        ),
        migrations.RemoveField(
            model_name='userdatapermission',
            name='user',
        ),
        migrations.DeleteModel(
            name='RoleDataPermission',
        ),
        migrations.DeleteModel(
            name='UserDataPermission',
        ),
    ]
