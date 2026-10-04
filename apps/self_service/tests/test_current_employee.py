"""
Batas identitas `/api/me/*`.

Yang diuji di sini bukan bentuk payload — itu urusan Stage 4 — melainkan
satu pertanyaan: **bisakah seseorang membuka `/me` dan mendapat orang
lain.** Karena itu seluruhnya lewat HTTP sungguhan dengan token JWT,
bukan lewat pemanggilan service: yang dijaga adalah jalur yang dipakai
layar, dan service yang benar di balik view yang salah pasang permission
tetap membocorkan.

`TenantTestCase` tidak me-rollback antar test dan tidak menjalankan
`setUpTestData`, jadi tiap test membuat orangnya sendiri dengan nama yang
unik. Pola yang sama dengan test Attendance Permission dan Roster.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.hr.models import Employee


User = get_user_model()

ME = "/api/me/"


class SelfServiceIdentityTests(TenantTestCase):
    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "self-service"
        tenant.name = "Self Service"

    def setUp(self):
        super().setUp()

        # `TenantClient`, bukan `APIClient`: request harus lewat
        # middleware django-tenants, dan client biasa mendarat di schema
        # `public` yang tabel HR-nya tidak ada di sana.
        self.http = TenantClient(self.tenant)

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    def _next(self) -> int:
        type(self)._counter += 1

        return type(self)._counter

    def make_user(self, prefix: str = "u"):
        n = self._next()

        return User.objects.create_user(
            username=f"ss-{prefix}-{n}",
            email=f"ss-{prefix}-{n}@example.test",
            password="pw-not-used-jwt",
        )

    def make_employee(self, *, user=None, is_active=True, is_deleted=False):
        n = self._next()

        return Employee.objects.create(
            user=user,
            employee_number=f"SS{n:04d}",
            first_name=f"Pegawai{n}",
            last_name="Uji",
            is_active=is_active,
            is_deleted=is_deleted,
        )

    def as_user(self, user):
        token = RefreshToken.for_user(user).access_token

        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def get_me(self, user):
        return self.http.get(ME, **self.as_user(user))

    # ------------------------------------------------------------------
    # Jalur normal
    # ------------------------------------------------------------------

    def test_employee_membaca_dirinya_sendiri(self):
        user = self.make_user("self")
        employee = self.make_employee(user=user)

        response = self.get_me(user)

        self.assertEqual(response.status_code, 200)

        data = response.json()["data"]

        self.assertEqual(data["id"], employee.pk)
        self.assertEqual(data["employee_number"], employee.employee_number)
        self.assertEqual(data["full_name"], employee.full_name)

    def test_tidak_butuh_hr_view_employee(self):
        """
        Inti keputusan Stage 2.

        Akun ini tidak memegang satu pun izin — termasuk
        `hr.view_employee` yang dituntut `EmployeeViewSet`. Ia tetap
        harus bisa membuka profilnya sendiri; kalau test ini merah,
        batas identitas Self Service diam-diam kembali menumpang izin
        baca administratif.
        """
        user = self.make_user("noperm")
        self.make_employee(user=user)

        self.assertFalse(user.has_perm("hr.view_employee"))

        self.assertEqual(self.get_me(user).status_code, 200)

    # ------------------------------------------------------------------
    # Batas identitas
    # ------------------------------------------------------------------

    def test_pegawai_lain_tidak_pernah_terbawa(self):
        """
        Dua pegawai, dua akun. Masing-masing hanya mendapat dirinya.
        """
        user_a = self.make_user("a")
        employee_a = self.make_employee(user=user_a)

        user_b = self.make_user("b")
        employee_b = self.make_employee(user=user_b)

        data_a = self.get_me(user_a).json()["data"]
        data_b = self.get_me(user_b).json()["data"]

        self.assertEqual(data_a["id"], employee_a.pk)
        self.assertEqual(data_b["id"], employee_b.pk)
        self.assertNotEqual(data_a["id"], data_b["id"])

    def test_identitas_tidak_bisa_digeser_lewat_query_param(self):
        """
        `?employee=<id>` dan kawan-kawannya harus **tidak berpengaruh**,
        bukan ditolak: yang ditolak memberi tahu bahwa parameternya
        dikenali, dan yang dikenali suatu hari akan dipakai.
        """
        user = self.make_user("qp")
        mine = self.make_employee(user=user)

        other = self.make_employee(user=self.make_user("qp-other"))

        for query in (
            f"?employee={other.pk}",
            f"?employee_id={other.pk}",
            f"?id={other.pk}",
            f"?user={other.user_id}",
        ):
            with self.subTest(query=query):
                response = self.http.get(
                    f"{ME}{query}",
                    **self.as_user(user),
                )

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["data"]["id"], mine.pk)

    def test_tidak_ada_rute_beridentitas(self):
        """
        `/api/me/<id>/` tidak boleh ada sama sekali.
        """
        user = self.make_user("route")
        other = self.make_employee(user=self.make_user("route-other"))
        self.make_employee(user=user)

        for path in (f"{ME}{other.pk}/", f"{ME}profile/{other.pk}/"):
            with self.subTest(path=path):
                response = self.http.get(path, **self.as_user(user))

                self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------
    # Akun yang tidak punya ruang Self Service
    # ------------------------------------------------------------------

    def test_akun_tanpa_pegawai(self):
        user = self.make_user("orphan")

        response = self.get_me(user)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["success"])
        self.assertIn("belum ditautkan", response.json()["message"])

    def test_superuser_tanpa_pegawai_juga_ditolak(self):
        """
        Superuser melewati hampir setiap penjagaan di sistem ini, dan
        di sini justru tidak boleh: `/me` bukan soal wewenang, dan tidak
        ada jawaban "profil saya" untuk akun yang memang bukan pegawai.
        """
        user = self.make_user("root")
        user.is_superuser = True
        user.is_staff = True
        user.save(update_fields=["is_superuser", "is_staff"])

        self.assertEqual(self.get_me(user).status_code, 404)

    def test_kartu_yang_sudah_dihapus_terbaca_seperti_tidak_ada(self):
        """
        Justru kasus yang ditutup resolver ini: `user.employee_profile`
        mengembalikan baris ber-`is_deleted=True` apa adanya, karena
        `BaseModel` tidak memasang manager kustom.
        """
        user = self.make_user("deleted")
        self.make_employee(user=user, is_deleted=True)

        response = self.get_me(user)

        self.assertEqual(response.status_code, 404)

    def test_pegawai_nonaktif(self):
        user = self.make_user("inactive")
        self.make_employee(user=user, is_active=False)

        response = self.get_me(user)

        self.assertEqual(response.status_code, 403)
        self.assertIn("tidak aktif", response.json()["message"])

    def test_tanpa_login(self):
        self.assertEqual(self.http.get(ME).status_code, 401)

    # ------------------------------------------------------------------
    # Kebocoran field
    # ------------------------------------------------------------------

    def test_catatan_internal_hr_tidak_ikut(self):
        """
        `notes` tidak terdaftar di `SUBJECT_EMPLOYEE_FIELDS`, jadi
        `EmployeeSerializer._mask_hidden()` tidak pernah membuangnya —
        itulah kenapa Self Service memakai whitelist, bukan serializer
        admin yang disaring.
        """
        user = self.make_user("notes")

        employee = self.make_employee(user=user)
        employee.notes = "Kandidat PIP. Jangan diperpanjang."
        employee.save(update_fields=["notes"])

        body = self.get_me(user).content.decode()
        data = self.get_me(user).json()["data"]

        for leaked in ("notes", "organization_notes", "employment_notes"):
            self.assertNotIn(leaked, data)

        self.assertNotIn("Kandidat PIP", body)

    def test_payload_hanya_field_yang_disetujui(self):
        """
        Daftar putih diuji sebagai **daftar**, bukan per field: yang
        dijaga justru field yang belum ada hari ini.

        Test ini memang harus merah setiap kali ada kunci baru — dan
        sudah sekali: `avatar` ditambahkan di Stage 3, disetujui, lalu
        didaftarkan di sini. Itu alur yang dimaksudkan. Kalau suatu saat
        ia merah tanpa ada yang sengaja menambah apa pun, yang terjadi
        adalah field yang bocor lewat jalur yang tidak diperhatikan.
        """
        user = self.make_user("shape")
        self.make_employee(user=user)

        data = self.get_me(user).json()["data"]

        self.assertEqual(
            set(data.keys()),
            {
                "id",
                "employee_number",
                "full_name",
                "is_active",
                # Stage 3 — Employee Photo.
                "avatar",
            },
        )


class SelfServiceResolverTests(TenantTestCase):
    """
    Resolver-nya sendiri, di luar HTTP.

    Dipisah karena dua perilakunya tidak punya permukaan HTTP di stage
    ini: bentuk `resolve_or_none()` dan cache per-request.
    """

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "self-service-resolver"
        tenant.name = "Self Service Resolver"

    def _next(self) -> int:
        type(self)._counter += 1

        return type(self)._counter

    def make_user(self):
        n = self._next()

        return User.objects.create_user(
            username=f"rs-{n}",
            email=f"rs-{n}@example.test",
            password="pw",
        )

    def test_resolve_or_none_tidak_melempar(self):
        from apps.self_service.services import CurrentEmployeeService

        self.assertIsNone(
            CurrentEmployeeService.resolve_or_none(self.make_user()),
        )

    def test_resolve_or_none_untuk_anonim(self):
        from django.contrib.auth.models import AnonymousUser

        from apps.self_service.services import CurrentEmployeeService

        self.assertIsNone(
            CurrentEmployeeService.resolve_or_none(AnonymousUser()),
        )

    def test_hasil_disimpan_pada_request(self):
        from apps.self_service.services import CurrentEmployeeService

        user = self.make_user()
        n = self._next()

        employee = Employee.objects.create(
            user=user,
            employee_number=f"RS{n:04d}",
            first_name="Cache",
        )

        class FakeRequest:
            pass

        request = FakeRequest()
        request.user = user

        first = CurrentEmployeeService.for_request(request)

        # Baris di database dihapus setelah resolusi pertama. Kalau
        # panggilan kedua masih mengembalikan objek yang sama, cache-nya
        # memang dipakai — bukan query kedua yang kebetulan sama.
        Employee.objects.filter(pk=employee.pk).delete()

        second = CurrentEmployeeService.for_request(request)

        self.assertIs(first, second)
