"""
Data peragaan untuk layar Reports → HR → Manpower Movement.

Bukan cast baru dan bukan pegawai baru. Yang diterbitkan berkas ini
cuma **peristiwa** — dua kepergian dan dua mutasi — lewat
`EmployeeActionService`, jalur yang sama persis dengan pengguna.

Kenapa perlu perintah tersendiri, dan kenapa peristiwanya tidak
disuntikkan langsung ke tabel:

* Tenant peragaan sebelum ini tidak punya satu pun pergerakan. Nol
  dokumen `APPLIED`, nol `termination_date` terisi, tiga puluh pegawai
  aktif semua. Layar Manpower Movement karenanya berdiri dengan lima
  dari enam kartunya bernilai nol — tidak bisa dibedakan dari layar
  yang gagal memuat.
* Mutasi yang ditulis langsung ke `OrganizationAssignment` **tidak akan
  muncul** di laporan sama sekali, dan itu bukan bug melainkan
  kontraknya: sejak `OrganizationService.PROTECTED_FIELDS` berlaku,
  satu-satunya sumber Transfer In/Out adalah `EmployeeAction` yang
  sudah diterapkan. Seed yang menembus jalur itu akan memperagakan
  keadaan yang tidak mungkin terjadi lewat layar.

Peristiwanya dijangkarkan ke **bulan berjalan**, bukan ke tanggal
patokan cast (`demo_employees.TODAY`): laporan ini default-nya bulan
berjalan, dan peragaan yang tanggalnya menjauh satu hari tiap hari akan
mengosongkan layar yang justru sedang diuji — pelajaran yang sama sudah
dibayar Contract Expiry.

**`join_date` sengaja tidak disentuh satu pun.** Ia menentukan jatah
cuti seluruh data uji, dan menggesernya demi mengisi satu kartu KPI
akan merusak peragaan cuti yang sudah benar. Akibatnya kartu Join
bernilai nol pada tampilan bulan berjalan; ganti periodenya ke **Year**
dan ketiga join 2026 muncul bersama kepergian dan mutasinya, identitas
tetap tertutup. Itu batas yang diterima, bukan yang disembunyikan.

**Yang ikut berubah, dan memang tidak bisa tidak:** dua pegawai jadi
tidak aktif, jadi Manpower Summary tenant peragaan turun dari 30 ke 28,
dan dua mutasi memindahkan penempatan LOK006 dan HO006. Itu konsekuensi
dari memperagakan pergerakan yang sungguhan; peragaan pergerakan yang
tidak menggerakkan apa pun tidak memperagakan apa pun.

Aman diulang: peristiwa yang sudah diterapkan tidak pernah diterbitkan
kedua kalinya.
"""

from __future__ import annotations

from datetime import date

from django.db import transaction

from apps.administration.models import Location, TerminationReason
from apps.hr.models import (
    Employee,
    EmployeeAction,
    EmployeeActionStatus,
    EmployeeActionType,
)
from apps.hr.seeds.demo_employee_actions import (
    DOCUMENT_TYPE,
    MODULE,
    _approve_all,
    _hr_actor,
    _qualified_initiator,
)
from apps.hr.models import OrganizationAssignment
from apps.workflow.services import WorkflowService


# **Tidak ada import dari `apps.reports` di berkas ini**, dan itu aturan
# arah ketergantungan, bukan selera: `reports → hr`, tidak pernah
# sebaliknya (`docs/claude/reports.md`). Seed ini karena itu tidak
# menyebut satu pun nama jenis pergerakan — yang memutuskan sebuah
# dokumen jadi Transfer In, Transfer Out, atau Internal Move adalah
# laporannya, dari batas populasi yang sedang dilihat pembacanya.


MARKER = "[demo-manpower-movement]"


# Kode lokasi tenant peragaan. **Ada dua baris ber-kode `JKT-HO`**,
# satu per badan usaha, jadi mencarinya lewat kode saja akan
# memindahkan orang ke perusahaan lain tanpa ada yang memintanya.
# Pencariannya karena itu selalu dibatasi ke company pegawainya
# sendiri — lihat `_location()`.
HO_LOCATION_CODE = "JKT-HO"
SITE_LOCATION_CODE = "SAGEA-MINE"


