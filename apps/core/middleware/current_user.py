"""
Konteks request yang sedang berjalan, dibaca lapisan yang tidak
menerimanya sebagai argumen.

Dipakai `AuditService`: IP dan user agent tidak pernah sampai ke service
— `BaseService.create()` cuma menerima `data` dan `user` — sementara
jejak audit tanpa keduanya tidak bisa menjawab "dari mana perubahan ini
datang".

**Sengaja hanya untuk data pelengkap.** Otorisasi dan `created_by` tetap
mengoper `user=` eksplisit, dan itu tidak boleh berubah: nilai yang
diambil diam-diam dari thread-local membuat pemanggil non-HTTP (perintah
manajemen, task Celery, test) berperilaku berbeda dari jalur API tanpa
satu pun tanda di kodenya.

`contextvars`, bukan `threading.local`: yang kedua bocor antar-request di
server async dan antar-task di kode berbasis coroutine — nilai milik
pengguna lain terbaca sebagai milik sendiri, dan itu justru kesalahan
yang paling berbahaya di jejak audit.
"""

from __future__ import annotations

import contextvars


_request_context: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "meinova_request_context",
    default=None,
)


def get_request_context() -> dict:
    """Konteks request sekarang; dict kosong di luar siklus request."""
    return _request_context.get() or {}


def get_current_user():
    user = get_request_context().get("user")

    if user is None or not getattr(user, "is_authenticated", False):
        return None

    return user


def set_request_context(context: dict | None):
    return _request_context.set(context)


def reset_request_context(token) -> None:
    _request_context.reset(token)


def _client_ip(request) -> str | None:
    """
    IP klien, mendahulukan `X-Forwarded-For`.

    Nilai pertama di daftar itu yang paling dekat ke pengguna; sisanya
    proxy. Di belakang load balancer, `REMOTE_ADDR` selalu berisi alamat
    proxy-nya sendiri — jejak audit yang seluruh barisnya menunjuk satu
    IP internal tidak memberi tahu apa pun.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")

    if forwarded:
        return forwarded.split(",")[0].strip() or None

    return request.META.get("REMOTE_ADDR") or None


class CurrentRequestMiddleware:
    """Menyimpan user, IP, dan user agent selama request berjalan."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = set_request_context({
            "user": getattr(request, "user", None),
            "ip_address": _client_ip(request),
            # Dipotong: kolomnya TextField, tapi user agent sepanjang
            # dua kilobyte dari bot tidak menambah informasi apa pun.
            "user_agent": (request.META.get("HTTP_USER_AGENT") or "")[:512],
            "path": request.path,
            "method": request.method,
        })

        try:
            return self.get_response(request)
        finally:
            # Wajib dilepas: worker thread dipakai ulang untuk request
            # berikutnya, dan konteks yang tertinggal membuat perubahan
            # milik orang lain tercatat atas nama pengguna sebelumnya.
            reset_request_context(token)
