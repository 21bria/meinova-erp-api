"""
Layar pos jaga `GET /api/hr/visitor-requests/gate/` yang berlaku hari
ini (BT-1).

Business Trip (BT-4) **tidak** menumpang endpoint ini — ia mendapat
proyeksi baca sendiri yang dicakup lokasi tujuan. Yang dikunci di sini
perilaku gate Visitor supaya tetap utuh sesudahnya:

* hanya dokumen APPROVED/COMPLETED yang rentang kunjungannya mencakup
  hari ini, dan bukan No Show;
* disaring cakupan data lewat kolom `location` dokumen (lokasi yang
  dikunjungi; bawaannya lokasi pemohon);
* isinya baris VisitorRequest saja.

Lewat HTTP sungguhan dengan token JWT: yang diuji penyaringan barisnya,
dan itu baru berarti kalau `request.user` datang dari jalur layar.
"""

from __future__ import annotations

import json

from datetime import timedelta

from django.contrib.auth.models import Permission
from django.utils import timezone
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.accounts.models import AuthorityMode, Role
from apps.accounts.services.role_assignment import assign_roles
from apps.hr.models import (
    VisitorArrivalStatus,
    VisitorRequestStatus,
)

from .base import VisitorTestCase


GATE = "/api/hr/visitor-requests/gate/"


class VisitorGateContractTests(VisitorTestCase):
    def setUp(self):
        super().setUp()

        self.http = TenantClient(self.tenant)

        self.gate_role = Role.objects.create(
            code=f"VST-GATE-{self._counter}",
            name="Gate (site scope)",
        )

        # Izin model diberikan: yang dijaga berkas ini penyaringan
        # barisnya, bukan izin tabelnya.
        self.gate_role.permissions.set(
            Permission.objects.filter(
                content_type__app_label="hr",
                codename__in=[
                    "view_visitorrequest",
                    "change_visitorrequest",
                ],
            ),
        )

        self.guard = self.make_employee(location=self.site)

        # WHERE dinyatakan eksplisit (Stage 4H): `.roles.add()` saja
        # tidak memberi akses baris.
        assign_roles(self.guard.user, [{
            "role": self.gate_role.pk,
            "authority_mode": AuthorityMode.EXPLICIT,
            "authorities": [
                {"resource_type": "location", "resource_id": self.site.pk},
            ],
        }])

        self.requester = self.make_employee(location=self.head_office)

        self.today = timezone.localdate()

    def request_at(self, location, *, status=VisitorRequestStatus.APPROVED,
                   start=None, end=None, **extra):
        request = self.make_request(
            requester=self.requester,
            location=location,
            start=start,
            end=end,
            **extra,
        )

        request.status = status
        request.save(update_fields=["status"])

        return request

    def gate_ids(self, user) -> set[int]:
        token = RefreshToken.for_user(user).access_token

        response = self.http.get(
            GATE,
            HTTP_AUTHORIZATION=f"Bearer {token}",
        )

        self.assertEqual(response.status_code, 200, response.content[:500])

        body = json.loads(response.content)

        return {row["id"] for row in body["data"]}

    # ------------------------------------------------------------------

    def test_guard_sees_only_todays_approved_visits_at_their_location(self):
        visible = self.request_at(self.site)

        completed = self.request_at(
            self.site,
            status=VisitorRequestStatus.COMPLETED,
        )

        other_location = self.request_at(self.head_office)

        draft = self.request_at(self.site, status=VisitorRequestStatus.DRAFT)

        submitted = self.request_at(
            self.site,
            status=VisitorRequestStatus.SUBMITTED,
        )

        tomorrow = self.request_at(
            self.site,
            start=self.today + timedelta(days=1),
            end=self.today + timedelta(days=2),
        )

        ended = self.request_at(
            self.site,
            start=self.today - timedelta(days=3),
            end=self.today - timedelta(days=1),
        )

        no_show = self.request_at(self.site)
        no_show.arrival_status = VisitorArrivalStatus.NO_SHOW
        no_show.save(update_fields=["arrival_status"])

        ids = self.gate_ids(self.guard.user)

        self.assertIn(visible.pk, ids)
        self.assertIn(completed.pk, ids)

        for hidden in (other_location, draft, submitted, tomorrow, ended,
                       no_show):
            self.assertNotIn(hidden.pk, ids)

    def test_multi_day_visit_covering_today_is_listed(self):
        request = self.request_at(
            self.site,
            start=self.today - timedelta(days=1),
            end=self.today + timedelta(days=1),
        )

        self.assertIn(request.pk, self.gate_ids(self.guard.user))

    def test_legacy_internal_visitor_still_appears_at_the_gate(self):
        """
        Dokumen internal lama yang sudah disetujui tetap tampil di pos
        jaga sampai selesai. Internal baru tidak bisa dibuat lagi
        (BT-2A); pegawai yang datang ke site akan tampil lewat proyeksi
        Business Trip sendiri (BT-4), tanpa membuat Visitor Request.
        """
        request = self.make_legacy_internal(
            requester=self.requester,
            employee=self.make_employee(location=self.head_office),
            status=VisitorRequestStatus.APPROVED,
            location=self.site,
        )

        self.assertIn(request.pk, self.gate_ids(self.guard.user))

    def test_scope_follows_the_document_location_not_the_requester(self):
        """
        Pemohon duduk di HO, dokumennya menyebut site: guard site
        melihatnya. Cakupannya kolom `location` dokumen.
        """
        request = self.request_at(self.site)

        self.assertEqual(request.requester.organization.location_id,
                         self.head_office.pk)

        self.assertIn(request.pk, self.gate_ids(self.guard.user))