# Cast dipilih dari pegawai peragaan yang **paling sedikit dirujuk seed
# lain**, dan itu disengaja: memindahkan atau memberhentikan orang yang
# jadi atasan, approver, atau anggota crew roster akan menjatuhkan
# peragaan modul di sebelahnya, dan yang gagal duluan justru bukan
# laporan ini.
SCENARIOS = [
    {
        "employee_number": "HO007",
        "action_type": EmployeeActionType.RESIGNATION,
        "label": "Mengundurkan diri",
        "day": 10,
        "reason_code": "RESIGN",
        "reason": (
            "Mengundurkan diri atas permintaan sendiri; melanjutkan "
            "studi pascasarjana."
        ),
    },
    {
        "employee_number": "LOK005",
        "action_type": EmployeeActionType.TERMINATION,
        "label": "Kontrak berakhir, tidak diperpanjang",
        "day": 20,
        "reason_code": "CONTRACT_END",
        "reason": (
            "Masa kontrak berakhir dan kebutuhan tenaga di posisi ini "
            "sudah terpenuhi."
        ),
    },
    {
        "employee_number": "LOK006",
        "action_type": EmployeeActionType.TRANSFER,
        "label": "Mutasi site → head office",
        "day": 5,
        "to_location_code": HO_LOCATION_CODE,
        "reason": (
            "Mutasi ke kantor pusat mengikuti kebutuhan penguatan tim "
            "operasional."
        ),
    },
    {
        "employee_number": "HO008",
        "action_type": EmployeeActionType.TRANSFER,
        "label": "Mutasi head office → site",
        "day": 15,
        "to_location_code": SITE_LOCATION_CODE,
        "reason": (
            "Penugasan ke site untuk mendampingi implementasi sistem "
            "baru."
        ),
    },
]


SEPARATION_TYPES = (
    EmployeeActionType.RESIGNATION,
    EmployeeActionType.TERMINATION,
)


# ----------------------------------------------------------------------
# Pembantu
# ----------------------------------------------------------------------


def _employee(number: str) -> Employee | None:
    return (
        Employee.objects
        .filter(employee_number=number, is_deleted=False)
        .select_related(
            "user",
            "employment__employment_type",
            "organization__company",
            "organization__location",
        )
        .first()
    )


def _already_applied(employee: Employee, action_type: str) -> bool:
    return EmployeeAction.objects.filter(
        employee=employee,
        action_type=action_type,
        status=EmployeeActionStatus.APPLIED,
        is_deleted=False,
    ).exists()


def _anchor(today: date, day: int) -> date:
    """
    Tanggal berlaku di **bulan berjalan**.

    Dipatok ke hari tertentu, bukan ke `today - n`: dua kali menjalankan
    seed dalam bulan yang sama harus menghasilkan tanggal yang sama,
    kalau tidak baris tabelnya bergeser tiap kali perintahnya diulang.
    """
    return today.replace(day=day)


def _location(code: str, company_id) -> Location | None:
    """
    Lokasi tujuan mutasi, dicari lewat kode **di dalam company
    pegawainya**.

    Dibatasi ke satu company dengan sengaja: tenant peragaan punya dua
    baris ber-kode `JKT-HO`, satu per badan usaha. Pencarian lewat kode
    saja akan memulangkan yang mana pun yang lebih dulu, dan peragaan
    mutasi antarlokasi diam-diam berubah jadi mutasi antarperusahaan —
    beserta seluruh angka Transfer In/Out yang ikut berubah artinya.

    Baris yang sudah di-soft-delete tidak ikut: pelajaran
    `SITE_SHIFT_CODE` — seed yang menunjuk baris terhapus gagal diam,
    dan yang terlihat cuma peragaan yang kosong tanpa sebab.
    """
    return (
        Location.objects
        .filter(
            code=code,
            company_id=company_id,
            is_deleted=False,
            is_active=True,
        )
        .select_related("company")
        .first()
    )


def _termination_reason(code: str | None) -> TerminationReason | None:
    """
    Alasan kepergian, diutamakan yang kodenya diminta skenario.

    Jatuh ke baris mana pun kalau kodenya tidak ada: yang menentukan
    peragaan ini jalan atau tidak adalah **ada tidaknya master**-nya,
    bukan cocok tidaknya satu kode. Master-nya sendiri baru ikut
    di-seed bersama laporan ini — sebelumnya `TerminationReason` tidak
    pernah terisi di tenant mana pun.
    """
    queryset = TerminationReason.objects.filter(
        is_deleted=False,
        is_active=True,
    )

    if code:
        match = queryset.filter(code=code).first()

        if match is not None:
            return match

    return queryset.order_by("code").first()


