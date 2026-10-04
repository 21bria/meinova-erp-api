"""
Penjagaan `/api/me/*`.

**Sengaja tidak memakai `ModelPermission`.** Seluruh API lain di sistem
ini menjawab "role Anda boleh membaca model ini?"; Self Service menjawab
pertanyaan yang berbeda — "baris ini memang Anda?". Yang kedua tidak bisa
diturunkan dari yang pertama, dan mencoba menurunkannya menghasilkan dua
kesalahan sekaligus: HR Admin yang izin bacanya luas tetap hanya boleh
melihat dirinya sendiri di sini, dan pegawai yang `hr.view_employee`-nya
dicabut tetap harus bisa membuka profilnya sendiri.

Karena itu `require_view_permission` tidak berlaku di sini, dan
`hr.view_employee` tidak pernah ditanyakan.
"""

from rest_framework.permissions import BasePermission

from apps.self_service.services import CurrentEmployeeService


class IsSelfServiceEmployee(BasePermission):
    """
    Pemegang akun ini punya kartu pegawai yang aktif.

    Sebabnya **dilempar, bukan dikembalikan `False`.** DRF menerjemahkan
    `False` jadi satu 403 generik, sementara ketiga sebab di
    `apps.self_service.exceptions` punya status dan kalimatnya
    masing-masing — dan perbedaan itulah yang membuat pemakainya tahu
    harus menghubungi siapa.
    """

    def has_permission(self, request, view) -> bool:
        CurrentEmployeeService.for_request(request)

        return True
