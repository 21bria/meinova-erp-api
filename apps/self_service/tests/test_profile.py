"""
`GET /api/me/profile/` — kontrak, batas privasi, dan batas identitas.

Tiga hal diuji, dan ketiganya harus benar bersamaan: bentuknya stabil,
isinya tidak memuat yang tidak boleh, dan tidak ada cara menggesernya ke
orang lain. Yang pertama tanpa yang kedua adalah kebocoran yang rapi.

Penjagaan daftar putihnya diuji sebagai **daftar**, bukan per field:
yang berbahaya justru field yang belum ada hari ini.
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.administration.models import (
    BloodType,
    Company,
    CostCenter,
    Department,
    Division,
    EmploymentStatus,
    EmploymentType,
    Gender,
    JobGrade,
    JobLevel,
    Location,
    MaritalStatus,
    Nationality,
    Position,
    Religion,
    Section,
)
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    OrganizationAssignment,
)
from apps.uploads.models import UploadedFile


User = get_user_model()

PROFILE = "/api/me/profile/"

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
    b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
    b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

SECTIONS = {
    "identity",
    "photo",
    "personal",
    "contact",
    "employment",
    "organization",
    "emergency_contact",
}

# Yang **tidak boleh** muncul di mana pun dalam respons, sedalam apa pun
# ia bersarang. Diuji terhadap JSON yang sudah diratakan, bukan terhadap
# kunci tingkat atas: field yang bocor lewat objek bersarang bocor sama
# saja.
FORBIDDEN_KEYS = {
    "notes",
    "organization_notes",
    "employment_notes",
    "payroll_notes",
    "basic_salary",
    "salary_grade",
    "salary_level",
    "payroll_group",
    "payment_method",
    "currency",
    "allowance_template",
    "deduction_template",
    "overtime_group",
    "overtime_eligible",
    "tax_number",
    "tax_number_payroll",
    "tax_status",
    "bpjs_kesehatan_number",
    "bpjs_ketenagakerjaan_number",
    "nik",
    "passport_number",
    "user",
    "user_name",
    "created_by",
    "updated_by",
    "deleted_by",
    "deleted_at",
    "is_deleted",
    "avatar",
    "avatar_file",
    "avatar_display",
    "public_id",
    "file",
    "storage_path",
    "stored_name",
    "contract_start",
    "contract_end",
    "probation_start",
    "probation_end",
    "notice_period_days",
    "employee_group",
    "termination_date",
    "termination_reason",
    "retirement_date",
    "roster_crew",
    "roster_policy",
    "shift",
    "work_schedule",
    "working_calendar",
}


def walk_keys(node, prefix=""):
    """Seluruh nama kunci di dalam struktur, sedalam apa pun."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_keys(item)


