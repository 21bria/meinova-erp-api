"""
Meja HR pada alur izin kehadiran dicari **per lokasi**, bukan se-company.

Temuan UAT browser 8 Sep 2026 yang memunculkan berkas ini: izin Bimo
Nugroho (Jakarta Head Office) menerbitkan **dua** kotak tanda tangan di
meja HR — HR kantor pusat dan HR site — lalu yang site ditandai
`SKIPPED` begitu yang HO menyetujui. ANY-ONE-nya benar; yang salah satu
tingkat sebelumnya, karena HR site tidak pernah berwenang atas pegawai
kantor pusat sejak awal.

Yang membuat **satu** meja cukup untuk kantor pusat dan site sekaligus:
HR site dan HR kantor pusat memegang **kode role yang sama**
(`HR-ADMIN`), dan yang memisahkan keduanya penempatan organisasinya.
Jadi `approver_scope = location` menyaring ke orang yang tepat di kedua
sisi tanpa alur kedua dan tanpa role kedua — dan itu yang dikunci di
sini, karena "cukup satu alur" adalah bagian yang paling mudah hilang
saat seseorang menambahkan alur khusus site di kemudian hari.

Meja yang dicetak lalu dicoret bukan hal yang netral: ia menyatakan
"orang ini seharusnya menandatangani, tapi tidak jadi". Untuk HR site
pada dokumen pegawai kantor pusat itu keterangan yang salah. Karena itu
yang diuji bukan cuma "yang benar ikut", tapi **"yang salah tidak punya
baris sama sekali"**.
"""

from __future__ import annotations

import json

from datetime import time

from rest_framework.test import APIClient

from apps.hr.api.attendance_permission.services import (
    AttendancePermissionService,
)
from apps.hr.models import AttendancePermissionType
from apps.workflow.models import (
    ApprovalStatus,
    ApproverScope,
    InstanceStatus,
    WorkflowDefinition,
)

from .base import AttendancePermissionTestCase


