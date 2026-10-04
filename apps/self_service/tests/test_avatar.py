"""
Foto pegawai: urutan resolusi, fallback, dan yang tidak boleh ikut.

Dua hal diuji bersamaan dan sengaja tidak dipisah ke dua berkas, karena
keduanya satu keputusan: **alamat mana yang dikirim** (berautentikasi,
bukan jalur penyimpanan mentah) dan **apa yang terjadi kalau tidak ada
foto** (inisial, bukan kotak kosong). Yang kedua tanpa yang pertama
menghasilkan layar yang rapi tapi bocor.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.hr.avatar import employee_initials, resolve_employee_avatar
from apps.hr.models import Employee
from apps.uploads.models import UploadedFile


User = get_user_model()

ME = "/api/me/"

# PNG 1×1 yang sah. Berkas fisik memang diperlukan: `_upload_url()`
# memeriksa `uploaded.file`, dan baris tanpa berkas harus jatuh ke
# jalur berikutnya — perilaku yang tidak bisa diuji dengan mock.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
    b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
    b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class EmployeeAvatarTests(TenantTestCase):
    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "self-service-avatar"
        tenant.name = "Self Service Avatar"

    def setUp(self):
        super().setUp()

        self.http = TenantClient(self.tenant)

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    def _next(self) -> int:
        type(self)._counter += 1

        return type(self)._counter

    def make_user(self):
        n = self._next()

        return User.objects.create_user(
            username=f"av-{n}",
            email=f"av-{n}@example.test",
            password="pw",
        )

    def make_employee(self, *, user=None, first="Bimo", last="Nugroho"):
        n = self._next()

        return Employee.objects.create(
            user=user,
            employee_number=f"AV{n:04d}",
            first_name=first,
            last_name=last,
        )

    def make_upload(
        self,
        *,
        category=UploadedFile.Category.AVATAR,
        file_type=UploadedFile.FileType.IMAGE,
        with_file=True,
    ):
        n = self._next()

        return UploadedFile.objects.create(
            file=(
                SimpleUploadedFile(f"foto-{n}.png", PNG, "image/png")
                if with_file
                else None
            ),
            original_name=f"foto-{n}.png",
            extension=".png",
            mime_type="image/png",
            file_type=file_type,
            category=category,
        )

    def as_user(self, user):
        token = RefreshToken.for_user(user).access_token

        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    # ------------------------------------------------------------------
    # Inisial
    # ------------------------------------------------------------------

    def test_inisial_dua_kata(self):
        employee = self.make_employee(first="Bimo", last="Nugroho")

        self.assertEqual(employee_initials(employee), "BN")

    def test_inisial_satu_kata(self):
        employee = self.make_employee(first="Sukarno", last="")

        self.assertEqual(employee_initials(employee), "SU")

    def test_inisial_tanpa_nama(self):
        """
        Tidak mungkin lewat form — `first_name` wajib — tapi mungkin
        lewat importer dan lewat data lama. Yang dijaga: jangan sampai
        melempar di tengah render halaman.
        """
        employee = self.make_employee(first="", last="")

        self.assertEqual(employee_initials(employee), "?")

    # ------------------------------------------------------------------
    # Urutan resolusi
    # ------------------------------------------------------------------

    def test_tanpa_foto_jatuh_ke_inisial(self):
        avatar = resolve_employee_avatar(self.make_employee())

        self.assertIsNone(avatar["url"])
        self.assertIsNone(avatar["source"])
        self.assertEqual(avatar["initials"], "BN")

    def test_avatar_file_memakai_alamat_berautentikasi(self):
        employee = self.make_employee()
        employee.avatar_file = self.make_upload()
        employee.save(update_fields=["avatar_file"])

        avatar = resolve_employee_avatar(employee)

        self.assertEqual(avatar["source"], "upload")

        # `resolve_employee_avatar()` melayani audiens **administratif**
        # — kartu pegawai HR dan sidebar — dan di sana `preview/` memang
        # alamat yang benar: hak bacanya diturunkan dari hak baca baris
        # Employee-nya, persis seperti tab lain di kartu yang sama.
        # Self Service memakai alamatnya sendiri; lihat
        # `SelfAvatarEndpointTests`.
        self.assertEqual(
            avatar["url"],
            f"/api/uploads/{employee.avatar_file.public_id}/preview/",
        )

        # Yang paling penting: **bukan** jalur penyimpanan. Kalau baris
        # ini merah, foto pegawai dilayani tanpa satu pun pemeriksaan
        # siapa yang membukanya.
        self.assertNotIn("/media/", avatar["url"])
        self.assertNotIn("uploads/test/", avatar["url"])

    def test_kolom_lama_dipakai_kalau_avatar_file_kosong(self):
        employee = self.make_employee()
        employee.avatar = SimpleUploadedFile("lama.png", PNG, "image/png")
        employee.save(update_fields=["avatar"])

        avatar = resolve_employee_avatar(employee)

        self.assertEqual(avatar["source"], "legacy")
        self.assertIn("employees/avatars/", avatar["url"])

    def test_avatar_file_menang_atas_kolom_lama(self):
        employee = self.make_employee()
        employee.avatar = SimpleUploadedFile("lama.png", PNG, "image/png")
        employee.avatar_file = self.make_upload()
        employee.save(update_fields=["avatar", "avatar_file"])

        avatar = resolve_employee_avatar(employee)

        self.assertEqual(avatar["source"], "upload")

    def test_berkas_terhapus_jatuh_ke_jalur_berikutnya(self):
        """
        Berkas yang di-soft-delete tidak punya gambar untuk ditampilkan.
        Mengirim alamatnya berarti mengirim alamat yang pasti 404 —
        lebih buruk daripada inisial, karena terbaca seperti gangguan.
        """
        employee = self.make_employee()

        uploaded = self.make_upload()
        uploaded.soft_delete()

        employee.avatar_file = uploaded
        employee.save(update_fields=["avatar_file"])

        avatar = resolve_employee_avatar(employee)

        self.assertIsNone(avatar["url"])
        self.assertEqual(avatar["initials"], "BN")

    # ------------------------------------------------------------------
    # Validasi
    # ------------------------------------------------------------------

    def test_kategori_selain_avatar_ditolak(self):
        employee = self.make_employee()
        employee.avatar_file = self.make_upload(
            category=UploadedFile.Category.ATTACHMENT,
        )

        with self.assertRaises(ValidationError) as caught:
            employee.full_clean()

        self.assertIn("avatar_file", caught.exception.error_dict)

    def test_berkas_bukan_gambar_ditolak(self):
        employee = self.make_employee()
        employee.avatar_file = self.make_upload(
            file_type=UploadedFile.FileType.PDF,
        )

        with self.assertRaises(ValidationError) as caught:
            employee.full_clean()

        self.assertIn("avatar_file", caught.exception.error_dict)

    def test_kolom_lama_tidak_bisa_ditulis_lewat_api(self):
        """
        Penjagaannya di serializer, bukan cuma di schema: schema
        menyembunyikan tombolnya, dan tombol tersembunyi masih bisa
        ditembak lewat PATCH langsung.
        """
        from apps.hr.api.employee.serializers.employee import (
            EmployeeSerializer,
        )

        self.assertIn("avatar", EmployeeSerializer.Meta.read_only_fields)
        self.assertIn("avatar_file", EmployeeSerializer.Meta.fields)

    # ------------------------------------------------------------------
    # Lewat HTTP
    # ------------------------------------------------------------------

    def test_payload_me_memuat_avatar(self):
        user = self.make_user()
        employee = self.make_employee(user=user)
        employee.avatar_file = self.make_upload()
        employee.save(update_fields=["avatar_file"])

        data = self.http.get(ME, **self.as_user(user)).json()["data"]

        self.assertEqual(
            set(data.keys()),
            {"id", "employee_number", "full_name", "is_active", "avatar"},
        )

        self.assertEqual(
            set(data["avatar"].keys()),
            {"url", "source", "initials"},
        )

        # Alamat mutlak: frontend berdiri di origin lain, jadi jalur
        # relatif menunjuk ke dirinya sendiri lalu gagal diam-diam.
        self.assertTrue(data["avatar"]["url"].startswith("http"))

        # Dan menunjuk rute Self Service, **bukan** `preview/` milik
        # uploads: yang terakhir hak bacanya diturunkan dari hak baca
        # baris Employee, jadi ia membawa kembali ketergantungan pada
        # `hr.view_employee` yang sengaja dilepas di Stage 2.
        self.assertTrue(data["avatar"]["url"].endswith("/api/me/avatar/"))
        self.assertNotIn("/api/uploads/", data["avatar"]["url"])

    def test_payload_me_tanpa_foto(self):
        user = self.make_user()
        self.make_employee(user=user)

        data = self.http.get(ME, **self.as_user(user)).json()["data"]

        self.assertIsNone(data["avatar"]["url"])
        self.assertEqual(data["avatar"]["initials"], "BN")

    # ------------------------------------------------------------------
    # Kode mesin pada galat
    # ------------------------------------------------------------------

    def test_kode_galat_akun_tanpa_pegawai(self):
        response = self.http.get(ME, **self.as_user(self.make_user()))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "employee_not_linked")

    def test_kode_galat_pegawai_nonaktif(self):
        user = self.make_user()

        employee = self.make_employee(user=user)
        employee.is_active = False
        employee.save(update_fields=["is_active"])

        response = self.http.get(ME, **self.as_user(user))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "employee_inactive")

    def test_pengambilan_foto_diatur_hak_baca_employee(self):
        """
        **Temuan batas, dikunci di sini supaya tidak bergeser diam-diam.**

        `FileAccessService` menurunkan hak baca sebuah berkas dari
        record yang memuatnya. Begitu `Employee.avatar_file` ada, foto
        pegawai otomatis ikut aturan baca `EmployeeViewSet` — termasuk
        `require_view_permission`, yang berarti `hr.view_employee`.

        Akibatnya `/api/me/` dan **isi** fotonya dijaga dua aturan yang
        berbeda: yang pertama sengaja lepas dari `hr.view_employee`
        (keputusan Stage 2), yang kedua tidak. Untuk seluruh role yang
        diseed hal ini tidak terasa — `READ_GRANTS["EMPLOYEE"]` memuat
        `hr.employee`, jadi pegawai membaca barisnya sendiri lewat
        cakupan `own` dan fotonya ikut terbaca. Tapi tenant yang
        mencabut izin itu dari sebuah role akan mendapat `/me` yang
        tetap 200 dengan alamat foto yang membalas 404.

        Test ini tidak menyatakan keadaan itu benar. Ia menyatakan
        **mekanismenya memang begitu**, supaya keputusan memperbaikinya
        diambil sadar dan bukan ditemukan dari layar yang gambarnya
        kosong. Lihat docs/claude/self-service.md → OPEN.
        """
        from apps.uploads.services.access_service import FileAccessService

        references = [
            (model.__name__, field)
            for model, field in FileAccessService.references()
        ]

        self.assertIn(("Employee", "avatar_file"), references)

    def test_handler_global_tidak_ikut_berubah(self):
        """
        Kunci `code` hanya untuk `/me`. Kalau ia muncul di endpoint
        lain, yang terjadi bukan fitur melainkan perubahan bentuk
        balasan seluruh API yang tidak pernah diminta siapa pun.
        """
        response = self.http.get(
            "/api/hr/employees/",
            **self.as_user(self.make_user()),
        )

        self.assertNotIn("code", response.json())


class SelfAvatarEndpointTests(TenantTestCase):
    """
    `GET /api/me/avatar/` — jaminan yang membuatnya ada.

    Dua hal, dan keduanya harus benar bersamaan: pegawai **tanpa**
    `hr.view_employee` tetap mendapat fotonya, dan pegawai mana pun
    tetap **tidak** bisa mendapat foto orang lain. Yang pertama tanpa
    yang kedua adalah lubang; yang kedua tanpa yang pertama adalah
    halaman profil dengan gambar rusak.
    """

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "self-service-avatar-endpoint"
        tenant.name = "Self Service Avatar Endpoint"

    def setUp(self):
        super().setUp()

        self.http = TenantClient(self.tenant)

    def _next(self) -> int:
        type(self)._counter += 1

        return type(self)._counter

    def make_user(self):
        n = self._next()

        return User.objects.create_user(
            username=f"ave-{n}",
            email=f"ave-{n}@example.test",
            password="pw",
        )

    def make_employee(self, *, user=None, first="Bimo", last="Nugroho"):
        n = self._next()

        return Employee.objects.create(
            user=user,
            employee_number=f"AVE{n:04d}",
            first_name=first,
            last_name=last,
        )

    def make_upload(self, payload=PNG):
        n = self._next()

        return UploadedFile.objects.create(
            file=SimpleUploadedFile(f"foto-{n}.png", payload, "image/png"),
            original_name=f"foto-{n}.png",
            extension=".png",
            mime_type="image/png",
            file_type=UploadedFile.FileType.IMAGE,
            category=UploadedFile.Category.AVATAR,
        )

    def as_user(self, user):
        token = RefreshToken.for_user(user).access_token

        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def get_avatar(self, user, query=""):
        return self.http.get(
            f"/api/me/avatar/{query}",
            **self.as_user(user),
        )

    def body(self, response) -> bytes:
        return b"".join(response.streaming_content)

    # ------------------------------------------------------------------
    # Jaminan utama
    # ------------------------------------------------------------------

    def test_tanpa_hr_view_employee_foto_tetap_terambil(self):
        """
        **Alasan endpoint ini ada.**

        Akun ini tidak memegang satu pun izin. Lewat
        `/api/uploads/<id>/preview/` fotonya tertutup — `FileAccessService`
        menurunkan hak bacanya dari hak baca baris Employee, dan tanpa
        `hr.view_employee` baris itu nol. Lewat sini ia terbuka, karena
        yang dijaga identitasnya, bukan izin modelnya.
        """
        user = self.make_user()

        employee = self.make_employee(user=user)
        employee.avatar_file = self.make_upload()
        employee.save(update_fields=["avatar_file"])

        self.assertFalse(user.has_perm("hr.view_employee"))

        # Jaminan Stage 2 tetap berlaku.
        self.assertEqual(
            self.http.get(ME, **self.as_user(user)).status_code,
            200,
        )

        response = self.get_avatar(user)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.body(response), PNG)
        self.assertEqual(response["Content-Type"], "image/png")

    def test_jalur_uploads_tetap_tertutup(self):
        """
        Endpoint baru **tidak** melonggarkan `FileAccessService`.

        Berkas yang sama, diminta lewat pintu uploads oleh orang yang
        sama, tetap tidak boleh terbuka. Kalau baris ini berubah jadi
        200, yang terjadi bukan fitur melainkan pelonggaran global yang
        menyentuh tujuh model lain yang memakai kerangka unggahan.
        """
        user = self.make_user()

        employee = self.make_employee(user=user)
        uploaded = self.make_upload()
        employee.avatar_file = uploaded
        employee.save(update_fields=["avatar_file"])

        response = self.http.get(
            f"/api/uploads/{uploaded.public_id}/preview/",
            **self.as_user(user),
        )

        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------
    # Batas identitas
    # ------------------------------------------------------------------

    def test_foto_pegawai_lain_tidak_bisa_diambil(self):
        """
        Enam bentuk pengenal dicoba sekaligus. Semuanya harus
        **diabaikan**, bukan ditolak: yang ditolak memberi tahu bahwa
        parameternya dikenali, dan yang dikenali suatu hari dipakai.
        """
        mine_bytes = PNG
        other_bytes = PNG + b"\x00"

        user = self.make_user()
        me = self.make_employee(user=user)
        me.avatar_file = self.make_upload(mine_bytes)
        me.save(update_fields=["avatar_file"])

        other_user = self.make_user()
        other = self.make_employee(user=other_user, first="Rina", last="Sari")
        other_upload = self.make_upload(other_bytes)
        other.avatar_file = other_upload
        other.save(update_fields=["avatar_file"])

        queries = [
            f"?employee={other.pk}",
            f"?employee_id={other.pk}",
            f"?id={other.pk}",
            f"?public_id={other_upload.public_id}",
            f"?uploaded_file={other_upload.pk}",
            f"?file={other_upload.file.name}",
        ]

        for query in queries:
            with self.subTest(query=query):
                response = self.get_avatar(user, query)

                self.assertEqual(response.status_code, 200)

                # Yang terkirim tetap fotonya sendiri — dibandingkan
                # isinya, bukan status: 200 yang berisi berkas orang
                # lain adalah persis kebocoran yang sedang diuji.
                self.assertEqual(self.body(response), mine_bytes)

    def test_rute_beridentitas_tidak_ada(self):
        user = self.make_user()
        self.make_employee(user=user)

        other = self.make_employee(user=self.make_user())

        for path in (
            f"/api/me/avatar/{other.pk}/",
            f"/api/me/{other.pk}/avatar/",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    self.http.get(path, **self.as_user(user)).status_code,
                    404,
                )

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def test_kolom_lama_ikut_disajikan(self):
        user = self.make_user()

        employee = self.make_employee(user=user)
        employee.avatar = SimpleUploadedFile("lama.png", PNG, "image/png")
        employee.save(update_fields=["avatar"])

        response = self.get_avatar(user)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.body(response), PNG)

    def test_avatar_file_menang(self):
        baru = PNG
        lama = PNG + b"\x00"

        user = self.make_user()

        employee = self.make_employee(user=user)
        employee.avatar = SimpleUploadedFile("lama.png", lama, "image/png")
        employee.avatar_file = self.make_upload(baru)
        employee.save(update_fields=["avatar", "avatar_file"])

        self.assertEqual(self.body(self.get_avatar(user)), baru)

    def test_berkas_terhapus_jatuh_ke_kolom_lama(self):
        lama = PNG + b"\x00"

        user = self.make_user()

        employee = self.make_employee(user=user)
        employee.avatar = SimpleUploadedFile("lama.png", lama, "image/png")

        uploaded = self.make_upload()
        uploaded.soft_delete()
        employee.avatar_file = uploaded

        employee.save(update_fields=["avatar", "avatar_file"])

        self.assertEqual(self.body(self.get_avatar(user)), lama)

    def test_tanpa_foto_balas_404_berkode(self):
        """
        404 dan bukan gambar bawaan: yang menentukan tampilan "tanpa
        foto" adalah layar, dan `/api/me/` sudah mengirim `initials`
        untuk itu.
        """
        user = self.make_user()
        self.make_employee(user=user)

        response = self.get_avatar(user)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "avatar_not_set")

    def test_payload_me_tanpa_foto_tidak_mengirim_url(self):
        user = self.make_user()
        self.make_employee(user=user)

        data = self.http.get(ME, **self.as_user(user)).json()["data"]

        self.assertIsNone(data["avatar"]["url"])
        self.assertIsNone(data["avatar"]["source"])

    # ------------------------------------------------------------------
    # Penjagaan yang sama dengan /me
    # ------------------------------------------------------------------

    def test_tanpa_login(self):
        self.assertEqual(self.http.get("/api/me/avatar/").status_code, 401)

    def test_akun_tanpa_pegawai(self):
        response = self.get_avatar(self.make_user())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "employee_not_linked")

    def test_pegawai_nonaktif(self):
        user = self.make_user()

        employee = self.make_employee(user=user)
        employee.avatar_file = self.make_upload()
        employee.is_active = False
        employee.save(update_fields=["avatar_file", "is_active"])

        response = self.get_avatar(user)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "employee_inactive")

    def test_kepala_respons_tidak_mengizinkan_cache_bersama(self):
        user = self.make_user()

        employee = self.make_employee(user=user)
        employee.avatar_file = self.make_upload()
        employee.save(update_fields=["avatar_file"])

        response = self.get_avatar(user)

        self.assertIn("private", response["Cache-Control"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
