"""
Dua status yang dibaca Contract Expiry, dan keduanya **dihitung atau
dibacakan** — tidak satu pun disimpan di database.

* **Expiry Status** turun dari satu pengurangan: `contract_end -
  as_of`. Menyimpannya sebagai kolom berarti nilai yang mulai salah
  pada hari pertama sesudah ditulis, tanpa satu pun proses yang
  berbunyi — masalah yang sama dengan masa kerja di Employee Reporting
  Audit, dan diselesaikan dengan cara yang sama.
* **Renewal Status** dibacakan apa adanya dari dokumen `EmployeeAction`
  yang **masih berjalan**. Bukan kesimpulan: laporan ini tidak pernah
  menyatakan seseorang "sudah diperpanjang" hanya karena tanggalnya
  bergeser. Yang bergeser tanggalnya sudah tidak lagi berdiri di bucket
  yang mendesak — itu jawabannya sendiri.

Ambang bucket ditulis **sekali** di sini dan dipakai KPI, chart, tabel,
maupun filter. Ambang yang ditulis ulang di tiap pemakainya adalah cara
paling pasti membuat kartu "≤ 30 Hari" dan tabel yang disaring "≤ 30
Hari" menyebut jumlah yang berbeda.
"""

from __future__ import annotations


# ----------------------------------------------------------------------
# Ambang
# ----------------------------------------------------------------------
#
# Batasnya **inklusif di atas**: 30 masih `EXPIRING_30`, 31 sudah
# `EXPIRING_60`. Ditulis sebagai daftar (batas, kode) supaya urutan
# pemeriksaannya tidak bisa tertukar, dan supaya menambah bucket baru
# nanti berarti menambah satu baris — bukan menyisipkan satu `elif` di
# tengah rantai yang sudah panjang.

NEAR_TERM_DAYS = 30
MID_TERM_DAYS = 60
LONG_TERM_DAYS = 90


class ExpiryStatus:
    """
    Keadaan masa kontrak pada tanggal acuan.

    `NO_END_DATE` bukan bucket kelima yang dikarang: `EmploymentAssignment.
    clean()` memang mewajibkan Contract End begitu Contract Start diisi,
    tapi seed dan importer massal menulis lewat `save()` yang tidak
    memanggil `full_clean()`. Baris seperti itu **ada** di data hidup,
    dan menghilangkannya dari laporan berarti satu-satunya layar yang
    bisa menemukannya justru yang menyembunyikannya.
    """

    EXPIRED = "expired"
    EXPIRING_30 = "expiring_30"
    EXPIRING_60 = "expiring_60"
    EXPIRING_90 = "expiring_90"
    FUTURE = "future"
    NO_END_DATE = "no_end_date"


# Label yang dibaca manusia. Dipisah dari kodenya supaya yang dikirim
# ke frontend dan yang dipakai menyaring tidak pernah tertukar: kode
# tidak berubah kalau labelnya diperbaiki, dan label boleh berubah tanpa
# memutus filter yang sudah tersimpan di bookmark siapa pun.
EXPIRY_LABELS: dict[str, str] = {
    ExpiryStatus.EXPIRED: "Expired",
    ExpiryStatus.EXPIRING_30: "≤ 30 Hari",
    ExpiryStatus.EXPIRING_60: "31–60 Hari",
    ExpiryStatus.EXPIRING_90: "61–90 Hari",
    ExpiryStatus.FUTURE: "> 90 Hari",
    ExpiryStatus.NO_END_DATE: "Tanpa Tanggal Akhir",
}


# Yang **perlu ditindaklanjuti** hari ini. Dipakai chart per department
# dan tidak dipakai KPI: kartu KPI memecah keempatnya supaya yang
# membacanya tahu mana yang sudah lewat dan mana yang masih punya waktu.
FOLLOW_UP_STATUSES: tuple[str, ...] = (
    ExpiryStatus.EXPIRED,
    ExpiryStatus.EXPIRING_30,
    ExpiryStatus.EXPIRING_60,
    ExpiryStatus.EXPIRING_90,
)


