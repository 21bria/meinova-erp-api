"""
Status satu baris file absensi di layar review.

Dibagi dua, dan pembedanya satu pertanyaan: **barisnya jadi presensi
atau tidak.**

* **Blocking** — barisnya tidak ditulis. Nomor mesin yang belum
  dipetakan, waktu yang tidak terbaca, pegawai di luar cakupan.
* **Peringatan** — barisnya **tetap** ditulis. Tap yang jatuh di hari
  tidak terjadwal masuk ke sini: kehilangan tap sungguhan lebih buruk
  daripada baris presensi yang kolom jadwalnya kosong, dan lembur akhir
  pekan memang tidak punya jadwal.
"""

from __future__ import annotations


VALID = "valid"

# Tetap ditulis.
NO_SCHEDULE = "no_schedule"
NO_ROSTER_SHIFT = "no_roster_shift"

# Baris harian yang cuma membawa satu sisi — jam masuk tanpa jam pulang,
# atau keduanya sama. Tetap masuk, tapi **tidak** boleh terbaca sebagai
# hari kerja yang lengkap: itu bedanya antara "pulangnya belum tercatat"
# dan "pulang tepat waktu".
INCOMPLETE_DAY = "incomplete_day"

# Tidak ditulis.
UNKNOWN_DEVICE = "unknown_device"
UNKNOWN_DEVICE_EMPLOYEE = "unknown_device_employee"
UNKNOWN_EMPLOYEE = "unknown_employee"
INVALID_DATETIME = "invalid_datetime"
INVALID_EVENT = "invalid_event"
OUTSIDE_ORGANIZATION_SCOPE = "outside_organization_scope"
NOT_APPLICABLE = "not_applicable"
NO_ORGANIZATION = "no_organization"
DUPLICATE = "duplicate"


LABELS = {
    VALID: "Valid",
    NO_SCHEDULE: "No Schedule",
    NO_ROSTER_SHIFT: "No Roster / Shift",
    INCOMPLETE_DAY: "Incomplete Day",
    UNKNOWN_DEVICE: "Unknown Device",
    UNKNOWN_DEVICE_EMPLOYEE: "Unknown Device Employee",
    UNKNOWN_EMPLOYEE: "Unknown Employee",
    INVALID_DATETIME: "Invalid Datetime",
    INVALID_EVENT: "Invalid Event",
    OUTSIDE_ORGANIZATION_SCOPE: "Outside Organization Scope",
    NOT_APPLICABLE: "Not Applicable",
    NO_ORGANIZATION: "No Organization Assignment",
    DUPLICATE: "Duplicate",
}


# Status yang barisnya tetap masuk.
IMPORTABLE = frozenset({
    VALID,
    NO_SCHEDULE,
    NO_ROSTER_SHIFT,
    INCOMPLETE_DAY,
})


def label(code: str) -> str:
    return LABELS.get(code, code or "")


def is_importable(code: str) -> bool:
    return code in IMPORTABLE
