"""
Kredensial mesin untuk agent absensi on-premise (SEC-ATT-SYNC-1).

Menggantikan `MEINOVA_AGENT_API_KEY` — satu kunci global yang sah di host
tenant mana pun — dengan satu kredensial **per `AttendanceDevice`**, yang
hidup di schema tenant pemiliknya.

Bentuk kunci (dikirim agent lewat header `X-Agent-Key`, tanpa perubahan
protokol agent; cukup ganti `ERP_API_KEY` di `.env` agent):

    atk_<key_id>.<secret>

* `key_id` — 16 hex acak, publik, untuk menemukan baris device-nya.
* `secret` — `secrets.token_urlsafe(32)`, tidak pernah disimpan.

Yang disimpan: `agent_key_id` + `make_password("<tenant_id>:<key_id>:<secret>")`.

Ikatan tenant, tiga lapis:
1. barisnya dicari di schema yang dipilih host — kunci tenant A tidak
   punya baris di schema B;
2. `tenant_id` (UUID `Client.pk`, identitas kanonik yang sama dengan JWT
   — `apps.accounts.jwt.current_tenant_id`) ikut di-hash: baris yang
   disalin ke schema lain pun tidak cocok di sana;
3. schema public / tanpa tenant → selalu gagal.

Gagal karena apa pun (bentuk salah, id tak dikenal, secret salah, device
nonaktif, dicabut, tenant lain) → `None`. Pemanggil membalas satu pesan
generik; sebab sebenarnya tidak dibocorkan. Id yang tidak dikenal tidak
memicu perhitungan hash, jadi tebakan acak murah untuk ditolak.
"""

from __future__ import annotations

import re
import secrets

from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.utils import timezone

from apps.accounts.jwt import current_tenant_id


PREFIX = "atk_"

KEY_PATTERN = re.compile(r"^atk_([0-9a-f]{16})\.([A-Za-z0-9_\-]{20,128})$")


class CredentialError(Exception):
    """Operasi kredensial yang tidak bisa dijalankan (mis. tanpa tenant)."""


def _material(tenant_id: str, key_id: str, secret: str) -> str:
    return f"{tenant_id}:{key_id}:{secret}"


class AttendanceAgentCredentialService:
    # ------------------------------------------------------------------
    # Siklus hidup
    # ------------------------------------------------------------------

    @staticmethod
    @transaction.atomic
    def issue(device) -> str:
        """
        Terbitkan (atau rotasi) kredensial device. Mengembalikan kunci
        mentah — **satu-satunya kesempatan** melihatnya. Kunci lama, kalau
        ada, langsung tidak berlaku.
        """
        tenant_id = current_tenant_id()

        if tenant_id is None:
            raise CredentialError(
                "Kredensial agent hanya bisa diterbitkan di dalam tenant "
                "(pakai `manage.py tenant_command ... --schema=<tenant>`).",
            )

        key_id = secrets.token_hex(8)
        secret = secrets.token_urlsafe(32)

        device.agent_key_id = key_id
        device.agent_key_hash = make_password(_material(tenant_id, key_id, secret))
        device.agent_key_issued_at = timezone.now()
        device.agent_key_revoked_at = None
        device.save(
            update_fields=[
                "agent_key_id",
                "agent_key_hash",
                "agent_key_issued_at",
                "agent_key_revoked_at",
                "updated_at",
            ],
        )

        return f"{PREFIX}{key_id}.{secret}"

    rotate = issue

    @staticmethod
    @transaction.atomic
    def revoke(device) -> None:
        device.agent_key_id = ""
        device.agent_key_hash = ""
        device.agent_key_revoked_at = timezone.now()
        device.save(
            update_fields=[
                "agent_key_id",
                "agent_key_hash",
                "agent_key_revoked_at",
                "updated_at",
            ],
        )

    # ------------------------------------------------------------------
    # Autentikasi
    # ------------------------------------------------------------------

    @staticmethod
    def authenticate(raw_key: str):
        """`AttendanceDevice` pemilik kunci ini di tenant aktif, atau `None`."""
        from apps.hr.models import AttendanceDevice

        match = KEY_PATTERN.match((raw_key or "").strip())

        if match is None:
            return None

        tenant_id = current_tenant_id()

        if tenant_id is None:
            return None

        key_id, secret = match.groups()

        device = (
            AttendanceDevice.objects
            .select_related("company", "location")
            .filter(agent_key_id=key_id)
            .first()
        )

        if device is None or not device.agent_key_hash or not device.is_active:
            return None

        if not check_password(_material(tenant_id, key_id, secret), device.agent_key_hash):
            return None

        return device
