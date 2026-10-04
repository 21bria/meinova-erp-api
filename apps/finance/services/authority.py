"""
Wewenang tindakan Finance — FIN-B1/B2.

Satu pertanyaan, dijawab di satu tempat: **boleh orang ini menjalankan
tindakan Finance ini atas baris ini?** Jawabannya selalu dua syarat, dan
tidak satu pun menggantikan yang lain:

1. **Izin eksplisit** untuk tindakannya (`user.has_perm(permission)`).
   Cakupan data yang luas — termasuk akun tanpa penugasan, yang oleh
   `DataScopeService` dianggap *tak tersaring* — tidak pernah berarti
   boleh membukukan.
2. **Cakupan baris**, dihitung **dari izin itu sendiri**
   (`required_permission=permission`), bukan gabungan seluruh role
   orangnya. Izin se-tenant tanpa cakupan perusahaan jurnalnya tetap
   ditolak.

Dipanggil dari **service**, bukan hanya viewset: `ModelPermission`
cuma menjaga aksi CRUD baku, dan jalur yang menyusul (perintah
manajemen, importer, modul lain) tidak lewat viewset sama sekali.

Kontrak pemanggil internal: `user=None` berarti **pemanggil tepercaya
tanpa konteks pengguna** — shell server, seed, fixture test. Jalur API
tidak pernah mengirim `None`; ia mengirim `request.user`, dan pengguna
anonim ditolak di sini. Pemanggil mana saja yang memakai `None` ditulis
di `docs/claude/finance.md` § FIN-B1/B2.
"""

from __future__ import annotations

from rest_framework.exceptions import PermissionDenied

from apps.accounts.scoping import DataScopeService


CHANGE_JOURNAL_PERMISSION = "finance.change_journal"
POST_JOURNAL_PERMISSION = "finance.post_journal"
REVERSE_JOURNAL_PERMISSION = "finance.reverse_journal"

CHANGE_PERIOD_PERMISSION = "finance.change_accountingperiod"
ADD_PERIOD_PERMISSION = "finance.add_accountingperiod"


def assert_finance_capability(*, user, permission: str, action: str) -> None:
    """
    Syarat pertama saja: izinnya dipegang.

    Dipisah supaya tindakan massal (`post-all`) bisa menolak **sebelum**
    menyentuh satu jurnal pun, alih-alih gagal di tengah daftar.
    """
    if user is None:
        return

    if not getattr(user, "is_authenticated", False):
        raise PermissionDenied(
            f"Hanya pengguna yang masuk yang bisa {action}.",
        )

    if getattr(user, "is_superuser", False):
        return

    if not user.has_perm(permission):
        raise PermissionDenied(
            f"Anda tidak punya wewenang {action} ('{permission}').",
        )


def assert_finance_action(
    *,
    user,
    permission: str,
    queryset,
    scope: dict,
    action: str,
) -> None:
    """
    Kedua syarat: izin **dan** cakupan baris dari izin itu.

    `queryset` adalah satu baris (`Model.objects.filter(pk=...)`);
    cakupannya dinilai mesin yang sama dengan penyaringan daftar, bukan
    salinan aturannya.
    """
    assert_finance_capability(user=user, permission=permission, action=action)

    if user is None or getattr(user, "is_superuser", False):
        return

    visible = DataScopeService.filter(
        queryset,
        scope,
        user,
        required_permission=permission,
    )

    if not visible.exists():
        raise PermissionDenied(
            "Dokumen ini berada di luar kewenangan data Anda untuk "
            f"{action}.",
        )