class SelfProfileTestCase(TenantTestCase):
    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "self-service-profile"
        tenant.name = "Self Service Profile"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(code="SSP", name="Profile Co")
        cls.site = Location.objects.create(
            company=cls.company, code="SSP-HO", name="Head Office",
        )
        # Unit organisasi menggantung pada company — `Section` bahkan
        # pada department-nya juga. Dibuat berantai supaya panggungnya
        # sama bentuknya dengan data sungguhan, bukan baris yatim yang
        # kebetulan lolos.
        cls.division = Division.objects.create(
            company=cls.company, code="OPS", name="Operations",
        )
        cls.department = Department.objects.create(
            company=cls.company, code="ENG", name="Engineering",
        )
        cls.section = Section.objects.create(
            company=cls.company,
            department=cls.department,
            code="PLT",
            name="Plant",
        )
        cls.position = Position.objects.create(
            company=cls.company, code="SPV", name="Supervisor",
        )
        cls.job_level = JobLevel.objects.create(code="L3", name="Level 3")
        cls.job_grade = JobGrade.objects.create(code="G7", name="Grade 7")
        cls.cost_center = CostCenter.objects.create(
            company=cls.company, code="CC1", name="Cost Centre 1",
        )

        cls.gender = Gender.objects.create(code="M", name="Laki-laki")
        cls.religion = Religion.objects.create(code="ISL", name="Islam")
        cls.nationality = Nationality.objects.create(code="ID", name="Indonesia")
        cls.blood = BloodType.objects.create(code="O", name="O")
        cls.marital = MaritalStatus.objects.create(code="S", name="Single")

        cls.status = EmploymentStatus.objects.create(code="ACT", name="Active")
        cls.etype = EmploymentType.objects.create(code="PKWTT", name="Permanent")

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
            username=f"sp-{n}",
            email=f"sp-{n}@example.test",
            password="pw",
        )

    def make_employee(self, *, user=None, first="Bimo", last="Nugroho", full=False):
        n = self._next()

        employee = Employee.objects.create(
            user=user,
            employee_number=f"SP{n:04d}",
            first_name=first,
            last_name=last,
            personal_email=f"{first.lower()}@pribadi.test",
            work_email=f"{first.lower()}@kantor.test",
            phone=f"021-{n:04d}",
            mobile=f"0812-{n:04d}",
            address=f"Jalan {first} No. {n}",
            birth_place=f"Kota {first}",
            emergency_contact_name=f"Kontak {first}",
            emergency_contact_phone=f"0899-{n:04d}",
            # Yang tidak boleh bocor — diisi supaya kebocorannya
            # terdeteksi lewat nilainya, bukan cuma lewat nama kuncinya.
            notes="RAHASIA-CATATAN-HR",
            nik=f"NIK-{n}",
            passport_number=f"PASPOR-{n}",
            tax_number=f"NPWP-{n}",
        )

        if not full:
            return employee

        employee.gender = self.gender
        employee.religion = self.religion
        employee.nationality = self.nationality
        employee.blood_type = self.blood
        employee.marital_status = self.marital
        employee.save()

        return employee

    def attach_org(self, employee, *, supervisor=None):
        return OrganizationAssignment.objects.create(
            employee=employee,
            company=self.company,
            location=self.site,
            division=self.division,
            department=self.department,
            section=self.section,
            position=self.position,
            job_level=self.job_level,
            job_grade=self.job_grade,
            cost_center=self.cost_center,
            reports_to=supervisor,
            organization_effective_date="2026-01-01",
            organization_notes="RAHASIA-CATATAN-ORG",
        )

    def attach_employment(self, employee):
        return EmploymentAssignment.objects.create(
            employee=employee,
            employment_status=self.status,
            employment_type=self.etype,
            join_date="2020-01-06",
            employment_effective_date="2020-01-06",
            job_location="Site A",
            employment_notes="RAHASIA-CATATAN-KEPEGAWAIAN",
        )

    def as_user(self, user):
        token = RefreshToken.for_user(user).access_token

        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def get_profile(self, user, query=""):
        return self.http.get(f"{PROFILE}{query}", **self.as_user(user))

    def full_employee(self):
        """Pegawai lengkap beserta atasannya, sudah tertaut akun."""
        user = self.make_user()

        supervisor = self.make_employee(first="Rina", last="Sari")

        employee = self.make_employee(user=user, full=True)
        self.attach_org(employee, supervisor=supervisor)
        self.attach_employment(employee)

        return user, employee, supervisor

    # ------------------------------------------------------------------
    # Otorisasi
    # ------------------------------------------------------------------

    def test_tanpa_login(self):
        self.assertEqual(self.http.get(PROFILE).status_code, 401)

    def test_akun_tanpa_pegawai(self):
        response = self.get_profile(self.make_user())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "employee_not_linked")

    def test_pegawai_terhapus(self):
        user = self.make_user()

        employee = self.make_employee(user=user)
        employee.is_deleted = True
        employee.save(update_fields=["is_deleted"])

        response = self.get_profile(user)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "employee_not_linked")

    def test_pegawai_nonaktif(self):
        user = self.make_user()

        employee = self.make_employee(user=user)
        employee.is_active = False
        employee.save(update_fields=["is_active"])

        response = self.get_profile(user)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "employee_inactive")

    def test_tanpa_izin_hr_apa_pun(self):
        """Batas identitas Stage 2 harus tetap berlaku di sini."""
        user, _employee, _sup = self.full_employee()

        self.assertFalse(user.has_perm("hr.view_employee"))

        self.assertEqual(self.get_profile(user).status_code, 200)

    # ------------------------------------------------------------------
    # Batas identitas
    # ------------------------------------------------------------------

    def test_identitas_tidak_bisa_digeser(self):
        """
        Pegawai A dan B dengan nilai yang jelas berbeda. Apa pun yang
        dititipkan di query, yang kembali tetap A.
        """
        user_a, employee_a, _ = self.full_employee()

        user_b = self.make_user()
        employee_b = self.make_employee(user=user_b, first="Citra", last="Dewi")

        for query in (
            f"?employee={employee_b.pk}",
            f"?employee_id={employee_b.pk}",
            f"?id={employee_b.pk}",
            f"?user={user_b.pk}",
            f"?employee_number={employee_b.employee_number}",
        ):
            with self.subTest(query=query):
                response = self.get_profile(user_a, query)

                self.assertEqual(response.status_code, 200)

                identity = response.json()["data"]["identity"]

                self.assertEqual(identity["id"], employee_a.pk)
                self.assertEqual(
                    identity["employee_number"],
                    employee_a.employee_number,
                )
                self.assertNotEqual(identity["id"], employee_b.pk)

    def test_rute_beridentitas_tidak_ada(self):
        user, _e, _s = self.full_employee()

        other = self.make_employee(user=self.make_user())

        for path in (f"{PROFILE}{other.pk}/", f"/api/me/{other.pk}/profile/"):
            with self.subTest(path=path):
                self.assertEqual(
                    self.http.get(path, **self.as_user(user)).status_code,
                    404,
                )

    # ------------------------------------------------------------------
    # Daftar putih
    # ------------------------------------------------------------------

    def test_seksi_yang_dikirim_persis(self):
        user, _e, _s = self.full_employee()

        data = self.get_profile(user).json()["data"]

        self.assertEqual(set(data.keys()), SECTIONS)

    def test_tidak_ada_field_terlarang_sedalam_apa_pun(self):
        user, _e, _s = self.full_employee()

        data = self.get_profile(user).json()["data"]

        leaked = FORBIDDEN_KEYS & set(walk_keys(data))

        self.assertEqual(leaked, set(), f"field bocor: {sorted(leaked)}")

    def test_nilai_rahasia_tidak_muncul_di_badan_respons(self):
        """
        Diuji terhadap **teks mentahnya**, bukan cuma nama kuncinya:
        catatan HR yang terbawa lewat kunci bernama lain tetap
        kebocoran.
        """
        user, _e, _s = self.full_employee()

        body = json.dumps(self.get_profile(user).json())

        for secret in (
            "RAHASIA-CATATAN-HR",
            "RAHASIA-CATATAN-ORG",
            "RAHASIA-CATATAN-KEPEGAWAIAN",
        ):
            self.assertNotIn(secret, body)

    def test_nomor_identitas_pemerintah_tidak_ikut(self):
        user, employee, _s = self.full_employee()

        body = json.dumps(self.get_profile(user).json())

        self.assertNotIn(employee.nik, body)
        self.assertNotIn(employee.passport_number, body)
        self.assertNotIn(employee.tax_number, body)

    # ------------------------------------------------------------------
    # Isi
    # ------------------------------------------------------------------

    def test_isi_seksi_benar(self):
        user, employee, supervisor = self.full_employee()

        data = self.get_profile(user).json()["data"]

        self.assertEqual(data["identity"]["full_name"], employee.full_name)
        self.assertEqual(data["personal"]["gender"]["code"], "M")
        self.assertEqual(data["personal"]["religion"]["name"], "Islam")
        self.assertEqual(data["contact"]["personal_email"], employee.personal_email)
        self.assertEqual(data["contact"]["address"], employee.address)

        self.assertEqual(data["employment"]["status"]["code"], "ACT")
        self.assertEqual(data["employment"]["type"]["name"], "Permanent")
        self.assertEqual(data["employment"]["join_date"], "2020-01-06")
        self.assertEqual(data["employment"]["job_location"], "Site A")

        org = data["organization"]
        self.assertEqual(org["company"]["name"], "Profile Co")
        self.assertEqual(org["department"]["code"], "ENG")
        self.assertEqual(org["position"]["name"], "Supervisor")
        self.assertEqual(org["job_grade"]["code"], "G7")
        self.assertEqual(org["cost_center"]["code"], "CC1")

        self.assertEqual(
            data["emergency_contact"]["name"],
            employee.emergency_contact_name,
        )

    def test_atasan_ditampilkan(self):
        user, _employee, supervisor = self.full_employee()

        sup = self.get_profile(user).json()["data"]["organization"]["supervisor"]

        self.assertEqual(sup["id"], supervisor.pk)
        self.assertEqual(sup["employee_number"], supervisor.employee_number)
        self.assertEqual(sup["full_name"], supervisor.full_name)

        # Atasan ditampilkan seperlunya — bukan kartu pegawainya.
        self.assertEqual(
            set(sup.keys()),
            {"id", "employee_number", "full_name"},
        )

    def test_relasi_kosong_aman(self):
        """
        Pegawai tanpa penempatan, kepegawaian, dan master apa pun.
        Seksinya tetap ada, isinya `null` — bukan seksinya yang hilang.
        """
        user = self.make_user()
        self.make_employee(user=user)

        response = self.get_profile(user)

        self.assertEqual(response.status_code, 200)

        data = response.json()["data"]

        self.assertEqual(set(data.keys()), SECTIONS)
        self.assertIsNone(data["personal"]["gender"])
        self.assertIsNone(data["organization"]["company"])
        self.assertIsNone(data["organization"]["supervisor"])
        self.assertIsNone(data["employment"]["status"])
        self.assertIsNone(data["employment"]["join_date"])

    def test_atasan_kosong_aman(self):
        user = self.make_user()

        employee = self.make_employee(user=user, full=True)
        self.attach_org(employee, supervisor=None)
        self.attach_employment(employee)

        data = self.get_profile(user).json()["data"]

        self.assertIsNone(data["organization"]["supervisor"])
        self.assertEqual(data["organization"]["company"]["name"], "Profile Co")

    # ------------------------------------------------------------------
    # Foto
    # ------------------------------------------------------------------

    def test_foto_menunjuk_endpoint_self_service(self):
        user, employee, _s = self.full_employee()

        n = self._next()

        employee.avatar_file = UploadedFile.objects.create(
            file=SimpleUploadedFile(f"f-{n}.png", PNG, "image/png"),
            original_name=f"f-{n}.png",
            extension=".png",
            mime_type="image/png",
            file_type=UploadedFile.FileType.IMAGE,
            category=UploadedFile.Category.AVATAR,
        )
        employee.save(update_fields=["avatar_file"])

        photo = self.get_profile(user).json()["data"]["photo"]

        self.assertEqual(set(photo.keys()), {"url", "source", "initials"})
        self.assertEqual(photo["source"], "upload")
        self.assertTrue(photo["url"].endswith("/api/me/avatar/"))
        self.assertNotIn("/api/uploads/", photo["url"])
        self.assertNotIn("/media/", photo["url"])

    def test_inisial_saat_tanpa_foto(self):
        user, _employee, _s = self.full_employee()

        photo = self.get_profile(user).json()["data"]["photo"]

        self.assertIsNone(photo["url"])
        self.assertIsNone(photo["source"])
        self.assertEqual(photo["initials"], "BN")

    # ------------------------------------------------------------------
    # Efisiensi
    # ------------------------------------------------------------------

    @override_settings(DEBUG=True)
    def test_jumlah_query_tidak_tumbuh_per_relasi(self):
        """
        Profil menyentuh dua puluh master. Kalau `select_related` di
        `CurrentEmployeeService` lepas, jumlahnya melonjak ke belasan —
        dan lonjakan itu tidak pernah berbunyi sebagai error, cuma
        sebagai halaman yang pelan.

        Empatnya, supaya kegagalan nanti bisa langsung dibaca:

        1. `tenants_domain` — resolusi tenant milik `TenantClient`
        2. `tenants_domain` + `tenants_client` — lanjutannya
        3. `auth_users` — pemegang token JWT
        4. `hr_employee` + 25 JOIN — pegawainya beserta seluruh master

        Yang keempat itu intinya: dua puluh lima relasi dalam **satu**
        perjalanan ke database. Kalau angka ini naik, yang hampir pasti
        terjadi adalah satu relasi lepas dari `_RELATED` dan berubah jadi
        query tersendiri.

        Ditulis persis, bukan sebagai batas atas: batas atas yang longgar
        membiarkan pertumbuhan satu-satu lewat tanpa ada yang melihatnya,
        dan justru pertumbuhan satu-satu itu yang terjadi di dunia nyata.
        """
        user, _e, _s = self.full_employee()

        with self.assertNumQueries(4):
            response = self.get_profile(user)

        self.assertEqual(response.status_code, 200)
