"""
Roster policy MMN milik dataset (DEMO-1F, 28 Sep 2026).

Sebelum DEMO-1F, 16 pegawai roster MMN memakai dua policy milik MMR
(`ROSTER-SAGEA-MINE-6-2-2-SHIFT`, `ROSTER-SAGEA MINE-8-2`). MMR dibuang,
jadi keduanya dipindah ke sumber ini — **nilai disalin kolom per kolom**
dari policy MMR id 1 dan 2 sebagaimana adanya di tenant `demo` pada
28 Sep 2026, bukan dirancang ulang:

    siklus, basis mulai, horizon, istirahat, hari perjalanan bawaan,
    mode & aturan hari perjalanan, kredit rotasi, tenggat permintaan,
    rotasi shift (SHIFT-1 → SHIFT-3 → SHIFT-2, 7 hari per blok),
    tujuan mendesak (SICK, DUTY, DEMOB), tabel hari perjalanan per POH
    (hanya baris aktif yang POH-nya kota aktif — lihat
    `NOT_COPIED_DEAD_TRAVEL_DAYS`; baris yang sudah dihapus lunak tidak ikut).

Kode policy dipertahankan: keunikannya per company
(`uniq_active_administration_rosterpolicy_code`). Rujukan ke master global
lewat **kode**: shift, tujuan rotasi, dan kota POH lewat (kode kota, kode
provinsi) — kode kota sendiri tidak unik di tenant ini.

Policy MMR `ROSTER-SAGEA-MINE-6-2-DAY` tidak ikut: tidak dipakai pegawai
dataset.
"""

from __future__ import annotations

from dataclasses import dataclass

COMPANY = "MMN"
LOCATION = "SAGEA-MINE"

#: Kolom aturan yang sama pada kedua policy (disalin dari MMR id 1/2).
COMMON = {
    "description": (
        "Diturunkan dari dokumen Substansi Roster. Hari perjalanan mengikuti "
        "Point of Hire; rasio konversi dihitung dari pola siklus di atas."
    ),
    "roster_start_basis": "site_arrival",
    "rolling_horizon_months": 12,
    "min_rest_hours": 24,
    "default_travel_out_days": 1,
    "default_travel_in_days": 1,
    "travel_day_mode": "fixed",
    "travel_creates_segment": True,
    "travel_out_counts_as_roster_day": False,
    "travel_in_counts_as_roster_day": True,
    "count_transit_overnight": True,
    "travel_variance_credit_eligible": False,
    "travel_variance_credit_max_days": 0,
    "credit_enabled": True,
    "conversion_ratio": None,
    "credit_rounding": "floor",
    "credit_carry_remainder": True,
    "credit_max_balance_days": None,
    "credit_expiry_months": None,
    "credit_allow_negative": False,
    "request_lead_days": 7,
    "notify_lead_days": 7,
    "is_active": True,
}

#: Rotasi shift: (urutan, kode shift, hari per blok).
ROTATION = ((1, "SHIFT-1", 7), (2, "SHIFT-3", 7), (3, "SHIFT-2", 7))

URGENT_PURPOSES = ("SICK", "DUTY", "DEMOB")

ROTATION_NOTE = "[demo] pola peragaan"


@dataclass(frozen=True)
class PolicySpec:
    code: str
    name: str
    cycle_work_days: int
    cycle_off_days: int
    is_default: bool
    #: ((kode kota, kode provinsi), hari keluar, hari masuk)
    travel_days: tuple[tuple[tuple[str, str], int, int], ...]

    def fields(self) -> dict:
        return {
            **COMMON,
            "code": self.code,
            "name": self.name,
            "cycle_work_days": self.cycle_work_days,
            "cycle_off_days": self.cycle_off_days,
            "is_default": self.is_default,
        }


POLICIES: tuple[PolicySpec, ...] = (
    PolicySpec(
        code="ROSTER-SAGEA-MINE-6-2-2-SHIFT",
        name="Roster 6:2 (42/14) — Sagea Mine — 2 Shift",
        cycle_work_days=42,
        cycle_off_days=14,
        is_default=True,
        travel_days=(
            (("32.04", "32"), 1, 1),
            (("34.71", "34"), 1, 1),
            (("72.01", "72"), 1, 1),
            (("73.71", "73"), 1, 1),
            (("82.71", "82"), 0, 1),
            (("96.71", "96"), 0, 1),
        ),
    ),
    PolicySpec(
        code="ROSTER-SAGEA MINE-8-2",
        name="Roster 8:2 (56/14) — Sagea Mine",
        cycle_work_days=56,
        cycle_off_days=14,
        is_default=False,
        travel_days=(
            (("32.04", "32"), 2, 1),
            (("96.01", "96"), 1, 1),
        ),
    ),
)

#: Baris POH policy MMR id 2 yang **tidak** disalin: seluruhnya menunjuk
#: master City yang sudah dihapus lunak (kota non-Kemendagri seed lama),
#: jadi tidak bisa dipilih sebagai POH siapa pun — konfigurasi mati. Tidak
#: satu pun pegawai dataset ber-POH, jadi hasil roster tidak berubah.
NOT_COPIED_DEAD_TRAVEL_DAYS = {
    "ROSTER-SAGEA MINE-8-2": (
        ("BDG", "JB"), ("LUWUK-BANGGAI", "SULAWESI-TENGAH"), ("LUWUK-BANGGAI", "72"),
        ("MAKASSAR", "SULAWESI-SELATAN"), ("MAKASSAR", "73"), ("SORONG", "PAPUA-BARAT-DAYA"),
        ("TERNATE", "MALUKU-UTARA"), ("TERNATE", "82"), ("YOGYAKARTA", "DI-YOGYAKARTA"),
        ("YOGYAKARTA", "34"),
    ),
}

BY_CODE = {spec.code: spec for spec in POLICIES}


def reference_codes() -> dict[str, set]:
    """Master global yang dirujuk — diperiksa perencana."""
    return {
        "Shift": {code for _, code, _ in ROTATION},
        "RotationPurpose": set(URGENT_PURPOSES),
        "City": {city for spec in POLICIES for city, _, _ in spec.travel_days},
    }


def resolve_city(key: tuple[str, str]):
    from apps.administration.models import City

    code, province = key
    found = list(City.objects.filter(code=code, province__code=province, is_deleted=False)[:2])

    if len(found) != 1:
        raise LookupError(f"Kota POH {code}/{province}: {len(found)} baris (harus tepat satu).")

    return found[0]


def policy(code: str):
    """Policy MMN dataset untuk satu kode — company + kode, bukan kode saja."""
    from apps.administration.models import RosterPolicy

    return RosterPolicy.objects.get(company__code=COMPANY, code=code, is_deleted=False)
