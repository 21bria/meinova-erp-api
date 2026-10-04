"""
Status cuti bukan isian formulir, dan hak baca bukan hak tulis.

Dua lubang yang ditutup berkas ini, keduanya terbukti di tenant demo
17 Sep 2026 lewat probe yang di-rollback:

1. **Status bisa dipilih bebas.** `POST /api/hr/leaves/` menerima
   `"status": "approved"`, dan `after_create` langsung memotong saldo —
   jadi setiap pemegang `hr.add_employeeleave` (role EMPLOYEE hasil seed
   memilikinya) bisa membuat cutinya sendiri jadi sah tanpa satu tanda
   tangan pun. PATCH draft -> approved juga 200.
2. **Cakupan ubah/hapus dihitung dari izin baca.** Untuk resource yang
   bacanya tidak dijaga, izin yang dikirim ke `DataScopeService` adalah
   `None`, dan `None` berarti gabungan seluruh penugasan. Farah
   (EMPLOYEE `own` + FINANCE-MANAGER se-company) karena itu bisa
   menyetujui dan menghapus cuti 45 orang lain.

Yang **tidak** ikut diuji di sini karena sudah punya rumahnya sendiri:
identitas pengajuan pribadi (`apps.self_service.tests.test_requests`)
dan kotak masuk approval (`test_leave_access_control`).

Satu catatan yang harus ikut dibaca bersama hasil hijaunya:
penegakan cakupan tulis **bergantung pada `ROLE_AWARE_DATA_SCOPE`**.
Dua test terakhir mengunci apa yang terjadi saat saklarnya mati — bukan
karena itu benar, melainkan supaya keadaannya tercatat dan tidak bisa
berubah tanpa ada yang tahu.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import override_settings

from apps.accounts.models import AuthorityMode, Role
from apps.accounts.services.role_assignment import grant_role
from apps.administration.models import Location
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.models import Employee, EmployeeLeave, LeaveStatus
from apps.uploads.services.access_service import FileAccessService
from apps.workflow.models import WorkflowInstance

from .test_leave_access_control import (
    LEAVES,
    MONDAY,
    TUESDAY,
    LeaveAccessTestBase,
)


RECORD_PERMISSION = "record_employeeleave"


class LeaveWriteGovernanceBase(LeaveAccessTestBase):
    """
    Pemeran tambahan di atas fixture `test_leave_access_control`.

    * **Farah** (`supervisor`) mendapat role kedua bercakupan seluruh
      company yang isinya **izin baca saja** — persis bentuk
      FINANCE-MANAGER di tenant demo. Ia yang membuktikan hak baca tidak
      lagi melebarkan hak ubah.
    * **Sarah** (`hr_manager`) mendapat kemampuan pencatatan
      (`hr.record_employeeleave`), jadi jalur administratif tetap ada
      pemakainya yang sah.
    * **Rudi** admin site, cakupannya satu lokasi lewat kewenangan
      `explicit` — ia yang membuktikan penyempitan ini berhenti di batas
      unitnya, bukan di "semua atau tidak sama sekali".
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Kemampuan pencatatan administratif. Sengaja **hanya** ke role
        # HR: kalau ia ikut ke role EMPLOYEE, seluruh perbaikan ini
        # kembali ke titik awal lewat pintu yang namanya berbeda.
        cls.record_permission = Permission.objects.get(
            content_type__app_label="hr",
            codename=RECORD_PERMISSION,
        )

        cls.hr_role.permissions.add(cls.record_permission)

        # Role "banyak membaca, sedikit menulis".
        cls.reader_role = Role.objects.create(
            code="LAC-READER",
            name="Finance Reader",
        )

        cls.reader_role.permissions.set(
            Permission.objects.filter(
                content_type__app_label="hr",
                codename__in=["view_employee", "view_employeeleave"],
            )
        )

        grant_role(
            cls.supervisor.user,
            cls.reader_role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("company", cls.company.pk)],
        )

        # Lokasi kedua + penghuninya, untuk membuktikan batas unit.
        cls.site = Location.objects.create(
            company=cls.company,
            code="LAC-SITE",
            name="Site Gebe",
        )

        cls.site_admin_role = Role.objects.create(
            code="LAC-ADMIN-SITE",
            name="Admin Site",
        )

        cls.site_admin_role.permissions.set(
            Permission.objects.filter(
                content_type__app_label="hr",
                codename__in=[
                    "view_employeeleave",
                    "add_employeeleave",
                    "change_employeeleave",
                    "delete_employeeleave",
                ],
            )
        )

        cls.site_admin = cls._make_employee(
            number="LAC0005",
            first_name="Rudi",
            last_name="Pratama",
            username="lac.siteadmin",
        )

        grant_role(
            cls.site_admin.user,
            cls.site_admin_role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("location", cls.head_office.pk)],
        )

    # ------------------------------------------------------------------
    # Pembantu
    # ------------------------------------------------------------------

    def leave_payload(self, employee=None, **extra) -> dict:
        return {
            "employee": (employee or self.staff).pk,
            "leave_type": self.annual.pk,
            "start_date": str(MONDAY),
            "end_date": str(TUESDAY),
            "total_days": "2",
            **extra,
        }

    def workflow_count(self, leave) -> int:
        return WorkflowInstance.objects.filter(
            module="hr",
            document_type="leave_request",
            object_id=str(leave.pk),
        ).count()


