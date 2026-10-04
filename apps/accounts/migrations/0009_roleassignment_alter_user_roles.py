"""
Keanggotaan user-role jadi model eksplisit — **tanpa menyentuh data**.

`auth_users_roles` sudah ada sejak `0005_user_roles`, dibuat Django
sebagai tabel perantara M2M implisit. Bentuknya sudah persis yang
dibutuhkan: `id`, `user_id`, `role_id`, `UNIQUE(user_id, role_id)`.
Yang berubah di sini cuma **siapa yang mendeklarasikan tabel itu** —
dari Django, jadi `accounts.RoleAssignment` yang ditulis sendiri.

Karena itu `SeparateDatabaseAndState` dengan `database_operations`
**kosong**. Dijalankan apa adanya, `CreateModel` akan
`CREATE TABLE auth_users_roles` — dan tabel itu sudah ada berisi data;
`AlterField` pada M2M akan membuang lalu membuat ulang tabelnya, yang
artinya **seluruh keanggotaan hilang**. Dua-duanya cuma boleh berlaku
di state, tidak di database.

Yang membuat ini sah, dan bukan kebohongan yang kebetulan jalan:
model eksplisitnya sengaja dibuat identik dengan through model bikinan
Django — nama field `user`/`role` (jadi kolomnya `user_id`/`role_id`),
`id` `BigAutoField` (`DEFAULT_AUTO_FIELD`, identity bigint seperti yang
ada), dan `unique_together` alih-alih `UniqueConstraint` supaya nama
constraint yang dihasilkan sama persis. Satu-satunya selisih adalah
`related_name` pada kedua FK — Django memakai `'%s+'` (tanpa accessor
balik), kita memberi nama sungguhan — dan `related_name` tidak
menyentuh skema sama sekali.

Balikannya: `migrate accounts 0008`. Tidak ada data yang perlu
dipulihkan karena tidak ada data yang disentuh.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_user_language'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.CreateModel(
                    name='RoleAssignment',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('role', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='role_assignments', to='accounts.role')),
                        ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='role_assignments', to=settings.AUTH_USER_MODEL)),
                    ],
                    options={
                        'db_table': 'auth_users_roles',
                        'unique_together': {('user', 'role')},
                    },
                ),
                migrations.AlterField(
                    model_name='user',
                    name='roles',
                    field=models.ManyToManyField(blank=True, related_name='users', through='accounts.RoleAssignment', to='accounts.role'),
                ),
            ],
        ),
    ]
