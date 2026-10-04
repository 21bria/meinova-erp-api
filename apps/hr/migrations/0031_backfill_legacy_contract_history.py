"""
Memindahkan kontrak lama pegawai tetap ke riwayat Employee Action.

Masalahnya: banyak baris existing berbentuk

    Employment Type = Permanent
    Contract Type   = PKWT
    Contract Start  = 2022-05-09
    Contract End    = 2026-08-03

Itu **bukan** data sampah — hampir selalu artinya "dulu PKWT, sekarang
tetap". Tapi sebagai keadaan sekarang ia ambigu: tidak ada cara
membedakannya dari pegawai tetap yang kontraknya masih berjalan.

Sejak `EmploymentAssignment.clean()` menolak kombinasi itu, baris
seperti ini juga **tidak bisa disimpan lagi** — membuka kartu pegawai
lalu mengoreksi satu nomor telepon akan ditolak dengan alasan kontrak,
dan orang yang mengoreksinya tidak punya jalan keluar. Itu keadaan yang
tidak boleh dibiarkan sampai ada yang sempat menjalankan perintah
manual.

Yang dilakukan migration ini, per baris bermasalah:

1. menulis satu `EmployeeAction` bertipe Employment Type Change yang
   sudah `APPLIED`, dengan `values_before` memuat kontrak lamanya apa
   adanya dan `values_after` memuat keadaan tetapnya;
2. baru sesudah itu mengosongkan kolom kontrak pada keadaan sekarang.

Urutannya begitu supaya tidak ada satu titik pun di mana datanya sudah
hilang tapi riwayatnya belum ada.

**Tidak ada model riwayat baru.** `EmployeeAction` yang berstatus
APPLIED memang sudah jadi sumber riwayat kepegawaian, dan endpoint
`employment-history` membacanya dari sana — jadi hasil backfill ini
langsung muncul di timeline pegawainya.

Aman diulang: baris hasil backfill ditandai `BACKFILL_MARKER` di
`values_before`, dan pegawai yang sudah punya penanda itu dilewati.
"""

from django.db import migrations
from django.db.models import Q
from django.utils import timezone


# Penanda di `values_before`. Dipakai dua hal: membuat migration ini
# idempotent, dan memberi tahu siapa pun yang membaca dokumennya nanti
# bahwa tanggal dan alasannya hasil kesimpulan, bukan hasil pengajuan.
BACKFILL_MARKER = "_legacy_backfill"


REASON = (
    "Dibuat otomatis dari data lama. Pegawai ini tercatat sebagai "
    "pegawai tetap tetapi kolom kontraknya masih terisi — kontrak "
    "tersebut dipindahkan ke riwayat ini supaya keadaan sekarang tidak "
    "lagi terbaca seperti kontrak yang masih berjalan. Tanggal berlaku "
    "adalah perkiraan terbaik dari data yang ada."
)


def _snapshot(assignment, *, with_contract: bool) -> dict:
    """
    Nilai yang dibekukan, dalam bentuk teks siap baca.

    Sengaja nama, bukan pk: riwayat harus tetap terbaca bertahun-tahun
    kemudian walau baris masternya sudah diganti nama atau dihapus.
    """
    def name(value):
        return getattr(value, "name", None)

    def iso(value):
        return value.isoformat() if value else None

    data = {
        "employment_type": name(assignment.employment_type),
        "employment_status": name(assignment.employment_status),
        "employee_group": name(assignment.employee_group),
        "confirmation_date": iso(assignment.confirmation_date),
    }

    if with_contract:
        data.update(
            {
                "contract_type": name(assignment.contract_type),
                "contract_start": iso(assignment.contract_start),
                "contract_end": iso(assignment.contract_end),
            },
        )
    else:
        data.update(
            {
                "contract_type": None,
                "contract_start": None,
                "contract_end": None,
            },
        )

    return data


def _effective_date(assignment):
    """
    Sejak kapan status tetapnya berlaku.

    Urutan tebakannya dari yang paling berhak jadi jawaban:
    tanggal pengangkatan → akhir kontrak terakhir → tanggal masuk →
    hari ini. Tidak ada yang benar-benar tahu, dan itu sebabnya
    alasannya menyebut bahwa tanggalnya perkiraan.
    """
    return (
        assignment.confirmation_date
        or assignment.contract_end
        or assignment.join_date
        or timezone.localdate()
    )


