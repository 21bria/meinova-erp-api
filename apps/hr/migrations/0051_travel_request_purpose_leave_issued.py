"""
`TravelRequestPurpose.leave_issued` — menandai baris yang catatan
cutinya benar-benar terbit dari dokumen ini.

Baris yang sudah ada di lapangan tidak bisa dibedakan dari tautannya
saja, tapi cuti terbitan Travel Request selalu diberi catatan
"Diterbitkan otomatis dari ..." oleh `issue_leave_records`. Itu yang
dipakai mengisi ulang nilai lama. Yang tidak cocok dibiarkan `False` —
lebih baik satu pembatalan tidak menyentuh catatan cuti yang mungkin
miliknya sendiri daripada membatalkan catatan cuti milik HR.
"""

from django.db import migrations, models


ISSUED_MARKER = "Diterbitkan otomatis dari"


def mark_issued_rows(apps, schema_editor):
    TravelRequestPurpose = apps.get_model("hr", "TravelRequestPurpose")

    (
        TravelRequestPurpose.objects
        .filter(
            employee_leave__isnull=False,
            employee_leave__notes__startswith=ISSUED_MARKER,
        )
        .update(leave_issued=True)
    )


def unmark_issued_rows(apps, schema_editor):
    """Kolomnya ikut hilang saat mundur; tidak ada yang perlu dipulihkan."""


class Migration(migrations.Migration):

    dependencies = [
        ('hr', '0050_align_entitlement_with_opening_balance'),
    ]

    operations = [
        migrations.AddField(
            model_name='travelrequestpurpose',
            name='leave_issued',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_issued_rows, unmark_issued_rows),
    ]
