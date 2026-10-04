# Rename master Site -> Location.
#
# Ditulis tangan, bukan hasil makemigrations: autodetector membaca
# perubahan ini sebagai "hapus model Site, buat model Location" karena
# target FK-nya ikut berubah — dan itu berarti seluruh isi master_site
# hilang. RenameModel/RenameField mempertahankan datanya.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        (
            "administration",
            "0010_alter_attendancestatus_code_alter_bank_code_and_more",
        ),
    ]

    operations = [
        migrations.RenameModel(
            old_name="SiteType",
            new_name="LocationType",
        ),
        migrations.AlterModelTable(
            name="locationtype",
            table="master_location_type",
        ),

        migrations.RenameModel(
            old_name="Site",
            new_name="Location",
        ),
        migrations.AlterModelTable(
            name="location",
            table="master_location",
        ),

        migrations.RenameField(
            model_name="location",
            old_name="site_type",
            new_name="location_type",
        ),

        migrations.RenameField(
            model_name="division",
            old_name="site",
            new_name="location",
        ),
        migrations.RenameField(
            model_name="department",
            old_name="site",
            new_name="location",
        ),
        migrations.RenameField(
            model_name="section",
            old_name="site",
            new_name="location",
        ),
        migrations.RenameField(
            model_name="position",
            old_name="site",
            new_name="location",
        ),
        migrations.RenameField(
            model_name="costcenter",
            old_name="site",
            new_name="location",
        ),

        migrations.RenameField(
            model_name="holiday",
            old_name="site",
            new_name="location",
        ),
        migrations.RenameField(
            model_name="workcalendar",
            old_name="site",
            new_name="location",
        ),

        migrations.RenameField(
            model_name="audittrail",
            old_name="site",
            new_name="location",
        ),

        migrations.RenameField(
            model_name="workflowdelegation",
            old_name="site",
            new_name="location",
        ),
        migrations.RenameField(
            model_name="workflowinstance",
            old_name="site",
            new_name="location",
        ),
    ]
