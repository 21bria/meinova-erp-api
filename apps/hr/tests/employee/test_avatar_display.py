"""
`avatar_display` pada daftar pegawai.

Kolom identitas di tabel Employee menampilkan foto, nama, dan nomor
pegawai dalam satu sel. Yang membuatnya mungkin satu field turunan:
`avatar_display` — `{url, source, initials}` yang dirakit
`resolve_employee_avatar()`.

Dua hal yang dijaga berkas ini, dan keduanya gagal dengan **diam**
kalau rusak:

1. **Field-nya benar-benar terkirim di daftar**, bukan cuma di detail.
   Tabel yang tidak menerimanya tidak menampilkan error — ia
   menampilkan inisial untuk semua orang, termasuk yang punya foto,
   dan itu terbaca sebagai "belum ada yang mengunggah foto".

2. **Satu baris tidak berarti satu query tambahan.** `avatar_display`
   membaca berkasnya per pegawai; tanpa `select_related` halaman
   berisi 25 pegawai menambah 25 query, dan itu baru terasa setelah
   tenant pertama benar-benar mengunggah foto — jauh setelah kodenya
   ditulis.

Urutan resolusinya sendiri (`avatar_file` → `avatar` lama → inisial)
diuji di `apps/self_service/tests/test_avatar.py`; yang di sini
kontrak daftarnya.
"""

from __future__ import annotations

import tempfile

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context

from apps.hr.api.employee.serializers.employee import EmployeeSerializer
from apps.hr.api.employee.services.employee_service import EmployeeService
from apps.hr.models import Employee
from apps.uploads.models import UploadedFile


User = get_user_model()

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
    b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
    b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="avatar-display-test-"))
