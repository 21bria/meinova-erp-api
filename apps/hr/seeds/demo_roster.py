"""
Data uji modul roster: setup massal → baseline → penyesuaian → kredit.

Dijalankan lewat **service**, bukan `objects.create` — supaya dokumen
yang dihasilkan sebentuk dengan buatan pengguna, dan rantai perhitungan
yang sebenarnya ikut teruji. Seed yang menulis langsung ke tabel selalu
terlihat benar sampai ada orang yang memakai layarnya.

Aman diulang: dokumen lama data uji dibuang lebih dulu (hard delete —
baris bertanda terhapus tetap menempati kunci uniknya dan justru
menggagalkan pembangunan ulang), lalu dibangun dari nol.

    python manage.py tenant_command seed_demo_roster --schema=demo
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone


# Ditandai supaya seed berikutnya bisa mengenali miliknya sendiri tanpa
# menyentuh dokumen yang dibuat pengguna.
MARKER = "[seed_demo_roster]"


def _location(Location, Employee):
    """
    Site data uji: lokasi **berpenghuni** yang bukan kantor pusat.

    Dipilih dari jumlah pegawainya, bukan dari kode yang ditebak. Master
    tenant lazim memuat beberapa baris "Default Location" kosong hasil
    seed awal, dan menebak kode (`SGA`) meleset begitu klien menamainya
    lain — hasilnya seed yang melaporkan "belum ada pegawai" di lokasi
    yang memang tidak pernah dihuni siapa pun.
    """
    from django.db.models import Count, Q

    return (
        Location.objects
        .filter(is_deleted=False)
        .exclude(code__iexact="HO")
        .exclude(name__icontains="head office")
        .annotate(
            headcount=Count(
                "employee_organizations",
                filter=Q(
                    employee_organizations__is_deleted=False,
                    employee_organizations__employee__is_deleted=False,
                ),
                distinct=True,
            ),
        )
        .filter(headcount__gt=0)
        .order_by("-headcount", "code")
        .first()
    )


def _policy(RosterPolicy, *, location):
    """
    Policy berpola siklus yang cocok untuk site itu.

    Yang **tidak** punya pola dilewati: ia cuma memuat aturan site, dan
    tidak bisa menghasilkan jadwal.

    **`is_default` menang lebih dulu, baru kodenya.** Sebelum ini
    urutannya kode saja, dan itu memilih policy berdasarkan ejaan:
    `ROSTER-SAGEA MINE-8-2` (spasi) menang atas
    `ROSTER-SAGEA-MINE-6-2-2-SHIFT` (tanda hubung) semata-mata karena
    spasi lebih kecil dari tanda hubung di urutan byte. Site yang sudah
    menandai policy bakunya justru tidak dipakai, dan tidak ada satu
    pun pesan yang menyebutkan kenapa.

    Kolom `is_default` memang untuk ini: ia pernyataan sadar admin
    tentang pola mana yang berlaku di sini. Kodenya tinggal pemutus
    kalau tidak ada yang ditandai.
    """
    queryset = RosterPolicy.objects.filter(
        is_deleted=False,
        is_active=True,
        cycle_work_days__isnull=False,
        cycle_off_days__isnull=False,
    )

    order = ("-is_default", "code")

    scoped = queryset.filter(location=location).order_by(*order).first()

    return scoped or queryset.order_by(*order).first()


@transaction.atomic
def run(
    *,
    log=print,
    employees: int = 0,
    as_of: date | None = None,
    stagger_days: int = 3,
    only_roster_employees: bool = False,
) -> dict:
    """
    `employees=0` berarti **seluruh** pegawai site itu, dan itu bawaan
    yang benar: `seed_demo_workforce` sudah menerbitkan rencana lewat
    jalur lama (`RosterCrew`) untuk semuanya. Menyetup sebagiannya saja
    meninggalkan daftar jadwal yang separuh barisnya punya Roster Crew
    dan separuhnya punya Roster Policy — dua jalur yang memang berbeda,
    tapi berdampingan di satu tabel tanpa penjelasan mereka terbaca
    seperti data yang setengah terisi.
    """
    from apps.administration.models import Location, RosterPolicy
    from apps.hr.api.roster.adjustment_service import RosterAdjustmentService
    from apps.hr.api.roster.credit_service import RotationCreditService
    from apps.hr.api.roster.setup_service import (
        RosterSetupLineService,
        RosterSetupService,
    )
    from apps.hr.models import (
        AdjustmentKind,
        AdjustmentStatus,
        Employee,
        RosterAdjustment,
        RosterSetupRequest,
        RotationCreditTransaction,
        RotationPeriod,
        SiteRotation,
    )

    result = {
        "lines": 0,
        "plans": 0,
        "adjustments": 0,
        "credits": 0,
        "skipped": [],
    }

    site = _location(Location, Employee)

    if site is None:
        result["skipped"].append(
            "Belum ada lokasi kerja selain kantor pusat di master.",
        )

        return result

    policy = _policy(RosterPolicy, location=site)

    if policy is None:
        result["skipped"].append(
            "Belum ada Roster Policy yang punya pola siklus — jalankan "
            "seed_roster_policy dulu.",
        )

        return result

    log(f"Site {site} · policy {policy.code} "
        f"({policy.cycle_work_days}/{policy.cycle_off_days})")

    people = list(
        Employee.objects
        .filter(
            is_deleted=False,
            is_active=True,
            organization__location=site,
            organization__is_deleted=False,
        )
        .select_related("organization", "employment")
        .order_by("employee_number")
    )

    # Menyaring ke pegawai yang **sudah** dinyatakan roster.
    #
    # Bawaannya mati, dan itu benar untuk pemakaian biasa:
    # `candidates()` sengaja ikut menawarkan pegawai yang belum punya
    # Roster Policy, karena justru merekalah yang perlu disetup di
    # tenant baru. Tapi di tenant peragaan hal itu menarik masuk
    # pegawai kantor yang kebetulan berkantor di site — dan begitu
    # dokumennya di-commit, `commit_line()` menuliskan Roster Policy ke
    # kepegawaiannya. Orangnya berubah jadi pegawai roster tanpa ada
    # yang memutuskannya.
    if only_roster_employees:
        before = len(people)

        people = [
            person
            for person in people
            if getattr(
                getattr(person, "employment", None), "roster_policy_id", None,
            )
            or getattr(
                getattr(person, "employment", None), "roster_crew_id", None,
            )
        ]

        if before != len(people):
            log(
                f"{before - len(people)} pegawai site dilewati: belum "
                "dinyatakan sebagai pegawai roster.",
            )

    if employees:
        people = people[:employees]

    if not people:
        result["skipped"].append(
            f"Belum ada pegawai di {site} — jalankan seed_demo_workforce "
            "dulu.",
        )

        return result

    ids = [person.pk for person in people]

    # --- bersihkan data uji sebelumnya --------------------------------
    #
    # Urutannya penting: ledger dulu (menunjuk rencana lewat FK
    # SET_NULL, tapi barisnya tetap harus hilang), lalu dokumen, lalu
    # rencananya.
    removed = RotationCreditTransaction.objects.filter(
        employee_id__in=ids,
    ).delete()[0]

    removed += RosterAdjustment.objects.filter(
        employee_id__in=ids,
    ).delete()[0]

    removed += RosterSetupRequest.objects.filter(
        notes__startswith=MARKER,
    ).delete()[0]

    RotationPeriod.objects.filter(rotation__employee_id__in=ids).delete()

    removed += SiteRotation.objects.filter(
        employee_id__in=ids,
        setup_line__isnull=True,
    ).delete()[0]

    removed += SiteRotation.objects.filter(employee_id__in=ids).delete()[0]

    log(f"{removed} baris data uji lama dibuang.")

    # --- dokumen setup -------------------------------------------------

    # Jangkar dokumen. Dioper pemanggil supaya seluruh fase peragaan
    # berangkat dari satu tanggal yang sama; bawaannya tanggal 1 bulan
    # berjalan, yang benar untuk pemakaian sehari-hari tapi salah untuk
    # membangun sejarah — jadwal lahir di bulan ini sementara
    # presensinya diisi dua bulan ke belakang, dan keduanya terlihat
    # benar sendiri-sendiri.
    if as_of is None:
        today = timezone.localdate()

        as_of = date(today.year, today.month, 1)

    log(f"Jangkar dokumen (as_of): {as_of}")

    setup = RosterSetupService.create(
        data={
            "company": site.company,
            "location": site,
            "as_of_date": as_of,
            "horizon_months": 12,
            "notes": (
                f"{MARKER} Setup roster awal {site} — data uji, aman "
                "dihapus."
            ),
        },
    )

    log(f"Dokumen {setup.document_number} dibuat.")

    # Daftar pegawai di atas disusun sebelum dokumennya ada, jadi ia
    # belum melewati penyaring kelayakan dokumen — Feature
    # Applicability yang mematikan Roster untuk sebuah Employee Group,
    # misalnya. Sejak penambahan baris dijaga service, pegawai seperti
    # itu **menghentikan** seed alih-alih menghasilkan baris yang gagal
    # di commit. Disaring di sini, dan yang dilewati disebutkan.
    eligible = set(
        RosterSetupService.eligible_employees(request=setup)
        .values_list("pk", flat=True),
    )

    passed_over = [
        person.employee_number
        for person in people
        if person.pk not in eligible
    ]

    people = [person for person in people if person.pk in eligible]

    if passed_over:
        log(
            f"{len(passed_over)} pegawai dilewati (Roster tidak berlaku "
            f"atau sudah punya rencana): {', '.join(passed_over[:10])}",
        )

    for offset, person in enumerate(people):
        # Jangkar sengaja berjenjang: satu batch, beberapa gelombang.
        # Kalau semuanya sama, kasus yang justru paling sering di
        # lapangan — gelombang bergantian — tidak pernah terlihat di
        # layar.
        #
        # Sebarannya **dilipat ke dalam satu putaran**. Dulu jaraknya
        # tetap 15 hari per orang, jadi batch berisi sembilan belas
        # pegawai membentang 270 hari ke belakang: separuhnya jatuh
        # beberapa putaran sebelum jangkar, dan tiap satunya memicu
        # peringatan `stale_anchor` yang benar tapi tidak berguna —
        # yang dimaksud memang blok yang sedang dijalani, bukan blok
        # pertama dulu.
        cycle = policy.cycle_length or 1

        # Mundur **minimal satu langkah**, tidak pernah nol.
        #
        # Jangkar yang jatuh persis di `as_of` membuat blok kerjanya
        # mulai sesudah hari perjalanan — jadi tanggal pertama jendela
        # tidak tertutup segmen apa pun, dan presensi hari itu tidak
        # punya jadwal untuk dibandingkan. Satu langkah mundur memberi
        # kelonggaran yang cukup untuk hari perjalanan terpanjang
        # policy ini.
        back = ((offset + 1) * stagger_days) % cycle or stagger_days

        RosterSetupLineService.create(
            data={
                "request": setup,
                "employee": person,
                "roster_policy": policy,
                "current_cycle_start": as_of - timedelta(days=back),
                # Satu orang membawa saldo dari sistem lama.
                "opening_rotation_credit": (
                    Decimal("10.00") if offset == 0 else Decimal("0.00")
                ),
                "note": (
                    "Saldo dibawa dari sistem lama."
                    if offset == 0
                    else ""
                ),
            },
        )

        result["lines"] += 1

    preview = RosterSetupService.preview(request=setup)

    log(f"Preview: {preview['total_lines']} baris, "
        f"{preview['blocking_lines']} bermasalah, "
        f"{preview['warning_lines']} berperingatan.")

    # **`can_commit`, bukan `can_submit`.** Seed ini commit langsung
    # tanpa approval, jadi kesiapan meja persetujuannya bukan syaratnya:
    # batch satu site penuh lazimnya memuat pegawai dengan atasan
    # langsung berbeda-beda, dan itu memang menghalangi Submit — tapi
    # bukan menghalangi seed menerbitkan jadwalnya. Kalau yang dipakai
    # `can_submit`, seed roster berhenti tanpa satu rencana pun dan itu
    # terbaca seperti seed yang rusak, bukan seperti aturan yang bekerja.
    if not preview["can_commit"]:
        for item in preview["document_validations"]:
            if item["level"] == "blocking":
                result["skipped"].append(item["message"])

        for row in preview["lines"]:
            for item in row["validations"]:
                if item["level"] == "blocking":
                    result["skipped"].append(
                        f"{row['employee_number']}: {item['message']}",
                    )

        return result

    # Kesiapan alurnya tetap dilaporkan — supaya jelas kenapa dokumen
    # peragaan ini tidak bisa diajukan lewat tombol Submit.
    for item in preview["workflow_validations"]:
        if item["level"] == "blocking":
            log(f"  (tidak menghalangi seed) {item['message']}")

    # Commit langsung tanpa approval: seed tidak boleh bergantung pada
    # ada tidaknya akun approver di tenant ini. Jalur approval-nya diuji
    # terpisah di `apps/hr/tests/roster/`.
    RosterSetupService.commit(request=setup)

    setup.refresh_from_db()

    result["plans"] = SiteRotation.objects.filter(
        employee_id__in=ids,
        is_deleted=False,
    ).count()

    log(f"Status dokumen: {setup.get_status_display()} · "
        f"{result['plans']} rencana terbit.")

    if setup.commit_error:
        result["skipped"].append(setup.commit_error)

    # --- penyesuaian ---------------------------------------------------

    plan = (
        SiteRotation.objects
        .filter(
            employee=people[0],
            is_deleted=False,
            baseline_version__isnull=False,
        )
        .order_by("-id")
        .first()
    )

    if plan is None:
        return result

    # Blok kerja yang **belum dijalani**. Bukan yang pertama.
    #
    # `RosterRecalculationService.assert_recalculable()` menolak
    # tanggal berlaku yang jatuh di segmen terkunci: jadwal yang sudah
    # lewat tidak dihitung ulang, dan itu aturan yang benar. Selama
    # jangkar dokumen selalu tanggal 1 bulan berjalan, blok pertama
    # kebetulan selalu masih di depan — jadi memilih yang pertama tidak
    # pernah terlihat salah. Begitu jangkarnya mundur dua bulan untuk
    # membangun sejarah, blok pertama sudah dikunci dan seed berhenti
    # dengan galat yang menyebut tanggal, bukan menyebut seed.
    today = timezone.localdate()

    first_work = (
        RotationPeriod.objects
        .filter(
            rotation=plan,
            is_deleted=False,
            version_to__isnull=True,
            segment_type="work",
            end_date__gte=today,
        )
        .order_by("start_date")
        .first()
    )

    if first_work is None:
        result["skipped"].append(
            "Tidak ada blok kerja yang belum dijalani untuk "
            f"{people[0].employee_number}; contoh penyesuaian roster "
            "dilewati.",
        )

        return result

    adjustment = RosterAdjustmentService.create(
        data={
            "plan": plan,
            "adjustment_kind": AdjustmentKind.WORK_EXTENSION,
            "effective_date": first_work.end_date,
            "days": 7,
            "reason": (
                f"{MARKER} Kapal pengganti terlambat; blok kerja "
                "diperpanjang seminggu."
            ),
            "reference": "MEMO-DEMO-001",
        },
    )

    adjustment.status = AdjustmentStatus.APPROVED

    adjustment.save(update_fields=["status"])

    RosterAdjustmentService.apply(adjustment=adjustment)

    adjustment.refresh_from_db()

    result["adjustments"] = 1

    log(f"Penyesuaian {adjustment.document_number}: "
        f"{adjustment.get_status_display()}, "
        f"kredit {adjustment.credit_days}.")

    if adjustment.apply_error:
        result["skipped"].append(adjustment.apply_error)

    result["credits"] = RotationCreditTransaction.objects.filter(
        employee_id__in=ids,
        is_deleted=False,
    ).count()

    balance = RotationCreditService.balance_for(people[0])

    log(f"Saldo rotation credit {people[0].employee_number}: "
        f"{balance.balance} (sisa {balance.carried_excess_days} hari).")

    return result
