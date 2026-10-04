"""
TR-CLEANUP-2 — DEMOB milik Travel Request, Hapus di tab Accommodation
tidak destruktif, dan endpoint Travel Purpose mengikuti cakupan TR
induknya.

Cakupan diuji lewat HTTP: penyaringannya hidup di lapisan view.
"""

from __future__ import annotations

import json
from datetime import date

from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError

from apps.accounts.models import AuthorityMode, Role
from apps.accounts.services.role_assignment import grant_role
from apps.administration.models import Location, RotationPurpose
from apps.hr.api.travel_request.schema import TRAVEL_REQUEST_TABS
from apps.hr.api.travel_request.services import (
    TravelArrangementService,
    TravelRequestPurposeService,
)
from apps.hr.models import TravelArrangement, TravelRequestPurpose

# Modulnya, bukan kelasnya: nama kelas TestCase di namespace modul ini
# akan ikut dikumpulkan loader dan seluruh test TR-CLEANUP-1 jalan dua kali.
from . import test_tr_cleanup_1 as cleanup1
from .test_tr_cleanup_1 import _record, _rows


PURPOSES = "/api/hr/travel-request-purposes/"
ARRANGEMENTS = "/api/hr/travel-arrangements/"

TR_MODELS = ("travelrequest", "travelrequestpurpose", "travelarrangement")
ALL_VERBS = ("add", "change", "view", "delete")