class EmployeeAvatarDisplayTests(TenantTestCase):
    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "employee-avatar-display"
        tenant.name = "Employee Avatar Display"

    def _next(self) -> int:
        type(self)._counter += 1

        return type(self)._counter

    def make_employee(self, *, first="Adrian", last="Mahendra"):
        n = self._next()

        return Employee.objects.create(
            employee_number=f"AD{n:04d}",
            first_name=first,
            last_name=last,
        )

    def make_upload(self):
        n = self._next()

        return UploadedFile.objects.create(
            file=SimpleUploadedFile(f"foto-{n}.png", PNG, "image/png"),
            original_name=f"foto-{n}.png",
            extension=".png",
            mime_type="image/png",
            file_type=UploadedFile.FileType.IMAGE,
            category=UploadedFile.Category.AVATAR,
        )

    # ------------------------------------------------------------------
    # Kontrak field
    # ------------------------------------------------------------------

    def test_field_terdaftar_dan_read_only(self):
        self.assertIn(
            "avatar_display",
            EmployeeSerializer.Meta.fields,
        )

        # Turunan murni. Terdaftar sebagai bisa ditulis, PATCH yang
        # mengirimnya dibalas 400 alih-alih diabaikan — dan form yang
        # mengirim balik seluruh payload bacanya jadi tidak bisa
        # menyimpan apa pun.
        self.assertIn(
            "avatar_display",
            EmployeeSerializer.Meta.read_only_fields,
        )

    def test_pegawai_tanpa_foto_tetap_mengirim_inisial(self):
        employee = self.make_employee(first="Adrian", last="Mahendra")

        data = EmployeeSerializer(employee).data

        self.assertEqual(
            data["avatar_display"],
            {
                "url": None,
                "source": None,
                "initials": "AM",
            },
        )

    def test_avatar_file_mengirim_alamat_preview(self):
        """
        Yang dikirim alamat `preview/`, **bukan** `file.url`.

        Yang kedua jalur penyimpanan mentah yang dilayani `MEDIA_URL`
        statis: siapa pun yang menebaknya bisa membuka foto pegawai
        tanpa login. Pemeriksaan ini yang menahannya kalau suatu saat
        ada yang "menyederhanakan" resolvernya.
        """
        employee = self.make_employee()
        employee.avatar_file = self.make_upload()
        employee.save(update_fields=["avatar_file"])

        avatar = EmployeeSerializer(employee).data["avatar_display"]

        self.assertEqual(avatar["source"], "upload")
        self.assertIn(
            f"/api/uploads/{employee.avatar_file.public_id}/preview/",
            avatar["url"],
        )
        self.assertNotIn("/media/", avatar["url"])

    # ------------------------------------------------------------------
    # Daftar
    # ------------------------------------------------------------------

    def test_daftar_ikut_mengirim_avatar_display(self):
        self.make_employee(first="Citra", last="Halimah")

        rows = EmployeeSerializer(
            EmployeeService.list(),
            many=True,
        ).data

        self.assertTrue(rows)
        self.assertTrue(
            all("avatar_display" in row for row in rows),
        )

    def test_daftar_ikut_mengambil_berkas_fotonya(self):
        """
        `avatar_file` ikut di-`select_related`.

        Diperiksa dari bentuk querysetnya, bukan dengan menghitung
        query: daftar pegawai sudah membawa query per baris dari
        sumber lain (baris payroll `is_current`), jadi angka totalnya
        tidak bisa membuktikan apa pun soal foto — ia naik dan turun
        karena hal yang sama sekali lain, dan pemeriksaan yang
        bersandar padanya akan merah karena perubahan yang tidak ada
        hubungannya.

        Tanpa ini, satu halaman berisi 25 pegawai berfoto menambah 25
        query — dan tidak ada satu pun gejala sampai tenant pertama
        benar-benar mengunggah foto.
        """
        related = EmployeeService.list().query.select_related

        self.assertIsInstance(related, dict)
        self.assertIn("avatar_file", related)

    def test_foto_terbaca_untuk_seluruh_baris_daftar(self):
        for _ in range(3):
            employee = self.make_employee()
            employee.avatar_file = self.make_upload()
            employee.save(update_fields=["avatar_file"])

        rows = EmployeeSerializer(
            EmployeeService.list(),
            many=True,
        ).data

        self.assertEqual(len(rows), 3)
        self.assertTrue(
            all(row["avatar_display"]["source"] == "upload" for row in rows),
        )


    # ------------------------------------------------------------------
    # `avatar_file_detail` — pratinjau foto di form yang dibuka ulang
    # ------------------------------------------------------------------
    #
    # Form Edit membaca berkasnya dari `avatar_file_detail` (detailField
    # schema `avatar_file`). Tanpa field ini form yang dibuka ulang hanya
    # memegang id: foto yang sudah tersimpan tidak tampil sama sekali,
    # dan tombol ganti/hapus tidak punya `public_id` untuk ditembak.

    def test_detail_berkas_terdaftar_dan_read_only(self):
        self.assertIn("avatar_file_detail", EmployeeSerializer.Meta.fields)
        self.assertIn(
            "avatar_file_detail",
            EmployeeSerializer.Meta.read_only_fields,
        )

    def test_detail_berkas_null_tanpa_foto(self):
        employee = self.make_employee()

        self.assertIsNone(
            EmployeeSerializer(employee).data["avatar_file_detail"],
        )

    def test_detail_berkas_menunjuk_alamat_berautentikasi_saja(self):
        """
        Cukup untuk widget unggah — dan **tanpa** jalur `MEDIA_URL`.

        `file_url`/`thumbnail_url` milik `UploadedFileSerializer` utuh
        adalah jalur statis yang terbuka tanpa login. Field ini ikut di
        setiap baris daftar pegawai, jadi keduanya tidak boleh ikut.
        """
        employee = self.make_employee()
        employee.avatar_file = self.make_upload()
        employee.save(update_fields=["avatar_file"])

        detail = EmployeeSerializer(employee).data["avatar_file_detail"]

        public_id = str(employee.avatar_file.public_id)

        self.assertEqual(detail["id"], employee.avatar_file_id)
        self.assertEqual(str(detail["public_id"]), public_id)
        self.assertEqual(detail["category"], UploadedFile.Category.AVATAR)
        self.assertIn(f"/api/uploads/{public_id}/preview/", detail["preview_url"])
        self.assertIn(f"/api/uploads/{public_id}/download/", detail["download_url"])

        self.assertNotIn("file_url", detail)
        self.assertNotIn("thumbnail_url", detail)
        self.assertNotIn("/media/", str(detail))

    def test_foto_pengganti_mengganti_alamatnya(self):
        """
        Mengganti foto = berkas baru = `public_id` baru = alamat baru.

        Itulah yang membuat cache gambar di frontend (dikunci per
        alamat) tidak pernah menyajikan foto lama setelah diganti —
        tanpa stempel waktu buatan di setiap render.
        """
        employee = self.make_employee()
        employee.avatar_file = self.make_upload()
        employee.save(update_fields=["avatar_file"])

        before = EmployeeSerializer(employee).data

        employee.avatar_file = self.make_upload()
        employee.save(update_fields=["avatar_file"])

        after = EmployeeSerializer(employee).data

        self.assertNotEqual(
            before["avatar_display"]["url"],
            after["avatar_display"]["url"],
        )
        self.assertEqual(
            after["avatar_display"]["url"],
            after["avatar_file_detail"]["preview_url"],
        )

    def test_foto_tidak_menambah_query_per_baris(self):
        """
        Daftar berfoto dan daftar tanpa foto, jumlah baris sama —
        jumlah query-nya juga harus sama.

        Dibandingkan berpasangan, bukan terhadap angka mutlak: daftar
        pegawai sudah membawa query per baris dari sumber lain (lihat
        `test_daftar_ikut_mengambil_berkas_fotonya`), dan angka itu
        berubah karena hal yang tidak ada hubungannya dengan foto.
        Selisih nol yang dibuktikan di sini: `avatar_display` dan
        `avatar_file_detail` tidak menambah satu query pun.
        """
        plain = [self.make_employee() for _ in range(3)]

        def count(ids) -> int:
            queryset = EmployeeService.list().filter(pk__in=ids)

            with CaptureQueriesContext(connection) as captured:
                rows = EmployeeSerializer(queryset, many=True).data

            self.assertEqual(len(rows), len(ids))

            return len(captured)

        without_photo = count([e.pk for e in plain])

        for employee in plain:
            employee.avatar_file = self.make_upload()
            employee.save(update_fields=["avatar_file"])

        with_photo = count([e.pk for e in plain])

        self.assertEqual(with_photo, without_photo)

    def test_foto_tinggal_di_schema_tenant(self):
        """
        Berkas foto dan pegawainya hidup di schema tenant, tidak di
        `public`: tenant lain tidak punya baris untuk ditemukan, apalagi
        dipratinjau lewat `public_id`-nya.
        """
        employee = self.make_employee()
        employee.avatar_file = self.make_upload()
        employee.save(update_fields=["avatar_file"])

        with schema_context("public"):
            tables = connection.introspection.table_names()

        self.assertNotIn(UploadedFile._meta.db_table, tables)
        self.assertNotIn(Employee._meta.db_table, tables)

        with schema_context(self.tenant.schema_name):
            self.assertTrue(
                UploadedFile.objects.filter(
                    public_id=employee.avatar_file.public_id,
                ).exists(),
            )


