"""
Tombol **Quick Actions** di halaman depan.

Dulu daftarnya ditulis mati di frontend (`dashboardDummy`) dan separuh
isinya menunjuk modul yang belum ada — "New Purchase Request" ke
`/scm/purchase-requests/create`, "New Journal" ke `/finance/journals/`.
Keduanya mendarat di 404. Sama persis dengan alasan katalog aplikasi
dipindah ke backend: statusnya mengikuti apa yang benar-benar ada di
repo ini, dan tombol yang tampak berfungsi lalu mendarat di 404 lebih
buruk daripada tombol yang tidak ada.

Dua saringan dipasang, dan keduanya perlu:

* `menu` — rute yang harus terlihat menurut `RoleMenuPermission`.
  Menawarkan pintasan ke layar yang menunya sengaja disembunyikan
  membatalkan pengaturan yang baru saja dibuat orang.
* `permission` — izin model untuk **membuat**. Tombol "Add Employee"
  untuk orang yang pasti ditolak saat menekan Simpan cuma memindahkan
  penolakannya satu layar lebih dalam.

Ini bukan penjagaan; endpoint-nya tetap penjaga sebenarnya. Ini soal
tidak menyodorkan pintu yang tidak akan dibuka.
"""

from __future__ import annotations


# `icon`/`color` menunjuk kunci di `app/registry/` pada repo Nuxt —
# nama yang tidak dikenal jatuh ke bawaan, tidak error.
QUICK_ACTIONS: list[dict] = [
    {
        "code": "request-leave",
        "title": "Request Leave",
        "description": "Ajukan cuti untuk disetujui atasan.",
        "link": "/hr/leave/create",
        "icon": "calendar-plus",
        "color": "emerald",
        "menu": "/hr/leave",
        "permission": "hr.add_employeeleave",
    },
    {
        "code": "travel-request",
        "title": "New Travel Request",
        "description": "Pengajuan satu kepulangan beserta tiketnya.",
        "link": "/hr/travel-requests/create",
        "icon": "plane",
        "color": "sky",
        "menu": "/hr/travel-requests",
        "permission": "hr.add_travelrequest",
    },
    {
        "code": "add-employee",
        "title": "Add Employee",
        "description": "Menambahkan data karyawan baru.",
        "link": "/hr/employees/create",
        "icon": "user-plus",
        "color": "blue",
        "menu": "/hr/employees",
        "permission": "hr.add_employee",
    },
    {
        "code": "approval-inbox",
        "title": "Approval Inbox",
        "description": "Dokumen lintas modul yang menunggu keputusan Anda.",
        "link": "/workflow/inbox",
        "icon": "inbox",
        "color": "violet",
        "menu": "/workflow/inbox",
        # Kotak masuk tidak membuat apa pun — yang menentukan siapa boleh
        # memutuskan adalah barisnya sendiri, bukan izin model.
        "permission": None,
    },
]
