# Ikutan rename master Site -> Location di administration.
# Sama seperti di sana: RenameField supaya isinya tidak hilang.

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0012_alter_attendanceimportprofile_code_and_more"),
        ("administration", "0011_rename_site_to_location"),
    ]

    operations = [
        migrations.RenameField(
            model_name="organizationassignment",
            old_name="site",
            new_name="location",
        ),
        migrations.RenameField(
            model_name="attendancedevice",
            old_name="site",
            new_name="location",
        ),
        migrations.RenameField(
            model_name="attendancelog",
            old_name="site",
            new_name="location",
        ),
        migrations.RenameField(
            model_name="employeeattendance",
            old_name="site",
            new_name="location",
        ),
        migrations.RenameField(
            model_name="attendanceimportprofile",
            old_name="site",
            new_name="location",
        ),
    ]