class TravelRequestCleanup2Tests(cleanup1.TravelRequestCleanupTests):
    """
    Turunan kelas TR-CLEANUP-1 demi pabrik & helper-nya. Test induknya
    tidak ikut dijalankan ulang (lihat `__test__` di bawah) — hanya
    pabriknya yang dipakai.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.third_site = Location.objects.create(
            company=cls.company,
            code="TRCLN2-THIRD",
            name="Makassar Transit",
        )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @classmethod
    def role_user(cls, location, codenames):
        cls._user_counter += 1

        role = Role.objects.create(
            code=f"TRCLN2-{cls._user_counter}",
            name=f"TR Cleanup2 {cls._user_counter}",
        )
        role.permissions.add(
            *Permission.objects.filter(
                content_type__app_label="hr",
                codename__in=list(codenames),
            ),
        )

        user = cls.make_user()
        grant_role(
            user,
            role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("location", location.pk)],
        )

        return user

    def request_at(self, location):
        request = self.make_request()
        request.location = location
        request.save(update_fields=["location"])

        return request

    # ------------------------------------------------------------------
    # DEMOB / batas alasan
    # ------------------------------------------------------------------

    def test_demob_accepted_in_travel_request(self):
        self.assertFalse(self.demob.is_business_trip_domain)

        request = self.make_request(with_purpose=False)
        response = self.api(
            "post",
            PURPOSES,
            {
                "request": request.pk,
                "purpose": self.demob.pk,
                "start_date": "2026-10-13",
                "end_date": "2026-10-14",
            },
        )

        self.assertEqual(response.status_code, 201, response.content)

    def test_canonical_policy_codes(self):
        self.assertEqual(
            RotationPurpose.BUSINESS_TRIP_CODES,
            frozenset({"DUTY", "TRAINING"}),
        )

        for code in ("FB", "ANNUAL", "SICK", "BIG", "UNPAID", "DEMOB"):
            self.assertNotIn(code, RotationPurpose.BUSINESS_TRIP_CODES)

    def test_duty_and_training_still_rejected(self):
        request = self.make_request(with_purpose=False)

        for purpose in (self.duty, self.training):
            with self.subTest(purpose=purpose.code):
                with self.assertRaises(ValidationError):
                    TravelRequestPurposeService.create(
                        data={
                            "request": request,
                            "purpose": purpose,
                            "start_date": request.start_date,
                            "end_date": request.end_date,
                        },
                    )

    # ------------------------------------------------------------------
    # Cakupan endpoint Travel Purpose
    # ------------------------------------------------------------------

    def test_purpose_read_scope_follows_parent(self):
        user = self.scoped_user(self.site)

        mine = self.make_request()
        elsewhere = self.request_at(self.other_site)
        foreign_row = elsewhere.purposes.get()

        own_list = self.api("get", f"{PURPOSES}?request={mine.pk}", user=user)
        self.assertEqual(own_list.status_code, 200, own_list.content)
        self.assertEqual(len(_rows(own_list.json())), 1)

        foreign_list = self.api(
            "get", f"{PURPOSES}?request={elsewhere.pk}", user=user,
        )
        self.assertEqual(_rows(foreign_list.json()), [])

        # Tanpa filter `request` pun barisnya tidak ikut.
        all_ids = {
            row["id"]
            for row in _rows(self.api("get", PURPOSES, user=user).json())
        }
        self.assertNotIn(foreign_row.pk, all_ids)

        detail = self.api("get", f"{PURPOSES}{foreign_row.pk}/", user=user)
        self.assertEqual(detail.status_code, 404, detail.content)

    def test_purpose_write_outside_scope_denied(self):
        user = self.scoped_user(self.site)

        elsewhere = self.request_at(self.other_site)
        foreign_row = elsewhere.purposes.get()

        create = self.api(
            "post",
            PURPOSES,
            {
                "request": elsewhere.pk,
                "purpose": self.annual_leave.pk,
                "start_date": "2026-10-20",
                "end_date": "2026-10-21",
            },
            user=user,
        )
        self.assertEqual(create.status_code, 400, create.content)
        self.assertIn("cakupan", create.content.decode())

        edit = self.api(
            "patch",
            f"{PURPOSES}{foreign_row.pk}/",
            {"notes": "dibobol"},
            user=user,
        )
        self.assertEqual(edit.status_code, 404, edit.content)

        remove = self.api("delete", f"{PURPOSES}{foreign_row.pk}/", user=user)
        self.assertEqual(remove.status_code, 404, remove.content)

        bulk = self.api(
            "post",
            f"{PURPOSES}bulk-delete/",
            {"ids": [foreign_row.pk]},
            user=user,
        )
        self.assertIn(bulk.status_code, (200, 400, 404), bulk.content)

        foreign_row.refresh_from_db()
        self.assertEqual(foreign_row.notes, "")
        self.assertFalse(foreign_row.is_deleted)
        self.assertEqual(elsewhere.purposes.filter(is_deleted=False).count(), 1)

    def test_purpose_write_inside_scope_allowed(self):
        user = self.scoped_user(self.site)
        request = self.make_request(with_purpose=False)

        create = self.api(
            "post",
            PURPOSES,
            {
                "request": request.pk,
                "purpose": self.field_break.pk,
                "start_date": "2026-10-13",
                "end_date": "2026-10-26",
            },
            user=user,
        )
        self.assertEqual(create.status_code, 201, create.content)
        row_id = _record(create)["id"]

        edit = self.api(
            "patch", f"{PURPOSES}{row_id}/", {"notes": "ok"}, user=user,
        )
        self.assertEqual(edit.status_code, 200, edit.content)

        remove = self.api("delete", f"{PURPOSES}{row_id}/", user=user)
        self.assertEqual(remove.status_code, 200, remove.content)

    def test_update_delete_require_change_on_parent_request(self):
        """
        Pemegang izin ubah **baris anak** yang hanya boleh **membaca** TR
        induknya tidak boleh mengubah isi dokumen itu.
        """
        child_only = self.role_user(
            self.third_site,
            ["view_travelrequest"]
            + [
                f"{verb}_{model}"
                for verb in ALL_VERBS
                for model in ("travelrequestpurpose", "travelarrangement")
            ],
        )

        request = self.request_at(self.third_site)
        row = request.purposes.get()
        leg = TravelArrangementService.create(
            data={
                "request": request,
                "direction": "out",
                "travel_start_date": date(2026, 10, 11),
            },
        )

        for url, payload in (
            (f"{PURPOSES}{row.pk}/", {"notes": "x"}),
            (f"{ARRANGEMENTS}{leg.pk}/", {"notes": "x"}),
        ):
            with self.subTest(url=url):
                edit = self.api("patch", url, payload, user=child_only)
                self.assertEqual(edit.status_code, 400, edit.content)

                remove = self.api("delete", url, user=child_only)
                self.assertEqual(remove.status_code, 400, remove.content)

        create = self.api(
            "post",
            PURPOSES,
            {
                "request": request.pk,
                "purpose": self.annual_leave.pk,
                "start_date": "2026-10-20",
                "end_date": "2026-10-21",
            },
            user=child_only,
        )
        self.assertEqual(create.status_code, 400, create.content)

        row.refresh_from_db()
        leg.refresh_from_db()
        self.assertFalse(row.is_deleted)
        self.assertFalse(leg.is_deleted)
        self.assertEqual(row.notes, "")

    def test_purpose_cannot_move_to_another_request(self):
        mine = self.make_request()
        other = self.make_request()
        row = mine.purposes.get()

        response = self.api(
            "patch", f"{PURPOSES}{row.pk}/", {"request": other.pk},
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(
            TravelRequestPurpose.objects.get(pk=row.pk).request_id,
            mine.pk,
        )

    # ------------------------------------------------------------------
    # Tab Accommodation
    # ------------------------------------------------------------------

    def test_accommodation_tab_has_no_destructive_delete(self):
        tab = next(
            t for t in TRAVEL_REQUEST_TABS if t["key"] == "accommodation"
        )

        self.assertIs(tab["delete"], False)
        self.assertNotEqual(tab.get("create"), False)
        self.assertIn("clear its fields", tab["description"])

    def test_travel_arrangement_tab_keeps_delete(self):
        tab = next(t for t in TRAVEL_REQUEST_TABS if t["key"] == "travels")

        self.assertNotEqual(tab.get("delete"), False)

        # Semantik DELETE di API tidak berubah: menghapus etape.
        request = self.make_request()
        leg = TravelArrangementService.create(
            data={
                "request": request,
                "direction": "out",
                "travel_start_date": date(2026, 10, 11),
                "accommodation_name": "Hotel",
                "accommodation_checkin": date(2026, 10, 11),
                "accommodation_checkout": date(2026, 10, 12),
            },
        )

        response = self.api("delete", f"{ARRANGEMENTS}{leg.pk}/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(
            TravelArrangement.objects.filter(
                pk=leg.pk, is_deleted=False,
            ).exists(),
        )

    def test_clearing_accommodation_keeps_transport_leg(self):
        request = self.make_request()
        leg = TravelArrangementService.create(
            data={
                "request": request,
                "direction": "out",
                "travel_start_date": date(2026, 10, 11),
                "transport_detail": "GA-642",
                "ticket_number": "TKT-1",
                "accommodation_name": "Hotel Bela",
                "accommodation_checkin": date(2026, 10, 11),
                "accommodation_checkout": date(2026, 10, 12),
            },
        )

        row = self.api("get", f"{ARRANGEMENTS}{leg.pk}/").json()
        row = row.get("data", row) if isinstance(row, dict) else row
        row.update(
            {
                "accommodation_type": None,
                "accommodation_name": "",
                "accommodation_checkin": None,
                "accommodation_checkout": None,
            },
        )

        response = self.api("put", f"{ARRANGEMENTS}{leg.pk}/", row)
        self.assertEqual(response.status_code, 200, response.content)

        leg.refresh_from_db()
        self.assertFalse(leg.is_deleted)
        self.assertFalse(leg.accommodation_needed)
        self.assertEqual(leg.accommodation_name, "")
        self.assertEqual(leg.transport_detail, "GA-642")
        self.assertEqual(leg.ticket_number, "TKT-1")
        self.assertEqual(leg.travel_start_date, date(2026, 10, 11))


# Test milik kelas TR-CLEANUP-1 sudah dijalankan di berkasnya sendiri;
# yang diwarisi di sini cuma pabriknya. Tanpa ini setiap test induk
# jalan dua kali (sekali per kelas).
for _name in list(vars(cleanup1.TravelRequestCleanupTests)):
    if _name.startswith("test_") and _name not in vars(
        TravelRequestCleanup2Tests,
    ):
        setattr(TravelRequestCleanup2Tests, _name, None)
