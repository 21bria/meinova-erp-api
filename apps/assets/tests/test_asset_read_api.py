"""
ASSET-6 — read model operasional (custody saat ini, riwayat custody,
riwayat kondisi, dokumen terkait) dan kapabilitas aksi per record.

Yang dikunci:

* custody saat ini terstruktur dari baris `AssetCustody` terbuka —
  pemegang, lokasi, sejak kapan, dan dokumen pembukanya;
* riwayat custody/kondisi dari tabel kanonik, terbaru dulu, tanpa jalur
  tulis;
* riwayat tunduk pada visibilitas aset: izin baca, cakupan data,
  isolasi company penerima lintas company, dan soft delete;
* dokumen terkait lewat filter `?asset=` pada endpoint dokumen yang ada;
* kapabilitas (`can_*`, `approval.can_act`) dihitung dengan jalur yang sama
  dengan penegakannya — termasuk wewenang per sisi Transfer/Return.
"""

from __future__ import annotations

import json

from django.test import override_settings
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.assets.models import AssetCondition, CustodyType
from apps.assets.services import (
    AssetAssignmentService,
    AssetReturnService,
    AssetService,
    AssetTransferService,
)

from .base import AssetsTestCase


ASSETS = "/api/assets/assets/"

VIEW_ALL = (
    "view_asset",
    "view_assetassignment",
    "view_assetreturn",
    "view_assettransfer",
)


@override_settings(
    ENFORCE_MODEL_PERMISSIONS=True,
    ENFORCE_VIEW_PERMISSIONS=True,
)
class ReadApiTestCase(AssetsTestCase):
    @classmethod
    def build_baseline(cls):
        super().build_baseline()

        cls.loc_a3 = cls._location(cls.company_a, "AST-A-THIRD", "A Third Site")

    def setUp(self):
        super().setUp()

        self.http = TenantClient(self.tenant)

    def call(self, method, path, user, payload=None):
        token = RefreshToken.for_user(user).access_token

        kwargs = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        if payload is not None:
            kwargs["data"] = json.dumps(payload)
            kwargs["content_type"] = "application/json"

        return getattr(self.http, method)(path, **kwargs)

    def get_data(self, path, user):
        response = self.call("get", path, user)
        self.assertEqual(response.status_code, 200, response.content[:500])

        body = json.loads(response.content)

        # Daftar dan aksi dibungkus `{data, meta, status_code}`; `retrieve`
        # bawaan mengembalikan record polos.
        if isinstance(body, dict) and "status_code" in body and "data" in body:
            return body["data"]

        return body

    def full_cycle(self):
        """Register → STORAGE → Assignment → Transfer → Return → STORAGE."""
        asset = self.make_active_asset()
        first = self.make_employee()
        second = self.make_employee()

        assignment = AssetAssignmentService.create(data={
            "asset": asset,
            "target_custody_type": CustodyType.EMPLOYEE,
            "employee": first,
            "location": self.loc_a1,
        })
        AssetAssignmentService.submit(assignment=assignment)
        AssetAssignmentService.complete(assignment=assignment)

        transfer = self.make_transfer(asset, target_employee=second, location=self.loc_a2)
        AssetTransferService.submit(transfer=transfer)
        AssetTransferService.complete(transfer=transfer, condition=AssetCondition.FAIR)

        asset_return = self.make_return(asset, destination=self.loc_a1)
        AssetReturnService.submit(asset_return=asset_return)
        AssetReturnService.complete(
            asset_return=asset_return,
            condition=AssetCondition.DAMAGED,
            note="layar retak",
        )

        asset.refresh_from_db()

        return asset, assignment, transfer, asset_return


# ======================================================================
# Custody saat ini
# ======================================================================


