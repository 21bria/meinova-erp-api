# `RoleDataPermission.resource_type` menyimpan nilai choices sebagai
# teks, jadi baris lama masih berisi "site" setelah master-nya berganti
# nama. Tanpa migrasi ini, permission tersebut tidak akan pernah cocok
# dengan resource "location" mana pun — gagal diam-diam, bukan error.

from django.db import migrations


def site_to_location(apps, schema_editor):
    RoleDataPermission = apps.get_model(
        "accounts",
        "RoleDataPermission",
    )

    RoleDataPermission.objects.filter(
        resource_type="site",
    ).update(
        resource_type="location",
    )


def location_to_site(apps, schema_editor):
    RoleDataPermission = apps.get_model(
        "accounts",
        "RoleDataPermission",
    )

    RoleDataPermission.objects.filter(
        resource_type="location",
    ).update(
        resource_type="site",
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_alter_roledatapermission_resource_type"),
    ]

    operations = [
        migrations.RunPython(
            site_to_location,
            location_to_site,
        ),
    ]
