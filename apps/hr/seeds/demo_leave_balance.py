"""
Saldo cuti tenant peragaan — titik awalnya, bukan sekadar kartunya.

Kenapa perlu seed tersendiri
----------------------------
Kartu saldo (`LeaveBalance`) tidak punya angka miliknya sendiri. Tiap
kantongnya dijumlah ulang dari sumber lain:

* `entitlement` — dari Leave Policy, lewat `LeaveBalanceGenerator`;
* `opening_balance` — dari dokumen `LeaveOpeningBalance` yang di-post;
* `used` — dari catatan `EmployeeLeave`, lewat
  `LeaveBalanceService.recalculate_used`.

Tenant peragaan ini punya baris `LeaveGoLive` (MMR, 1 September), dan
itu membalik arahnya: pada tahun go-live jatah **tidak** diterbitkan
dari policy untuk pegawai yang sudah bekerja sebelum tanggal itu —
lihat gerbangnya di `LeaveEntitlementCalculator.for_employee`. Seluruh
saldo tahun itu datang dari dokumen saldo awal.

Sampai berkas ini ada, dokumen itu **tidak diseed satu pun**. Angkanya
pernah masuk sekali lewat layar Import, dan `reset_demo_data`
membuangnya bersama pegawainya — jadi tiap pembangunan ulang tenant
peragaan menghasilkan kartu bernilai nol untuk semua orang, lalu cuti
data uji yang disetujui memotongnya jadi minus. Itulah sebabnya "saldo
demo tidak ikut berubah setelah seed": yang berubah memang bukan
seed-nya, karena seed-nya belum pernah ada.

Kenapa angkanya ditulis tangan di sini
--------------------------------------
Saldo awal migrasi memang tidak bisa dihitung. Ia pernyataan tentang
sistem **lama** — sisa cuti seseorang pada hari terakhir sistem itu
dipakai — dan tidak ada satu pun data di sistem ini yang bisa
menurunkannya. Yang bisa dilakukan seed cuma satu: menuliskan angka
yang sama setiap kali, supaya layar peragaan tidak berubah sendiri di
antara dua kali pembangunan.

Nol pun ditulis, dan itu bukan kelalaian. "Habis terpakai di sistem
lama" dan "belum diimport" terlihat sama persis di kartu saldo, dan
satu-satunya yang membedakannya adalah adanya dokumen bertanggal.

Aman diulang
------------
Dokumen yang sudah di-post **tidak bisa disunting di tempat**
(`assert_editable`). Jadi menyamakan angkanya butuh tiga langkah —
unpost, update, post — dan itu yang dikerjakan `sync_document` di
bawah. `get_or_create(defaults=...)` di tempat ini akan berbohong: ia
melapor "sudah ada" lalu membiarkan angka lama menempel selamanya.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from apps.hr.seeds.demo_reset import EMPLOYEE_PREFIXES


# Jenis cuti yang punya saldo di tenant peragaan. Satu-satunya yang
# `uses_balance`-nya menyala di seed Leave Policy — lihat
# `apps/administration/seeds/reference/leave_policy.py`.
LEAVE_TYPE_CODE = "ANNUAL"


# Tanggal go-live tenant peragaan, ditulis sebagai (bulan, hari) dan
# dilekatkan pada tahun saldo yang diminta. Bukan tanggal mati: tenant
# peragaan yang dibangun ulang tahun depan harus tetap konsisten —
# go-live, tahun dokumen, dan tahun kartunya wajib satu tahun yang sama,
# kalau tidak potongan cutinya mendarat di kartu yang tidak ada isinya.
GO_LIVE_MONTH = 9
GO_LIVE_DAY = 1


# Penanda, supaya dokumen buatan seed bisa dibedakan dari yang diketik
# orang saat memperagakan layar Leave Opening Balance.
REMARK = "[data uji] saldo per hari terakhir sistem lama"


# Sisa cuti tiap pegawai peragaan pada hari go-live.
#
# Angka-angka ini menyalin keadaan tenant peragaan yang sedang dipakai
# UAT, supaya berkas ini tidak menggeser satu pun layar yang sudah
# pernah ditunjukkan ke orang. Yang paling perlu diingat: **HO003 Bimo
# Nugroho = 5** — itu angka yang dipakai skenario cuti kantor pusat,
# dan dua hari cutinya yang disetujui harus menyisakan tiga.
#
# Empat nol di bawah punya dua sebab yang berbeda, dan keduanya sah:
#
# * HO004, LOK008, SGA006 masuk **pada tahun go-live** — masa tunggu 12
#   bulan belum lewat, jadi sistem lama pun tidak pernah menerbitkan
#   jatah untuk mereka.
# * SGA004 pegawai lama yang jatahnya habis terpakai di sistem lama.
#   Ini contoh yang memang perlu ada di tenant peragaan: kartu bersaldo
#   nol yang **punya** dokumen, dan karena itu bisa dibedakan dari kartu
#   yang datanya belum masuk.
OPENING_DAYS: dict[str, Decimal] = {
    # Kantor pusat
    "HO001": Decimal("7.0"),
    "HO002": Decimal("4.0"),
    "HO003": Decimal("5.0"),
    "HO004": Decimal("0.0"),
    "HO005": Decimal("2.0"),
    "HO006": Decimal("9.0"),
    "HO007": Decimal("6.0"),
    "HO008": Decimal("8.0"),

    # Site — staf
    "SGA001": Decimal("6.0"),
    "SGA002": Decimal("11.0"),
    "SGA003": Decimal("5.0"),
    "SGA004": Decimal("0.0"),
    "SGA005": Decimal("8.0"),
    "SGA006": Decimal("0.0"),
    "SGA007": Decimal("4.0"),
    "SGA008": Decimal("9.0"),
    "SGA009": Decimal("2.0"),
    "SGA010": Decimal("12.0"),

    # Site — tenaga lokal
    "LOK001": Decimal("3.0"),
    "LOK002": Decimal("10.0"),
    "LOK003": Decimal("12.0"),
    "LOK004": Decimal("2.0"),
    "LOK005": Decimal("5.0"),
    "LOK006": Decimal("1.0"),
    "LOK007": Decimal("7.0"),
    "LOK008": Decimal("0.0"),
}


# ----------------------------------------------------------------------
# Pencarian
# ----------------------------------------------------------------------


def _employees():
    """
    Pegawai data uji saja.

    Awalan nomornya dipinjam dari `demo_reset` — satu daftar untuk
    "mana yang boleh dibuang" dan "mana yang boleh diisi", supaya
    keduanya tidak bisa berbeda. Ini juga yang membuat perintah ini
    tidak akan menyentuh data sungguhan walau dijalankan di schema yang
    salah.
    """
    from django.db.models import Q

    from apps.hr.models import Employee

    condition = Q()

    for prefix in EMPLOYEE_PREFIXES:
        condition |= Q(employee_number__startswith=prefix)

    return (
        Employee.objects
        .filter(condition, is_deleted=False, is_active=True)
        .select_related(
            "employment",
            "employment__employee_group",
            "employment__employment_type",
            "organization",
            "organization__company",
        )
        .order_by("employee_number")
    )


def _leave_type():
    from apps.administration.models import LeaveType

    return (
        LeaveType.objects
        .filter(code=LEAVE_TYPE_CODE, is_deleted=False)
        .first()
    )


def go_live_date_for(year: int) -> date:
    return date(year, GO_LIVE_MONTH, GO_LIVE_DAY)


# ----------------------------------------------------------------------
# Go-live
# ----------------------------------------------------------------------


def ensure_go_live(*, companies, go_live_date: date, log) -> int:
    """
    Menyalakan go-live cuti untuk company pegawai data uji.

    Harus lebih dulu dari dokumen saldo awalnya: `apply_opening_date`
    mengambil tanggalnya dari sini, dan `LeaveEntitlementCalculator`
    memakainya untuk memutuskan tahun itu milik siapa. Tanpa baris ini
    jatah 12 hari tetap terbit dari policy, lalu saldo awal ditambahkan
    di atasnya — kartu berbunyi 17 untuk orang yang sisanya 5.
    """
    from apps.hr.models import LeaveGoLive

    touched = 0

    for company in companies:
        row = (
            LeaveGoLive.objects
            .filter(company=company, is_deleted=False)
            .first()
        )

        if row is None:
            row = LeaveGoLive(company=company)

        if (
            row.pk
            and row.go_live_date == go_live_date
            and row.is_active
        ):
            continue

        row.go_live_date = go_live_date
        row.is_active = True

        row.full_clean()
        row.save()

        touched += 1

        log(f"    go-live {company.code} = {go_live_date}")

    return touched


# ----------------------------------------------------------------------
# Dokumen saldo awal
# ----------------------------------------------------------------------


@transaction.atomic
def sync_document(
    *,
    employee,
    leave_type,
    days: Decimal,
    go_live_date: date,
    year: int,
    user=None,
) -> str:
    """
    Menyamakan satu dokumen saldo awal dengan angka di daftar ini.

    Mengembalikan salah satu: `created`, `updated`, `unchanged`.

    Tiga langkah untuk baris yang sudah di-post, dan urutannya bukan
    selera: `assert_editable` menolak penyuntingan di tempat karena
    angkanya sudah menempel di kartu cuti orang. Unpost menariknya
    kembali lewat jalur resmi (kartunya ikut dijumlah ulang), update
    menuliskan angka barunya, post menerbitkannya lagi. Yang dilewati
    tidak akan pernah berubah — dan itu persis keluhan yang membuat
    berkas ini ditulis.
    """
    from apps.hr.api.leave_opening.services import LeaveOpeningBalanceService
    from apps.hr.models import LeaveOpeningBalance, LeaveOpeningSource

    document = (
        LeaveOpeningBalance.objects
        .filter(
            employee=employee,
            leave_type=leave_type,
            is_deleted=False,
        )
        .first()
    )

    payload = {
        "days": days,
        "opening_date": go_live_date,
        "year": year,
        "source": LeaveOpeningSource.MANUAL,
        "remark": REMARK,
    }

    if document is None:
        document = LeaveOpeningBalanceService.create(
            data={
                "employee": employee,
                "leave_type": leave_type,
                **payload,
            },
            user=user,
        )

        LeaveOpeningBalanceService.post(instance=document, user=user)

        return "created"

    same = (
        document.days == days
        and document.opening_date == go_live_date
        and document.year == year
        and document.is_posted
    )

    if same:
        # Tetap disinkronkan ulang walau dokumennya tidak berubah.
        # Kartunya bisa saja terhapus atau tertimpa penulis lain di
        # antara dua kali seed, dan penjumlahan ulang tidak bisa hanyut.
        LeaveOpeningBalanceService.sync_for(document, user=user)

        return "unchanged"

    if document.is_posted:
        LeaveOpeningBalanceService.unpost(instance=document, user=user)

    document = LeaveOpeningBalanceService.update(
        instance=document,
        data=payload,
        user=user,
    )

    LeaveOpeningBalanceService.post(instance=document, user=user)

    return "updated"


# ----------------------------------------------------------------------
# Reset
# ----------------------------------------------------------------------


def reset(*, log, force: bool = False) -> dict:
    """
    Membuang kartu saldo dan dokumen saldo awal pegawai data uji.

    Hard delete, alasan yang sama dengan `reset_demo_data`: baris
    bertanda terhapus tetap menempati kunci uniknya
    (`uniq_active_hr_leave_opening_balance`), jadi pembangunan ulang
    justru gagal karena bentrok dengan bangkai sebelumnya.

    `used` tidak perlu dijaga — ia dijumlah ulang dari catatan cuti,
    dan catatan cutinya tidak disentuh sama sekali. Yang **tidak** bisa
    diterbitkan ulang perintah mana pun cuma `adjustment` dan
    `carried_over`: yang pertama diketik orang, yang kedua hasil carry
    over tahun sebelumnya. Keduanya menghentikan reset kecuali diminta
    dengan `force`.
    """
    from apps.hr.models import LeaveBalance, LeaveOpeningBalance

    employee_ids = list(_employees().values_list("id", flat=True))

    cards = LeaveBalance.objects.filter(employee_id__in=employee_ids)
    documents = LeaveOpeningBalance.objects.filter(
        employee_id__in=employee_ids,
    )

    risky = [
        card for card in cards.select_related("employee", "leave_type")
        if card.adjustment or card.carried_over
    ]

    if risky and not force:
        for card in risky[:10]:
            log(
                f"    ! {card.employee.employee_number} "
                f"{card.leave_type.code} {card.year} "
                f"adj={card.adjustment} carried={card.carried_over}"
            )

        raise RuntimeError(
            f"{len(risky)} kartu membawa adjustment / carried_over "
            f"bukan nol, dan angka itu tidak bisa diterbitkan ulang "
            f"perintah mana pun. Pakai --force kalau memang mau "
            f"dibuang.",
        )

    counts = {
        "documents": documents.count(),
        "cards": cards.count(),
    }

    documents.delete()
    cards.delete()

    log(
        f"    buang {counts['documents']} dokumen saldo awal, "
        f"{counts['cards']} kartu saldo"
    )

    return counts


# ----------------------------------------------------------------------
# Laporan
# ----------------------------------------------------------------------


def report(*, year: int) -> list[dict]:
    """Isi kartu saldo pegawai data uji, siap dicetak apa adanya."""
    from apps.hr.models import LeaveBalance

    rows = (
        LeaveBalance.objects
        .filter(
            employee_id__in=_employees().values_list("id", flat=True),
            year=year,
            is_deleted=False,
        )
        .select_related("employee", "leave_type")
        .order_by("employee__employee_number", "leave_type__code")
    )

    return [
        {
            "employee_number": row.employee.employee_number,
            "employee": row.employee.full_name,
            "leave_type": row.leave_type.code,
            "opening": row.opening_balance,
            "entitlement": row.entitlement,
            "used": row.used,
            "remaining": row.remaining,
        }
        for row in rows
    ]


# ----------------------------------------------------------------------


def run(
    *,
    year: int | None = None,
    do_reset: bool = False,
    force: bool = False,
    user=None,
    log=print,
) -> dict:
    """
    Membangun ulang seluruh saldo cuti tenant peragaan.

    Empat langkah, dan urutannya yang membuatnya boleh dijalankan
    berkali-kali tanpa menghasilkan angka yang berbeda:

    1. go-live dinyalakan — tahun itu jadi milik sistem lama;
    2. dokumen saldo awal disamakan dengan daftar di berkas ini,
       lalu di-post;
    3. `LeaveBalanceGenerator` dijalankan ulang — ia yang menerbitkan
       kartu untuk pegawai yang saldo awalnya nol (`sync_balance`
       sengaja tidak membuat kartu untuk angka nol tanpa masa berlaku),
       sekaligus menuliskan jatah tahun berikutnya;
    4. `used` dijumlah ulang dari catatan cuti yang sudah RECORDED /
       APPROVED.

    Langkah 4 tidak boleh dilewatkan walau tidak ada cuti baru:
    `recalculate_used` mengembalikan `None` kalau kartunya belum ada,
    jadi cuti yang disetujui **sebelum** kartunya terbit meninggalkan
    `used` nol yang tidak pernah dibetulkan siapa pun.
    """
    from apps.hr.api.leave.entitlement import LeaveBalanceGenerator
    from apps.hr.api.leave.services import LeaveBalanceService
    from apps.hr.models import LeaveBalance

    if year is None:
        year = timezone.localdate().year

    leave_type = _leave_type()

    if leave_type is None:
        log(
            f"  ! Jenis cuti {LEAVE_TYPE_CODE} belum ada di master — "
            f"jalankan dulu `seed_administration --only=hr-reference`."
        )

        return {"year": year, "note": "leave type missing"}

    employees = list(_employees())

    if not employees:
        log(
            "  Belum ada pegawai data uji — jalankan dulu "
            "`seed_demo_workforce`."
        )

        return {"year": year, "note": "no demo employees"}

    log(f"  Saldo cuti data uji {year}:")

    if do_reset:
        reset(log=log, force=force)

    go_live_date = go_live_date_for(year)

    companies = {
        employee.organization.company
        for employee in employees
        if employee.organization and employee.organization.company
    }

    ensure_go_live(
        companies=sorted(companies, key=lambda row: row.code),
        go_live_date=go_live_date,
        log=log,
    )

    counts = {"created": 0, "updated": 0, "unchanged": 0}

    # Pegawai yang tidak punya baris di daftar saldo awal. Disebut, tidak
    # didiamkan: kartunya akan berbunyi nol, dan nol tanpa dokumen tidak
    # bisa dibedakan dari data yang belum masuk.
    unlisted: list[str] = []

    for employee in employees:
        days = OPENING_DAYS.get(employee.employee_number)

        if days is None:
            unlisted.append(employee.employee_number)

            continue

        outcome = sync_document(
            employee=employee,
            leave_type=leave_type,
            days=days,
            go_live_date=go_live_date,
            year=year,
            user=user,
        )

        counts[outcome] += 1

    log(
        f"    saldo awal          {counts['created']} dibuat, "
        f"{counts['updated']} disamakan, {counts['unchanged']} tetap"
    )

    if unlisted:
        log(
            f"    ! {len(unlisted)} pegawai belum punya angka saldo "
            f"awal di seed: {', '.join(unlisted)}"
        )

    # Kartunya diterbitkan ulang untuk tahun saldo **dan** tahun
    # berikutnya. Tahun berikutnya ikut karena go-live cuma memegang
    # tahunnya sendiri — 2027 kembali dihitung dari policy, dan HR yang
    # sedang memperagakan carry over perlu melihat angkanya sekarang.
    generated = {}

    for target in (year, year + 1):
        generated[target] = LeaveBalanceGenerator.run(
            year=target,
            employees=employees,
            user=user,
        )

        log(
            f"    kartu saldo {target}    "
            f"{generated[target]['created']} dibuat, "
            f"{generated[target]['updated']} diperbarui"
        )

    # Penjumlahan ulang pemakaian, untuk **semua** kartu data uji dan
    # bukan cuma yang cutinya berubah hari ini.
    cards = (
        LeaveBalance.objects
        .filter(
            employee__in=employees,
            is_deleted=False,
        )
        .select_related("employee", "leave_type")
    )

    recalculated = 0

    for card in cards:
        LeaveBalanceService.recalculate_used(
            employee=card.employee,
            leave_type=card.leave_type,
            year=card.year,
        )

        recalculated += 1

    log(f"    pemakaian           {recalculated} kartu dihitung ulang")

    return {
        "year": year,
        "go_live_date": go_live_date,
        "opening": counts,
        "unlisted": unlisted,
        "generated": generated,
        "recalculated": recalculated,
        "rows": report(year=year),
    }