class CurrentCustodyTests(ReadApiTestCase):
    def test_storage_custody_after_activation(self):
        viewer = self.make_user(permissions=VIEW_ALL)
        asset = self.make_active_asset()

        data = self.get_data(f"{ASSETS}{asset.pk}/", viewer)
        custody = data["current_custody_detail"]

        self.assertEqual(custody["custody_type"], CustodyType.STORAGE)
        self.assertEqual(custody["holder"], "Storage")
        self.assertEqual(custody["location"], self.loc_a1.pk)
        self.assertEqual(custody["location_name"], self.loc_a1.name)
        self.assertTrue(custody["is_current"])
        self.assertIsNone(custody["ended_on"])
        self.assertEqual(custody["opened_by"]["type"], "registration")
        self.assertIsNone(custody["opened_by"]["route"])
        self.assertEqual(data["custody_holder"], "Storage")

    def test_employee_and_organization_custody_are_structured(self):
        viewer = self.make_user(permissions=VIEW_ALL)
        employee = self.make_employee()
        asset = self.hand_over(self.make_active_asset(), employee)

        custody = self.get_data(f"{ASSETS}{asset.pk}/", viewer)["current_custody_detail"]

        self.assertEqual(custody["custody_type"], CustodyType.EMPLOYEE)
        self.assertEqual(custody["employee"], employee.pk)
        self.assertEqual(custody["employee_name"], str(employee))
        self.assertIsNone(custody["department"])
        self.assertEqual(custody["opened_by"]["type_label"], "Assignment")
        self.assertTrue(custody["opened_by"]["document_number"].startswith("AAS"))
        self.assertEqual(
            custody["opened_by"]["route"],
            f"/assets/assignments/{custody['opened_by']['document_id']}",
        )

        pic = self.make_employee()
        lv = self.hand_to_department(self.make_active_asset(), self.dept_a_mining, pic=pic)

        data = self.get_data(f"{ASSETS}{lv.pk}/", viewer)
        custody = data["current_custody_detail"]

        self.assertEqual(custody["custody_type"], CustodyType.ORGANIZATION)
        self.assertEqual(custody["department_name"], self.dept_a_mining.name)
        self.assertEqual(custody["pic_employee_name"], str(pic))
        self.assertIsNone(custody["employee"])
        self.assertEqual(data["custody_holder"], f"{self.dept_a_mining.name} (PIC: {pic})")

    def test_draft_asset_has_no_custody(self):
        viewer = self.make_user(permissions=VIEW_ALL)
        draft = self.make_asset()

        data = self.get_data(f"{ASSETS}{draft.pk}/", viewer)

        self.assertIsNone(data["current_custody_detail"])
        self.assertIsNone(data["custody_holder"])

    def test_list_carries_holder_but_no_per_row_extras(self):
        viewer = self.make_user(permissions=VIEW_ALL)
        employee = self.make_employee()
        asset = self.hand_over(self.make_active_asset(), employee)

        rows = self.get_data(f"{ASSETS}?page_size=500", viewer)
        row = next(item for item in rows if item["id"] == asset.pk)

        self.assertEqual(row["custody_holder"], str(employee))
        # Dokumen pembuka dan kapabilitas hanya di layar detail.
        self.assertIsNone(row["current_custody_detail"]["opened_by"])
        self.assertNotIn("can_edit", row)
        self.assertNotIn("can_activate", row)


# ======================================================================
# Riwayat custody & kondisi
# ======================================================================


