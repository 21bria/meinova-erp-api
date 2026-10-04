"""
BT-5 — kontrak tampilan Business Trip (schema + satu kolom serializer).

Yang dikunci: kolom daftar dan penyaring yang dipakai frontend hasil
generate, lampiran di tab form, `supersedes` di luar form selama belum
ada lookup per pegawai, teks tujuan untuk kolom daftar, dan opsi
`business_trip` di form presensi yang tidak bisa dipilih tangan.
Tidak ada aturan API, data, atau izin yang berubah.
"""

from __future__ import annotations

from types import SimpleNamespace

from django.test import SimpleTestCase
from django.test.client import RequestFactory

from apps.framework.introspection.schema import build_crud_schema
from apps.hr.api.attendance.schema.fields.general import (
    GENERAL_FIELDS as ATTENDANCE_GENERAL_FIELDS,
)
from apps.hr.api.business_trip.serializers import BusinessTripSerializer
from apps.hr.api.business_trip.views import BusinessTripViewSet


def _schema():
    return build_crud_schema(BusinessTripViewSet(), RequestFactory().get("/"))


class BusinessTripListContract(SimpleTestCase):
    def test_list_columns(self):
        fields = _schema()["fields"]

        self.assertEqual(
            {name for name, meta in fields.items() if meta.get("table")},
            {
                "document_number",
                "employee",
                "company",
                "destination_summary",
                "departure_datetime",
                "return_datetime",
                "purpose_category",
                "status",
            },
        )

    def test_filters_are_ones_the_viewset_filters(self):
        fields = _schema()["fields"]

        filtered = {name for name, meta in fields.items() if meta.get("filter")}

        self.assertTrue(filtered <= set(BusinessTripViewSet.filterset_fields))
        self.assertIn("company", filtered)
        self.assertIn("employee", filtered)
        self.assertIn("status", filtered)


class BusinessTripFormContract(SimpleTestCase):
    def test_attachment_has_its_own_tab(self):
        tabs = {tab["key"]: tab for tab in _schema()["tabs"]}

        self.assertEqual(tabs["attachments"]["fields"], ["attachment"])

    def test_supersedes_not_editable_until_a_lookup_exists(self):
        tabs = {tab["key"]: tab for tab in _schema()["tabs"]}

        self.assertNotIn("supersedes", tabs["trip"]["fields"])
        self.assertNotIn("supersede_type", tabs["trip"]["fields"])

    def test_snapshot_is_read_only(self):
        fields = _schema()["fields"]

        self.assertTrue(fields["company"].get("read_only"))


class DestinationSummaryTests(SimpleTestCase):
    def summary(self, **values):
        trip = SimpleNamespace(
            **{
                "destination_location": None,
                "destination_city": None,
                "destination_country": None,
                "destination_detail": "",
                **values,
            },
        )

        return BusinessTripSerializer().get_destination_summary(trip)

    def test_internal_location(self):
        self.assertEqual(
            self.summary(
                destination_location=SimpleNamespace(name="Gebe Site"),
                destination_detail="Kantor tambang",
            ),
            "Gebe Site — Kantor tambang",
        )

    def test_external_city_country(self):
        self.assertEqual(
            self.summary(
                destination_city=SimpleNamespace(name="Kendari"),
                destination_country=SimpleNamespace(name="Indonesia"),
            ),
            "Kendari, Indonesia",
        )

    def test_detail_only(self):
        self.assertEqual(self.summary(destination_detail="Hotel X"), "Hotel X")


class ManualAttendanceStatusContract(SimpleTestCase):
    def test_business_trip_is_not_selectable_but_still_listed(self):
        options = {
            option["value"]: option
            for option in ATTENDANCE_GENERAL_FIELDS["status"]["options"]
        }

        self.assertTrue(options["business_trip"].get("disabled"))
        self.assertFalse(options["present"].get("disabled", False))