def forwards(apps, schema_editor):
    EmploymentAssignment = apps.get_model("hr", "EmploymentAssignment")
    EmployeeAction = apps.get_model("hr", "EmployeeAction")

    stale = (
        EmploymentAssignment.objects
        .select_related(
            "employee",
            "employee__organization",
            "employment_type",
            "employment_status",
            "employee_group",
            "contract_type",
        )
        .filter(
            employment_type__isnull=False,
            employment_type__requires_contract=False,
        )
        .filter(
            Q(contract_start__isnull=False)
            | Q(contract_end__isnull=False)
            | Q(contract_type__isnull=False),
        )
    )

    now = timezone.now()

    for assignment in stale:
        already = (
            EmployeeAction.objects
            .filter(
                employee_id=assignment.employee_id,
                action_type="employment_type_change",
                values_before__has_key=BACKFILL_MARKER,
            )
            .exists()
        )

        if not already:
            organization = getattr(
                assignment.employee,
                "organization",
                None,
            )

            before = _snapshot(assignment, with_contract=True)
            before[BACKFILL_MARKER] = True

            EmployeeAction.objects.create(
                employee_id=assignment.employee_id,
                action_type="employment_type_change",
                status="applied",
                effective_date=_effective_date(assignment),
                reason=REASON,
                # Nomor dokumen sengaja dikosongkan. Deret penomoran
                # tidak boleh dihabiskan oleh baris yang tidak pernah
                # diajukan siapa pun, dan constraint uniknya memang
                # mengecualikan nomor kosong.
                document_number="",
                company_id=getattr(organization, "company_id", None),
                branch_id=getattr(organization, "branch_id", None),
                location_id=getattr(organization, "location_id", None),
                proposed_employment_type_id=(
                    assignment.employment_type_id
                ),
                values_before=before,
                values_after=_snapshot(
                    assignment,
                    with_contract=False,
                ),
                applied_at=now,
                is_deleted=False,
            )

        # Baru sesudah riwayatnya tersimpan.
        assignment.contract_type = None
        assignment.contract_start = None
        assignment.contract_end = None

        assignment.save(
            update_fields=[
                "contract_type",
                "contract_start",
                "contract_end",
                "updated_at",
            ],
        )


def backwards(apps, schema_editor):
    """
    Mengembalikan kontrak lama ke keadaan sekarang.

    Dipakai kalau migration ini diturunkan: nilainya dibaca kembali dari
    `values_before` baris backfill, lalu barisnya dibuang. Tanpa ini,
    menurunkan migration berarti kehilangan datanya untuk selamanya —
    dan itu yang justru mau dihindari seluruh berkas ini.
    """
    EmploymentAssignment = apps.get_model("hr", "EmploymentAssignment")
    EmployeeAction = apps.get_model("hr", "EmployeeAction")
    ContractType = apps.get_model("administration", "ContractType")

    rows = EmployeeAction.objects.filter(
        action_type="employment_type_change",
        values_before__has_key=BACKFILL_MARKER,
    )

    for row in rows:
        before = row.values_before or {}

        assignment = (
            EmploymentAssignment.objects
            .filter(employee_id=row.employee_id)
            .first()
        )

        if assignment is not None:
            contract_type = None

            if before.get("contract_type"):
                contract_type = (
                    ContractType.objects
                    .filter(name=before["contract_type"])
                    .first()
                )

            assignment.contract_type = contract_type
            assignment.contract_start = before.get("contract_start")
            assignment.contract_end = before.get("contract_end")

            assignment.save(
                update_fields=[
                    "contract_type",
                    "contract_start",
                    "contract_end",
                    "updated_at",
                ],
            )

    rows.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("hr", "0030_employeeaction"),
        # `requires_contract` harus sudah terisi benar — kalau tidak,
        # seluruh jenis terbaca "tidak berkontrak" dan backfill ini
        # akan mengosongkan kontrak pegawai yang memang masih
        # berkontrak. Urutannya tidak boleh diserahkan ke abjad nama
        # app, sama seperti `framework.0003` yang bergantung pada
        # `workflow.0002`.
        (
            "administration",
            "0023_backfill_employment_type_requires_contract",
        ),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
