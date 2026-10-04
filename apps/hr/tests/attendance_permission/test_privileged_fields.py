"""
Kolom yang bukan milik pemohon: override HR, organisasi, dan lampiran.

Tiga lubang yang ditutup berkas ini, ketiganya terbukti di tenant demo
17 Sep 2026 lewat probe yang di-rollback:

1. **`allow_outside_shift` bisa dikirim siapa pun.** Kolom itu
   mem-bypass `assert_within_shift` — satu-satunya penjagaan yang
   memastikan izin berada di dalam jam kerja pegawainya — dan setiap
   pemegang `hr.add_attendancepermission` (role EMPLOYEE hasil seed
   memilikinya) bisa menyalakannya untuk dirinya sendiri.
2. **Organisasi bisa ditentukan dari payload.** `apply_organization`
   hanya mengisi yang kosong, jadi satu request berisi `"location": <id>`
   memindahkan dokumen ke unit lain: keluar dari jangkauan HR yang
   seharusnya melihatnya, masuk ke jangkauan HR yang tidak
   berkepentingan.
3. **Lampiran orang lain bisa diklaim.** Id `UploadedFile` berurutan,
   dan menempelkan berkas ke dokumen **memberi hak baca** kepada semua
   orang yang boleh membaca dokumen itu.

Yang diuji lewat serializer + request sungguhan, bukan lewat service:
ketiganya penjagaan di batas API, dan jalur service memang sengaja
dibiarkan bebas untuk importir dan seed.
"""

from __future__ import annotations

import json

from datetime import time

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.accounts.models import AuthorityMode, Role
from apps.accounts.services.role_assignment import grant_role
from apps.hr.models import AttendancePermission, AttendancePermissionType
from apps.uploads.services.access_service import FileAccessService

from .base import TRIAL_DATE, AttendancePermissionTestCase


PERMISSIONS = "/api/hr/attendance-permissions/"

OVERRIDE = "override_attendancepermission"

CRUD = [
    "view_attendancepermission",
    "add_attendancepermission",
    "change_attendancepermission",
    "delete_attendancepermission",
]


