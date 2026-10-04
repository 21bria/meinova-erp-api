"""
Penjagaan API untuk aksi kustom Finance — FIN-B1/B2.

`ModelPermission` sengaja hanya menjaga aksi CRUD baku; aksi `@action`
yang namanya tidak ada di `ACTION_VERBS` lolos begitu saja di sana.
Aturan generik itu **tidak** diubah di stage ini (78 aksi tulis kustom
di seluruh ERP bergantung padanya). Finance menutupnya sendiri:

* setiap aksi tulis kustom Finance dinyatakan di
  `action_scope_permissions` viewset-nya;
* kelas ini menolak aksi yang dinyatakan itu dengan 403 kalau izinnya
  tidak dipegang — **sebelum** barisnya dicari;
* aksi tulis kustom yang **tidak** dinyatakan ditolak juga (gagal
  tertutup), jadi aksi baru yang lupa dinyatakan tidak diam-diam
  terbuka.

Ini lapis cermin. Penolakan yang menentukan tetap di service
(`apps.finance.services.authority`), karena jalur lain tidak lewat
viewset sama sekali.
"""

from __future__ import annotations

from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.permissions import ACTION_VERBS


class FinanceActionPermission(BasePermission):
    message = (
        "Anda tidak punya wewenang menjalankan tindakan Finance ini. "
        "Hubungi administrator untuk menambahkannya ke role Anda."
    )

    def has_permission(self, request, view) -> bool:
        if request.method in SAFE_METHODS:
            return True

        action = getattr(view, "action", None) or ""

        if action in ACTION_VERBS:
            # CRUD baku: urusan `ModelPermission`.
            return True

        user = request.user

        if not getattr(user, "is_authenticated", False):
            return False

        declared = getattr(view, "action_scope_permissions", None) or {}

        permission = declared.get(action)

        if permission is None:
            # Aksi tulis kustom tanpa izin yang dinyatakan: tertutup.
            return False

        if getattr(user, "is_superuser", False):
            return True

        return user.has_perm(permission)
