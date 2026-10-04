"""
Menyambungkan `Role.permissions` ke `user.has_perm()`.

Selama ini `Role` punya M2M ke `auth.Permission` berisi 708 baris dan
layar Roles bisa mencentanginya, tapi **tidak ada satu baris kode pun
yang membacanya**. `user.has_perm()` bawaan Django cuma melihat
`user.user_permissions` dan `user.groups` — dua kolom yang di codebase
ini tidak dipakai sama sekali. Jadi centang di layar Roles tersimpan
rapi dan tidak berpengaruh apa-apa.

Backend ini yang menutup jaraknya. Setelah terdaftar di
`AUTHENTICATION_BACKENDS`, seluruh mesin izin bawaan Django dan DRF
(`user.has_perm`, `DjangoModelPermissions`, admin) membaca role tanpa
perlu tahu bahwa role itu ada.

Sengaja backend terpisah, bukan mengganti `ModelBackend`: yang bawaan
tetap dibutuhkan untuk `authenticate()` saat login, dan Django
menggabungkan hasil semua backend dengan OR.
"""

from __future__ import annotations

from django.contrib.auth.backends import BaseBackend


class RolePermissionBackend(BaseBackend):
    """
    Sumber izin dari role, bukan dari group.

    **Tidak** ikut mengautentikasi — `authenticate()` sengaja tidak
    diimplementasikan supaya login tetap satu jalur lewat `ModelBackend`.
    """

    def authenticate(self, request, **kwargs):
        return None

    def get_user(self, user_id):
        return None

    def get_all_permissions(self, user_obj, obj=None) -> set[str]:
        # Izin per objek tidak didukung; itu ranah cakupan data yang
        # menyaring baris, bukan menentukan kata kerjanya.
        if obj is not None:
            return set()

        if user_obj is None or not user_obj.is_active:
            return set()

        if not getattr(user_obj, "is_authenticated", False):
            return set()

        # Superuser sudah ditangani `ModelBackend` (mengembalikan seluruh
        # Permission). Menghitungnya lagi cuma menambah query.
        if user_obj.is_superuser:
            return set()

        cached = getattr(user_obj, "_role_perm_cache", None)

        if cached is not None:
            return cached

        rows = (
            user_obj.roles
            .filter(is_deleted=False)
            .values_list(
                "permissions__content_type__app_label",
                "permissions__codename",
            )
        )

        permissions = {
            f"{app_label}.{codename}"
            for app_label, codename in rows
            if app_label and codename
        }

        user_obj._role_perm_cache = permissions

        return permissions
