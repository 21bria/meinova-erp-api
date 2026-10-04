"""
Katalog pintasan untuk bagian **Favorite Menus** di halaman depan.

Pola yang sama dengan katalog aplikasi, dengan satu perbedaan penting:
**daftarnya tidak ditulis di sini**. Sumbernya tabel `Menu` — 17 grup +
57 item yang sudah diseed `tenant_command seed_menus` dan dipakai layar
Menu Permissions. Menulis daftar keduanya di berkas ini berarti dua
daftar menu yang harus dijaga tetap sama, dan bedanya baru ketahuan saat
ada yang menekan pintasan yang sudah tidak ada.

Konsekuensinya bagus: menu baru dari modul mana pun otomatis bisa
dipilih jadi pintasan begitu diseed ke tabel `Menu`, tanpa satu baris
pun kode beranda disentuh.

Sebelum ini pintasannya **tidak bisa dipilih sama sekali**. Barisnya
ditulis seed untuk setiap pengguna (lima pintasan tetap), endpoint-nya
cuma `POST`/`DELETE` per baris yang tidak pernah dipanggil frontend, dan
drag di layarnya menyusun state lokal yang hilang begitu halaman dimuat
ulang.
"""

from __future__ import annotations

from apps.accounts.models import Menu
from apps.administration.api.dashboard.catalog import by_code as apps_by_code
from apps.administration.models import FavoriteApp


Status = FavoriteApp.Status


# Modul yang halamannya belum ada tidak ikut ditawarkan. Alasannya sama
# dengan `OBSOLETE_CODES` dulu: pintasan `/scm/purchase-requests` yang
# menghasilkan `[Vue Router warn] No match found` di beranda setiap kali
# dimuat lebih buruk daripada pintasan yang tidak ada.
#
# Statusnya dibaca dari `APP_CATALOG`, bukan didaftar ulang di sini —
# begitu modul SCM/Finance jadi, satu baris status di sana sudah cukup.
AVAILABLE_STATUSES = {Status.ACTIVE, Status.BETA}


# Yang ditampilkan untuk pengguna yang **belum pernah** memilih sendiri.
# Kodenya diturunkan dari route (`_code()` di `apps/accounts/seeds/menus.py`),
# jadi mengganti judul menu tidak membuat bawaan ini meleset.
DEFAULT_CODES = [
    "hr.employees",
    "hr.attendance",
    "hr.leave",
    "hr.travel-requests",
    "workflow.inbox",
]


def _icon(value: str) -> str:
    """
    `i-lucide-users` → `users`.

    Tabel `Menu` menyimpan nama ikon bergaya Nuxt UI karena sidebar
    memakainya apa adanya; beranda memetakannya lewat `appRegistry` di
    `app/registry/app.ts`. Kunci yang tidak dikenal jatuh ke ikon bawaan
    tanpa error — jadi salah ketik di sini gagal tanpa suara.
    """
    return (value or "").removeprefix("i-lucide-")


def _module_color(module: str) -> str:
    """
    Warna kartu mengikuti modulnya, diambil dari katalog aplikasi.

    Satu sumber untuk dua tempat: kartu Applications dan pintasan yang
    menunjuk modul yang sama tidak boleh berbeda warna di satu halaman.
    """
    entry = apps_by_code().get(module) or {}

    return entry.get("color") or "slate"


def _is_available(module: str) -> bool:
    entry = apps_by_code().get(module)

    # Modul yang tidak terdaftar di katalog aplikasi tetap dilewatkan:
    # barisnya cuma ada kalau seseorang mendaftarkannya di `MENU_TREE`,
    # yang memang cerminan sidebar Nuxt. Yang disaring di sini hanya
    # modul yang **sudah diketahui** belum punya halaman.
    if entry is None:
        return True

    return entry.get("status") in AVAILABLE_STATUSES


def menu_entries() -> list[dict]:
    """Seluruh menu yang layak jadi pintasan, urut seperti di sidebar."""
    menus = (
        Menu.objects
        .filter(is_deleted=False, is_group=False)
        .exclude(route="")
        .select_related("parent")
        .order_by("sort_order", "title")
    )

    entries = []

    for position, menu in enumerate(menus):
        if not _is_available(menu.module):
            continue

        entries.append({
            "menu_code": menu.code,
            "title": menu.title,

            # Judul grupnya, bukan nama modul: empat menu berjudul
            # "Dashboard" di daftar pilihan tidak bisa dibedakan satu
            # sama lain tanpa keterangan ini.
            "description": menu.parent.title if menu.parent_id else "",

            "link": menu.route,
            "icon": _icon(menu.icon),
            "color": _module_color(menu.module),
            "module": menu.module,
            "position": position,
        })

    return entries


def by_code() -> dict[str, dict]:
    return {entry["menu_code"]: entry for entry in menu_entries()}
