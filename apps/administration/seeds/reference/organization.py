"""
Referensi struktur organisasi.

**Location Type dan Facility Type dipisah, dan itu inti berkas ini.**
Sebelumnya `LocationType` memuat 18 baris: Head Office dan Mine
berdampingan dengan Workshop, Warehouse, Jetty, dan Camp. Akibatnya
satu site Gebe harus dipecah jadi belasan Location supaya gudang dan
jettynya bisa dicatat — dan begitu dipecah, "berapa orang di Gebe"
tidak lagi bisa dijawab satu angka, karena penempatan, absensi, dan
kalender libur semuanya menempel ke Location.

Pembedanya satu pertanyaan: **apakah ada orang yang penempatannya di
situ?** Kalau ya, itu Location. Kalau tidak, itu Facility.
"""

from apps.administration.models.references.organization import (
    BranchType,
    CompanyType,
    FacilityType,
    LocationType,
)

from .base import seed_reference


# Jenis lokasi kerja. Pendek, dan memang seharusnya pendek.
LOCATION_TYPES = [
    ("HO", "Head Office", 10),
    ("OFFICE", "Office", 20),
    ("MINE", "Mine", 30),
    ("PROJECT", "Project", 40),
    ("PORT", "Port", 50),
]


# Jenis fasilitas di dalam sebuah lokasi.
FACILITY_TYPES = [
    ("WORKSHOP", "Workshop", 10),
    ("WAREHOUSE", "Warehouse", 20),
    ("JETTY", "Jetty", 30),
    ("PLANT", "Plant", 40),
    ("FACTORY", "Factory", 50),
    ("LAB", "Laboratory", 60),
    ("STORE", "Store", 70),
    ("CAMP", "Camp", 80),
    ("DC", "Distribution Center", 90),
    ("DEPOT", "Depot", 100),
    ("TERMINAL", "Terminal", 110),
]


# Baris `LocationType` yang pindah ke `FacilityType`, plus dua yang
# tidak menjelaskan apa pun (`DEFAULT`, `OTHER`).
#
# **Soft delete, dan hanya kalau tidak dipakai.** `Location.location_type`
# memang `SET_NULL`, jadi hard delete tidak akan menggagalkan apa pun —
# justru itu masalahnya: lokasi yang tipenya terpakai akan kehilangan
# tipenya tanpa ada yang tahu. Yang masih dipakai dilaporkan supaya
# dipindahkan sadar.
OBSOLETE_LOCATION_TYPES = [
    "DEFAULT",
    "OTHER",
    "JETTY",
    "PLANT",
    "FACTORY",
    "WAREHOUSE",
    "WORKSHOP",
    "LAB",
    "STORE",
    "CAMP",
    "DC",
    "DEPOT",
    "TERMINAL",
]


ORGANIZATION_REFERENCE_DATA = {
    CompanyType: [
        ("COMP", "Company", 10),
        ("SUB", "Subsidiary", 20),
        ("JV", "Joint Venture", 30),
        ("REP", "Representative Company", 40),
    ],

    BranchType: [
        ("DEFAULT", "Default Branch", 10),
        ("HO", "Head Office", 20),
        ("BR", "Branch Office", 30),
        ("AREA", "Area Office", 40),
        ("REGIONAL", "Regional Office", 50),
        ("REP", "Representative Office", 60),
    ],

    LocationType: LOCATION_TYPES,

    FacilityType: FACILITY_TYPES,
}


def retire_obsolete_location_types() -> list[str]:
    """
    Tarik jenis lokasi yang sebenarnya fasilitas.

    Mengembalikan daftar kode yang **dilewati** karena masih dipakai —
    pemanggilnya yang melaporkan, supaya perintah seed bisa memberi
    tahu apa yang harus dibereskan tangan.
    """
    from apps.administration.models import Location

    skipped = []

    for code in OBSOLETE_LOCATION_TYPES:
        row = LocationType.objects.filter(
            code=code,
            is_deleted=False,
        ).first()

        if row is None:
            continue

        used = Location.objects.filter(
            location_type=row,
            is_deleted=False,
        ).count()

        if used:
            skipped.append(f"{code} ({used} lokasi)")
            continue

        row.is_deleted = True
        row.is_active = False

        row.save(update_fields=["is_deleted", "is_active", "updated_at"])

    return skipped


def seed_organization_reference() -> None:
    for model, rows in ORGANIZATION_REFERENCE_DATA.items():
        seed_reference(
            model,
            [
                {
                    "code": code,
                    "name": name,
                    "sort_order": sort_order,
                    # Baris yang pernah ditarik lalu didaftarkan lagi
                    # harus hidup kembali — `update_or_create` tidak
                    # menyentuh kolom yang tidak disebut, jadi tanpa ini
                    # jenis yang sama tetap tidak muncul di dropdown.
                    "is_deleted": False,
                    "is_active": True,
                }
                for code, name, sort_order in rows
            ],
        )

    retire_obsolete_location_types()
