"""
Memindahkan kepemilikan tahun buku dan periode akuntansi ke Finance.

`administration.FiscalYear` (`master_fiscal_year`) dan
`administration.PostingPeriod` (`master_posting_period`) sudah ada
sejak migrasi pertama, tapi **tidak satu pun model menunjuk keduanya
dan tidak satu baris logika bisnis pun membacanya** — keduanya layar
CRUD murni yang diseed `seed_administration --only=calendar`.

Barisnya tetap disalin, **beserta id aslinya**. Bukan karena ada yang
merujuknya, melainkan karena tenant yang sudah pernah menutup sebuah
periode berhak menemukan penutupan itu masih tercatat sesudah pindah;
dan karena membuang data yang bisa dipindahkan adalah kebiasaan yang
tidak boleh dimulai di modul akuntansi.

Satu kolom **tidak** ikut: `FiscalYear.year`. Ia bisa dihitung dari
`start_date`, dan menyimpannya justru memaksa asumsi yang §4 minta
dibuang — tahun buku April 2026–Maret 2027 tidak punya satu "tahun"
yang benar.
"""

from django.db import migrations


# `PostingPeriod.Status` -> `PeriodStatus`. `CLOSING` jadi
# `soft_closed` dan bukan `closed`: artinya di model lama adalah "sedang
# ditutup, penyesuaian masih masuk", dan itu persis arti `SOFT_CLOSED`
# yang baru. Memetakannya ke `closed` akan mengunci periode yang
# sebenarnya masih dipakai orang menutup buku.
PERIOD_STATUS_MAP = {
    "OPEN": "open",
    "CLOSING": "soft_closed",
    "LOCKED": "locked",
}

BASE_FIELDS = (
    "created_at",
    "created_by_id",
    "updated_at",
    "updated_by_id",
    "is_active",
    "is_deleted",
    "deleted_at",
    "deleted_by_id",
)


def _base_values(row) -> dict:
    return {name: getattr(row, name) for name in BASE_FIELDS}


def adopt(apps, schema_editor):
    OldYear = apps.get_model("administration", "FiscalYear")
    OldPeriod = apps.get_model("administration", "PostingPeriod")

    NewYear = apps.get_model("finance", "FiscalYear")
    NewPeriod = apps.get_model("finance", "AccountingPeriod")

    years = list(OldYear.objects.all().order_by("pk"))

    if years:
        NewYear.objects.bulk_create([
            NewYear(
                # Id dipertahankan. Tanpa ini, periode yang menunjuk
                # tahun bukunya lewat `fiscal_year_id` harus dipetakan
                # ulang — satu langkah lagi yang bisa salah, untuk
                # sesuatu yang tidak perlu berubah sama sekali.
                id=row.pk,
                company_id=row.company_id,
                code=row.code,
                name=row.name,
                start_date=row.start_date,
                end_date=row.end_date,
                status="closed" if row.is_closed else "open",
                # Dibiarkan mati untuk semuanya. Menandai tahun buku
                # yang kebetulan memuat hari ini akan menebak — dan
                # tebakan itu salah tepat di tenant yang baru saja
                # membuka tahun buku berikutnya lebih awal. Yang
                # menyalakannya nanti `FiscalYearService.set_current()`,
                # sadar, dari layar.
                is_current=False,
                closed_at=row.closed_at,
                closed_by_id=row.closed_by_id,
                **_base_values(row),
            )
            for row in years
        ])

    periods = list(
        OldPeriod.objects.all().order_by("fiscal_year_id", "start_date", "pk")
    )

    # `period_number` tidak ada di model lama — nomornya diturunkan dari
    # urutan tanggal mulai di dalam tahun bukunya. Kronologis, bukan
    # menurut abjad kode: kode "2026-1" dan "2026-10" berurutan salah
    # kalau diurutkan sebagai teks, dan periode yang bernomor salah
    # membuat perbandingan antarperiode menunjuk bulan yang keliru.
    counter: dict[int, int] = {}
    rows = []

    for row in periods:
        counter[row.fiscal_year_id] = counter.get(row.fiscal_year_id, 0) + 1

        rows.append(
            NewPeriod(
                id=row.pk,
                fiscal_year_id=row.fiscal_year_id,
                period_number=counter[row.fiscal_year_id],
                code=row.code,
                name=row.name,
                start_date=row.start_date,
                end_date=row.end_date,
                status=PERIOD_STATUS_MAP.get(row.status, "open"),
                closed_at=row.locked_at,
                closed_by_id=row.locked_by_id,
                reopened_at=row.unlocked_at,
                reopened_by_id=row.unlocked_by_id,
                reopen_reason=row.unlock_reason or "",
                **_base_values(row),
            )
        )

    if rows:
        NewPeriod.objects.bulk_create(rows)

    _resync_sequences(schema_editor, NewYear, NewPeriod)


def _resync_sequences(schema_editor, *models) -> None:
    """
    Menyetel ulang sequence sesudah `bulk_create` ber-id eksplisit.

    Tanpa ini, baris **berikutnya** yang dibuat lewat layar memakai id 1
    dan ditolak sebagai duplikat — kegagalan yang muncul jauh dari
    sebabnya, berhari-hari sesudah migrasinya jalan, dan terbaca seperti
    bug pada form.
    """
    connection = schema_editor.connection

    if connection.vendor != "postgresql":
        return

    with connection.cursor() as cursor:
        for model in models:
            table = model._meta.db_table

            cursor.execute(
                f"""
                SELECT setval(
                    pg_get_serial_sequence(%s, 'id'),
                    COALESCE((SELECT MAX(id) FROM "{table}"), 1),
                    (SELECT MAX(id) IS NOT NULL FROM "{table}")
                )
                """,
                [table],
            )


def unadopt(apps, schema_editor):
    """
    Mundur = mengosongkan tabel Finance-nya.

    Barisnya di `master_*` belum dihapus pada titik ini — migrasi yang
    menghapusnya (`administration.0042`) berjalan **sesudah** yang ini,
    jadi mundur satu langkah mengembalikan keadaan dengan utuh.
    """
    apps.get_model("finance", "AccountingPeriod").objects.all().delete()
    apps.get_model("finance", "FiscalYear").objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("finance", "0001_initial"),
        ("administration", "0041_backfill_calendar_scope"),
    ]

    operations = [
        migrations.RunPython(adopt, unadopt),
    ]
