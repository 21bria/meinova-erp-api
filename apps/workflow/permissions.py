"""
Hak mengubah konfigurasi alur.

Mengubah `WorkflowDefinition`/`WorkflowStep` sama dengan menentukan
**siapa yang menyetujui dokumen siapa**. Tanpa penjagaan, pegawai mana
pun yang login bisa menambahkan dirinya sebagai approver cutinya
sendiri, atau menghapus step HR dari alur — dan tidak ada satu pun
jejak di dokumen yang berjalan sesudahnya yang terlihat janggal, karena
alurnya memang "sesuai konfigurasi".

Menyembunyikan menunya di frontend tidak cukup: endpoint-nya tetap bisa
ditembak langsung. Penjagaannya harus di sini.
"""

from __future__ import annotations

from django.conf import settings

from rest_framework.permissions import SAFE_METHODS, BasePermission


# Role yang boleh mengubah konfigurasi alur. Dipisah ke settings supaya
# tenant bisa menamainya sendiri, dan supaya wewenang ini bisa diberikan
# ke orang IT/HR tertentu **tanpa** menjadikannya superuser — yang
# artinya bisa mengubah apa pun di seluruh sistem.
CONFIG_ROLE_CODES = getattr(
    settings,
    "WORKFLOW_CONFIG_ROLES",
    ["WORKFLOW-ADMIN"],
)


def can_configure(user) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False

    if user.is_superuser:
        return True

    if not CONFIG_ROLE_CODES:
        return False

    return user.roles.filter(
        code__in=CONFIG_ROLE_CODES,
        is_deleted=False,
    ).exists()


class CanConfigureWorkflow(BasePermission):
    """
    Baca boleh untuk semua yang login, tulis hanya untuk yang berhak.

    Membaca sengaja dibiarkan terbuka: layar dokumen menampilkan nama
    alur dan judul step-nya, dan pengaju berhak tahu ke meja mana
    dokumennya akan berjalan.
    """

    message = (
        "Hanya superuser atau pemegang role administrator workflow yang "
        "boleh mengubah konfigurasi alur persetujuan."
    )

    def has_permission(self, request, view) -> bool:
        if not getattr(request.user, "is_authenticated", False):
            return False

        if request.method in SAFE_METHODS:
            return True

        return can_configure(request.user)


class CanManageDelegation(BasePermission):
    """
    Surat kuasa: orang boleh mengurus kuasanya **sendiri**.

    Atasan yang mau cuti tidak perlu menunggu IT untuk menyerahkan
    persetujuannya — itu justru membuat kuasa tidak pernah dipakai dan
    dokumen mengendap. Yang dijaga: tidak boleh membuat kuasa atas nama
    orang lain, karena itu sama dengan mengambil alih hak tanda tangan
    orang tersebut.

    Administrator workflow dan superuser tetap boleh mengurus kuasa
    siapa pun — dibutuhkan saat atasannya sudah terlanjur berangkat dan
    tidak bisa dihubungi.
    """

    message = (
        "Anda hanya boleh membuat surat kuasa atas nama diri sendiri."
    )

    def has_permission(self, request, view) -> bool:
        if not getattr(request.user, "is_authenticated", False):
            return False

        if request.method in SAFE_METHODS or can_configure(request.user):
            return True

        delegator = request.data.get("delegator")

        if delegator in (None, ""):
            # Dikosongkan = diisi service dengan penggunanya sendiri.
            return True

        return str(delegator) == str(request.user.pk)

    def has_object_permission(self, request, view, obj) -> bool:
        if request.method in SAFE_METHODS or can_configure(request.user):
            return True

        return obj.delegator_id == request.user.pk
