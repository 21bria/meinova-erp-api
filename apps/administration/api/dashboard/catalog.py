"""
Katalog aplikasi untuk kartu **Applications** di halaman depan.

Sebelum ini bagian itu selalu kosong, dan bukan karena hak akses:
`FavoriteApp` adalah tabel **per pengguna**, dan tidak ada satu pun
endpoint yang mendaftar "aplikasi apa saja yang tersedia". Jadi tidak
ada tempat untuk memilihnya, dan tombol Customize cuma menyusun ulang
daftar yang kosong.

Katalognya ditulis di backend, bukan di frontend, karena statusnya
mengikuti apa yang benar-benar ada di sini — `finance` dan `scm` masih
kerangka kosong, dan itu fakta yang dipegang repo ini. `FavoriteApp.Status`
sudah lama punya `COMING_SOON`/`BETA` untuk keperluan persis ini.

**Isinya hanya modul yang punya halaman.** Kartu yang mendarat di 404
lebih buruk daripada kartu yang tidak ada. (`assets` masuk sejak ASSET-6,
1 Okt 2026, bersama halaman `/assets/*`-nya.) `reports` sudah punya
halamannya (`/reports`) dan karena itu sudah ada di bawah. Nambah modul
baru = tambah satu baris di sini.

Baris baru **sampai juga ke pengguna lama**: `FavoriteAppService.
get_favorites` menyusulkan modul yang belum punya baris `FavoriteApp`
sama sekali. Tanpa itu modul yang ditambahkan di sini hanya terlihat
oleh akun yang belum pernah menekan Save di Customize — dan
`seed_dashboard` menekan Save untuk semua orang sekaligus.
"""

from __future__ import annotations

from apps.administration.models import FavoriteApp


Status = FavoriteApp.Status


# `icon` dan `color` menunjuk kunci di `app/registry/{app,color}.ts` pada
# repo Nuxt — nama yang tidak dikenal jatuh ke ikon bawaan, tidak error.
APP_CATALOG: list[dict] = [
    {
        # Ruang pribadi pemegang akun — **bukan** aplikasi administratif.
        #
        # Ditaruh paling depan karena ia satu-satunya kartu yang relevan
        # untuk setiap orang yang punya akun, apa pun mejanya.
        #
        # Kodenya `me`, mengikuti konvensi katalog ini: kode = segmen
        # pertama rutenya (`hr` → `/hr`, `payroll` → `/payroll`). Bukan
        # `self_service`, yang akan jadi identitas kedua untuk satu hal
        # yang sama — dan `allowed_codes()` mencocokkan lewat `link`,
        # bukan lewat kode, jadi dua nama tidak akan pernah berbunyi
        # sebagai konflik. Ia cuma diam-diam tidak cocok.
        "app_code": "me",
        "title": "My Workspace",
        "description": "Profil, dokumen, dan pengajuan pribadi Anda.",
        "link": "/me",
        "icon": "id-card",
        "color": "indigo",
        "status": Status.ACTIVE,
        "position": 0,
    },
    {
        "app_code": "hr",
        "title": "Human Resources",
        "description": "Karyawan, absensi, cuti, lembur, dan rekrutmen.",
        "link": "/hr",
        "icon": "users",
        "color": "blue",
        "status": Status.ACTIVE,
        "position": 1,
    },
    {
        "app_code": "payroll",
        "title": "Payroll",
        "description": "Struktur gaji, tunjangan, potongan, dan pajak.",
        "link": "/payroll",
        "icon": "wallet",
        "color": "emerald",
        "status": Status.BETA,
        "position": 2,
    },
    {
        "app_code": "workflow",
        "title": "Workflow",
        "description": "Persetujuan lintas modul, delegasi, dan pemantauan.",
        "link": "/workflow",
        "icon": "workflow",
        "color": "violet",
        "status": Status.ACTIVE,
        "position": 3,
    },
    {
        "app_code": "administration",
        "title": "Administration",
        "description": "Organisasi, master data, penomoran, dan keamanan.",
        "link": "/administration",
        "icon": "settings-2",
        "color": "slate",
        "status": Status.ACTIVE,
        "position": 4,
    },
    {
        # Laporan manajemen lintas modul, seluruhnya read-only. Status
        # ACTIVE karena layarnya memang sudah ada dan berisi — bukan
        # janji: `DEFAULT_CODES` di bawah menyaring justru berdasarkan
        # status ini, dan modul yang belum jadi tidak boleh muncul di
        # beranda orang.
        "app_code": "reports",
        "title": "Reports",
        "description": "Laporan manajemen lintas modul — HR lebih dulu.",
        "link": "/reports",
        "icon": "chart-column",
        "color": "cyan",
        "status": Status.ACTIVE,
        "position": 5,
    },
    {
        # **BETA, bukan COMING_SOON lagi.** Finance Core sudah berdiri:
        # bagan akun, tahun buku, periode, jurnal, posting, buku besar,
        # dan neraca saldo. Yang belum — AP/AR, kas & bank, aset tetap,
        # anggaran — belum punya halaman, jadi kartunya tidak menjanjikan
        # apa yang tidak ada.
        "app_code": "finance",
        "title": "Finance",
        "description": "Buku besar, jurnal, dan neraca saldo.",
        "link": "/finance",
        "icon": "receipt-text",
        "color": "amber",
        "status": Status.BETA,
        "position": 6,
    },
    {
        "app_code": "scm",
        "title": "Supply Chain",
        "description": "Pembelian, persediaan, dan gudang.",
        "link": "/scm",
        "icon": "package",
        "color": "orange",
        "status": Status.COMING_SOON,
        "position": 7,
    },
    {
        # **BETA** sejak ASSET-6: register, custody, dan tiga dokumen
        # pergerakan (Assignment/Transfer/Return) sudah punya layar.
        # Entitlement dan Fixed Asset Accounting belum, jadi kartunya
        # tidak menjanjikannya. Ikon memakai kunci yang sudah ada di
        # `app/registry/app.ts` — nama baru di sana harus diperiksa dulu
        # di `lucide-vue-next`.
        "app_code": "assets",
        "title": "Asset Management",
        "description": "Register aset, penyerahan, transfer, dan pengembalian.",
        "link": "/assets/register",
        "icon": "package",
        "color": "indigo",
        "status": Status.BETA,
        "position": 8,
    },
]


# Yang ditampilkan untuk pengguna yang belum pernah menyusun sendiri.
# Modul yang belum jadi sengaja tidak ikut: halaman depan seharusnya
# memperlihatkan yang bisa dipakai, bukan daftar janji.
DEFAULT_CODES = [
    entry["app_code"]
    for entry in APP_CATALOG
    if entry["status"] in {Status.ACTIVE, Status.BETA}
]


def by_code() -> dict[str, dict]:
    return {entry["app_code"]: entry for entry in APP_CATALOG}
