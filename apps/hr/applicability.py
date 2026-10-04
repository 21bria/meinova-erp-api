"""
Menerjemahkan Feature Applicability jadi penyaring queryset pegawai.

Konfigurasinya tinggal di `EmployeeGroup` (`apps.administration`); yang
di sini cuma cara membacanya dari sisi pegawai. Dipisah supaya modul
pemakai tidak satu pun perlu tahu jalur ORM-nya — `employment__
employee_group__roster_applicable` yang disalin ke lima berkas adalah
persis cara satu perubahan relasi meninggalkan empat pemanggil yang
diam-diam berhenti menyaring.

**`exclude(... = False)`, bukan `filter(... = True)`.** Bedanya bukan
gaya: pegawai yang belum punya `EmploymentAssignment`, atau yang
assignment-nya belum menyebut Employee Group, menghasilkan `NULL` pada
join — dan `filter(...=True)` membuang mereka semua. Tenant yang belum
mengisi group-nya akan melihat seluruh layar Roster, Attendance, dan
Travel Request mendadak kosong, tanpa satu pun pesan yang menyebut
sebabnya. `exclude` membuang **hanya** yang memang dimatikan admin.

Yang **tidak** dilakukan di sini: menyembunyikan pegawai dari Employee
Master, Org Chart, Reporting Line, atau Headcount. Applicability
menjawab "proses ini berlaku untuk siapa", bukan "baris ini boleh
dilihat siapa" — yang terakhir tetap `DataScopeService`, dan mencampur
keduanya membuat data hilang dari layar yang tidak ada hubungannya.
"""

from __future__ import annotations

from django.db.models import Q

from apps.administration.models.references.hr import (
    HRFeature,
    applicability_field,
)


__all__ = [
    "HRFeature",
    "applicability_field",
    "is_applicable",
    "applicable_features",
    "any_applicable",
    "all_applicable",
    "exclude_not_applicable",
    "exclude_none_applicable",
    "filter_employees",
    "parse_feature",
    "TRAVEL_REQUEST",
    "BUSINESS_TRIP",
    "BOTH",
    "NONE",
    "travel_document",
    "group_travel_document",
    "travel_document_warnings",
]


# Dokumen perjalanan yang berlaku — **turunan** dua penanda yang sudah
# ada, bukan konfigurasi ketiga. `field_break_applicable` = Travel
# Request (kepulangan site), `business_trip_applicable` = Business Trip
# (perjalanan dinas). Konstanta string biasa, sengaja bukan kolom atau
# TextChoices: nilainya tidak pernah disimpan, jadi tidak ada yang bisa
# hanyut dari kedua penanda sumbernya.
TRAVEL_REQUEST = "travel_request"
BUSINESS_TRIP = "business_trip"
BOTH = "both"
NONE = "none"


def parse_feature(value):
    """
    Kode dari query param jadi anggota `HRFeature`, atau `None`.

    Melempar bukan pilihan di sini: pemanggilnya dropdown, dan `?feature=
    typo` yang membalas 400 mematikan lookup untuk seluruh layar. Yang
    tidak dikenal diabaikan — dropdown tetap terbuka apa adanya, dan
    yang salah ketik ketahuan lewat pegawai yang seharusnya tersaring
    tapi tetap muncul.
    """
    if not value:
        return None

    try:
        return HRFeature(str(value).strip().lower())
    except ValueError:
        return None


def is_applicable(employee, feature) -> bool:
    """
    Proses ini berlaku untuk satu pegawai?

    Belum punya employment, atau belum punya Employee Group: **berlaku**.
    Sama alasannya dengan `exclude` di bawah — belum dikonfigurasi
    berarti seperti kemarin, bukan berarti dimatikan.
    """
    employment = getattr(employee, "employment", None)

    if employment is None:
        return True

    group = getattr(employment, "employee_group", None)

    if group is None:
        return True

    return group.applies_to(feature)


def applicable_features(employee) -> frozenset:
    """
    Himpunan proses yang berlaku untuk satu pegawai.

    Dipakai laporan yang mewakili **beberapa** proses sekaligus: alih-alih
    memanggil `is_applicable()` enam kali dan menyusun logikanya sendiri
    di tiap service, pemanggil menerima himpunannya lalu memutuskan
    sekali.
    """
    return frozenset(
        feature
        for feature in HRFeature
        if is_applicable(employee, feature)
    )


def any_applicable(employee, features) -> bool:
    """
    Minimal satu proses dari `features` berlaku untuk pegawai ini.

    Ini semantik **populasi laporan**: sebuah laporan yang mewakili
    Attendance + Leave + Overtime + Field Break memuat pegawai yang
    setidaknya salah satunya berlaku. Yang keenam-enamnya dimatikan
    tidak menghasilkan apa pun selain baris nol, dan baris nol di tengah
    tabel terbaca sebagai "orang ini tidak masuk sebulan penuh" — bukan
    sebagai "proses ini memang tidak berlaku untuknya".
    """
    return any(is_applicable(employee, feature) for feature in features)


def all_applicable(employee, features) -> bool:
    """
    Seluruh proses dari `features` berlaku.

    Untuk proses yang memang menuntut beberapa penanda sekaligus.
    Belum ada pemakainya hari ini; disediakan supaya pemanggil berikutnya
    tidak menulis `all(...)` sendiri lalu berbeda tafsir soal pegawai
    tanpa group.
    """
    return all(is_applicable(employee, feature) for feature in features)


