"""
Katalog widget halaman depan.

Halaman `app/pages/index.vue` dulu merender **delapan komponen tetap
dalam urutan tetap**, dan tidak pernah menyentuh `UserDashboardLayout`
walau tabelnya sudah berisi dua belas baris dan endpoint-nya sudah
jalan. Akibatnya: tidak ada yang bisa menyusun ulang beranda, dan
menambah widget untuk modul baru berarti menyunting halaman itu.

Ini yang menggantikannya. Sesudah ini, menambah widget = satu baris di
`HOME_WIDGETS` + satu komponen di registry frontend.

**Katalognya di kode, bukan di database**, dengan alasan yang sama
seperti `APP_CATALOG`: `component` menunjuk komponen Vue yang memang ada
di repo frontend, dan baris database tidak bisa mengarang komponen.
Tabel `DashboardWidget` tetap diisi dari sini — `UserDashboardLayout`
menunjuknya lewat FK, jadi barisnya harus ada — tapi yang berwenang
tetap berkas ini.

`span` memakai grid 12 kolom, sama dengan dashboard modul. Urutan
susunannya sendiri yang membentuk baris: 12, 12, 12, lalu 4+4+4 mengisi
satu baris, lalu 12 lagi. Tidak ada koordinat x/y yang harus dijaga
tetap konsisten — memindahkan satu widget cukup mengubah urutannya.

`fixed_height` menandai widget yang tingginya **dikunci** di layar
lebar, isinya yang menggulir. Tanpa itu tinggi tiap kartu mengikuti
isinya sendiri, dan tiga kartu berjejer jadi tiga tinggi berbeda —
Notifications yang kosong tinggal seperempat tinggi tetangganya, dan
barisnya terbaca seperti ada yang gagal dimuat. Dikunci lewat katalog,
bukan di komponennya, supaya widget baru cukup menyatakan maunya tanpa
ada yang perlu menambah kelas CSS di berkas lain.

Sengaja **hanya di layar lebar**: kotak bergulir di dalam halaman yang
juga bergulir adalah hal yang paling menjengkelkan di ponsel.
"""

from __future__ import annotations


# Widget yang pernah diseed lalu ditarik. Baris `UserDashboardLayout`
# yang menunjuknya ikut dibuang — kalau tidak, susunan pengguna memuat
# widget yang tidak punya komponen dan beranda merender kotak kosong
# yang tidak bisa dihapus siapa pun.
#
# Keempatnya sisa rancangan awal: `component` dan `endpoint`-nya kosong,
# dan tidak satu pun pernah punya komponen di frontend.
OBSOLETE_CODES = [
    "executive_insight",
    "pending_approvals",
    "favorite_apps",
]


HOME_WIDGETS = [
    {
        "code": "kpi",
        "title": "Ringkasan",
        "description": (
            "Kotak masuk, pengajuan berjalan, dan jumlah pegawai aktif."
        ),
        "component": "DashboardKpi",
        "span": 12,
        "order": 10,
    },
    {
        "code": "favorite_menus",
        "title": "Favorite Menus",
        "description": "Pintasan menu yang dipilih sendiri.",
        "component": "DashboardFavoriteMenus",
        "span": 12,
        "order": 20,
    },
    {
        "code": "quick_actions",
        "title": "Quick Actions",
        "description": "Tombol buat dokumen yang paling sering dipakai.",
        "component": "DashboardQuickActions",
        "span": 12,
        "order": 30,
    },
    {
        "code": "approval_chart",
        "fixed_height": True,
        "title": "Approval Status",
        "description": "Sebaran dokumen yang sedang berjalan.",
        "component": "DashboardInsights",
        "span": 4,
        "order": 40,
    },
    {
        "code": "notifications",
        "fixed_height": True,
        "title": "Notifications",
        "description": "Pemberitahuan yang belum dibaca.",
        "component": "DashboardNotifications",
        "span": 4,
        "order": 50,
    },
    {
        "code": "recent_documents",
        "fixed_height": True,
        "title": "Recent Documents",
        "description": "Dokumen terakhir yang Anda buat atau setujui.",
        "component": "DashboardWorkflow",
        "span": 4,
        "order": 60,
    },
    {
        "code": "applications",
        "title": "Applications",
        "description": "Modul yang bisa dibuka, beserta statusnya.",
        "component": "DashboardApplications",
        "span": 12,
        "order": 70,
    },
]


# Susunan bawaan untuk yang belum pernah menyusun: semuanya, urut
# `order`. **Tidak ditulis ke database saat dibaca** — menulis saat
# membaca membuat "belum pernah menyusun" jadi keadaan yang tidak bisa
# dibedakan lagi dari "sudah menyusun dan kebetulan sama", dan bawaan
# yang berubah besok tidak akan pernah sampai ke pengguna lama.
#
# Pelajaran yang sama persis dengan `FavoriteApp.DEFAULT_CODES`.
DEFAULT_CODES = [item["code"] for item in HOME_WIDGETS]


WIDGETS_BY_CODE = {item["code"]: item for item in HOME_WIDGETS}
