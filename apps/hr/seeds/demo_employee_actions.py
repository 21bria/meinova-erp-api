"""
Data uji dokumen Employee Action.

Layar Employee Actions dan tab History pegawai sama-sama kosong di
tenant yang belum pernah menjalankan satu perubahan kepegawaian pun,
dan kosong itu tidak bisa dibedakan dari rusak. Seed ini mengisinya
dengan dokumen yang **melewati jalur yang sama dengan pengguna**:
dibuat lewat `EmployeeActionService`, diajukan lewat `submit()`, lalu
disetujui satu meja demi satu meja dari kotak masuk masing-masing
approver. Kalau ada yang salah di rantai itu, seed ini yang lebih dulu
berhenti — bukan pengguna pertama besok pagi.

Empat keadaan sengaja dibuat berbeda supaya tiap tombol punya dokumen
yang memperlihatkannya:

* **APPLIED** — sudah tertulis ke data pegawai, muncul di tab History
* **SUBMITTED** — sedang menunggu meja pertama, tombol Approve/Reject
* **DRAFT** — belum diajukan, tombol Submit

Pemilik cast tetap `seed_demo_workforce`: di sini orangnya hanya
**dicari**, tidak pernah dibentuk. Pegawai yang belum ada atau belum
punya akun dilaporkan kurang.

Aman diulang — dokumen bertanda `MARKER` dibuang lebih dulu, hard
delete, karena dokumen uji yang tertinggal menahan pengajuan berikutnya
lewat constraint "satu dokumen satu pengajuan berjalan".
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction

from apps.hr.api.employee_action.services import EmployeeActionService
from apps.hr.models import (
    Employee,
    EmployeeAction,
    EmployeeActionStatus,
    EmployeeActionType,
)
from apps.workflow.models import InstanceStatus
from apps.workflow.services import (
    WorkflowApprovalService,
    WorkflowService,
)


MARKER = "[demo-employee-action]"

MODULE = "hr"
DOCUMENT_TYPE = "employee_action"


# ----------------------------------------------------------------------
# Pencarian
# ----------------------------------------------------------------------

def _employee(number: str) -> Employee | None:
    return (
        Employee.objects
        .filter(employee_number=number, is_deleted=False)
        .select_related("user", "organization", "employment")
        .first()
    )


def _hr_actor() -> Employee | None:
    """
    Pegawai HR yang mengetikkan dokumen untuk jenis yang tidak diatur.

    Jenis yang tidak punya `EmployeeActionPolicy` dulu jatuh ke
    `employee.user` — subjeknya sendiri — dan hasilnya tabel data uji
    memperlihatkan tiga dokumen yang kolom Employee dan Requested
    By-nya berbunyi sama persis, seolah pegawai mengusulkan
    perpanjangan kontraknya sendiri. Aturannya memang tidak melarang,
    tapi data peragaan yang mengajarkan kebiasaan yang salah lebih
    merugikan daripada tidak ada data sama sekali.

    Dicari lewat role, bukan nomor pegawai yang ditebak: `HR-ADMIN`
    dipegang orang yang berbeda di tiap tenant.
    """
    return (
        Employee.objects
        .filter(
            is_deleted=False,
            user__isnull=False,
            user__roles__code__in=("HR-ADMIN", "HR-MANAGER"),
        )
        .select_related("user")
        .order_by("employee_number")
        .first()
    )


def _already_applied(employee: Employee, action_type: str) -> bool:
    """
    Dokumen uji yang **sudah diterapkan** dibiarkan apa adanya.

    Menghapus lalu membuatnya ulang berarti perubahannya diterapkan
    dua kali: kontrak yang tadinya diperpanjang setahun jadi dua tahun
    di jalankan kedua, dan riwayat pegawainya berubah tiap seed
    dijalankan. Yang boleh dibuat ulang cuma dokumen yang belum
    menyentuh data pegawai.
    """
    return EmployeeAction.objects.filter(
        employee=employee,
        action_type=action_type,
        status=EmployeeActionStatus.APPLIED,
        notes__contains=MARKER,
    ).exists()


def _clear_previous(employee: Employee) -> int:
    """Membuang dokumen uji sebelumnya yang belum diterapkan."""
    actions = EmployeeAction.objects.filter(
        employee=employee,
        notes__contains=MARKER,
    ).exclude(
        status=EmployeeActionStatus.APPLIED,
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


# ----------------------------------------------------------------------
# Alur
# ----------------------------------------------------------------------

def _approve_all(instance, log, limit=None) -> None:
    """
    Menjalankan alurnya sampai berhenti, satu keputusan per putaran.

    Approver diambil dari baris yang sedang ditunggu, lalu **diperiksa
    lewat kotak masuknya** sebelum tombolnya ditekan — itu jalur yang
    dilewati pengguna sungguhan, jadi penyaringan kotak masuk yang salah
    menghentikan seed ini, bukan lolos diam-diam.
    """
    from apps.workflow.registry import completion_handler

    handler = completion_handler(
        module=MODULE,
        document_type=DOCUMENT_TYPE,
    )

    taken = 0

    for _ in range(12):
        if limit is not None and taken >= limit:
            return

        instance.refresh_from_db()

        if instance.status != InstanceStatus.PENDING:
            return

        pending = instance.pending_approvals.select_related(
            "approver",
            "approver_employee",
        ).first()

        if pending is None or pending.approver_id is None:
            log(
                "      ! Baris berjalan tidak punya approver berakun — "
                "alur berhenti."
            )

            return

        actor = pending.approver

        in_inbox = (
            WorkflowApprovalService.pending_for(
                actor,
                module=MODULE,
                document_type=DOCUMENT_TYPE,
            )
            .filter(pk=pending.pk)
            .exists()
        )

        if not in_inbox:
            log(
                f"      ! Baris #{pending.sequence} tidak muncul di "
                f"kotak masuk {actor.email} — alur berhenti."
            )

            return

        name = (
            pending.approver_employee.full_name
            if pending.approver_employee_id
            else actor.email
        )

        WorkflowService.approve(
            instance=instance,
            user=actor,
            comment=f"Disetujui oleh {name}.",
            on_complete=handler,
        )

        taken += 1

        log(f"      ✓ {pending.name} disetujui {name}")


# ----------------------------------------------------------------------
# Skenario
# ----------------------------------------------------------------------

def _scenarios(today: date) -> list[dict]:
    """
    Skenario dipilih dari keadaan pegawai data uji yang sudah ada,
    bukan dikarang: perpanjangan hanya untuk yang memang berkontrak,
    pengangkatan hanya untuk yang jenis kepegawaiannya berkontrak.
    Kalau `seed_demo_workforce` berubah, yang tidak cocok dilewati
    dengan alasannya, bukan gagal di tengah.
    """
    return [
        {
            "employee_number": "SGA003",
            "action_type": EmployeeActionType.CONTRACT_EXTENSION,
            "label": "Perpanjangan kontrak, disetujui penuh",
            "requires_contract": True,
            "extend_months": 12,
            "reason": (
                "Perpanjangan kontrak satu tahun. Penilaian kinerja "
                "periode berjalan memenuhi target."
            ),
            "run": "apply",
        },
        {
            "employee_number": "HO004",
            "action_type": EmployeeActionType.EMPLOYMENT_TYPE_CHANGE,
            "label": "Pengangkatan jadi karyawan tetap",
            "requires_contract": True,
            "to_permanent": True,
            "reason": (
                "Diangkat menjadi karyawan tetap setelah dua periode "
                "kontrak."
            ),
            "run": "apply",
        },
        {
            "employee_number": "SGA006",
            "action_type": EmployeeActionType.CONTRACT_EXTENSION,
            "label": "Perpanjangan kontrak, menunggu persetujuan",
            "requires_contract": True,
            "extend_months": 6,
            "reason": (
                "Perpanjangan enam bulan menunggu keputusan kebutuhan "
                "tenaga site."
            ),
            "run": "submit",
        },
        {
            "employee_number": "HO002",
            "action_type": EmployeeActionType.PROMOTION,
            "label": "Promosi jabatan, masih draft",
            "position_of": "HO001",
            "reason": (
                "Diusulkan naik jabatan mengikuti struktur baru "
                "departemen."
            ),
            "run": "draft",
        },
    ]


def _qualified_initiator(employee, action_type):
    """
    Pegawai yang usulannya sah menurut `EmployeeActionPolicy`.

    Seed harus melewati aturan yang sama dengan pengguna, bukan
    menembusnya lewat superuser: kalau aturannya membuat sebuah
    skenario tidak mungkin dijalankan, itu justru yang perlu terlihat
    di sini — bukan besok, saat kepala departemen pertama mencoba
    mengusulkan kenaikan gaji.

    Mengembalikan `None` kalau jenisnya memang tidak dibatasi.
    """
    from apps.administration.models import ActionInitiator
    from apps.hr.api.employee_action.policy import (
        EmployeeActionPolicyResolver,
    )

    policy = EmployeeActionPolicyResolver.match(
        employee=employee,
        action_type=action_type,
    )

    if policy is None or policy.initiator_type == ActionInitiator.ANY:
        return None

    candidates = (
        Employee.objects
        .filter(is_deleted=False, user__isnull=False)
        .select_related("organization__position", "employment", "user")
    )

    for candidate in candidates:
        if EmployeeActionPolicyResolver.qualifies(
            employee=employee,
            policy=policy,
            candidate=candidate,
        ):
            return candidate

    # Aturannya ada tapi tidak ada yang memenuhinya — dilaporkan
    # pemanggil sebagai skenario yang dilewati, bukan dipaksa lewat.
    return False


def _permanent_type():
    from apps.administration.models import EmploymentType

    return (
        EmploymentType.objects
        .filter(requires_contract=False, is_deleted=False)
        .order_by("sort_order", "code")
        .first()
    )


def _build_payload(scenario, employee, today) -> dict | None:
    employment = getattr(employee, "employment", None)

    if employment is None:
        return None

    data = {
        "employee": employee,
        "action_type": scenario["action_type"],
        "reason": scenario["reason"],
        "notes": MARKER,
    }

    if scenario.get("extend_months"):
        current_end = employment.contract_end

        if current_end is None:
            return None

        # 30 hari per bulan sudah cukup untuk data uji, dan tidak
        # menyeret ketergantungan tanggal baru hanya untuk seed.
        new_end = current_end + timedelta(
            days=30 * scenario["extend_months"],
        )

        data["effective_date"] = current_end + timedelta(days=1)
        data["proposed_contract_end"] = new_end
        data["proposed_contract_type"] = employment.contract_type

        return data

    if scenario.get("to_permanent"):
        permanent = _permanent_type()

        if permanent is None:
            return None

        effective = employment.contract_end or today

        data["effective_date"] = effective + timedelta(days=1)
        data["proposed_employment_type"] = permanent
        data["confirmation_date"] = effective + timedelta(days=1)

        return data

    if scenario.get("position_of"):
        source = _employee(scenario["position_of"])
        organization = getattr(source, "organization", None)
        position = getattr(organization, "position", None)

        if position is None:
            return None

        data["effective_date"] = today + timedelta(days=30)
        data["proposed_position"] = position

        return data

    return None


# ----------------------------------------------------------------------
# Seed
# ----------------------------------------------------------------------

def run(*, log=print) -> dict:
    today = date.today()

    created = 0
    applied = 0
    submitted = 0
    drafts = 0
    removed = 0
    missing: list[str] = []
    skipped: list[str] = []

    for scenario in _scenarios(today):
        number = scenario["employee_number"]
        employee = _employee(number)

        if employee is None or employee.user_id is None:
            missing.append(number)

            continue

        if _already_applied(employee, scenario["action_type"]):
            skipped.append(
                f"{number}: {scenario['label'].lower()} sudah "
                f"diterapkan sebelumnya, dibiarkan"
            )

            continue

        employment = getattr(employee, "employment", None)

        if scenario.get("requires_contract") and not getattr(
            getattr(employment, "employment_type", None),
            "requires_contract",
            False,
        ):
            skipped.append(
                f"{number}: bukan pegawai berkontrak, "
                f"{scenario['label'].lower()} dilewati"
            )

            continue

        removed += _clear_previous(employee)

        payload = _build_payload(scenario, employee, today)

        if payload is not None:
            initiator = _qualified_initiator(
                employee,
                scenario["action_type"],
            )

            if initiator is False:
                skipped.append(
                    f"{number}: tidak ada yang memenuhi syarat "
                    f"pengusul untuk {scenario['label'].lower()}"
                )

                continue

            if initiator is None:
                # Jenis yang tidak diatur: yang mengusulkan HR, bukan
                # pegawainya sendiri. Kalau tenant belum punya pemegang
                # role HR, biarkan kosong — `apply_requested_by` yang
                # mengisinya dari pelaku, dan perilaku itu memang yang
                # ingin diperagakan.
                initiator = _hr_actor()

            if initiator:
                payload["requested_by"] = initiator

        if payload is None:
            skipped.append(
                f"{number}: data pendukung belum lengkap, "
                f"{scenario['label'].lower()} dilewati"
            )

            continue

        # Yang menjalankan = pengusulnya sendiri kalau aturannya
        # menyebut orang tertentu. Dengan begitu seed menempuh jalur
        # yang sama dengan pengguna, termasuk pelewatan meja pengusul.
        actor = (
            payload["requested_by"].user
            if payload.get("requested_by")
            and payload["requested_by"].user_id
            else employee.user
        )

        log(f"  • {number} — {scenario['label']}")

        try:
            with transaction.atomic():
                action = EmployeeActionService.create(
                    data=payload,
                    user=actor,
                )
        except Exception as error:  # noqa: BLE001
            skipped.append(f"{number}: gagal dibuat — {error}")

            continue

        created += 1

        if scenario["run"] == "draft":
            drafts += 1

            log("      · dibiarkan draft")

            continue

        try:
            instance = EmployeeActionService.submit(
                instance=action,
                user=actor,
            )
        except Exception as error:  # noqa: BLE001
            skipped.append(f"{number}: gagal diajukan — {error}")

            continue

        if scenario["run"] == "submit":
            submitted += 1

            log("      · menunggu meja pertama")

            continue

        _approve_all(instance, log)

        action.refresh_from_db()

        if action.status == EmployeeActionStatus.APPLIED:
            applied += 1

            log(f"      · diterapkan {action.applied_at:%Y-%m-%d}")
        else:
            submitted += 1

            skipped.append(
                f"{number}: alurnya berhenti di {action.status}"
            )

    return {
        "created": created,
        "applied": applied,
        "submitted": submitted,
        "drafts": drafts,
        "removed": removed,
        "missing": missing,
        "skipped": skipped,
    }
