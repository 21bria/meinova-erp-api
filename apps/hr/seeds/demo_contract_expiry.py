"""
Data peragaan untuk layar Reports → HR → Contract Expiry.

Bukan cast baru, dan bukan kontrak baru. Yang dikerjakan berkas ini
cuma dua hal, dan keduanya lahir dari satu sifat seed pegawai peragaan:
`demo_employees.TODAY` **dipatok** (`date(2026, 8, 9)`), sengaja, karena
masa kerja menentukan jatah cuti dan data uji yang jawabannya berubah
tiap hari tidak bisa dipakai membandingkan apa pun.

Akibatnya untuk laporan yang menghitung sisa hari dari **hari ini**:
seluruh tanggal kontrak peragaan bergeser mundur satu hari tiap hari.
Sebulan sesudah seed dijalankan, kontrak yang mestinya memperagakan
"≤ 30 Hari" sudah pindah ke "Expired", dan dua kartu KPI berdiri kosong
di layar yang justru sedang diuji.

Jadi:

1. **Menjangkarkan ulang** akhir kontrak pegawai peragaan ke
   `hari ini + offset`, dengan offset dibaca dari cast yang sudah ada
   (`demo_employees.PEOPLE`) — bukan dari daftar nomor pegawai kedua
   yang harus dijaga tetap sama. Lima pegawai berkontrak di cast itu
   memang sudah ditempatkan di lima bucket yang berbeda.
2. **Menerbitkan satu dokumen perpanjangan yang masih berjalan** untuk
   kontrak yang paling mendesak, supaya kolom Renewal Status punya
   nilai selain "No Renewal Record". Dokumennya lewat
   `EmployeeActionService` — jalur yang sama dengan pengguna, bukan
   baris yang disuntikkan langsung.

Aman diulang: menjalankannya dua kali menghasilkan tanggal yang sama
(relatif terhadap hari menjalankannya) dan tidak pernah menerbitkan
dokumen kedua.

**Yang tidak disentuh sama sekali:** join date, jatah cuti, presensi,
roster, dan pegawai yang kontraknya sudah pernah diubah oleh dokumen
Employee Action yang `APPLIED`. Yang terakhir itu aturan, bukan
kehati-hatian: menimpa tanggal hasil dokumen yang sudah diterapkan
membuat riwayat pegawainya berbohong tentang keadaannya sendiri.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.hr.models import (
    ACTION_OPEN_STATUSES,
    Employee,
    EmployeeAction,
    EmployeeActionStatus,
    EmployeeActionType,
)
from apps.hr.seeds import demo_employees
from apps.hr.seeds.demo_employee_actions import (
    _hr_actor,
    _qualified_initiator,
)


# **Tidak ada import dari `apps.reports` di berkas ini**, dan itu
# aturan arah ketergantungan, bukan selera: `reports → hr`, tidak pernah
# sebaliknya (`docs/claude/reports.md`). Seed ini karena itu tidak
# menyebut satu pun nama bucket — yang memutuskan bucket adalah
# laporannya, dan seed yang ikut menamainya menjadi tempat kedua yang
# harus diubah tiap ambangnya bergeser.


MARKER = "[demo-contract-expiry]"


CONTRACT_ACTION_TYPES = (
    EmployeeActionType.CONTRACT_EXTENSION,
    EmployeeActionType.CONTRACT_CHANGE,
)


def _offsets() -> dict[str, int]:
    """
    Nomor pegawai → offset akhir kontrak, dibaca dari cast peragaan.

    Satu sumber, bukan dua: daftar nomor yang ditulis ulang di sini
    akan berhenti cocok dengan cast pada perubahan pertama yang tidak
    ikut menyentuhnya, dan yang gagal duluan justru peragaannya.
    """
    return {
        person.number: person.contract_end
        for person in demo_employees.PEOPLE
        if person.contract_end is not None
    }


def _has_applied_contract_action(employee) -> bool:
    return EmployeeAction.objects.filter(
        employee=employee,
        action_type__in=CONTRACT_ACTION_TYPES,
        status=EmployeeActionStatus.APPLIED,
        is_deleted=False,
    ).exists()


def _has_any_contract_action(employee) -> bool:
    return EmployeeAction.objects.filter(
        employee=employee,
        action_type__in=CONTRACT_ACTION_TYPES,
        is_deleted=False,
    ).exists()


def _rebase(today: date, log) -> tuple[list[dict], list[str]]:
    """Menjangkarkan ulang akhir kontrak; satu baris log per pegawai."""
    moved: list[dict] = []
    skipped: list[str] = []

    for number, offset in sorted(_offsets().items(), key=lambda x: x[1]):
        employee = (
            Employee.objects
            .filter(employee_number=number, is_deleted=False)
            .select_related("employment__employment_type")
            .first()
        )

        if employee is None:
            skipped.append(f"{number}: pegawainya belum ada")

            continue

        employment = getattr(employee, "employment", None)
        employment_type = getattr(employment, "employment_type", None)

        # Penentunya `requires_contract`, bukan kode master. Pegawai
        # peragaan yang sudah diangkat tetap lewat dokumen Employee
        # Action tidak boleh dikembalikan berkontrak oleh seed.
        if employment is None or not getattr(
            employment_type,
            "requires_contract",
            False,
        ):
            skipped.append(f"{number}: bukan pegawai berkontrak lagi")

            continue

        if _has_applied_contract_action(employee):
            skipped.append(
                f"{number}: kontraknya hasil dokumen yang sudah "
                f"diterapkan, dibiarkan"
            )

            continue

        end = today + timedelta(days=offset)

        changes = {"contract_end": end}

        # `EmploymentAssignment.clean()` menolak akhir kontrak tanpa
        # awalnya. Baris peragaan selalu punya keduanya, tapi kalau
        # awalnya sempat kosong, mengisinya di sini lebih baik daripada
        # menyimpan baris yang tidak bisa dibuka lagi di layar.
        if employment.contract_start is None:
            changes["contract_start"] = employment.join_date or today

        for field, value in changes.items():
            setattr(employment, field, value)

        employment.save(update_fields=list(changes))

        moved.append(
            {
                "number": number,
                "name": employee.full_name,
                "contract_end": end,
                "days": offset,
            }
        )

        log(
            f"  • {number:<8}{employee.full_name:<20}"
            f"{end.isoformat()}  {offset:>+5} hari"
        )

    return moved, skipped


def _renewal(moved: list[dict], today: date, log) -> str | None:
    """
    Satu dokumen perpanjangan yang **masih menunggu persetujuan**,
    untuk kontrak yang paling mendesak dan belum punya dokumen apa pun.

    Kolom Renewal Status yang seluruh barisnya berbunyi "No Renewal
    Record" tidak bisa dibedakan dari kolom yang gagal dimuat — dan
    justru perbedaan antara "sudah ada yang mengurus" dan "belum ada
    yang mengurus" yang dicari pembaca laporan ini.
    """
    from apps.hr.api.employee_action.services import EmployeeActionService

    candidates = [
        item for item in moved
        if item["days"] >= 0
    ]

    if not candidates:
        return None

    target = min(candidates, key=lambda item: item["days"])

    employee = (
        Employee.objects
        .filter(employee_number=target["number"], is_deleted=False)
        .select_related("employment__contract_type", "user")
        .first()
    )

    if employee is None:
        return None

    if _has_any_contract_action(employee):
        log(
            f"  · {target['number']} sudah punya dokumen kontrak, "
            f"tidak diterbitkan lagi"
        )

        return None

    # Siapa yang **boleh** mengusulkan ditentukan `EmployeeActionPolicy`,
    # bukan ditebak seed. Helper-nya sudah ada di seed dokumen Employee
    # Action; memakainya berarti seed ini menempuh aturan yang sama
    # dengan pengguna — dan kalau aturannya membuat skenario ini tidak
    # mungkin, itu justru yang perlu terlihat di sini.
    initiator = _qualified_initiator(
        employee,
        EmployeeActionType.CONTRACT_EXTENSION,
    )

    if initiator is False:
        log(
            "  ! Tidak ada yang memenuhi syarat pengusul perpanjangan "
            "— dilewati"
        )

        return None

    if initiator is None:
        initiator = _hr_actor()

    actor = (
        initiator.user
        if initiator is not None and initiator.user_id
        else employee.user
    )

    if actor is None:
        log("  ! Tidak ada akun yang bisa menerbitkan dokumen — dilewati")

        return None

    employment = employee.employment

    payload = {
        "employee": employee,
        "action_type": EmployeeActionType.CONTRACT_EXTENSION,
        "effective_date": employment.contract_end + timedelta(days=1),
        "proposed_contract_type": employment.contract_type,
        "proposed_contract_end": employment.contract_end + timedelta(days=365),
        "reason": (
            "Perpanjangan kontrak satu tahun, menunggu keputusan "
            "kebutuhan tenaga."
        ),
        "notes": MARKER,
    }

    if initiator is not None:
        payload["requested_by"] = initiator

    try:
        with transaction.atomic():
            action = EmployeeActionService.create(data=payload, user=actor)
    except Exception as error:  # noqa: BLE001
        log(f"  ! Dokumen perpanjangan gagal dibuat — {error}")

        return None

    try:
        EmployeeActionService.submit(instance=action, user=actor)
    except Exception as error:  # noqa: BLE001
        # Draft tetap nilai Renewal Status yang sah, dan kegagalannya
        # disebut apa adanya — bukan dibiarkan terlihat seperti
        # dokumen yang memang sengaja dibiarkan draft.
        log(f"  ! Dokumen dibiarkan draft — {error}")

    action.refresh_from_db()

    log(
        f"  • {target['number']} — dokumen perpanjangan "
        f"{action.document_number or '(tanpa nomor)'} "
        f"berstatus {action.get_status_display()}"
    )

    return target["number"]


def seed(*, log=print) -> dict:
    today = timezone.localdate()

    log(f"Menjangkarkan akhir kontrak peragaan ke {today.isoformat()}")

    moved, skipped = _rebase(today, log)

    renewed = _renewal(moved, today, log)

    open_documents = EmployeeAction.objects.filter(
        action_type__in=CONTRACT_ACTION_TYPES,
        status__in=ACTION_OPEN_STATUSES,
        is_deleted=False,
    ).count()

    return {
        "as_of": today,
        "moved": moved,
        "skipped": skipped,
        "renewal": renewed,
        "open_documents": open_documents,
    }
