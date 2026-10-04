"""
Siapa boleh memanggil `/api/hr/attendance/sync/` (SEC-ATT-SYNC-1).

**Hanya mesin.** Endpoint ini jalur integrasi agent on-premise, bukan
jalur manusia. Dua celah lama ditutup di sini:

* dulu **user terautentikasi mana pun** diterima — pegawai biasa bisa
  mengirim tap mentah untuk nomor pegawai siapa pun di tenant-nya;
* dulu `MEINOVA_AGENT_API_KEY` satu kunci global yang sah di host tenant
  mana pun.

Sekarang view ini hanya memakai `AttendanceAgentAuthentication`: JWT
(manusia, termasuk superuser) tidak dibaca sama sekali, jadi tidak pernah
mengautentikasi di sini. Tap manusia lewat `/api/me/attendance/punch/`;
koreksi HR lewat layar Attendance. Kunci global tidak dibaca lagi di mana
pun.
"""

from __future__ import annotations

from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import BasePermission

from .credentials import AttendanceAgentCredentialService


HEADER = "X-Agent-Key"

GENERIC_FAILURE = "Invalid or missing attendance agent credentials."


class AttendanceAgentAuthentication(BaseAuthentication):
    """
    `X-Agent-Key` → `AttendanceDevice` di tenant aktif.

    Hasilnya `(AnonymousUser(), device)`: tidak ada User yang menumpang,
    dan `request.auth` adalah device yang terautentikasi.
    """

    def authenticate(self, request):
        raw = request.headers.get(HEADER, "")

        if not raw:
            return None

        device = AttendanceAgentCredentialService.authenticate(raw)

        if device is None:
            raise AuthenticationFailed(GENERIC_FAILURE)

        return (AnonymousUser(), device)

    def authenticate_header(self, request):
        # Membuat DRF membalas 401, bukan 403, saat kredensial tidak ada.
        return HEADER


class AttendanceAgentPermission(BasePermission):
    message = GENERIC_FAILURE

    def has_permission(self, request, view) -> bool:
        from apps.hr.models import AttendanceDevice

        return isinstance(getattr(request, "auth", None), AttendanceDevice)
