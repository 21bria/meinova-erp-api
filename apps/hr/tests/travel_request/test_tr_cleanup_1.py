"""
TR-CLEANUP-1 — Travel Request dipisah dari Business Trip, akomodasi
dipulihkan.

Dua hal yang dijaga di sini:

* **Batas alasan.** Travel Request = kepulangan site (Field Break + cuti
  yang menumpang perjalanannya). `DUTY`/`TRAINING` milik Business Trip:
  tidak bisa dipilih untuk baris baru/diganti dan tidak bisa diajukan,
  tapi TR lama yang menunjuknya tetap terbaca dan masternya tetap
  aktif (dipakai jadwal roster).
* **Akomodasi.** Tab Accommodation kembali bisa menambah baris; baris
  itu etape (`TravelArrangement`) yang Departure Date-nya diisi dari
  check-in. Hotel opsional, boleh lebih dari satu baris, dan tunduk
  pada pagar editable + cakupan data dokumen induknya.

Satu kelas: tiap `TenantTestCase` membayar satu `migrate_schemas`.
"""

from __future__ import annotations

import json
from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.accounts.models import AuthorityMode, Role
from apps.accounts.services.role_assignment import grant_role
from apps.administration.models import Location, RotationPurpose
from apps.hr.api.travel_request.schema import (
    ACCOMMODATION_GRID_FIELDS,
    TRAVEL_REQUEST_PURPOSE_SCHEMA,
    TRAVEL_REQUEST_TABS,
)
from apps.hr.api.travel_request.services import (
    TravelArrangementService,
    TravelRequestPurposeService,
    TravelRequestService,
)
from apps.hr.models import (
    TravelArrangement,
    TravelRequestPurpose,
    TravelRequestStatus,
)

from .base import TravelRequestTestCase


User = get_user_model()

ARRANGEMENTS = "/api/hr/travel-arrangements/"
PURPOSES = "/api/hr/travel-request-purposes/"
PURPOSE_LOOKUP = (
    "/api/administration/references/hr/lookup/rotation-purposes/"
)


def _record(response):
    """Satu record dari respons create/update, beramplop atau polos."""
    body = response.json()

    if isinstance(body, dict) and isinstance(body.get("data"), dict):
        return body["data"]

    return body


def _rows(body):
    """Isi daftar dari amplop `{data, meta}` maupun bentuk polos."""
    if isinstance(body, dict):
        body = body.get("data", body)

    if isinstance(body, dict):
        body = body.get("results", body.get("items", body))

    return body


