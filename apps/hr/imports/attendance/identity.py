"""
Nomor mesin -> Employee ERP.

Tiga tingkat, dan urutannya adalah aturannya:

1. **Pemetaan device yang ditulis orang** (`AttendanceDeviceEmployee`).
   Menang atas apa pun. Ini satu-satunya jalur yang benar untuk mesin
   yang nomor enroll-nya tidak berhubungan dengan Employee Number.
2. **Transform yang dikonfigurasi di Import Profile**, lalu dicocokkan
   ke `Employee.employee_number`. Opsional, dan bawaannya cuma
   "cocokkan apa adanya" — persis perilaku importer lama.
3. **Tidak ketemu.** Barisnya dilaporkan, dan tidak ada pegawai baru
   yang dibuat. File mesin tidak pernah menjadi sumber master.

Yang sengaja **tidak** ada di berkas ini: nama site, kode perusahaan,
awalan nomor pegawai, dan nama vendor mesin. Semuanya konfigurasi.
Satu `if lokasi == ...` di sini berarti klien berikutnya butuh rilis
kode untuk bisa mengimpor absensinya.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.hr.models import (
    AttendanceDevice,
    AttendanceDeviceEmployee,
    Employee,
)

from .config import IdentifierConfig


@dataclass
class EmployeeMatch:
    employee: Employee | None = None

    # "device_mapping" | "employee_number" | ""
    source: str = ""

    # Nilai yang benar-benar dipakai mencocokkan, sesudah transform.
    matched_value: str = ""


def apply_transform(
    raw_value: Any,
    config: IdentifierConfig,
) -> str:
    """
    Menjalankan langkah transform **berurutan**.

    Urutannya diambil dari profile apa adanya: `["strip_leading_zeros",
    "left_pad", "prefix"]` menghasilkan sesuatu yang lain daripada
    `["prefix", "left_pad"]`, dan menebak urutan "yang masuk akal" di
    sini berarti dua tenant dengan konfigurasi yang sama mendapat hasil
    berbeda tergantung versi kode.
    """
    value = str(raw_value or "").strip()

    for step in config.steps:
        if step == "trim":
            value = value.strip()

        elif step == "upper":
            value = value.upper()

        elif step == "lower":
            value = value.lower()

        elif step == "strip_leading_zeros":
            stripped = value.lstrip("0")

            # Nomor yang isinya nol semua tidak boleh jadi string
            # kosong — itu bukan "tidak ada nomor", itu nomor nol.
            value = stripped or "0"

        elif step == "left_pad":
            if config.pad_length > 0:
                value = value.rjust(
                    config.pad_length,
                    config.pad_char,
                )

        elif step == "prefix":
            value = f"{config.prefix}{value}"

        elif step == "suffix":
            value = f"{value}{config.suffix}"

    return value


def resolve_device(
    *,
    device_code: str,
    cache: dict[str, AttendanceDevice | None] | None = None,
) -> AttendanceDevice | None:
    code = str(device_code or "").strip()

    if not code:
        return None

    if cache is not None and code in cache:
        return cache[code]

    device = (
        AttendanceDevice.objects
        .filter(
            code__iexact=code,
            is_active=True,
        )
        .select_related(
            "company",
            "branch",
            "location",
        )
        .first()
    )

    if cache is not None:
        cache[code] = device

    return device


def find_device_mapping(
    *,
    device: AttendanceDevice | None,
    external_employee_id: str,
    cache: dict[tuple[int, str], Employee | None] | None = None,
) -> Employee | None:
    if device is None:
        return None

    external_id = str(external_employee_id or "").strip()

    if not external_id:
        return None

    key = (device.id, external_id.lower())

    if cache is not None and key in cache:
        return cache[key]

    mapping = (
        AttendanceDeviceEmployee.objects
        .filter(
            device=device,
            external_employee_id__iexact=external_id,
            is_active=True,
            is_deleted=False,
        )
        .select_related(
            "employee",
            "employee__employment",
            "employee__employment__employee_group",
            "employee__organization",
        )
        .first()
    )

    employee = mapping.employee if mapping is not None else None

    if employee is not None and (
        employee.is_deleted
        or not employee.is_active
    ):
        # Pemetaannya masih ada tapi orangnya sudah keluar. Diperlakukan
        # sebagai tidak terpetakan supaya barisnya terlihat di review,
        # bukan diam-diam menempel ke pegawai nonaktif.
        employee = None

    if cache is not None:
        cache[key] = employee

    return employee


def find_by_employee_number(
    value: str,
    *,
    cache: dict[str, Employee | None] | None = None,
) -> Employee | None:
    code = str(value or "").strip()

    if not code:
        return None

    key = code.lower()

    if cache is not None and key in cache:
        return cache[key]

    employee = (
        Employee.objects
        .filter(
            employee_number__iexact=code,
            is_active=True,
            is_deleted=False,
        )
        .select_related(
            "employment",
            "employment__employee_group",
            "employment__shift",
            "employment__work_schedule",
            "organization",
        )
        .first()
    )

    if cache is not None:
        cache[key] = employee

    return employee


def resolve_employee(
    *,
    raw_identifier: Any,
    device: AttendanceDevice | None,
    config: IdentifierConfig,
    caches: dict[str, Any] | None = None,
) -> EmployeeMatch:
    caches = caches if caches is not None else {}

    mapping_cache = caches.setdefault("device_mapping", {})
    number_cache = caches.setdefault("employee_number", {})

    raw_value = str(raw_identifier or "").strip()

    if not raw_value:
        return EmployeeMatch()

    # 1. Pemetaan eksplisit menang. Transform tidak dijalankan sama
    #    sekali di jalur ini — orang yang menulis pemetaan sudah
    #    menyatakan jawabannya, dan menimpanya dengan tebakan aturan
    #    membuat pemetaan manual tidak ada gunanya.
    employee = find_device_mapping(
        device=device,
        external_employee_id=raw_value,
        cache=mapping_cache,
    )

    if employee is not None:
        return EmployeeMatch(
            employee=employee,
            source="device_mapping",
            matched_value=raw_value,
        )

    if not config.match_employee_number:
        return EmployeeMatch()

    # 2. Transform lalu cocokkan ke Employee Number.
    candidate = apply_transform(raw_value, config)

    employee = find_by_employee_number(
        candidate,
        cache=number_cache,
    )

    if employee is not None:
        return EmployeeMatch(
            employee=employee,
            source="employee_number",
            matched_value=candidate,
        )

    # Transform yang menghasilkan nilai berbeda tetap diberi kesempatan
    # pada nilai aslinya: profile yang baru diberi awalan tidak boleh
    # mematikan baris yang selama ini cocok apa adanya.
    if candidate != raw_value:
        employee = find_by_employee_number(
            raw_value,
            cache=number_cache,
        )

        if employee is not None:
            return EmployeeMatch(
                employee=employee,
                source="employee_number",
                matched_value=raw_value,
            )

    return EmployeeMatch()