class HistoryTests(ReadApiTestCase):
    def test_custody_history_is_canonical_newest_first(self):
        viewer = self.make_user(permissions=VIEW_ALL)
        asset, assignment, transfer, asset_return = self.full_cycle()

        response = self.call("get", f"{ASSETS}{asset.pk}/custody-history/", viewer)
        self.assertEqual(response.status_code, 200, response.content[:500])

        body = json.loads(response.content)
        rows = body["data"]

        self.assertEqual(body["meta"]["count"], 4)
        self.assertEqual(
            [row["custody_type"] for row in rows],
            [
                CustodyType.STORAGE,
                CustodyType.EMPLOYEE,
                CustodyType.EMPLOYEE,
                CustodyType.STORAGE,
            ],
        )
        self.assertEqual([row["is_current"] for row in rows], [True, False, False, False])
        self.assertEqual(rows[0]["id"], asset.current_custody_id)

        # Provenance: pembuka/penutup tiap periode = dokumennya.
        self.assertEqual(rows[0]["opened_by"]["document_number"], asset_return.document_number)
        self.assertEqual(rows[0]["opened_by"]["route"], f"/assets/returns/{asset_return.pk}")
        self.assertIsNone(rows[0]["closed_by"])
        self.assertEqual(rows[1]["opened_by"]["route"], f"/assets/transfers/{transfer.pk}")
        self.assertEqual(rows[1]["closed_by"]["document_number"], asset_return.document_number)
        self.assertEqual(rows[2]["opened_by"]["document_number"], assignment.document_number)
        self.assertEqual(rows[3]["opened_by"]["type"], "registration")

        self.assertEqual(rows[1]["location_name"], self.loc_a2.name)
        self.assertEqual(rows[1]["start_condition"], AssetCondition.FAIR)
        self.assertEqual(rows[1]["end_condition"], AssetCondition.DAMAGED)

    def test_condition_history_newest_first(self):
        viewer = self.make_user(permissions=VIEW_ALL)
        asset, *_ = self.full_cycle()

        rows = self.get_data(f"{ASSETS}{asset.pk}/condition-history/", viewer)

        self.assertEqual(
            [row["source"] for row in rows],
            ["RETURN", "TRANSFER", "REGISTRATION"],
        )
        self.assertEqual(rows[0]["previous_condition"], AssetCondition.FAIR)
        self.assertEqual(rows[0]["new_condition"], AssetCondition.DAMAGED)
        self.assertEqual(rows[0]["new_condition_label"], "Damaged")
        self.assertEqual(rows[0]["source_label"], "Return")
        self.assertEqual(rows[0]["note"], "layar retak")
        self.assertIn("effective_at", rows[0])
        self.assertNotIn("source_id", rows[0])

    def test_recorded_by_is_human_readable(self):
        clerk = self.make_user(permissions=(*VIEW_ALL, "change_asset"))
        asset = self.make_active_asset()

        AssetService.record_condition(asset=asset, condition=AssetCondition.FAIR, user=clerk)

        rows = self.get_data(f"{ASSETS}{asset.pk}/condition-history/", clerk)

        self.assertEqual(rows[0]["recorded_by"], clerk.pk)
        self.assertEqual(rows[0]["recorded_by_name"], clerk.get_username())

    def test_history_endpoints_are_read_only(self):
        clerk = self.make_user(permissions=(*VIEW_ALL, "change_asset"))
        asset = self.make_active_asset()

        for path in ("custody-history", "condition-history"):
            for method in ("post", "patch", "delete"):
                with self.subTest(path=path, method=method):
                    response = self.call(method, f"{ASSETS}{asset.pk}/{path}/", clerk, {})
                    self.assertEqual(response.status_code, 405)


# ======================================================================
# Keamanan baca
# ======================================================================


class HistorySecurityTests(ReadApiTestCase):
    def paths(self, asset):
        return [
            f"{ASSETS}{asset.pk}/",
            f"{ASSETS}{asset.pk}/custody-history/",
            f"{ASSETS}{asset.pk}/condition-history/",
        ]

    def test_no_view_permission_no_history(self):
        asset = self.make_active_asset()
        nobody = self.make_user()

        for path in self.paths(asset):
            with self.subTest(path=path):
                self.assertIn(self.call("get", path, nobody).status_code, (403, 404))

    def test_location_scope_applies_to_history(self):
        asset = self.make_active_asset()  # STORAGE di A1

        site_viewer = self.make_user(
            permissions=VIEW_ALL,
            authorities=[("location", self.loc_a2.pk)],
        )
        ho_viewer = self.make_user(
            permissions=VIEW_ALL,
            authorities=[("location", self.loc_a1.pk)],
        )

        for path in self.paths(asset):
            with self.subTest(path=path):
                self.assertEqual(self.call("get", path, site_viewer).status_code, 404)
                self.assertEqual(self.call("get", path, ho_viewer).status_code, 200)

    def test_cross_company_recipient_admin_cannot_read_owner_history(self):
        outsider = self.make_employee(company=self.company_b)
        asset = self.hand_over(
            self.make_active_asset(),
            outsider,
            cross_company_reason="Pinjam holding",
        )

        recipient_admin = self.make_user(
            permissions=VIEW_ALL,
            authorities=[("company", self.company_b.pk)],
        )

        for path in self.paths(asset):
            with self.subTest(path=path):
                self.assertEqual(self.call("get", path, recipient_admin).status_code, 404)

    def test_soft_deleted_asset_has_no_history(self):
        viewer = self.make_user(permissions=VIEW_ALL)
        draft = self.make_asset()
        AssetService.soft_delete(instance=draft)

        for path in self.paths(draft):
            with self.subTest(path=path):
                self.assertEqual(self.call("get", path, viewer).status_code, 404)


# ======================================================================
# Dokumen terkait
# ======================================================================