# Urutan tampil: yang paling mendesak lebih dulu. Dipakai mengurutkan
# tabel dan menyusun pilihan dropdown, jadi keduanya tidak bisa berbeda
# pendapat soal mana yang "lebih dulu".
EXPIRY_ORDER: tuple[str, ...] = (
    ExpiryStatus.EXPIRED,
    ExpiryStatus.EXPIRING_30,
    ExpiryStatus.EXPIRING_60,
    ExpiryStatus.EXPIRING_90,
    ExpiryStatus.FUTURE,
    ExpiryStatus.NO_END_DATE,
)


def expiry_status(days_remaining: int | None) -> str:
    """
    Sisa hari → bucket. Satu-satunya tempat ambangnya diputuskan.

    `None` berarti kontraknya tidak punya tanggal akhir sama sekali —
    bukan nol hari. Nol hari adalah kontrak yang **habis hari ini**, dan
    keduanya menuntut tindakan yang sangat berbeda.
    """
    if days_remaining is None:
        return ExpiryStatus.NO_END_DATE

    if days_remaining < 0:
        return ExpiryStatus.EXPIRED

    if days_remaining <= NEAR_TERM_DAYS:
        return ExpiryStatus.EXPIRING_30

    if days_remaining <= MID_TERM_DAYS:
        return ExpiryStatus.EXPIRING_60

    if days_remaining <= LONG_TERM_DAYS:
        return ExpiryStatus.EXPIRING_90

    return ExpiryStatus.FUTURE


class RenewalStatus:
    """
    Keadaan dokumen perpanjangan/penerbitan kontrak yang **masih
    berjalan**, dibacakan dari `EmployeeAction`.

    Tidak ada nilai "Renewed" di sini, dan itu disengaja. Dokumen yang
    sudah `APPLIED` berarti kolom kontrak pegawainya sudah ikut
    berpindah — barisnya sendiri sudah berada di bucket yang lebih jauh,
    dan menyebutnya "sudah diperpanjang" di baris yang justru masih
    mendesak adalah cara memberi tahu HR bahwa pekerjaan yang belum
    selesai sudah selesai.
    """

    NONE = "no_renewal"
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"


RENEWAL_LABELS: dict[str, str] = {
    RenewalStatus.NONE: "No Renewal Record",
    RenewalStatus.DRAFT: "Draft",
    RenewalStatus.SUBMITTED: "Pending Approval",
    RenewalStatus.APPROVED: "Approved",
}


RENEWAL_ORDER: tuple[str, ...] = (
    RenewalStatus.NONE,
    RenewalStatus.DRAFT,
    RenewalStatus.SUBMITTED,
    RenewalStatus.APPROVED,
)


# ----------------------------------------------------------------------
# Pilihan dropdown
# ----------------------------------------------------------------------
#
# **Id-nya angka, dan itu bukan selera.** `MLookupSelect` di frontend
# meng-`Number()` nilai filter satu-pilihan (`toNumber` di
# `MDashboardFilters.vue`), jadi id berupa teks mendarat sebagai `null`
# dan dropdown-nya terlihat kosong padahal isinya terkirim. Pola yang
# sama dengan `reporting_status` di Employee Reporting Audit; kode
# manusiawinya tetap ikut sebagai `code`.

def _options(order, labels) -> tuple[dict, ...]:
    return tuple(
        {"id": index, "code": code, "name": labels[code]}
        for index, code in enumerate(order, start=1)
    )


EXPIRY_STATUS_OPTIONS = _options(EXPIRY_ORDER, EXPIRY_LABELS)
RENEWAL_STATUS_OPTIONS = _options(RENEWAL_ORDER, RENEWAL_LABELS)


def _code_from(raw, options) -> str | None:
    """
    Nilai filter (`?expiry_status=2`) → kode yang dipakai menyaring.

    Nilai yang tidak dikenal mengembalikan `None` = **tanpa
    penyaringan**, aturan yang sama dengan seluruh filter dashboard:
    satu query param salah ketik tidak boleh mematikan laporan, dan
    tidak boleh pula membuka satu baris pun — penyaringnya memang cuma
    mempersempit.
    """
    value = str(raw or "").strip()

    for option in options:
        if value in {str(option["id"]), option["code"]}:
            return option["code"]

    return None


def expiry_status_code(raw) -> str | None:
    return _code_from(raw, EXPIRY_STATUS_OPTIONS)


def renewal_status_code(raw) -> str | None:
    return _code_from(raw, RENEWAL_STATUS_OPTIONS)
