"""
Siapa boleh membaca izin siapa.

Employee Self Service berdiri di atas satu kunci: cakupan `own` di
`data_scope` viewset. Kalau kunci itu hilang atau salah tulis, pegawai
biasa membaca izin seluruh perusahaan — dan alasan izin sering memuat
hal yang paling pribadi yang pernah diketik seseorang ke sistem ini.

Dijalankan lewat HTTP sungguhan dengan token JWT, bukan lewat service:
yang diuji penyaringan barisnya, dan itu baru berarti kalau
`request.user`-nya datang dari jalur yang sama dengan layar.
"""

from __future__ import annotations

import json

from datetime import time, timedelta

from django.contrib.auth.models import Permission
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.accounts.models import (
    AuthorityMode,
    Role,
)
from apps.accounts.services.role_assignment import assign_roles
from apps.hr.models import AttendancePermissionType

from .base import TRIAL_DATE, AttendancePermissionTestCase


PERMISSIONS = "/api/hr/attendance-permissions/"


class _As:
    """Klien HTTP yang selalu membawa token satu orang."""

    def __init__(self, client, user):
        self.client = client
        self.headers = {
            "HTTP_AUTHORIZATION": (
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
        }

    def get(self, path):
        return self.client.get(path, **self.headers)

    def post(self, path, payload=None):
        return self.client.post(
            path,
            data=json.dumps(payload or {}),
            content_type="application/json",
            **self.headers,
        )


class PermissionScopeTestCase(AttendancePermissionTestCase):
    def setUp(self):
        super().setUp()

        # `TenantClient`, bukan `APIClient`: request lewat middleware
        # django-tenants, dan client biasa mendarat di schema `public`
        # — yang tabel HR-nya memang tidak ada di sana.
        self.http = TenantClient(self.tenant)

        self.own_role = Role.objects.create(
            code=f"APM-OWN-{self._counter}",
            name="Employee (own scope)",
        )

        # Izin model diberikan penuh: yang dijaga berkas ini
        # penyaringan **barisnya**, bukan izin tabelnya. Tanpa ini
        # penolakannya datang dari `ModelPermission` dan test-nya hijau
        # karena sebab yang salah.
        model_permissions = Permission.objects.filter(
            content_type__app_label="hr",
            codename__in=[
                "view_attendancepermission",
                "add_attendancepermission",
                "change_attendancepermission",
                "delete_attendancepermission",
            ],
        )

        self.own_role.permissions.set(model_permissions)

        self.mine = self.make_employee()
        self.theirs = self.make_employee()

        # **WHERE-nya disebut, bukan diwarisi dari `Role`.**
        #
        # Sampai Stage 4G penugasan mewarisi baris `own` di atas dan
        # fixture ini cukup memberi rolenya saja. Sejak 4H `Role`
        # menjawab WHAT saja: yang tidak dinyatakan tidak ada, dan
        # pemegangnya tidak melihat apa pun — termasuk datanya sendiri.
        #
        # Perhatikan bentuk kegagalannya kalau baris ini dilepas: yang
        # jatuh hanya pernyataan **positif** ("saya melihat punya
        # saya"), sedangkan seluruh pernyataan penolakan di kelas ini
        # tetap hijau karena pemegangnya tidak melihat apa-apa. Itu ciri
        # khas fail-closed — dan alasan kenapa fixture yang bergantung
        # pada turunan harus diperbaiki, bukan dibiarkan: kalau tidak,
        # test penolakannya lulus karena sebab yang salah.
        for employee in (self.mine, self.theirs):
            assign_roles(employee.user, [{
                "role": self.own_role.pk,
                "authority_mode": AuthorityMode.EXPLICIT,
                "authorities": [
                    {"resource_type": "own", "resource_id": None},
                ],
            }])

        self.my_permission = self.make_permission(
            self.mine,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
        )

        self.their_permission = self.make_permission(
            self.theirs,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
        )

    def as_(self, employee) -> _As:
        return _As(self.http, employee.user)

    def ids_from(self, response) -> set[int]:
        payload = response.json()

        rows = payload.get("data", payload)

        if isinstance(rows, dict):
            rows = rows.get("results", rows.get("data", []))

        return {row["id"] for row in rows}

    # ------------------------------------------------------------------

    def test_own_scope_hides_other_peoples_permissions(self):
        response = self.as_(self.mine).get(PERMISSIONS)

        self.assertEqual(response.status_code, 200)

        ids = self.ids_from(response)

        self.assertIn(self.my_permission.pk, ids)
        self.assertNotIn(self.their_permission.pk, ids)

    def test_own_scope_cannot_open_another_persons_permission(self):
        response = self.as_(self.mine).get(
            f"{PERMISSIONS}{self.their_permission.pk}/",
        )

        self.assertEqual(response.status_code, 404)

    def test_self_service_create_fills_in_the_employee(self):
        """
        Form Employee Self Service tidak punya kolom pegawai —
        pegawai mengajukan izin untuk dirinya sendiri.
        """
        response = self.as_(self.mine).post(
            PERMISSIONS,
            {
                "permission_type": AttendancePermissionType.EARLY_LEAVE,
                "date": TRIAL_DATE.isoformat(),
                "start_time": "15:00:00",
                "reason": "Menjemput anak sakit",
            },
        )

        self.assertIn(response.status_code, (200, 201), response.content)

        from apps.hr.models import AttendancePermission

        created = AttendancePermission.objects.filter(
            employee=self.mine,
            permission_type=AttendancePermissionType.EARLY_LEAVE,
        ).first()

        self.assertIsNotNone(created)

    def test_status_cannot_be_written_through_the_form(self):
        """
        Perpindahan status hanya lewat tombol alur. Kalau kolomnya bisa
        dikirim form, siapa pun yang menembak API langsung bisa
        menuliskan `approved` tanpa satu pun tanda tangan.
        """
        # Tanggal lain, bukan `TRIAL_DATE`: `setUp` sudah menerbitkan
        # izin Late Arrival di tanggal itu, dan izin sehari penuh
        # bertabrakan dengan izin apa pun di hari yang sama. Yang diuji
        # di sini kolom `status`, jadi biarkan penjagaan tumpang tindih
        # diuji berkas sebelah.
        other_day = TRIAL_DATE + timedelta(days=1)

        response = self.as_(self.mine).post(
            PERMISSIONS,
            {
                "permission_type": AttendancePermissionType.FULL_DAY,
                "date": other_day.isoformat(),
                "reason": "Urusan keluarga",
                "status": "approved",
            },
        )

        self.assertIn(response.status_code, (200, 201), response.content)

        from apps.hr.models import (
            AttendancePermission,
            AttendancePermissionStatus,
        )

        created = AttendancePermission.objects.filter(
            employee=self.mine,
            permission_type=AttendancePermissionType.FULL_DAY,
        ).first()

        self.assertEqual(
            created.status,
            AttendancePermissionStatus.DRAFT,
        )
