from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("imports", "0004_importprofile_branch_importprofile_company_and_more"),
        ("administration", "0011_rename_site_to_location"),
    ]

    operations = [
        migrations.RenameField(
            model_name="importprofile",
            old_name="site",
            new_name="location",
        ),
    ]