# ----------------------------------------------------------------------
# Siapa boleh menempelkan berkas sebagai foto
# ----------------------------------------------------------------------


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="avatar-claim-test-"))
class EmployeeAvatarAttachAuthorityTests(TenantTestCase):
    """
    `avatar_file` menerima id `UploadedFile`. Id itu berurutan dan mudah
    ditebak, dan menempelkannya memberi hak baca lewat `preview/` kepada
    siapa pun yang boleh membaca pegawai ini. Jadi yang menempel harus
    pengunggahnya — aturan `FileAccessService.attachment_problem()`,
    sama dengan lampiran cuti dan izin kehadiran.
    """

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "employee-avatar-claim"
        tenant.name = "Employee Avatar Claim"

    def _next(self) -> int:
        type(self)._counter += 1

        return type(self)._counter

    def make_user(self):
        n = self._next()

        return User.objects.create_user(
            username=f"avatar.claim{n}",
            email=f"avatar.claim{n}@example.test",
            password="Test-Only#Pw1",
        )

    def make_employee(self):
        n = self._next()

        return Employee.objects.create(
            employee_number=f"AC{n:04d}",
            first_name="Citra",
            last_name="Halimah",
        )

    def make_upload(self, owner):
        n = self._next()

        return UploadedFile.objects.create(
            file=SimpleUploadedFile(f"claim-{n}.png", PNG, "image/png"),
            original_name=f"claim-{n}.png",
            extension=".png",
            mime_type="image/png",
            file_type=UploadedFile.FileType.IMAGE,
            category=UploadedFile.Category.AVATAR,
            uploaded_by=owner,
        )

    def patch(self, employee, user, avatar_file):
        from types import SimpleNamespace

        return EmployeeSerializer(
            employee,
            data={"avatar_file": getattr(avatar_file, "pk", avatar_file)},
            partial=True,
            context={"request": SimpleNamespace(user=user)},
        )

    def test_berkas_milik_orang_lain_tidak_bisa_diklaim(self):
        owner = self.make_user()
        claimer = self.make_user()

        foreign = self.make_upload(owner)

        serializer = self.patch(self.make_employee(), claimer, foreign)

        self.assertFalse(serializer.is_valid())
        self.assertIn("avatar_file", serializer.errors)

    def test_berkas_yang_sudah_dipakai_pegawai_lain_ditolak(self):
        editor = self.make_user()

        upload = self.make_upload(editor)

        other = self.make_employee()
        other.avatar_file = upload
        other.save(update_fields=["avatar_file"])

        serializer = self.patch(self.make_employee(), editor, upload)

        self.assertFalse(serializer.is_valid())
        self.assertIn("avatar_file", serializer.errors)

    def test_unggahan_sendiri_boleh_ditempel(self):
        editor = self.make_user()

        serializer = self.patch(
            self.make_employee(), editor, self.make_upload(editor),
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_foto_boleh_dilepas(self):
        editor = self.make_user()

        employee = self.make_employee()
        employee.avatar_file = self.make_upload(editor)
        employee.save(update_fields=["avatar_file"])

        serializer = self.patch(employee, self.make_user(), None)

        self.assertTrue(serializer.is_valid(), serializer.errors)

    def test_penyunting_kedua_tidak_ditolak_karena_foto_yang_tidak_berubah(self):
        """
        Form mengirim ulang seluruh record. Foto yang diunggah HR A dan
        tidak disentuh HR B tidak boleh membuat Save milik HR B gagal.
        """
        first = self.make_user()
        second = self.make_user()

        employee = self.make_employee()
        employee.avatar_file = self.make_upload(first)
        employee.save(update_fields=["avatar_file"])

        serializer = self.patch(employee, second, employee.avatar_file)

        self.assertTrue(serializer.is_valid(), serializer.errors)
