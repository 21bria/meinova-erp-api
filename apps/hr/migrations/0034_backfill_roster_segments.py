"""
Mengisi kolom roster yang baru untuk data yang sudah ada.

Tiga hal, dan yang ketiga sengaja **tidak** dilakukan:

1. `RotationPeriod.segment_type` diturunkan dari `period_type`.
   `work` → WORK, `off` → FIELD_BREAK. Baris travel tidak ada yang
   perlu dipetakan: sebelum ini hari perjalanan memang cuma celah
   kalender tanpa baris.

2. `EmploymentAssignment.roster_cycle_start` diisi dari jangkar yang
   sudah dipakai perhitungan cuti hari ini — `roster_start_override`
   dulu, baru `RosterCrew.cycle_start_date`. Itu arti "override", dan
   urutannya harus sama persis dengan `LeaveDayCalculator.resolve_roster()`
   supaya angka hari cuti tidak berubah diam-diam.

3. **`roster_policy` TIDAK ditebak.** Memetakan pegawai ke policy
   berdasarkan pola crew-nya terdengar masuk akal sampai ada dua policy
   dengan pola yang sama di site yang sama — dan sejak constraint "satu
   policy per site" dicabut, itu keadaan yang wajar. Pemetaannya lewat
   `tenant_command migrate_roster_assignments`, yang melaporkan per
   pegawai policy mana yang dipilih dan menolak menebak kalau tidak ada
   yang cocok.
"""

from django.db import migrations


SEGMENT_BY_PERIOD_TYPE = {
    "work": "work",
    "off": "field_break",
}


def backfill(apps, schema_editor):
    RotationPeriod = apps.get_model("hr", "RotationPeriod")
    EmploymentAssignment = apps.get_model("hr", "EmploymentAssignment")

    for period in RotationPeriod.objects.all().iterator(chunk_size=500):
        period.segment_type = SEGMENT_BY_PERIOD_TYPE.get(
            period.period_type, "work",
        )

        # Sebelum ini hanya blok kerja yang dihitung hari kerja, dan
        # perilaku itu harus dipertahankan apa adanya — perubahannya
        # menyusul lewat policy, bukan lewat migrasi.
        period.counts_as_roster_day = period.period_type == "work"

        # Nilai rencana disamakan dengan nilai sekarang: dokumen lama
        # tidak punya baseline, jadi "rencana" terbaiknya adalah apa
        # yang tersimpan.
        period.planned_start_date = period.start_date
        period.planned_end_date = period.end_date

        period.save(
            update_fields=[
                "segment_type",
                "counts_as_roster_day",
                "planned_start_date",
                "planned_end_date",
            ],
        )

    assignments = (
        EmploymentAssignment.objects
        .filter(roster_crew__isnull=False, roster_cycle_start__isnull=True)
        .select_related("roster_crew")
    )

    for assignment in assignments.iterator(chunk_size=500):
        anchor = (
            assignment.roster_start_override
            or assignment.roster_crew.cycle_start_date
        )

        if anchor is None:
            continue

        assignment.roster_cycle_start = anchor

        assignment.save(update_fields=["roster_cycle_start"])


def unbackfill(apps, schema_editor):
    """
    Balik arah tidak menghapus apa pun.

    Kolomnya memang dibuang oleh migrasi sebelumnya saat di-rollback,
    jadi mengosongkannya di sini cuma pekerjaan yang langsung dibuang.
    """
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0033_roster_plan_versioning"),
    ]

    operations = [
        migrations.RunPython(backfill, unbackfill),
    ]