def exclude_none_applicable(queryset, features, *, path: str = ""):
    """
    Buang baris yang **seluruh** `features`-nya dimatikan admin.

    Pasangan queryset untuk `any_applicable()`. Yang tersisa: pegawai
    yang setidaknya satu prosesnya masih berlaku — plus, seperti biasa,
    yang belum dikonfigurasi.

    **`employee_group__isnull=False` disebut eksplisit di depan syarat
    lain**, dan itu bukan hiasan. Tanpa itu, baris yang belum punya
    employment atau belum punya Employee Group menghasilkan `NULL` di
    setiap ruas; `NULL AND NULL` tetap `NULL`, dan `NOT NULL` bukan
    `TRUE` — jadi seluruh pegawai yang masternya belum diisi ikut
    terbuang, persis kebalikan dari aturan backward-compatible yang
    dipegang berkas ini. Dengan ruas itu, AND-nya bernilai `FALSE` yang
    tegas untuk mereka, dan `NOT FALSE` menyimpan barisnya.

    `features` kosong mengembalikan queryset apa adanya: "tidak ada
    proses yang diminta" bukan alasan mengosongkan laporan.
    """
    resolved = [
        feature
        for feature in (parse_feature(value) for value in features)
        if feature is not None
    ]

    if not resolved:
        return queryset

    prefix = f"{path}__" if path else ""

    condition = Q(
        **{f"{prefix}employment__employee_group__isnull": False},
    )

    for feature in resolved:
        condition &= Q(
            **{
                f"{prefix}employment__employee_group__"
                f"{applicability_field(feature)}": False,
            },
        )

    return queryset.exclude(condition)


def exclude_not_applicable(queryset, feature, *, path: str = ""):
    """
    Buang baris yang Employee Group-nya mematikan proses ini.

    `path` adalah jalur ORM dari model queryset ke Employee — kosong
    kalau querysetnya memang `Employee`, `"employee"` untuk model yang
    menggantungnya (RotationPeriod, TravelRequest, …).

    `feature` yang tidak dikenal mengembalikan queryset apa adanya,
    bukan queryset kosong: penyaring yang salah tulis tidak boleh
    mengosongkan layar.
    """
    resolved = parse_feature(feature)

    if resolved is None:
        return queryset

    prefix = f"{path}__" if path else ""

    return queryset.exclude(
        **{
            f"{prefix}employment__employee_group__"
            f"{applicability_field(resolved)}": False,
        },
    )


def filter_employees(queryset, feature):
    """`exclude_not_applicable()` untuk queryset `Employee` langsung."""
    return exclude_not_applicable(queryset, feature)


# -----------------------------------------------------------------------------
# Dokumen perjalanan (TR/BT POLICY-1)
# -----------------------------------------------------------------------------


def _travel_document(travel_request: bool, business_trip: bool) -> str:
    if travel_request and business_trip:
        return BOTH

    if travel_request:
        return TRAVEL_REQUEST

    if business_trip:
        return BUSINESS_TRIP

    return NONE


def group_travel_document(group) -> str:
    """
    Dokumen perjalanan yang berlaku untuk satu Employee Group.

    `None` (belum dikonfigurasi) = `BOTH`, aturan yang sama dengan
    `is_applicable()`. `BOTH` adalah keadaan **sah** — group lama yang
    kedua penandanya masih bawaan, atau kebijakan khusus yang memang
    membolehkan keduanya — bukan galat yang harus ditolak saat simpan.
    """
    if group is None:
        return BOTH

    return _travel_document(
        group.applies_to(HRFeature.FIELD_BREAK),
        group.applies_to(HRFeature.BUSINESS_TRIP),
    )


def travel_document(employee) -> str:
    """
    Dokumen perjalanan yang berlaku untuk satu pegawai:
    `TRAVEL_REQUEST`, `BUSINESS_TRIP`, `BOTH`, atau `NONE`.

    Dibaca dari `is_applicable()`, jadi pegawai tanpa employment atau
    tanpa group = `BOTH` (seperti sebelum resolver ini ada). Tidak ada
    lokasi, kode group, atau keanggotaan roster yang ikut menentukan.

    Ini bacaan, bukan penjagaan. Penolakannya tetap di service masing-
    masing dokumen (`field_break` di Travel Request, `business_trip` di
    Business Trip), saat dibuat **dan** saat diajukan.
    """
    return _travel_document(
        is_applicable(employee, HRFeature.FIELD_BREAK),
        is_applicable(employee, HRFeature.BUSINESS_TRIP),
    )


def travel_document_warnings(group) -> list[dict]:
    """
    Peringatan konfigurasi dokumen perjalanan untuk satu group.

    **Peringatan, bukan penolakan.** Kedua penanda `default=True`, jadi
    setiap group yang belum disentuh admin adalah `BOTH`; menolaknya saat
    simpan akan mengunci seluruh master yang sudah ada. Yang dilakukan
    hanya membuatnya terlihat.

    Bentuknya sama dengan `schedule_warnings` Roster Schedule:
    `{"kind", "message"}`. `kind` = nilai `travel_document` yang
    memicunya (`both` / `none`) — kunci yang diterjemahkan frontend;
    `message` cadangan teks untuk klien yang tidak mengenalnya.
    """
    mode = group_travel_document(group)

    if mode == BOTH:
        return [{
            "kind": BOTH,
            # Bukan "pilih salah satu": BOTH adalah konfigurasi sah — dua
            # dokumen untuk dua tujuan perjalanan yang berbeda (POLICY-2C).
            "message": (
                "Pegawai dalam grup ini dapat menggunakan Travel Request "
                "dan Perjalanan Dinas. Gunakan masing-masing dokumen "
                "sesuai tujuan perjalanannya."
            ),
        }]

    if mode == NONE:
        return [{
            "kind": NONE,
            "message": (
                "Pegawai dalam grup ini tidak dapat menggunakan Travel "
                "Request maupun Perjalanan Dinas."
            ),
        }]

    return []