class _As:
    """Klien HTTP yang selalu membawa token satu orang."""

    def __init__(self, client, user):
        self.client = client
        self.headers = {
            "HTTP_AUTHORIZATION": (
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
        }

    def post(self, path, payload=None):
        return self.client.post(
            path,
            data=json.dumps(payload or {}, default=str),
            content_type="application/json",
            **self.headers,
        )

    def patch(self, path, payload=None):
        return self.client.patch(
            path,
            data=json.dumps(payload or {}, default=str),
            content_type="application/json",
            **self.headers,
        )


class PrivilegedFieldTests(AttendancePermissionTestCase):
    """
    Satu kelas, dan itu disengaja: tiap `TenantTestCase` membangun ulang
    schema tenantnya sendiri, jadi memecah berkas ini per tema berarti
    membayar pembangunan schema berkali-kali untuk panggung yang sama.
    """

    @classmethod
    def build_baseline(cls):
        """
        Hanya **konfigurasi** yang menetap di schema bersama.

        Role adalah master: kuncinya alami, isinya tidak berubah, dan
        dua kelas yang memintanya memang memaksudkan baris yang sama.
        Pegawai tidak: ia data transaksi, dan menaruhnya di sini berarti
        baris yang dibuat satu kelas ikut terbaca kelas berikutnya —
        persis keadaan yang membuat urutan eksekusi menentukan hasil.
        Karena itu pegawainya turun ke `setUp` dan ikut di-rollback.
        """
        super().build_baseline()

        crud = Permission.objects.filter(
            content_type__app_label="hr",
            codename__in=CRUD,
        )

        cls.override_permission = Permission.objects.get(
            content_type__app_label="hr",
            codename=OVERRIDE,
        )

        # Pegawai biasa: CRUD izin kehadiran, cakupan `own`. Persis
        # bentuk role EMPLOYEE hasil seed.
        cls.staff_role, _ = Role.objects.get_or_create(
            code="APM-STAFF", is_deleted=False, defaults={"name": "Staff"},
        )
        cls.staff_role.permissions.set(crud)

        # Atasan: izin yang sama, cakupan lebih luas — dan **tanpa**
        # kemampuan override. Garis pelaporan tidak memberi wewenang
        # apa pun di sini.
        cls.manager_role, _ = Role.objects.get_or_create(
            code="APM-MGR", is_deleted=False, defaults={"name": "Manager"},
        )
        cls.manager_role.permissions.set(crud)

        # HR: CRUD + kemampuan override yang dinyatakan eksplisit.
        cls.hr_role, _ = Role.objects.get_or_create(
            code="APM-HR", is_deleted=False, defaults={"name": "HR"},
        )
        cls.hr_role.permissions.set(crud)
        cls.hr_role.permissions.add(cls.override_permission)

    def setUp(self):
        super().setUp()

        self.staff = self.make_employee()
        self.manager = self.make_employee()
        self.hr = self.make_employee()

        # Pegawai di lokasi lain, untuk membuktikan organisasi memang
        # diturunkan dari penempatan — bukan dari payload.
        self.site_staff = self.make_employee(location=self.site)

        grant_role(
            self.staff.user,
            self.staff_role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("own", None)],
        )

        for employee, role in (
            (self.manager, self.manager_role),
            (self.hr, self.hr_role),
        ):
            grant_role(
                employee.user,
                role,
                mode=AuthorityMode.UNRESTRICTED,
                authorities=[],
            )

        self.http = TenantClient(self.tenant)

        self.as_staff = _As(self.http, self.staff.user)
        self.as_manager = _As(self.http, self.manager.user)
        self.as_hr = _As(self.http, self.hr.user)

    # ------------------------------------------------------------------
    # Pembantu
    # ------------------------------------------------------------------

    def body(self, employee=None, **extra) -> dict:
        """
        Izin datang terlambat sampai 23:30 — **di luar** shift kantor
        08:00–17:00, jadi tanpa override ia memang ditolak. Itu yang
        membuat kolom override di sini bukan hiasan.
        """
        return {
            "employee": (employee or self.staff).pk,
            "permission_type": AttendancePermissionType.LATE_ARRIVAL,
            "date": TRIAL_DATE,
            "end_time": time(23, 30),
            "reason": "Urusan keluarga",
            **extra,
        }

    def errors(self, response) -> dict:
        return response.json().get("errors", response.json())

    def upload(self, user):
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

    # ------------------------------------------------------------------
    # 1-5: override adalah wewenang HR
    # ------------------------------------------------------------------

    def test_pegawai_tidak_bisa_menyalakan_override(self):
        response = self.as_staff.post(
            PERMISSIONS,
            self.body(allow_outside_shift=True, outside_shift_reason="x"),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("allow_outside_shift", self.errors(response))
        self.assertFalse(
            AttendancePermission.objects.filter(
                employee=self.staff,
                allow_outside_shift=True,
            ).exists(),
        )

    def test_atasan_tanpa_kemampuan_juga_ditolak(self):
        response = self.as_manager.post(
            PERMISSIONS,
            self.body(
                employee=self.staff,
                allow_outside_shift=True,
                outside_shift_reason="x",
            ),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("allow_outside_shift", self.errors(response))

    def test_pegawai_tidak_bisa_menyalakan_override_lewat_patch(self):
        created = self.as_hr.post(
            PERMISSIONS,
            self.body(allow_outside_shift=True, outside_shift_reason="HR"),
        )

        self.assertEqual(created.status_code, 201, created.content)

        pk = created.json()["id"]

        response = self.as_staff.patch(
            f"{PERMISSIONS}{pk}/",
            {"allow_outside_shift": False},
        )

        self.assertEqual(response.status_code, 400)

        permission = AttendancePermission.objects.get(pk=pk)

        self.assertTrue(permission.allow_outside_shift)

    def test_hr_dengan_kemampuan_boleh_override(self):
        response = self.as_hr.post(
            PERMISSIONS,
            self.body(
                allow_outside_shift=True,
                outside_shift_reason="Rapat klien sampai malam",
            ),
        )

        self.assertEqual(response.status_code, 201, response.content)

        permission = AttendancePermission.objects.get(
            pk=response.json()["id"],
        )

        self.assertTrue(permission.allow_outside_shift)
        self.assertEqual(
            permission.outside_shift_reason,
            "Rapat klien sampai malam",
        )

    def test_override_tanpa_alasan_ditolak(self):
        response = self.as_hr.post(
            PERMISSIONS,
            self.body(allow_outside_shift=True),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("outside_shift_reason", self.errors(response))

    def test_tanpa_override_izin_di_luar_shift_tetap_ditolak(self):
        """
        Penjagaan aslinya tidak ikut longgar. Kalau test ini hijau
        karena izinnya diterima, yang diuji test lain bukan override
        melainkan formulir yang memang tidak dijaga apa pun.
        """
        response = self.as_staff.post(PERMISSIONS, self.body())

        self.assertEqual(response.status_code, 400)
        self.assertIn("start_time", self.errors(response))

    def test_mengirim_override_false_bukan_perubahan(self):
        """
        Formulir mengirim seluruh isi tab apa adanya, jadi
        `allow_outside_shift: false` dari pegawai biasa adalah keadaan
        normal — bukan percobaan menyalakan apa pun.
        """
        response = self.as_staff.post(
            PERMISSIONS,
            self.body(
                permission_type=AttendancePermissionType.FULL_DAY,
                end_time=None,
                allow_outside_shift=False,
                outside_shift_reason="",
            ),
        )

        self.assertEqual(response.status_code, 201, response.content)

    # ------------------------------------------------------------------
    # 6-7: organisasi diturunkan, bukan dikirim
    # ------------------------------------------------------------------

    def test_organisasi_diturunkan_dari_penempatan(self):
        response = self.as_staff.post(
            PERMISSIONS,
            self.body(
                permission_type=AttendancePermissionType.FULL_DAY,
                end_time=None,
            ),
        )

        self.assertEqual(response.status_code, 201, response.content)

        permission = AttendancePermission.objects.get(
            pk=response.json()["id"],
        )

        self.assertEqual(permission.location_id, self.head_office.pk)
        self.assertEqual(permission.company_id, self.company.pk)

    def test_lokasi_dari_payload_diabaikan(self):
        response = self.as_staff.post(
            PERMISSIONS,
            self.body(
                permission_type=AttendancePermissionType.FULL_DAY,
                end_time=None,
                location=self.site.pk,
                company=self.company.pk,
            ),
        )

        self.assertEqual(response.status_code, 201, response.content)

        permission = AttendancePermission.objects.get(
            pk=response.json()["id"],
        )

        self.assertEqual(permission.location_id, self.head_office.pk)

    def test_patch_tidak_bisa_memindahkan_dokumen_lintas_unit(self):
        created = self.as_staff.post(
            PERMISSIONS,
            self.body(
                permission_type=AttendancePermissionType.FULL_DAY,
                end_time=None,
            ),
        )

        pk = created.json()["id"]

        response = self.as_staff.patch(
            f"{PERMISSIONS}{pk}/",
            {"location": self.site.pk},
        )

        self.assertEqual(response.status_code, 200, response.content)

        permission = AttendancePermission.objects.get(pk=pk)

        self.assertEqual(permission.location_id, self.head_office.pk)

    def test_subjek_berganti_organisasinya_ikut(self):
        """
        HR memindahkan dokumen ke pegawai site: company/branch/location
        ikut pindah. Tanpa ini dokumennya menyebut dua unit sekaligus,
        dan yang menentukan siapa boleh membacanya justru kolom basi.
        """
        created = self.as_hr.post(
            PERMISSIONS,
            self.body(
                permission_type=AttendancePermissionType.FULL_DAY,
                end_time=None,
            ),
        )

        pk = created.json()["id"]

        response = self.as_hr.patch(
            f"{PERMISSIONS}{pk}/",
            {"employee": self.site_staff.pk},
        )

        self.assertEqual(response.status_code, 200, response.content)

        permission = AttendancePermission.objects.get(pk=pk)

        self.assertEqual(permission.employee_id, self.site_staff.pk)
        self.assertEqual(permission.location_id, self.site.pk)

    # ------------------------------------------------------------------
    # 9-16: kepemilikan lampiran
    # ------------------------------------------------------------------

    def test_lampiran_sendiri_diterima(self):
        attachment = self.upload(self.staff.user)

        response = self.as_staff.post(
            PERMISSIONS,
            self.body(
                permission_type=AttendancePermissionType.FULL_DAY,
                end_time=None,
                supporting_document=attachment.pk,
            ),
        )

        self.assertEqual(response.status_code, 201, response.content)

        permission = AttendancePermission.objects.get(
            pk=response.json()["id"],
        )

        self.assertEqual(permission.supporting_document_id, attachment.pk)

    def test_lampiran_milik_orang_lain_ditolak_dan_tidak_memberi_hak_baca(self):
        attachment = self.upload(self.hr.user)

        self.assertFalse(
            FileAccessService.can_read(self.staff.user, attachment),
        )

        response = self.as_staff.post(
            PERMISSIONS,
            self.body(
                permission_type=AttendancePermissionType.FULL_DAY,
                end_time=None,
                supporting_document=attachment.pk,
            ),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("supporting_document", self.errors(response))

        attachment.refresh_from_db()

        self.assertFalse(
            FileAccessService.can_read(self.staff.user, attachment),
        )
        self.assertFalse(FileAccessService.is_attached(attachment))

    def test_hr_tidak_mendapat_pengecualian(self):
        """
        Jabatan tidak memberi hak mengambil draf unggahan orang lain.
        Kalau nanti HR memang perlu, itu kemampuan yang dinyatakan
        sendiri — bukan efek samping.
        """
        attachment = self.upload(self.staff.user)

        response = self.as_hr.post(
            PERMISSIONS,
            self.body(
                employee=self.staff,
                permission_type=AttendancePermissionType.FULL_DAY,
                end_time=None,
                supporting_document=attachment.pk,
            ),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("supporting_document", self.errors(response))

    def test_berkas_terhapus_ditolak(self):
        attachment = self.upload(self.staff.user)

        attachment.is_deleted = True
        attachment.save(update_fields=["is_deleted"])

        response = self.as_staff.post(
            PERMISSIONS,
            self.body(
                permission_type=AttendancePermissionType.FULL_DAY,
                end_time=None,
                supporting_document=attachment.pk,
            ),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("supporting_document", self.errors(response))

    def test_berkas_yang_sudah_dipakai_dokumen_lain_ditolak(self):
        attachment = self.upload(self.staff.user)

        first = self.as_staff.post(
            PERMISSIONS,
            self.body(
                permission_type=AttendancePermissionType.FULL_DAY,
                end_time=None,
                supporting_document=attachment.pk,
            ),
        )

        self.assertEqual(first.status_code, 201, first.content)

        second = self.as_staff.post(
            PERMISSIONS,
            self.body(
                permission_type=AttendancePermissionType.FULL_DAY,
                end_time=None,
                date=TRIAL_DATE.replace(day=TRIAL_DATE.day + 1),
                supporting_document=attachment.pk,
            ),
        )

        self.assertEqual(second.status_code, 400)
        self.assertIn("supporting_document", self.errors(second))

    def test_menyimpan_ulang_dokumen_dengan_lampiran_yang_sama_tetap_boleh(self):
        """
        Aturan "belum dipakai dokumen lain" tidak boleh menolak dokumen
        yang memang sudah memegang berkas itu — kalau tidak, satu-satunya
        cara menyunting catatan adalah melepas lampirannya dulu.
        """
        attachment = self.upload(self.staff.user)

        created = self.as_staff.post(
            PERMISSIONS,
            self.body(
                permission_type=AttendancePermissionType.FULL_DAY,
                end_time=None,
                supporting_document=attachment.pk,
            ),
        )

        pk = created.json()["id"]

        response = self.as_staff.patch(
            f"{PERMISSIONS}{pk}/",
            {
                "supporting_document": attachment.pk,
                "reason": "Diperbarui",
            },
        )

        self.assertEqual(response.status_code, 200, response.content)