def _clear_open(employee: Employee) -> int:
    """
    Membuang dokumen peragaan milik berkas ini yang **belum
    diterapkan**.

    Tanpa ini seed tidak bisa diulang sama sekali:
    `assert_no_open_duplicate` menolak dokumen kedua untuk pegawai dan
    jenis yang sama selama yang pertama masih terbuka, jadi satu
    percobaan yang berhenti di tengah — master yang belum lengkap,
    penempatan tujuan yang tidak sah — mengunci pegawainya untuk
    selamanya sampai ada yang membersihkannya lewat layar.

    Yang `APPLIED` **tidak pernah** disentuh: itu sudah jadi riwayat
    kepegawaian orangnya, dan seed yang menghapus riwayat adalah seed
    yang membuat datanya berbohong. Penandanya `MARKER` di kolom
    `reason`, jadi dokumen peragaan modul lain — perpanjangan kontrak
    Contract Expiry, misalnya — tidak ikut terbawa.
    """
    actions = (
        EmployeeAction.objects
        .filter(employee=employee, reason__contains=MARKER)
        .exclude(status=EmployeeActionStatus.APPLIED)
    )

    removed = 0

    for action in actions:
        WorkflowService.history_for(
            document=action,
            module=MODULE,
            document_type=DOCUMENT_TYPE,
        ).delete()

        action.delete()

        removed += 1

    return removed


def _destination_placement(location) -> dict:
    """
    Kerangka penempatan yang sah di lokasi tujuan, **disalin dari
    pegawai yang sudah ada di sana**.

    Mutasi antarlokasi tidak cukup memindahkan `location` saja:
    `OrganizationAssignment.clean()` menuntut division, department,
    section, position, dan cost center berada di bawah lokasi yang
    sama, jadi dokumen yang cuma mengusulkan lokasi baru akan lolos
    seluruh alur persetujuan lalu gagal di detik penerapannya —
    persis kegagalan yang `apply_error` ada untuk menangkapnya.

    Disalin dari pegawai lain, bukan dipilih satu per satu lewat kode
    master: kombinasi yang sah **sudah** ada di baris orang yang
    bekerja di sana, dan menyusunnya sendiri berarti seed ini harus
    ikut mengetahui hierarki organisasi tenant peragaan — pengetahuan
    kedua yang akan berhenti cocok pada perubahan struktur pertama.
    """
    template = (
        OrganizationAssignment.objects
        .filter(
            location=location,
            company=location.company,
            is_deleted=False,
            employee__is_deleted=False,
            employee__is_active=True,
            department__isnull=False,
            position__isnull=False,
        )
        .select_related(
            "division",
            "department",
            "section",
            "position",
            "cost_center",
        )
        .order_by("pk")
        .first()
    )

    if template is None:
        return {}

    placement = {
        "proposed_division": template.division,
        "proposed_department": template.department,
        "proposed_section": template.section,
        "proposed_position": template.position,
        "proposed_cost_center": template.cost_center,
    }

    return {
        key: value
        for key, value in placement.items()
        if value is not None
    }


