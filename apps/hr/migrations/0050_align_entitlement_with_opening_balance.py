"""
Kartu yang sudah punya saldo awal tidak lagi membawa jatah tahun itu.

Sejak `replaces_entitlement` dibuang (`0049`), **setiap** saldo awal yang
sudah di-post memegang tahunnya: jatah tahun go-live tidak diterbitkan
sistem ini, karena sebagiannya sudah dipakai di sistem lama dan yang
tersisa persis angka yang diserahkan HR.

Baris yang dibuat sebelum ini dengan penandanya mati sudah menempel di
kartu cuti **di atas** jatah yang ikut terbit — kartu berbunyi 19 untuk
orang yang sisanya 7. Membiarkannya berarti aturan barunya hanya berlaku
untuk baris yang kebetulan dibuat sesudah hari ini, dan dua tafsir
berdampingan di satu tabel adalah keadaan yang paling sulit dijelaskan
ke siapa pun.

Yang ditulis cuma `entitlement`. `used`, `adjustment`, `carried_over`,
dan `opening_balance` tidak disentuh — masing-masing punya pemiliknya,
dan `adjustment` justru yang harus bertahan dari perhitungan ulang apa
pun.

Baris DRAFT dilewati: yang belum di-post belum berlaku apa-apa, termasuk
belum berhak mematikan jatah tahun berjalan.
"""

from django.db import migrations


def align(apps, schema_editor):
    opening_model = apps.get_model("hr", "LeaveOpeningBalance")
    balance_model = apps.get_model("hr", "LeaveBalance")

    rows = (
        opening_model.objects
        .filter(status="posted", is_deleted=False)
        .values_list("employee_id", "leave_type_id", "year")
    )

    for employee_id, leave_type_id, year in rows.iterator():
        (
            balance_model.objects
            .filter(
                employee_id=employee_id,
                leave_type_id=leave_type_id,
                year=year,
                is_deleted=False,
            )
            .exclude(entitlement=0)
            .update(entitlement=0)
        )


def unalign(apps, schema_editor):
    """
    Tidak bisa dibalik, dan pura-pura bisa lebih buruk.

    Angka jatah sebelumnya tidak disimpan di mana pun — ia hasil
    perhitungan dari policy. Yang mau mengembalikannya menjalankan
    `tenant_command generate_leave_balances --year=<tahun>`, yang
    memang menghitungnya ulang dari aturan yang berlaku.
    """


class Migration(migrations.Migration):
    dependencies = [
        ("hr", "0049_remove_leaveopeningbalance_replaces_entitlement"),
    ]

    operations = [
        migrations.RunPython(align, unalign),
    ]
