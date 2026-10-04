"""
Kebijakan roster bawaan, diturunkan dari dokumen "Substansi Roster".

Hari perjalanan dipetakan dari Point of Hire karena itu yang
menentukannya di lapangan — Makassar 2 hari, Yogyakarta/Bandung/Luwuk
Banggai 3 hari, walau orangnya satu crew dan satu pola roster.

Tenggat pengajuan 7 hari mengikuti kebutuhan notifikasi H-7. Alasan
mendadak (duka, sakit, dinas, penyesuaian roster karena ada pengganti)
boleh menembusnya — itu keadaan yang memang tidak bisa direncanakan
seminggu sebelumnya.

Dua pola diseed, bukan satu
---------------------------
Sejak policy jadi pembawa pola siklus, satu site butuh satu baris per
pola yang benar-benar dipakainya. Gebe memakai 6:2 dan 8:2, dan yang
6:2 ditandai bawaan karena itu yang paling banyak dipakai.

Angkanya **tidak dikarang**: keduanya cocok dengan `RosterCrew` yang
sudah ada di seed data uji (`CREW-6W` 42/14 dan `CREW-8W` 56/14).
"""

from django.db import transaction

from apps.administration.models import (
    City,
    Company,
    Country,
    Location,
    Province,
    RosterPolicy,
    RosterTravelDay,
)
from apps.administration.models.references.hr import RotationPurpose


# (nama kota, provinsi, hari keluar, hari kembali)
#
# Dipecah per arah sejak jendela travel jadi baris jadwal tersendiri.
# Angka totalnya tetap sama dengan sebelumnya (Makassar 2, Yogyakarta 3),
# cuma sekarang terbaca ke mana perginya — dan pembulatan sisi keluar
# yang dulu tersembunyi di generator jadi angka yang bisa diubah.
#
# Kotanya ikut dibuat kalau belum ada di master. Master kota bawaan
# cuma memuat Jawa dan Bali, sementara Point of Hire pegawai site
# tersebar sampai Sulawesi dan Maluku — dan POH yang tidak ketemu
# membuat pemetaan hari perjalanannya diam-diam jatuh ke angka bawaan.
TRAVEL_DAYS_BY_POH = [
    ("Makassar", "Sulawesi Selatan", 1, 1),
    ("Yogyakarta", "DI Yogyakarta", 2, 1),
    ("Bandung", "Jawa Barat", 2, 1),
    ("Luwuk Banggai", "Sulawesi Tengah", 2, 1),
    # Titik transit menuju Gebe. Bukan POH, tapi lazim jadi asal
    # perjalanan pegawai lokal Maluku Utara.
    ("Ternate", "Maluku Utara", 1, 0),
    ("Sorong", "Papua Barat Daya", 1, 1),
]


# (kode, nama, work, off, bawaan?)
#
# Suffix polanya ditulis apa adanya supaya orang yang membaca daftar
# dropdown tahu mana yang dipilihnya tanpa membuka detailnya. Yang
# membaca angkanya tetap kolom, bukan kodenya.
CYCLE_PATTERNS = [
    ("6-2", "Roster 6:2 (42/14)", 42, 14, True),
    ("8-2", "Roster 8:2 (56/14)", 56, 14, False),
]


def ensure_city(*, name: str, province_name: str) -> City:
    """
    Kota beserta provinsinya, dibuat kalau belum ada.

    Dicari lewat `filter().first()`, **bukan** `get_or_create` — dan itu
    bukan selera. Master wilayah tenant ini diisi dua sumber: seed
    peragaan lama (kode pendek, tanpa `aid`) dan import Kemendagri
    (`aid` terisi). Keduanya menulis "DI Yogyakarta", jadi
    `get_or_create(name=...)` melempar `MultipleObjectsReturned` dan
    menjatuhkan **seluruh** seed policy roster — hari perjalanan per
    Point of Hire ikut hilang, dan hilangnya baru terbaca saat ada
    jadwal roster yang terbit tanpa satu pun segmen travel.

    Yang dipilih baris **tertua** (`id` menaik), bukan yang ber-`aid`.
    Baris tanpa `aid` justru yang sudah ditunjuk `RosterTravelDay` di
    tenant yang pernah diseed; memindahkannya ke baris resmi akan
    menerbitkan pasangan kedua untuk kota yang sama dan membuat tabel
    hari perjalanan punya dua baris yang saling bertentangan.
    """
    country = Country.objects.filter(is_deleted=False).order_by("id").first()

    province = (
        Province.objects
        .filter(name=province_name, is_deleted=False)
        .order_by("id")
        .first()
    )

    if province is None:
        province = Province.objects.create(
            name=province_name,
            code=province_name.upper().replace(" ", "-")[:20],
            country=country,
        )

    city = (
        City.objects
        .filter(name=name, is_deleted=False)
        .order_by("id")
        .first()
    )

    if city is None:
        city = City.objects.create(
            name=name,
            code=name.upper().replace(" ", "-")[:20],
            province=province,
        )

    return city


# Alasan yang boleh diajukan mendadak.
URGENT_PURPOSE_CODES = ["SICK", "DUTY", "DEMOB"]