def _build_payload(scenario: dict, employee: Employee, today: date):
    """Payload dokumen, atau `None` kalau data pendukungnya belum ada."""
    effective = _anchor(today, scenario["day"])

    payload = {
        "employee": employee,
        "action_type": scenario["action_type"],
        "effective_date": effective,
        "reason": f"{scenario['reason']} {MARKER}",
    }

    if scenario["action_type"] in SEPARATION_TYPES:
        payload["last_working_date"] = effective

        reason = _termination_reason(scenario.get("reason_code"))

        # Wajib untuk **keduanya**, walau `ACTION_FIELD_RULES` cuma
        # menuntutnya pada Termination. Yang menolak sebenarnya ada
        # satu lapis lebih dalam: `EmploymentAssignment.clean()`
        # mewajibkan Termination Reason begitu Termination Date diisi,
        # jadi Resignation tanpa alasan lolos seluruh alur persetujuan
        # lalu gagal di detik penerapannya — dokumen berstatus approved
        # dengan `apply_error` terisi, dan tidak satu pun kepergian
        # tercatat.
        if reason is None:
            return None

        payload["termination_reason"] = reason

        return payload

    current = getattr(employee, "organization", None)

    destination = _location(
        scenario["to_location_code"],
        getattr(current, "company_id", None),
    )

    if destination is None:
        return None

    # Mutasi yang tujuannya sama dengan asalnya bukan mutasi. Dilewati,
    # bukan diterbitkan sebagai dokumen yang tidak memindahkan apa-apa.
    if current is not None and current.location_id == destination.pk:
        return None

    placement = _destination_placement(destination)

    # Lokasi tujuan yang belum berpenghuni tidak bisa dijadikan tujuan
    # mutasi peragaan: tidak ada kombinasi sah yang bisa disalin, dan
    # menebaknya berarti dokumen yang gagal saat diterapkan.
    if not placement:
        return None

    payload["proposed_location"] = destination
    payload.update(placement)

    # Company ikut disebut hanya kalau memang berpindah — usulan yang
    # dikosongkan berarti "tidak berubah", dan mengisinya dengan nilai
    # yang sama membuat laporan mengira ada perpindahan perusahaan.
    if (
        destination.company_id
        and current is not None
        and current.company_id != destination.company_id
    ):
        payload["proposed_company"] = destination.company

    return payload


# ----------------------------------------------------------------------
# Perintah
# ----------------------------------------------------------------------


def seed(*, log=print) -> dict:
    from apps.hr.api.employee_action.services import EmployeeActionService

    today = date.today()

    applied: list[dict] = []
    skipped: list[str] = []

    for scenario in SCENARIOS:
        number = scenario["employee_number"]

        employee = _employee(number)

        if employee is None:
            skipped.append(f"{number}: pegawainya belum ada")

            continue

        if employee.user_id is None:
            skipped.append(f"{number}: belum punya akun, alur tidak jalan")

            continue

        if _already_applied(employee, scenario["action_type"]):
            skipped.append(
                f"{number}: {scenario['label'].lower()} sudah "
                f"diterapkan sebelumnya, dibiarkan"
            )

            continue

        _clear_open(employee)

        payload = _build_payload(scenario, employee, today)

        if payload is None:
            skipped.append(
                f"{number}: data pendukung belum lengkap, "
                f"{scenario['label'].lower()} dilewati"
            )

            continue

        # Siapa yang **boleh** mengusulkan ditentukan
        # `EmployeeActionPolicy`, bukan ditebak seed. Kalau aturannya
        # membuat skenario ini tidak mungkin, itu justru yang perlu
        # terlihat di sini — bukan ditembus lewat superuser.
        initiator = _qualified_initiator(employee, scenario["action_type"])

        if initiator is False:
            skipped.append(
                f"{number}: tidak ada yang memenuhi syarat pengusul "
                f"untuk {scenario['label'].lower()}"
            )

            continue

        if initiator is None:
            initiator = _hr_actor()

        if initiator:
            payload["requested_by"] = initiator

        actor = (
            initiator.user
            if initiator and initiator.user_id
            else employee.user
        )

        log(f"  • {number:<8}{scenario['label']}")

        try:
            with transaction.atomic():
                action = EmployeeActionService.create(
                    data=payload,
                    user=actor,
                )
        except Exception as error:  # noqa: BLE001
            skipped.append(f"{number}: gagal dibuat — {error}")

            continue

        try:
            instance = EmployeeActionService.submit(
                instance=action,
                user=actor,
            )
        except Exception as error:  # noqa: BLE001
            skipped.append(f"{number}: gagal diajukan — {error}")

            continue

        _approve_all(instance, log)

        action.refresh_from_db()

        if action.status != EmployeeActionStatus.APPLIED:
            skipped.append(
                f"{number}: alurnya berhenti di {action.status}"
            )

            continue

        applied.append(
            {
                "number": number,
                "name": employee.full_name,
                "label": scenario["label"],
                "effective_date": action.effective_date,
                "document": action.document_number,
            }
        )

        log(
            f"      · diterapkan, berlaku "
            f"{action.effective_date.isoformat()} "
            f"({action.document_number})"
        )

    return {
        "as_of": today,
        "applied": applied,
        "skipped": skipped,
    }