class RelatedDocumentTests(ReadApiTestCase):
    def test_documents_filter_by_asset(self):
        viewer = self.make_user(permissions=VIEW_ALL)
        asset, assignment, transfer, asset_return = self.full_cycle()
        other, other_assignment, other_transfer, other_return = self.full_cycle()

        for endpoint, mine, theirs in (
            ("/api/assets/assignments/", assignment, other_assignment),
            ("/api/assets/transfers/", transfer, other_transfer),
            ("/api/assets/returns/", asset_return, other_return),
        ):
            with self.subTest(endpoint=endpoint):
                rows = self.get_data(f"{endpoint}?asset={asset.pk}&page_size=50", viewer)
                ids = {row["id"] for row in rows}

                self.assertIn(mine.pk, ids)
                self.assertNotIn(theirs.pk, ids)
                self.assertTrue(all(row["asset"] == asset.pk for row in rows))

    def test_related_documents_keep_their_own_scope(self):
        # Assignment di-scope sisi pemilik (lokasi asal). Penonton yang
        # hanya berwenang di lokasi lain tidak mendapat dokumennya lewat
        # filter `asset`.
        asset = self.hand_over(self.make_active_asset())
        stranger = self.make_user(
            permissions=VIEW_ALL,
            authorities=[("location", self.loc_a3.pk)],
        )

        rows = self.get_data(f"/api/assets/assignments/?asset={asset.pk}", stranger)
        self.assertEqual(rows, [])


# ======================================================================
# Kapabilitas aksi
# ======================================================================


class CapabilityTests(ReadApiTestCase):
    TRANSFER_ALL = (
        "view_assettransfer",
        "add_assettransfer",
        "change_assettransfer",
        "delete_assettransfer",
        "submit_assettransfer",
        "complete_assettransfer",
        "cancel_assettransfer",
        "view_asset",
    )

    def admin(self, location, permissions=TRANSFER_ALL):
        return self.make_user(
            permissions=permissions,
            authorities=[("location", location.pk)],
        )

    def test_transfer_capabilities_follow_the_sides(self):
        asset = self.hand_over(self.make_active_asset(), location=self.loc_a2)
        transfer = self.make_transfer(
            asset,
            target_employee=self.make_employee(),
            location=self.loc_a1,
        )

        source_admin = self.admin(self.loc_a2)
        target_admin = self.admin(self.loc_a1)
        path = f"/api/assets/transfers/{transfer.pk}/"

        draft_source = self.get_data(path, source_admin)
        draft_target = self.get_data(path, target_admin)

        self.assertTrue(draft_source["can_submit"])
        self.assertTrue(draft_source["can_edit"])
        self.assertTrue(draft_source["can_delete"])
        self.assertFalse(draft_target["can_submit"])
        self.assertFalse(draft_target["can_edit"])
        self.assertFalse(draft_target["can_complete"])

        AssetTransferService.submit(transfer=transfer)  # → APPROVED tanpa alur

        approved_source = self.get_data(path, source_admin)
        approved_target = self.get_data(path, target_admin)

        self.assertFalse(approved_source["can_submit"])
        self.assertFalse(approved_source["can_edit"])
        self.assertTrue(approved_source["can_cancel"])
        self.assertFalse(approved_source["can_complete"])
        self.assertTrue(approved_target["can_complete"])
        self.assertFalse(approved_target["can_cancel"])

        # Kapabilitas sama dengan penegakan: yang dijawab "tidak" memang 404.
        response = self.call("post", f"{path}complete/", source_admin, {"condition": "GOOD"})
        self.assertEqual(response.status_code, 404)

    def test_return_complete_is_destination_only(self):
        permissions = (
            "view_assetreturn",
            "submit_assetreturn",
            "complete_assetreturn",
            "cancel_assetreturn",
            "view_asset",
        )
        asset = self.hand_over(self.make_active_asset(), location=self.loc_a2)
        asset_return = self.make_return(asset, destination=self.loc_a1)
        AssetReturnService.submit(asset_return=asset_return)

        path = f"/api/assets/returns/{asset_return.pk}/"
        source = self.get_data(path, self.admin(self.loc_a2, permissions))
        destination = self.get_data(path, self.admin(self.loc_a1, permissions))

        self.assertFalse(source["can_complete"])
        self.assertTrue(source["can_cancel"])
        self.assertTrue(destination["can_complete"])

    def test_permission_without_scope_is_not_a_capability(self):
        asset = self.hand_over(self.make_active_asset())
        transfer = self.make_transfer(asset, target_employee=self.make_employee())

        viewer_only = self.make_user(permissions=("view_assettransfer", "view_asset"))
        data = self.get_data(f"/api/assets/transfers/{transfer.pk}/", viewer_only)

        for name in ("can_edit", "can_delete", "can_submit", "can_cancel", "can_complete"):
            with self.subTest(name=name):
                self.assertFalse(data[name])

    def test_asset_capabilities(self):
        clerk = self.make_user(permissions=("view_asset", "change_asset", "delete_asset"))
        viewer = self.make_user(permissions=("view_asset",))

        draft = self.make_asset()
        active = self.make_active_asset()

        draft_clerk = self.get_data(f"{ASSETS}{draft.pk}/", clerk)
        active_clerk = self.get_data(f"{ASSETS}{active.pk}/", clerk)
        draft_viewer = self.get_data(f"{ASSETS}{draft.pk}/", viewer)

        self.assertTrue(draft_clerk["can_activate"])
        self.assertTrue(draft_clerk["can_delete"])
        self.assertFalse(draft_clerk["can_record_condition"])
        self.assertFalse(active_clerk["can_activate"])
        self.assertFalse(active_clerk["can_delete"])
        self.assertTrue(active_clerk["can_record_condition"])
        self.assertFalse(draft_viewer["can_activate"])
        self.assertFalse(draft_viewer["can_edit"])

    def test_approval_block_answers_who_may_decide(self):
        approver = self.make_user(permissions=VIEW_ALL)
        self.make_workflow(approver=approver, document_type="asset_transfer")

        holder_user = self.make_user(permissions=VIEW_ALL)
        holder = self.make_employee(user=holder_user)
        transfer = self.make_transfer(
            self.hand_over(self.make_active_asset(), holder),
            target_employee=self.make_employee(),
        )
        AssetTransferService.submit(transfer=transfer)

        path = f"/api/assets/transfers/{transfer.pk}/"

        as_approver = self.get_data(path, approver)["approval"]
        as_holder = self.get_data(path, holder_user)["approval"]

        self.assertTrue(as_approver["can_act"])
        self.assertEqual(len(as_approver["steps"]), 1)
        self.assertFalse(as_holder["can_act"])

    def test_document_without_workflow_has_no_approval_block(self):
        viewer = self.make_user(permissions=VIEW_ALL)
        transfer = self.make_transfer(
            self.hand_over(self.make_active_asset()),
            target_employee=self.make_employee(),
        )

        data = self.get_data(f"/api/assets/transfers/{transfer.pk}/", viewer)

        self.assertIsNone(data["approval"])


