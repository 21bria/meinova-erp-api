"""
Wewenang tingkat layar, satu tempat.

Dipakai dua arah: `permissions.py` tiap modul memakainya untuk menolak
request, dan `/api/accounts/auth/me/` mengirimkannya ke frontend untuk
menyembunyikan menu yang pasti ditolak. **Dua-duanya, bukan salah satu**
— menyembunyikan menu tidak menghalangi orang menembak API langsung,
dan API yang menolak tanpa menu yang disembunyikan membuat orang
mengetuk pintu yang tidak akan pernah dibuka.

Kuncinya berupa string bertitik (`security.manage`) supaya menu di
frontend cukup menyebut namanya, bukan mengulang daftar kode role —
mengubah nama role di satu tenant tidak boleh mengharuskan FE dirilis
ulang.
"""

from __future__ import annotations

from django.conf import settings


# Role yang boleh mengelola Users / Roles / Permissions. Di settings,
# bukan ditanam di kode, supaya tenant bisa menamainya sendiri.
SECURITY_ROLE_CODES = getattr(
    settings,
    "SECURITY_ADMIN_ROLES",
    ["SECURITY-ADMIN"],
)


def has_role(user, codes) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False

    if not codes:
        return False

    return user.roles.filter(code__in=codes, is_deleted=False).exists()


def can_manage_security(user) -> bool:
    """
    Boleh membuat/mengubah user, role, dan hak aksesnya.

    Ini wewenang paling berbahaya di sistem: yang memegangnya bisa
    memberi dirinya role apa pun, termasuk role yang membuka seluruh
    data tenant. Karena itu hanya superuser dan pemegang role khusus —
    bukan sekadar "sudah login", yang selama ini berlaku.
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False

    if user.is_superuser:
        return True

    return has_role(user, SECURITY_ROLE_CODES)


def capabilities_for(user) -> dict:
    """
    Peta wewenang yang dikirim ke frontend.

    Sengaja daftar tetap, bukan hasil refleksi: frontend membaca kunci
    yang sudah pasti ada, dan wewenang baru harus ditambahkan sadar di
    sini — bukan muncul sendiri karena ada yang menambah role.
    """
    from apps.workflow.permissions import can_configure as can_configure_workflow
    from apps.workflow.selectors import can_monitor_all

    if user is None or not getattr(user, "is_authenticated", False):
        return {
            "security.manage": False,
            "workflow.configure": False,
            "workflow.monitor_all": False,
        }

    return {
        "security.manage": can_manage_security(user),
        "workflow.configure": can_configure_workflow(user),
        "workflow.monitor_all": can_monitor_all(user),
    }