class PermissionLocationScopeTestCase(AttendancePermissionTestCase):
    """
    Panggung dua lokasi: `head_office` dan `site`, keduanya sudah ada di
    `base.py`.

    Dua lokasi, bukan satu — seluruh pertanyaan di berkas ini menanyakan
    "yang mana dari dua", dan panggung berlokasi tunggal akan tetap hijau
    apa pun aturan penyaringannya.
    """

    def setUp(self):
        super().setUp()

        # Meja HR di dua lokasi, **role yang sama persis**. Kalau test
        # ini bisa hijau dengan dua kode role berbeda, ia tidak menguji
        # apa yang dimaksud.
        self.hr_head_office = self.make_employee(
            roles=["HR-ADMIN"],
            location=self.head_office,
        )

        self.hr_site = self.make_employee(
            roles=["HR-ADMIN"],
            location=self.site,
        )

    # ------------------------------------------------------------------
    # Pabrik
    # ------------------------------------------------------------------

    def submit_for(self, employee):
        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
        )

        workflow = AttendancePermissionService.submit(
            permission=permission,
            user=employee.user,
        )

        permission.refresh_from_db()

        return permission, workflow

    def api_client(self, user) -> APIClient:
        """
        Klien API yang benar-benar mendarat di schema tenant.

        `APIClient` bawaan mengirim `Host: testserver`, dan
        `TenantMainMiddleware` tidak mengenali nama itu — permintaannya
        dilayani dari schema **public**, tempat tabel tenant memang
        tidak ada. Gejalanya `relation "workflow_approval" does not
        exist`, yang terbaca seperti migration yang belum jalan padahal
        yang salah alamat host-nya.

        Lebih buruk lagi: transaksi yang pecah di tengah meninggalkan
        koneksi pada schema public, jadi **test berikutnya** ikut gagal
        dengan tabel yang berbeda-beda. Yang harus dibaca error
        pertamanya, bukan yang terakhir.
        """
        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

        client.force_authenticate(user=user)

        return client

    @staticmethod
    def hr_rows(workflow):
        """Baris keputusan meja HR (step #2), apa adanya."""
        return list(
            workflow.approvals
            .filter(sequence=2)
            .select_related("approver_employee")
            .order_by("id")
        )

    # ------------------------------------------------------------------
    # Konfigurasi
    # ------------------------------------------------------------------

    def test_seeded_flow_is_two_desks_and_the_hr_desk_is_per_location(self):
        """
        Alurnya dari seed sungguhan, bukan rantai yang disusun di test.

        Rantai yang disalin ke test akan tetap hijau sesudah seed-nya
        berubah, dan itu justru kebalikan dari yang dibutuhkan berkas
        ini — nilai `approver_scope` inilah yang sempat berbeda antara
        seed dan tenant `demo`.
        """
        definition = WorkflowDefinition.objects.get(
            code="HR-ATT-PERMISSION",
            is_deleted=False,
        )

        steps = list(definition.steps.filter(is_deleted=False).order_by("sequence"))

        self.assertEqual(len(steps), 2, "Izin kehadiran cukup dua meja.")

        self.assertEqual(steps[1].approver_scope, ApproverScope.LOCATION)

        self.assertEqual(steps[1].approver_role.code, "HR-ADMIN")

        self.assertTrue(steps[1].is_required)

    # ------------------------------------------------------------------
    # CASE 1 — pegawai kantor pusat
    # ------------------------------------------------------------------

    def test_head_office_document_reaches_only_the_head_office_hr(self):
        supervisor = self.make_employee(location=self.head_office)

        staff = self.make_employee(
            location=self.head_office,
            reports_to=supervisor,
        )

        _permission, workflow = self.submit_for(staff)

        rows = self.hr_rows(workflow)

        self.assertEqual(len(rows), 1)

        self.assertEqual(rows[0].approver_employee_id, self.hr_head_office.pk)

        # Atasan langsung tidak ikut berubah oleh cakupan meja HR.
        first = workflow.approvals.get(sequence=1)

        self.assertEqual(first.approver_employee_id, supervisor.pk)

    def test_site_hr_gets_no_row_at_all_for_a_head_office_document(self):
        """
        Bukan `SKIPPED` — **tidak ada barisnya**.

        Inilah pembeda antara perbaikan ini dan keadaan sebelumnya:
        dulu HR site tetap mendapat kotak tanda tangan lalu dicoret.
        """
        supervisor = self.make_employee(location=self.head_office)

        staff = self.make_employee(
            location=self.head_office,
            reports_to=supervisor,
        )

        _permission, workflow = self.submit_for(staff)

        self.assertFalse(
            workflow.approvals
            .filter(approver_employee=self.hr_site)
            .exists(),
        )

    # ------------------------------------------------------------------
    # CASE 2 — pegawai site
    # ------------------------------------------------------------------

    def test_site_document_reaches_only_the_site_hr(self):
        supervisor = self.make_employee(location=self.site)

        staff = self.make_employee(
            location=self.site,
            reports_to=supervisor,
        )

        _permission, workflow = self.submit_for(staff)

        rows = self.hr_rows(workflow)

        self.assertEqual(len(rows), 1)

        self.assertEqual(rows[0].approver_employee_id, self.hr_site.pk)

        self.assertFalse(
            workflow.approvals
            .filter(approver_employee=self.hr_head_office)
            .exists(),
        )

    # ------------------------------------------------------------------
    # CASE 3 — ANY-ONE tidak berubah
    # ------------------------------------------------------------------

    def test_two_hr_at_the_same_location_both_get_a_row(self):
        second_hr = self.make_employee(
            roles=["HR-ADMIN"],
            location=self.head_office,
        )

        supervisor = self.make_employee(location=self.head_office)

        staff = self.make_employee(
            location=self.head_office,
            reports_to=supervisor,
        )

        _permission, workflow = self.submit_for(staff)

        approvers = {row.approver_employee_id for row in self.hr_rows(workflow)}

        self.assertEqual(approvers, {self.hr_head_office.pk, second_hr.pk})

    def test_one_approves_and_the_other_is_skipped_once(self):
        """
        ANY-ONE apa adanya: satu menyetujui, sisanya `SKIPPED`, mejanya
        selesai, dan alurnya maju **satu kali** — bukan dua.
        """
        second_hr = self.make_employee(
            roles=["HR-ADMIN"],
            location=self.head_office,
        )

        supervisor = self.make_employee(location=self.head_office)

        staff = self.make_employee(
            location=self.head_office,
            reports_to=supervisor,
        )

        permission, workflow = self.submit_for(staff)

        AttendancePermissionService.decide(
            permission=permission,
            approved=True,
            user=supervisor.user,
        )

        AttendancePermissionService.decide(
            permission=permission,
            approved=True,
            user=self.hr_head_office.user,
        )

        workflow.refresh_from_db()

        winner = workflow.approvals.get(
            sequence=2,
            approver_employee=self.hr_head_office,
        )

        loser = workflow.approvals.get(
            sequence=2,
            approver_employee=second_hr,
        )

        self.assertEqual(winner.status, ApprovalStatus.APPROVED)

        self.assertEqual(loser.status, ApprovalStatus.SKIPPED)

        self.assertEqual(workflow.status, InstanceStatus.APPROVED)

    # ------------------------------------------------------------------
    # CASE 4 — wewenang ditegakkan di server
    # ------------------------------------------------------------------

    def test_out_of_scope_hr_cannot_approve_through_the_api(self):
        """
        HR site menebak id baris keputusan dokumen pegawai kantor pusat.

        Yang menjaganya bukan tombol yang disembunyikan: barisnya
        memang **tidak pernah dibuat** untuknya, jadi tidak ada id yang
        bisa ia pakai — dan baris milik orang lain ditolak
        `check_right()`.
        """
        supervisor = self.make_employee(location=self.head_office)

        staff = self.make_employee(
            location=self.head_office,
            reports_to=supervisor,
        )

        permission, workflow = self.submit_for(staff)

        AttendancePermissionService.decide(
            permission=permission,
            approved=True,
            user=supervisor.user,
        )

        row = workflow.approvals.get(sequence=2)

        response = self.api_client(self.hr_site.user).post(
            f"/api/workflow/approvals/{row.pk}/approve/",
            {"comment": ""},
            format="json",
        )

        # Kontrak yang memang berlaku hari ini: `check_right()` gagal →
        # `ValidationError({"workflow": alasan})` → **400**, bukan 403.
        # Status kodenya diperiksa bersama kunci `workflow`, karena 400
        # telanjang juga bisa datang dari serializer yang menolak
        # payload — dan test keamanan yang puas dengan "pokoknya
        # ditolak" akan tetap hijau kalau suatu saat penolakannya
        # datang dari sebab yang sama sekali lain.
        self.assertEqual(response.status_code, 400, response.content[:300])

        body = response.json()

        self.assertIn(
            "workflow",
            json.dumps(body),
            msg=f"Penolakannya bukan dari check_right(): {body}",
        )

        row.refresh_from_db()

        self.assertEqual(row.status, ApprovalStatus.PENDING)

        # Dan alurnya tidak bergerak: dokumen tetap menunggu meja HR
        # yang benar.
        self.assertEqual(
            workflow.approvals.get(sequence=2).status,
            ApprovalStatus.PENDING,
        )

    def test_the_rightful_hr_can_approve_through_the_same_endpoint(self):
        """
        Pasangan test di atas.

        Tanpa ini, penolakan 403 bisa saja datang dari rute yang salah
        atau serializer yang menolak semua orang — dan test keamanannya
        akan tetap hijau tanpa membuktikan apa pun.
        """
        supervisor = self.make_employee(location=self.head_office)

        staff = self.make_employee(
            location=self.head_office,
            reports_to=supervisor,
        )

        permission, workflow = self.submit_for(staff)

        AttendancePermissionService.decide(
            permission=permission,
            approved=True,
            user=supervisor.user,
        )

        row = workflow.approvals.get(sequence=2)

        response = self.api_client(self.hr_head_office.user).post(
            f"/api/workflow/approvals/{row.pk}/approve/",
            {"comment": ""},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content[:400])

        row.refresh_from_db()

        self.assertEqual(row.status, ApprovalStatus.APPROVED)