class LeaveWriteGovernanceTests(LeaveWriteGovernanceBase):
    """
    Satu kelas, dan itu bukan kemalasan: setiap `TenantTestCase`
    membangun ulang schema tenantnya sendiri, jadi memecah berkas ini
    jadi empat kelas berarti membayar pembangunan schema empat kali
    untuk fixture yang sama persis.
    """

    def setUp(self):
        super().setUp()

        self.give_balance(self.staff, 12)

        self.as_staff = self.client_for(self.staff)
        self.as_hr = self.client_for(self.hr_manager)
        self.as_supervisor = self.client_for(self.supervisor)

    # ------------------------------------------------------------------
    # 1-7: status hanya berpindah lewat jalurnya sendiri
    # ------------------------------------------------------------------

    # 1 + 2
    def test_employee_tidak_bisa_memilih_status_saat_membuat(self):
        for status in (LeaveStatus.APPROVED, LeaveStatus.RECORDED):
            with self.subTest(status=status):
                response = self.as_staff.post(
                    LEAVES,
                    self.leave_payload(status=status),
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn("status", response.json()["errors"])
                self.assertFalse(
                    EmployeeLeave.objects.filter(
                        employee=self.staff,
                        status=status,
                    ).exists(),
                )

    def test_create_tanpa_status_lahir_sebagai_draft(self):
        """
        Bawaan modelnya RECORDED — kalau baris `perform_create` hilang,
        test ini yang merah, bukan salah satu test yang lain.
        """
        response = self.as_staff.post(LEAVES, self.leave_payload())

        self.assertEqual(response.status_code, 201, self.payload(response))

        leave = EmployeeLeave.objects.get(pk=self.payload(response)["id"])

        self.assertEqual(leave.status, LeaveStatus.DRAFT)
        self.assertEqual(self.balance().used, Decimal("0.0"))

    # 3 + 4
    def test_employee_tidak_bisa_memindahkan_status_lewat_patch(self):
        leave = self.make_leave()

        for status in (LeaveStatus.APPROVED, LeaveStatus.RECORDED):
            with self.subTest(status=status):
                response = self.as_staff.patch(
                    f"{LEAVES}{leave.pk}/",
                    {"status": status},
                )

                self.assertEqual(response.status_code, 400)

                leave.refresh_from_db()

                self.assertEqual(leave.status, LeaveStatus.DRAFT)

    # 5 + 6
    def test_submit_menghasilkan_alur_dan_tidak_ada_submitted_yatim(self):
        leave = self.make_leave()

        response = self.as_staff.post(f"{LEAVES}{leave.pk}/submit/")

        self.assertEqual(response.status_code, 200, self.payload(response))

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.SUBMITTED)
        self.assertEqual(self.workflow_count(leave), 1)

        # Tidak ada satu pun cuti SUBMITTED tanpa instance alurnya —
        # keadaan yang sebelumnya bisa dibuat dengan satu POST berisi
        # `"status": "submitted"`, dan yang membuatnya tidak pernah
        # muncul di kotak masuk siapa pun.
        orphans = [
            row.pk
            for row in EmployeeLeave.objects.filter(
                status=LeaveStatus.SUBMITTED,
            )
            if self.workflow_count(row) == 0
        ]

        self.assertEqual(orphans, [])

    # 7
    def test_saldo_tidak_terpotong_lewat_status(self):
        self.as_staff.post(
            LEAVES,
            self.leave_payload(status=LeaveStatus.APPROVED),
        )

        self.assertEqual(self.balance().used, Decimal("0.0"))

        leave = self.make_leave()

        self.as_staff.patch(
            f"{LEAVES}{leave.pk}/",
            {"status": LeaveStatus.APPROVED},
        )

        self.assertEqual(self.balance().used, Decimal("0.0"))


    # ------------------------------------------------------------------
    # 8-10: pencatatan administratif punya kemampuannya sendiri
    # ------------------------------------------------------------------

    # 8
    def test_employee_tidak_punya_kemampuan_mencatat(self):
        self.assertFalse(
            self.staff.user.has_perm(f"hr.{RECORD_PERMISSION}"),
        )

        response = self.as_staff.post(
            f"{LEAVES}record/",
            self.leave_payload(),
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            EmployeeLeave.objects.filter(
                status=LeaveStatus.RECORDED,
            ).count(),
            0,
        )

    # 9 + 10
    def test_hr_mencatat_lewat_jalur_eksplisit(self):
        response = self.as_hr.post(f"{LEAVES}record/", self.leave_payload())

        self.assertEqual(response.status_code, 201, response.json())

        leave = EmployeeLeave.objects.get(
            pk=response.json()["data"]["leave"]["id"],
        )

        self.assertEqual(leave.status, LeaveStatus.RECORDED)

        # Sinkronisasi saldo tetap jalan — pencatatan memang memotong
        # jatah; yang dibedakan cuma siapa yang boleh menyatakannya.
        self.assertEqual(self.balance().used, Decimal("2.0"))

        # Denormalisasi organisasi juga tetap, karena jalurnya service
        # yang sama dengan create biasa.
        self.assertEqual(leave.company_id, self.company.pk)
        self.assertEqual(leave.location_id, self.head_office.pk)

    def test_aturan_yang_wajib_untuk_pencatatan_tetap_berlaku(self):
        """Tumpang tindih tanggal tetap ditolak di jalur pencatatan."""
        self.as_hr.post(f"{LEAVES}record/", self.leave_payload())

        second = self.as_hr.post(f"{LEAVES}record/", self.leave_payload())

        self.assertEqual(second.status_code, 400)
        self.assertEqual(
            EmployeeLeave.objects.filter(
                employee=self.staff,
                status=LeaveStatus.RECORDED,
            ).count(),
            1,
        )

    def test_pembatalan_catatan_butuh_kemampuan_yang_sama(self):
        created = self.as_hr.post(f"{LEAVES}record/", self.leave_payload())

        leave = EmployeeLeave.objects.get(
            pk=created.json()["data"]["leave"]["id"],
        )

        self.assertEqual(
            self.as_staff.post(f"{LEAVES}{leave.pk}/cancel/").status_code,
            403,
        )

        response = self.as_hr.post(f"{LEAVES}{leave.pk}/cancel/")

        self.assertEqual(response.status_code, 200, response.json())

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.CANCELLED)

        # Dibatalkan berarti jatahnya kembali.
        self.assertEqual(self.balance().used, Decimal("0.0"))

    def test_dokumen_alur_tidak_dibatalkan_dari_jalur_pencatatan(self):
        leave = self.submitted_leave()

        response = self.as_hr.post(f"{LEAVES}{leave.pk}/cancel/")

        self.assertEqual(response.status_code, 400)

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.SUBMITTED)


    # ------------------------------------------------------------------
    # 11-15: cakupan tulis dihitung dari izin tulis
    # ------------------------------------------------------------------
    #
    # Saklarnya dinyatakan per test, bukan diwarisi dari settings yang
    # kebetulan menyala: yang diuji perilaku pada saklar **menyala**,
    # dan itu harus berbunyi sama di mesin mana pun.

    # 11
    @override_settings(ROLE_AWARE_DATA_SCOPE=True)
    def test_pembaca_luas_tidak_bisa_menyunting_cuti_orang_lain(self):
        leave = self.make_leave()

        response = self.as_supervisor.patch(
            f"{LEAVES}{leave.pk}/",
            {"notes": "disunting atasan"},
        )

        self.assertEqual(response.status_code, 404)

        leave.refresh_from_db()

        self.assertEqual(leave.notes, "")

    # 12
    @override_settings(ROLE_AWARE_DATA_SCOPE=True)
    def test_pembaca_luas_tidak_bisa_menghapus_cuti_orang_lain(self):
        leave = self.make_leave()

        response = self.as_supervisor.client.delete(
            f"{LEAVES}{leave.pk}/",
            **self.as_supervisor.headers,
        )

        self.assertEqual(response.status_code, 404)

        leave.refresh_from_db()

        self.assertFalse(leave.is_deleted)

    # 15
    @override_settings(ROLE_AWARE_DATA_SCOPE=True)
    def test_hak_baca_yang_lama_tidak_berubah(self):
        leave = self.make_leave()

        response = self.detail(self.as_supervisor, leave)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.payload(response)["id"], leave.pk)

        # Dan layar tahu ia tidak boleh menyuntingnya, jadi formulirnya
        # tidak menawarkan tombol yang pasti ditolak.
        self.assertFalse(self.payload(response)["can_edit"])

    # 13
    @override_settings(ROLE_AWARE_DATA_SCOPE=True)
    def test_hr_dengan_cakupan_sah_tetap_bekerja(self):
        leave = self.make_leave()

        as_hr = self.client_for(self.hr_manager)

        response = as_hr.patch(
            f"{LEAVES}{leave.pk}/",
            {"notes": "dikoreksi HR"},
        )

        self.assertEqual(response.status_code, 200, self.payload(response))

        leave.refresh_from_db()

        self.assertEqual(leave.notes, "dikoreksi HR")

        deleted = as_hr.client.delete(
            f"{LEAVES}{leave.pk}/",
            **as_hr.headers,
        )

        self.assertEqual(deleted.status_code, 200)

    # 14
    @override_settings(ROLE_AWARE_DATA_SCOPE=True)
    def test_admin_unit_hanya_menulis_di_dalam_unitnya(self):
        as_admin = self.client_for(self.site_admin)

        inside = self.make_leave()

        response = as_admin.patch(
            f"{LEAVES}{inside.pk}/",
            {"notes": "dikoreksi admin unit"},
        )

        self.assertEqual(response.status_code, 200, self.payload(response))

        # Pegawai yang dipindahkan ke lokasi lain keluar dari jangkauan
        # yang sama — batasnya unit, bukan "semua atau tidak sama
        # sekali".
        outsider = Employee.objects.get(pk=self.bystander.pk)

        outsider.organization.location = self.site
        outsider.organization.save(update_fields=["location"])

        self.give_balance(outsider, 12)

        outside = EmployeeLeaveService.create(
            data={
                "employee": outsider,
                "leave_type": self.annual,
                "start_date": MONDAY,
                "end_date": TUESDAY,
                "total_days": Decimal("2"),
                "status": LeaveStatus.DRAFT,
            },
            user=outsider.user,
        )

        blocked = as_admin.patch(
            f"{LEAVES}{outside.pk}/",
            {"notes": "di luar unit"},
        )

        self.assertEqual(blocked.status_code, 404)


    # ------------------------------------------------------------------
    # Kepemilikan lampiran (Stage B)
    # ------------------------------------------------------------------
    #
    # Menempelkan berkas ke dokumen **memberi hak baca** kepada semua
    # orang yang boleh membaca dokumen itu, jadi "boleh menempel apa"
    # adalah pertanyaan otorisasi. Sebelum ini jawabannya "apa saja
    # yang id-nya ditebak benar": keempat jenis aktor di tenant demo
    # bisa menempelkan draf milik superuser ke cutinya sendiri dan
    # langsung mendapat hak bacanya.

    def upload(self, user):
        from django.core.files.uploadedfile import SimpleUploadedFile

        from apps.uploads.services.upload_service import UploadService

        return UploadService.create(
            uploaded_file=SimpleUploadedFile(
                "surat.pdf",
                b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n",
                content_type="application/pdf",
            ),
            user=user,
            metadata={"category": "attachment"},
            generate_preview=False,
        )

    def test_lampiran_sendiri_diterima(self):
        attachment = self.upload(self.staff.user)

        response = self.as_staff.post(
            LEAVES,
            self.leave_payload(uploaded_file=attachment.pk),
        )

        self.assertEqual(response.status_code, 201, self.payload(response))

        leave = EmployeeLeave.objects.get(pk=self.payload(response)["id"])

        self.assertEqual(leave.uploaded_file_id, attachment.pk)

    def test_lampiran_orang_lain_ditolak_tanpa_menambah_hak_baca(self):
        attachment = self.upload(self.hr_manager.user)

        self.assertFalse(
            FileAccessService.can_read(self.staff.user, attachment),
        )

        response = self.as_staff.post(
            LEAVES,
            self.leave_payload(uploaded_file=attachment.pk),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("uploaded_file", response.json()["errors"])

        attachment.refresh_from_db()

        self.assertFalse(
            FileAccessService.can_read(self.staff.user, attachment),
        )
        self.assertFalse(FileAccessService.is_attached(attachment))

    def test_hr_tidak_bisa_mengambil_unggahan_pegawai(self):
        attachment = self.upload(self.staff.user)

        response = self.as_hr.post(
            LEAVES,
            self.leave_payload(uploaded_file=attachment.pk),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("uploaded_file", response.json()["errors"])

    def test_atasan_tidak_bisa_mengambil_unggahan_bawahannya(self):
        attachment = self.upload(self.staff.user)

        response = self.as_supervisor.post(
            LEAVES,
            self.leave_payload(
                employee=self.supervisor,
                uploaded_file=attachment.pk,
            ),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("uploaded_file", response.json()["errors"])

    def test_berkas_terhapus_ditolak(self):
        attachment = self.upload(self.staff.user)

        attachment.is_deleted = True
        attachment.save(update_fields=["is_deleted"])

        response = self.as_staff.post(
            LEAVES,
            self.leave_payload(uploaded_file=attachment.pk),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("uploaded_file", response.json()["errors"])

    # ------------------------------------------------------------------
    # Keadaan pada saklar mati — dicatat, bukan direstui
    # ------------------------------------------------------------------
    #
    # `DataScopeService.for_user()` membuang nama izin yang dikirim
    # pemanggil selama `ROLE_AWARE_DATA_SCOPE` mati, jadi pemilihan izin
    # per aksi tidak bisa menegakkan apa pun di sana: cakupannya kembali
    # jadi gabungan seluruh penugasan. Itu perilaku bawaan produksi hari
    # ini (`config/settings/base.py:76` -> `False`).
    #
    # Yang **tetap** menegakkan pada kedua keadaan saklar: penjagaan
    # status, karena ia tidak lewat cakupan data sama sekali.

    @override_settings(ROLE_AWARE_DATA_SCOPE=False)
    def test_cakupan_tulis_belum_menyempit_saat_saklar_mati(self):
        leave = self.make_leave()

        response = self.as_supervisor.patch(
            f"{LEAVES}{leave.pk}/",
            {"notes": "masih bisa"},
        )

        self.assertEqual(
            response.status_code,
            200,
            "Saklar ROLE_AWARE_DATA_SCOPE mati berarti cakupan tulis "
            "kembali ke gabungan seluruh role. Kalau test ini merah, "
            "saklarnya sudah dicabut — hapus test ini.",
        )

    @override_settings(ROLE_AWARE_DATA_SCOPE=False)
    def test_status_tetap_dijaga_saat_saklar_mati(self):
        response = self.as_staff.post(
            LEAVES,
            self.leave_payload(status=LeaveStatus.APPROVED),
        )

        self.assertEqual(response.status_code, 400)