class TravelRequestCleanupTests(TravelRequestTestCase):
    _user_counter = 0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Kode persis milik master seed — aturan batasnya membaca kode.
        cls.duty, _ = RotationPurpose.objects.get_or_create(
            code="DUTY",
            is_deleted=False,
            defaults={"name": "Dinas Luar"},
        )
        cls.training, _ = RotationPurpose.objects.get_or_create(
            code="TRAINING",
            is_deleted=False,
            defaults={"name": "Training"},
        )
        cls.demob, _ = RotationPurpose.objects.get_or_create(
            code="DEMOB",
            is_deleted=False,
            defaults={"name": "Demobilisasi"},
        )

        cls.other_site = Location.objects.create(
            company=cls.company,
            code="TRCLN-OTHER",
            name="Ternate Transit",
        )

    def setUp(self):
        super().setUp()

        self.client = TenantClient(self.tenant)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @classmethod
    def make_user(cls, *, superuser=False):
        cls._user_counter += 1

        return User.objects.create_user(
            username=f"trv.cleanup{cls._user_counter}",
            email=f"trv.cleanup{cls._user_counter}@example.test",
            password="Test-Only#Pw1",
            is_superuser=superuser,
            is_staff=superuser,
        )

    @classmethod
    def scoped_user(cls, location):
        """Pemegang izin TR penuh yang cakupannya satu Location."""
        cls._user_counter += 1

        role = Role.objects.create(
            code=f"TRCLN-{cls._user_counter}",
            name=f"TR Cleanup {cls._user_counter}",
        )

        role.permissions.add(
            *Permission.objects.filter(
                content_type__app_label="hr",
                codename__in=[
                    f"{verb}_{model}"
                    for verb in ("add", "change", "view", "delete")
                    for model in (
                        "travelrequest",
                        "travelrequestpurpose",
                        "travelarrangement",
                    )
                ],
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

    def auth(self, user=None):
        user = user or self.make_user(superuser=True)

        return {
            "HTTP_AUTHORIZATION": (
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
        }

    def api(self, method, url, payload=None, *, user=None):
        kwargs = self.auth(user)

        if payload is not None:
            kwargs["data"] = json.dumps(payload)
            kwargs["content_type"] = "application/json"

        return getattr(self.client, method)(url, **kwargs)

    def with_status(self, request, status):
        request.status = status
        request.save(update_fields=["status", "updated_at"])
        request.refresh_from_db()

        return request

    def legacy_purpose_row(self, request, purpose):
        """
        Baris lama yang menunjuk DUTY/TRAINING — dibuat sebelum aturan
        ini ada. Lewat ORM karena service sekarang menolaknya.
        """
        return TravelRequestPurpose.objects.create(
            request=request,
            purpose=purpose,
            sequence=9,
            start_date=request.start_date,
            end_date=request.start_date,
            total_days=1,
        )

    def stay_payload(self, request, **overrides):
        """Persis yang dikirim baris draft di tab Accommodation."""
        payload = {
            "request": request.pk,
            "direction": "out",
            "origin": "Gebe",
            "destination": "Ternate",
            "accommodation_name": "Hotel Bela Ternate",
            "accommodation_checkin": "2026-10-11",
            "accommodation_checkout": "2026-10-12",
            "notes": "Transit semalam sebelum pesawat ke Jakarta",
        }
        payload.update(overrides)

        return payload

    # ------------------------------------------------------------------
    # A. Batas Travel Purpose
    # ------------------------------------------------------------------

    def test_field_break_accepted(self):
        request = self.make_request()

        self.assertEqual(
            list(request.purposes.values_list("purpose__code", flat=True)),
            ["TR-FB"],
        )

    def test_leave_purpose_accepted(self):
        request = self.make_request(with_purpose=False)

        row = TravelRequestPurposeService.create(
            data={
                "request": request,
                "purpose": self.annual_leave,
                "start_date": date(2026, 10, 20),
                "end_date": date(2026, 10, 26),
            },
        )

        self.assertEqual(row.purpose, self.annual_leave)

    def test_duty_rejected_for_new_row(self):
        request = self.make_request(with_purpose=False)

        with self.assertRaises(ValidationError) as caught:
            TravelRequestPurposeService.create(
                data={
                    "request": request,
                    "purpose": self.duty,
                    "start_date": request.start_date,
                    "end_date": request.end_date,
                },
            )

        self.assertIn("purpose", caught.exception.message_dict)
        self.assertIn("Business Trip", str(caught.exception))

    def test_training_rejected_for_new_row_via_api(self):
        request = self.make_request(with_purpose=False)

        response = self.api(
            "post",
            PURPOSES,
            {
                "request": request.pk,
                "purpose": self.training.pk,
                "start_date": "2026-10-13",
                "end_date": "2026-10-14",
            },
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("purpose", response.content.decode())
        self.assertFalse(
            request.purposes.filter(purpose=self.training).exists(),
        )

    def test_changing_row_to_duty_rejected(self):
        request = self.make_request()
        row = request.purposes.get()

        response = self.api(
            "patch",
            f"{PURPOSES}{row.pk}/",
            {"purpose": self.duty.pk},
        )

        self.assertEqual(response.status_code, 400, response.content)

        row.refresh_from_db()
        self.assertEqual(row.purpose, self.field_break)

    def test_historical_duty_row_readable_and_other_columns_editable(self):
        request = self.make_request()
        legacy = self.legacy_purpose_row(request, self.duty)

        listed = self.api("get", f"{PURPOSES}?request={request.pk}")
        self.assertEqual(listed.status_code, 200, listed.content)
        names = {
            row["purpose_name"] for row in _rows(listed.json())
        }
        self.assertIn("Dinas Luar", names)

        # Grid inline mengirim ulang alasan yang tidak disentuh.
        response = self.api(
            "patch",
            f"{PURPOSES}{legacy.pk}/",
            {"purpose": self.duty.pk, "notes": "data lama"},
        )
        self.assertEqual(response.status_code, 200, response.content)

        legacy.refresh_from_db()
        self.assertEqual(legacy.notes, "data lama")
        self.assertEqual(legacy.purpose, self.duty)

    def test_historical_submitted_training_document_readable(self):
        request = self.make_request()
        self.legacy_purpose_row(request, self.training)
        self.with_status(request, TravelRequestStatus.APPROVED)

        detail = self.api("get", f"/api/hr/travel-requests/{request.pk}/")
        self.assertEqual(detail.status_code, 200, detail.content)

        listed = self.api("get", f"{PURPOSES}?request={request.pk}")
        codes = {row["purpose_name"] for row in _rows(listed.json())}
        self.assertIn("Training", codes)

    def test_submit_rejects_draft_with_business_trip_row(self):
        request = self.make_request()
        self.legacy_purpose_row(request, self.duty)

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.submit(request=request)

        self.assertIn("purposes", caught.exception.message_dict)
        self.assertIn("Dinas Luar", str(caught.exception))

        request.refresh_from_db()
        self.assertEqual(request.status, TravelRequestStatus.DRAFT)

    def test_lookup_hides_business_trip_purposes_only_for_tr(self):
        for_tr = self.api("get", f"{PURPOSE_LOOKUP}?document=travel_request")
        self.assertEqual(for_tr.status_code, 200, for_tr.content)
        tr_ids = {row["value"] for row in _rows(for_tr.json())}

        self.assertIn(self.field_break.pk, tr_ids)
        self.assertIn(self.annual_leave.pk, tr_ids)
        self.assertIn(self.demob.pk, tr_ids)
        self.assertNotIn(self.duty.pk, tr_ids)
        self.assertNotIn(self.training.pk, tr_ids)

        # Tanpa parameter (jadwal roster) daftarnya utuh, dan masternya
        # tidak dinonaktifkan.
        plain = self.api("get", PURPOSE_LOOKUP)
        plain_ids = {row["value"] for row in _rows(plain.json())}
        self.assertIn(self.duty.pk, plain_ids)
        self.assertIn(self.training.pk, plain_ids)

        self.duty.refresh_from_db()
        self.assertTrue(self.duty.is_active)
        self.assertFalse(self.duty.is_deleted)

    def test_schema_purpose_lookup_filters_for_travel_request(self):
        purpose = TRAVEL_REQUEST_PURPOSE_SCHEMA["fields"]["purpose"]
        self.assertEqual(
            purpose["lookup_params"],
            {"document": "travel_request"},
        )

        tab = next(t for t in TRAVEL_REQUEST_TABS if t["key"] == "purposes")
        self.assertEqual(
            tab["fields"]["purpose"]["lookup_params"],
            {"document": "travel_request"},
        )

    def test_from_rotation_period_does_not_copy_duty(self):
        employee = self.make_employee()
        rotation = self.make_rotation(employee)
        _, off = self.make_periods(rotation)
        off.purpose = self.duty
        off.save(update_fields=["purpose"])

        request = TravelRequestService.build_from_period(period=off)

        self.assertFalse(
            request.purposes.filter(is_deleted=False).exists(),
        )

    # ------------------------------------------------------------------
    # B. Akomodasi — backend
    # ------------------------------------------------------------------

    def test_accommodation_row_created_from_accommodation_tab(self):
        request = self.make_request()

        response = self.api("post", ARRANGEMENTS, self.stay_payload(request))
        self.assertEqual(response.status_code, 201, response.content)

        row = TravelArrangement.objects.get(pk=_record(response)["id"])
        self.assertEqual(row.request, request)
        # Departure Date = hari check-in.
        self.assertEqual(row.travel_start_date, date(2026, 10, 11))
        self.assertEqual(row.accommodation_nights, 1)
        self.assertTrue(row.accommodation_needed)
        self.assertEqual(row.sequence, 1)

    def test_multiple_accommodation_rows(self):
        request = self.make_request()

        first = self.api("post", ARRANGEMENTS, self.stay_payload(request))
        second = self.api(
            "post",
            ARRANGEMENTS,
            self.stay_payload(
                request,
                origin="Ternate",
                destination="Makassar",
                accommodation_name="Hotel Makassar",
                accommodation_checkin="2026-10-12",
                accommodation_checkout="2026-10-14",
            ),
        )

        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(second.status_code, 201, second.content)

        rows = TravelArrangement.objects.filter(
            request=request,
            is_deleted=False,
            accommodation_needed=True,
        ).order_by("sequence")

        self.assertEqual(
            [(r.sequence, r.accommodation_nights) for r in rows],
            [(1, 1), (2, 2)],
        )

    def test_accommodation_row_requires_a_date(self):
        request = self.make_request()

        response = self.api(
            "post",
            ARRANGEMENTS,
            self.stay_payload(
                request,
                accommodation_checkin=None,
                accommodation_checkout=None,
                accommodation_name="",
            ),
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("travel_start_date", response.content.decode())

    def test_travel_leg_without_hotel_still_allowed(self):
        """Hotel opsional — etape biasa tanpa akomodasi tetap sah."""
        request = self.make_request()

        response = self.api(
            "post",
            ARRANGEMENTS,
            {
                "request": request.pk,
                "direction": "out",
                "travel_start_date": "2026-10-11",
            },
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertFalse(
            TravelArrangement.objects.get(
                pk=_record(response)["id"],
            ).accommodation_needed,
        )

    def test_update_recomputes_nights(self):
        request = self.make_request()
        created = self.api("post", ARRANGEMENTS, self.stay_payload(request))
        row_id = _record(created)["id"]

        response = self.api(
            "patch",
            f"{ARRANGEMENTS}{row_id}/",
            {
                "accommodation_checkout": "2026-10-14",
                # Nilai basi yang dibawa baris grid — tidak dipercaya.
                "accommodation_nights": 1,
            },
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            TravelArrangement.objects.get(pk=row_id).accommodation_nights,
            3,
        )

    def test_clearing_accommodation_on_existing_leg(self):
        request = self.make_request()
        created = self.api("post", ARRANGEMENTS, self.stay_payload(request))
        row = _record(created)

        # Seluruh isi baris dikirim balik, termasuk penanda lamanya.
        row.update(
            {
                "accommodation_type": None,
                "accommodation_name": "",
                "accommodation_checkin": None,
                "accommodation_checkout": None,
                "accommodation_needed": True,
            },
        )

        response = self.api("put", f"{ARRANGEMENTS}{row['id']}/", row)

        self.assertEqual(response.status_code, 200, response.content)

        leg = TravelArrangement.objects.get(pk=row["id"])
        self.assertFalse(leg.accommodation_needed)
        self.assertIsNone(leg.accommodation_nights)
        # Etapenya sendiri tetap ada.
        self.assertFalse(leg.is_deleted)

    def test_delete_accommodation_row(self):
        request = self.make_request()
        created = self.api("post", ARRANGEMENTS, self.stay_payload(request))
        row_id = _record(created)["id"]

        response = self.api("delete", f"{ARRANGEMENTS}{row_id}/")

        self.assertIn(response.status_code, (200, 204), response.content)
        self.assertTrue(
            TravelArrangement.all_objects.get(pk=row_id).is_deleted
            if hasattr(TravelArrangement, "all_objects")
            else TravelArrangement.objects.get(pk=row_id).is_deleted,
        )

    def test_checkout_before_checkin_rejected(self):
        request = self.make_request()

        response = self.api(
            "post",
            ARRANGEMENTS,
            self.stay_payload(
                request,
                accommodation_checkin="2026-10-12",
                accommodation_checkout="2026-10-11",
            ),
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("accommodation_checkout", response.content.decode())

    def test_locked_document_cannot_mutate_accommodation(self):
        request = self.make_request()
        created = self.api("post", ARRANGEMENTS, self.stay_payload(request))
        row_id = _record(created)["id"]

        for status in (
            TravelRequestStatus.SUBMITTED,
            TravelRequestStatus.APPROVED,
            TravelRequestStatus.CANCELLED,
        ):
            with self.subTest(status=status):
                self.with_status(request, status)

                add = self.api(
                    "post",
                    ARRANGEMENTS,
                    self.stay_payload(request, accommodation_name="Lain"),
                )
                edit = self.api(
                    "patch",
                    f"{ARRANGEMENTS}{row_id}/",
                    {"accommodation_name": "Diganti"},
                )
                remove = self.api("delete", f"{ARRANGEMENTS}{row_id}/")

                self.assertEqual(add.status_code, 400, add.content)
                self.assertEqual(edit.status_code, 400, edit.content)
                self.assertEqual(remove.status_code, 400, remove.content)

        leg = TravelArrangement.objects.get(pk=row_id)
        self.assertEqual(leg.accommodation_name, "Hotel Bela Ternate")
        self.assertFalse(leg.is_deleted)

    def test_row_cannot_move_to_another_request(self):
        mine = self.make_request()
        other = self.make_request()
        created = self.api("post", ARRANGEMENTS, self.stay_payload(mine))
        row_id = _record(created)["id"]

        response = self.api(
            "patch",
            f"{ARRANGEMENTS}{row_id}/",
            {"request": other.pk},
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(
            TravelArrangement.objects.get(pk=row_id).request_id,
            mine.pk,
        )

    def test_scope_limits_accommodation_rows(self):
        user = self.scoped_user(self.site)

        own_site = self.make_request()
        elsewhere = self.make_request()
        elsewhere.location = self.other_site
        elsewhere.save(update_fields=["location"])

        # Baris yang sudah ada di dokumen luar cakupan.
        foreign_leg = TravelArrangementService.create(
            data={
                "request": elsewhere,
                "direction": "out",
                "travel_start_date": date(2026, 10, 11),
                "accommodation_name": "Hotel Rahasia",
                "accommodation_checkin": date(2026, 10, 11),
                "accommodation_checkout": date(2026, 10, 12),
            },
        )

        allowed = self.api(
            "post", ARRANGEMENTS, self.stay_payload(own_site), user=user,
        )
        self.assertEqual(allowed.status_code, 201, allowed.content)

        denied = self.api(
            "post", ARRANGEMENTS, self.stay_payload(elsewhere), user=user,
        )
        self.assertEqual(denied.status_code, 400, denied.content)
        self.assertIn("cakupan", denied.content.decode())

        listed = self.api(
            "get", f"{ARRANGEMENTS}?request={elsewhere.pk}", user=user,
        )
        self.assertEqual(listed.status_code, 200, listed.content)
        self.assertEqual(_rows(listed.json()), [])

        edit = self.api(
            "patch",
            f"{ARRANGEMENTS}{foreign_leg.pk}/",
            {"accommodation_name": "Dibobol"},
            user=user,
        )
        self.assertEqual(edit.status_code, 404, edit.content)

        foreign_leg.refresh_from_db()
        self.assertEqual(foreign_leg.accommodation_name, "Hotel Rahasia")

    # ------------------------------------------------------------------
    # C. Kontrak schema tab Accommodation
    # ------------------------------------------------------------------

    def test_accommodation_tab_offers_add_row_and_stays_locked_when_final(self):
        tab = next(
            t for t in TRAVEL_REQUEST_TABS if t["key"] == "accommodation"
        )

        self.assertNotEqual(tab.get("create"), False)
        self.assertTrue(tab["inline"])
        self.assertEqual(
            tab["readonly_when"],
            {"field": "is_editable", "op": "is_false"},
        )

        travels = next(t for t in TRAVEL_REQUEST_TABS if t["key"] == "travels")
        self.assertEqual(travels["endpoint"], tab["endpoint"])

        for key in ("direction", "sequence", "origin", "destination"):
            self.assertFalse(
                ACCOMMODATION_GRID_FIELDS[key].get("disabled", False),
                key,
            )

        self.assertEqual(
            list(ACCOMMODATION_GRID_FIELDS),
            [
                "direction",
                "sequence",
                "origin",
                "destination",
                "accommodation_type",
                "accommodation_name",
                "accommodation_checkin",
                "accommodation_checkout",
                "accommodation_nights",
                "notes",
            ],
        )