# Baris yang sudah tidak dipakai lagi. Policy lama tidak membawa pola
# siklus, jadi ia tidak bisa ditugaskan ke pegawai — dan membiarkannya
# di dropdown cuma menghasilkan pilihan yang gagal saat disimpan.
#
# Soft delete, bukan hard: `EmploymentAssignment.roster_policy` dan
# `SiteRotation.roster_policy` melindunginya dengan PROTECT, dan hard
# delete akan menggagalkan seluruh seed begitu ada satu dokumen yang
# menunjuknya.
OBSOLETE_CODES = ["ROSTER-GEBE"]


def find_location(*, company, name: str):
    """
    Site yang diatur, dicari kode dulu baru namanya.

    Pencarian nama persis sempat meleset: master menamainya "Gebe -
    Site", jadi `name="Gebe"` tidak ketemu dan seluruh policy mendarat
    sebagai aturan **se-company** tanpa satu pun pesan. Kesalahan
    seperti itu tidak pernah terlihat dari layar — policy-nya ada,
    isinya benar, cuma cakupannya salah.
    """
    token = name.strip().upper()

    return (
        Location.objects.filter(
            company=company, code__iexact=token, is_deleted=False,
        ).first()
        or Location.objects.filter(
            company=company, name__iexact=name, is_deleted=False,
        ).first()
        or Location.objects.filter(
            company=company, name__istartswith=name, is_deleted=False,
        ).first()
    )


@transaction.atomic
def seed(*, company_code: str = "MMR", location_name: str = "Sagea Mine") -> dict:
    company = Company.objects.filter(
        code=company_code, is_deleted=False,
    ).first()

    if company is None:
        return {"policies": 0, "travel_days": 0, "skipped": company_code}

    location = find_location(company=company, name=location_name)

    # Policy lama ditarik lebih dulu: ia memakai pasangan
    # (company, location) yang sama dan menyandang `is_default`, jadi
    # constraint `uniq_active_rosterpolicy_default` akan menolak baris
    # bawaan yang baru selama ia masih aktif.
    retired = (
        RosterPolicy.objects
        .filter(
            company=company,
            code__in=OBSOLETE_CODES,
            is_deleted=False,
        )
        .update(is_deleted=True, is_active=False, is_default=False)
    )

    policies = []
    rows = 0

    for suffix, name, work_days, off_days, is_default in CYCLE_PATTERNS:
        code = f"ROSTER-{location_name.upper()}-{suffix}"[:50]

        policy, _ = RosterPolicy.objects.update_or_create(
            company=company,
            code=code,
            defaults={
                "location": location,
                "name": f"{name} — {location_name}",
                "description": (
                    "Diturunkan dari dokumen Substansi Roster. Hari "
                    "perjalanan mengikuti Point of Hire; rasio konversi "
                    "dihitung dari pola siklus di atas."
                ),
                "is_default": is_default,
                "cycle_work_days": work_days,
                "cycle_off_days": off_days,
                # Aturan #4 dokumen: perjalanan Sorong/Ternate → site
                # sudah dihitung On Site, jadi tanggal yang dipegang HR
                # sebagai jangkar adalah tanggal tiba.
                "roster_start_basis": "site_arrival",
                "rolling_horizon_months": 12,
                "default_travel_out_days": 1,
                "default_travel_in_days": 1,
                "travel_day_mode": "fixed",
                "travel_creates_segment": True,
                # Aturan #1: site → POH bukan On Site.
                "travel_out_counts_as_roster_day": False,
                # Aturan #4: POH → site sudah dihitung On Site.
                "travel_in_counts_as_roster_day": True,
                "count_transit_overnight": True,
                # Aturan #17: pesawat cancel di luar kendali pegawai,
                # dan yang di luar kendali tidak menghasilkan hak
                # tambahan.
                "travel_variance_credit_eligible": False,
                "credit_enabled": True,
                # Dikosongkan: rasio dihitung dari pola policy sendiri
                # (56:14 = 4, 42:14 = 3), jadi pola baru tidak perlu
                # menunggu ada yang menambahkan barisnya di master.
                "conversion_ratio": None,
                "credit_rounding": "floor",
                "credit_carry_remainder": True,
                "credit_allow_negative": False,
                "request_lead_days": 7,
                "notify_lead_days": 7,
                "is_deleted": False,
                "is_active": True,
            },
        )

        for city_name, province_name, out_days, in_days in TRAVEL_DAYS_BY_POH:
            city = ensure_city(name=city_name, province_name=province_name)

            RosterTravelDay.objects.update_or_create(
                policy=policy,
                point_of_hire=city,
                defaults={
                    "travel_out_days": out_days,
                    "travel_in_days": in_days,
                    "is_deleted": False,
                },
            )

            rows += 1

        purposes = RotationPurpose.objects.filter(
            code__in=URGENT_PURPOSE_CODES, is_deleted=False,
        )

        policy.urgent_purposes.set(purposes)

        policies.append(policy)

    return {
        "policies": len(policies),
        "travel_days": rows,
        "retired": retired,
        "urgent_purposes": RotationPurpose.objects.filter(
            code__in=URGENT_PURPOSE_CODES, is_deleted=False,
        ).count(),
        "location": location.name if location else "(semua site)",
    }
