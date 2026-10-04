"""
Dua status yang dibaca laporan audit ini, dan **keduanya faktual**.

Yang membedakannya dari status di modul transaksi: tidak satu pun di
sini adalah kesimpulan. `Account Status` cuma membacakan kolom yang
sudah ada di `User`, dan `Reporting Status` cuma menyebutkan apakah
`OrganizationAssignment.reports_to` terisi. Tidak ada baris yang
memutuskan bahwa seorang pegawai *seharusnya* punya atasan.

Itu keputusan yang disengaja. Direksi dan sebagian pimpinan puncak
memang sah berdiri tanpa Report To, dan master organisasi hari ini
tidak punya penanda "root" yang bisa membedakan keduanya. Laporan yang
menandai mereka sebagai galat akan melatih pembacanya mengabaikan
kolom itu — dan begitu ada garis pelaporan yang benar-benar putus, ia
lewat bersama sisanya.
"""

from __future__ import annotations


class AccountStatus:
    """Keadaan akun login pegawai. Sumbernya `User.is_active`."""

    CONNECTED = "Connected"
    INACTIVE = "Inactive"
    NO_ACCOUNT = "No Account"


class ReportingStatus:
    """
    Kelengkapan garis pelaporan, **apa adanya**.

    Bukan "OK" dan "ERROR": tanpa penanda top-level di master, keduanya
    berarti menuduh. Yang disebutkan cuma ada-tidaknya baris atasannya.
    """

    HAS = "Has Report To"
    NONE = "No Report To"


HAS_REPORT_TO = "has_report_to"
NO_REPORT_TO = "no_report_to"


# Pilihan dropdown "Reporting Status".
#
# **Id-nya angka, dan itu bukan selera.** `MLookupSelect` di frontend
# meng-`Number()` nilai filter satu-pilihan (`toNumber` di
# `MDashboardFilters.vue`), jadi id berupa teks mendarat sebagai `null`
# dan dropdown-nya terlihat kosong padahal isinya terkirim. Kode
# manusiawinya tetap ikut sebagai `code` supaya yang membaca respons
# tidak perlu menghafal angkanya.
REPORTING_STATUS_OPTIONS: tuple[dict, ...] = (
    {"id": 1, "code": HAS_REPORT_TO, "name": ReportingStatus.HAS},
    {"id": 2, "code": NO_REPORT_TO, "name": ReportingStatus.NONE},
)


def reporting_status_code(raw) -> str | None:
    """
    Nilai filter (`?reporting_status=1`) → kode yang dipakai queryset.

    Nilai yang tidak dikenal mengembalikan `None` = **tanpa
    penyaringan**, aturan yang sama dengan filter dashboard lain: satu
    query param salah ketik tidak boleh mematikan seluruh laporan, dan
    tidak boleh pula membuka satu baris pun (penyaringannya memang
    hanya mempersempit).
    """
    value = str(raw or "").strip()

    for option in REPORTING_STATUS_OPTIONS:
        if value in {str(option["id"]), option["code"]}:
            return option["code"]

    return None
