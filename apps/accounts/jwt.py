"""
JWT yang terikat tenant (SEC-TENANT-JWT-1).

Masalah yang ditutup
--------------------
Semua tenant menandatangani token dengan `SECRET_KEY` yang sama, dan
`JWTAuthentication` bawaan mencari `user_id` di schema yang **sudah**
dipilih django-tenants dari hostname. Id User adalah bilangan kecil
berurutan per schema, jadi token tenant A yang dikirim ke host tenant B
lolos sebagai User B ber-id sama — terbukti di
`apps.self_service.tests.test_attendance_punch_tenancy`.

Klaimnya
--------
`tenant_id` = `str(Client.pk)`. `Client.id` adalah UUID primary key
`editable=False` — identitas tenant kanonik yang sudah ada, tidak berubah
sepanjang umur tenant, dan tidak membocorkan nama schema. `schema_name`
sengaja tidak dipakai: ia kunci routing yang secara teknis bisa diganti,
bukan identitas.

Pembandingnya `connection.tenant` — tenant yang schema-nya akan dipakai
mencari User. Itu persis yang harus cocok: token hanya sah di schema
tempat ia diterbitkan.

Di mana ditegakkan (satu tempat per jalur)
-----------------------------------------
* terbit   — `LoginSerializer.get_token()` → `bind_tenant()`
* akses    — `TenantJWTAuthentication.get_validated_token()` (kelas
             autentikasi bawaan DRF untuk seluruh API), **sebelum**
             User dicari
* refresh  — `TenantTokenRefreshSerializer` (lewat
             `SIMPLE_JWT["TOKEN_REFRESH_SERIALIZER"]`), **sebelum** User
             dicari; access token baru menyalin klaim tenant dari
             refresh token-nya (`RefreshToken.access_token`)

Token tanpa klaim (terbit sebelum perubahan ini) ditolak — tidak ada
jalur kompatibilitas. Deploy = seluruh sesi lama berakhir, pengguna
login ulang.

Balasan gagal sengaja generik (`InvalidToken`, 401): tidak menyebut
apakah token itu milik tenant lain atau apakah id-nya ada di sini.
"""

from __future__ import annotations

from django.db import connection
from django_tenants.utils import get_public_schema_name
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.tokens import RefreshToken


TENANT_CLAIM = "tenant_id"


def current_tenant_id() -> str | None:
    """
    UUID tenant yang schema-nya sedang aktif, atau `None` untuk public /
    tanpa tenant. Tidak ada User di schema public (`accounts` adalah
    tenant app), jadi `None` selalu berarti "tidak ada token yang sah di
    sini".
    """
    tenant = getattr(connection, "tenant", None)

    if tenant is None:
        return None

    if getattr(tenant, "schema_name", None) == get_public_schema_name():
        return None

    pk = getattr(tenant, "pk", None)

    return str(pk) if pk else None


def bind_tenant(token) -> None:
    tenant_id = current_tenant_id()

    if tenant_id is None:
        # Login hanya mungkin di schema tenant; sampai sini berarti ada
        # yang salah memanggil. Lebih baik gagal daripada menerbitkan
        # token tanpa ikatan.
        raise InvalidToken()

    token[TENANT_CLAIM] = tenant_id


def assert_token_tenant(token) -> None:
    claimed = token.get(TENANT_CLAIM)
    current = current_tenant_id()

    if not claimed or current is None or str(claimed) != current:
        raise InvalidToken()


class TenantRefreshToken(RefreshToken):
    """
    `RefreshToken.for_user()` yang langsung terikat tenant aktif. Access
    token turunannya mewarisi klaimnya. Dipakai siapa pun yang menerbitkan
    token di luar endpoint login (test, alat internal) — token tanpa
    ikatan tidak lagi berguna di mana pun.
    """

    @classmethod
    def for_user(cls, user):
        token = super().for_user(user)

        bind_tenant(token)

        return token


class TenantJWTAuthentication(JWTAuthentication):
    def get_validated_token(self, raw_token):
        validated = super().get_validated_token(raw_token)

        assert_token_tenant(validated)

        return validated


class TenantTokenRefreshSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        try:
            refresh = self.token_class(attrs["refresh"])
        except TokenError as exc:
            raise InvalidToken(exc.args[0]) from exc

        assert_token_tenant(refresh)

        return super().validate(attrs)