# ======================================================================
# Schema (kontrak ke generator frontend)
# ======================================================================


class WorkspaceSchemaTests(ReadApiTestCase):
    def schema(self, module):
        response = self.http.get(f"/api/framework/schema/{module}/")
        self.assertEqual(response.status_code, 200, response.content[:300])

        body = json.loads(response.content)

        return body.get("data", body)

    def test_operational_modules_are_workspaces(self):
        expected = {
            "assets/register": {
                "overview", "general", "placement", "acquisition",
                "custody_history", "condition_history", "documents",
            },
            "assets/assignments": {"summary", "general", "result"},
            "assets/returns": {"summary", "general", "source", "result"},
            "assets/transfers": {"summary", "general", "source", "result"},
        }

        for module, tab_keys in expected.items():
            with self.subTest(module=module):
                schema = self.schema(module)

                self.assertEqual(schema["ui"]["editor"], "workspace")
                self.assertEqual({tab["key"] for tab in schema["tabs"]}, tab_keys)

        self.assertEqual(self.schema("assets/categories")["ui"]["editor"], "dialog")

    def test_actions_are_driven_by_server_capabilities(self):
        expected = {
            "submit": {"can_submit": True},
            "approve": {"approval.can_act": True},
            "reject": {"approval.can_act": True},
            "complete": {"can_complete": True},
            "cancel": {"can_cancel": True},
        }

        for module in ("assets/assignments", "assets/returns", "assets/transfers"):
            actions = {item["key"]: item for item in self.schema(module)["actions"]}

            for key, condition in expected.items():
                with self.subTest(module=module, action=key):
                    self.assertEqual(actions[key]["visible_when"], condition)
