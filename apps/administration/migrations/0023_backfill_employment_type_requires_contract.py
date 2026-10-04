"""
Mengisi `EmploymentType.requires_contract` untuk tenant yang sudah ada.

Kolomnya lahir dengan `default=False`, jadi tanpa migration ini seluruh
jenis kepegawaian di tenant lama terbaca sebagai "tidak berkontrak" —
kolom Contract Type/Start/End tidak pernah muncul di form, dan tidak ada
satu pun pesan yang menjelaskannya. Menyerahkannya ke
`seed_administration --only=hr-reference` berarti tenant yang lupa
menjalankan seed kehilangan fitur kontraknya diam-diam; seed tetap
dipakai untuk tenant baru, tapi tidak boleh jadi satu-satunya jalan.

Dijalankan otomatis per schema oleh `migrate_schemas`, sama seperti
`workflow.0002`. Aman diulang: yang sudah `True` tidak disentuh.

Penentuannya berlapis, dan urutannya penting:

1. **Kode yang pasti tetap** — jangan pernah dinaikkan, walau datanya
   berkata lain. Ini yang melindungi kasus legacy "Permanent tapi
   kolom kontraknya terisi": justru baris itulah yang mau dibereskan
   `hr.0031`, bukan dijadikan alasan menandai Permanent sebagai
   berkontrak.
2. **Kode yang dikenal berkontrak** — daftar kode seed bawaan plus
   ejaan yang lazim dipakai klien Indonesia.
3. **Kesimpulan dari data** — untuk kode karangan tenant yang tidak ada
   di dua daftar itu: kalau ada pegawai berjenis ini yang menyimpan
   tanggal kontrak, jenisnya memang berkontrak. Ini yang membuat tenant
   dengan master sendiri tidak perlu menunggu daftar di bawah ditambah.

Sengaja **tidak** menebak dari nama tampilan: nama berubah jauh lebih
sering daripada kode, dan tenant boleh menamainya dalam bahasa apa pun.
"""

from django.db import migrations
from django.db.models import Q


# Tidak pernah berkontrak, apa pun isi datanya.
PERMANENT_CODES = {
    "PERM",
    "PERMANENT",
    "TETAP",
    "PKWTT",
    "KARYAWAN-TETAP",
}


# Berkontrak. `CONT` … `CONSULTANT` adalah kode seed bawaan; sisanya
# ejaan yang lazim muncul di master klien.
CONTRACT_CODES = {
    "CONT",
    "DAILY",
    "INTERN",
    "OUTSOURCE",
    "CONSULTANT",

    "PKWT",
    "CONTRACT",
    "KONTRAK",
    "HARIAN",
    "FREELANCE",
    "PROBATION",
    "MAGANG",
    "OUTSOURCING",
    "TEMPORARY",
    "TEMP",
}


def _normalized(code: str) -> str:
    return str(code or "").strip().upper()


def forwards(apps, schema_editor):
    EmploymentType = apps.get_model("administration", "EmploymentType")
    EmploymentAssignment = apps.get_model("hr", "EmploymentAssignment")

    # Jenis yang punya pegawai dengan tanggal kontrak tersimpan.
    # Dipakai hanya untuk kode yang tidak dikenal — lihat docstring.
    with_contract_data = set(
        EmploymentAssignment.objects
        .filter(
            Q(contract_start__isnull=False)
            | Q(contract_end__isnull=False)
            | Q(contract_type__isnull=False),
        )
        .exclude(employment_type__isnull=True)
        .values_list("employment_type_id", flat=True)
        .distinct(),
    )

    promoted = []

    for employment_type in EmploymentType.objects.all():
        code = _normalized(employment_type.code)

        if code in PERMANENT_CODES:
            continue

        if code in CONTRACT_CODES:
            requires = True

        else:
            requires = employment_type.pk in with_contract_data

        if not requires or employment_type.requires_contract:
            continue

        employment_type.requires_contract = True

        promoted.append(employment_type)

    if promoted:
        EmploymentType.objects.bulk_update(
            promoted,
            ["requires_contract"],
        )


def backwards(apps, schema_editor):
    """
    Tidak mengembalikan apa pun.

    Mengosongkan `requires_contract` massal akan menghapus juga nilai
    yang sudah disunting orang lewat layar master, dan kolomnya sendiri
    dibuang oleh migration schema di bawahnya kalau memang diturunkan.
    """
    return None


class Migration(migrations.Migration):

    dependencies = [
        ("administration", "0022_employmenttype_requires_contract"),
        # Kesimpulan dari data membaca `hr.EmploymentAssignment`, jadi
        # tabelnya harus sudah ada bentuk terakhirnya sebelum ini jalan.
        ("hr", "0030_employeeaction"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
