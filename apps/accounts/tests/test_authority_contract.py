"""
Kontrak kewenangan yang **berlaku**, lepas dari skema yang sudah tiada.

Berkas ini gabungan dari dua berkas yang dihapus di gelombang C:
`test_legacy_retirement.py` dan `test_legacy_schema_readiness.py`.
Keduanya menjaga dua hal sekaligus, dan cuma satu yang boleh ikut
hilang bersama tabelnya:

* **yang ikut hilang** — pembuktian bahwa mekanisme lama *inert*:
  baris `RoleDataPermission` yang tidak menggeser apa pun, baris
  `UserDataPermission` yang tidak melebarkan apa pun, penjaga
  penulisan, perkakas banding cutover, dan pengelompokan kesiapan
  tenant. Sesudah tabelnya tidak ada, tidak ada lagi yang bisa
  dibuktikan tidak berpengaruh, dan assertion pengganti yang tidak
  bisa merah lebih buruk daripada tidak ada test.
* **yang tidak boleh hilang** — kontrak kewenangan sekarang. Itu isi
  berkas ini.

Yang dikunci di sini:

1. kewenangan kosong selalu gagal-**tertutup**;
2. keanggotaan tanpa WHERE tidak membuka satu baris pun;
3. `EXPLICIT` tanpa satu pun baris tetap gagal-tertutup — bukan
   "tanpa batasan";
4. tidak ada peminjaman kewenangan antar role;
5. pembuatan penugasan normal tidak membaca cakupan lama;
6. API kewenangan tetap bekerja;
7. permukaan administrasi lama tetap tidak tersedia;
8. kewenangan `RoleAssignment` satu-satunya sumber WHERE saat runtime.

Nomor 5 dan 8 diperiksa dari **SQL yang benar-benar dijalankan**, dan
nama tabelnya ditulis sebagai literal — bukan diambil dari
`Model._meta.db_table`. Penjaga yang mengambil namanya dari model yang
dihapus ikut lenyap bersama model itu, persis di rilis ketika seseorang
paling mungkin menuliskan ulang tabel lama dengan nama yang sama.

Tiap skenario punya assertion negatifnya. Test cakupan yang hanya
memeriksa "yang berhak melihat memang melihat" akan tetap hijau pada
mesin yang tidak menyaring apa pun.
"""

from __future__ import annotations

import re
from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import (
    AuthorityMode,
    Role,
    RoleAssignment,
    RoleAssignmentAuthority,
)
from apps.accounts.scoping import DataScopeService
from apps.accounts.services.role_assignment import assign_roles, grant_role
from apps.administration.models import Company, Department, Location, Position
from apps.hr.models import Employee, OrganizationAssignment


JOIN = date(2020, 1, 6)

EMPLOYEE_SCOPE = {
    "company": "organization__company",
    "location": "organization__location",
    "department": "organization__department",
    "own": "user_id",
}

# Nama tabel dan kolom lama sebagai **literal**. Lihat docstring modul:
# penjaga yang menurunkan namanya dari model tidak selamat dari
# penghapusan model itu.
LEGACY_TABLES = re.compile(
    r"accounts_role_data_permission|accounts_user_data_permission")

LEGACY_COLUMNS = re.compile(r"data_scope_mode|data_scope_level")

UPDATE = re.compile(r"^\s*UPDATE", re.IGNORECASE)


@override_settings(ROLE_AWARE_DATA_SCOPE=True)
class AuthorityContractTestCase(TenantTestCase):
    """Dua company, dua lokasi, dan orang di tiap sudutnya."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company_a = Company.objects.create(code="AC-A", name="AC A")
        cls.company_b = Company.objects.create(code="AC-B", name="AC B")

        cls.site_a = Location.objects.create(
            code="AC-LOC-A", name="AC Site A", company=cls.company_a)

        cls.site_b = Location.objects.create(
            code="AC-LOC-B", name="AC Site B", company=cls.company_b)

        cls.department = Department.objects.create(
            code="AC-DEP", name="AC Dept", company=cls.company_a)

        cls.position = Position.objects.create(
            code="AC-POS", name="AC Pos", company=cls.company_a)

        cls.view_employee = Permission.objects.get(
            content_type__app_label="hr", codename="view_employee")

        cls.view_payslip = Permission.objects.get(
            content_type__app_label="payroll", codename="view_payslip")

        cls.counter = 0

        cls.admin = cls.make_employee(cls.company_a, cls.site_a).user

        cls.admin.is_superuser = True
        cls.admin.save(update_fields=["is_superuser"])

    # ------------------------------------------------------------------
    # Perkakas
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(cls, company, location):
        cls.counter += 1

        number = f"AC{cls.counter:04d}"

        user = get_user_model().objects.create_user(
            username=f"ac.user{cls.counter}",
            email=f"ac{cls.counter}@example.com",
            password="x",
        )

        employee = Employee.objects.create(
            employee_number=number, first_name="AC", last_name=number,
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee, company=company, location=location,
            department=cls.department, position=cls.position,
            organization_effective_date=JOIN,
        )

        return employee

    @classmethod
    def make_role(cls, code, *, permissions=()):
        """
        `Role` menjawab WHAT, dan **hanya** WHAT.

        Tidak ada parameter cakupan, dan itu bukan penyederhanaan: tidak
        ada lagi tempat di `Role` untuk menyimpannya. Tiap test di bawah
        menyebut WHERE-nya sendiri.

        Izin bacanya selalu diberikan, juga disengaja. Role tanpa izin
        akan membuat tiap assertion "tidak melihat apa pun" hijau karena
        izinnya yang menolak — bukan karena kewenangannya kosong.
        """
        role = Role.objects.create(code=code, name=code.title())

        if permissions:
            role.permissions.add(*permissions)

        return role

    def setUp(self):
        super().setUp()

        self.clear_caches()

    @staticmethod
    def clear_caches():
        for user in get_user_model().objects.all():
            for attribute in ("_role_perm_cache", "_data_scope_cache"):
                if hasattr(user, attribute):
                    delattr(user, attribute)

    def visible(self, user, *, permission="hr.view_employee"):
        self.clear_caches()

        fresh = get_user_model().objects.get(pk=user.pk)

        return set(
            DataScopeService.filter(
                Employee.objects.filter(is_deleted=False),
                EMPLOYEE_SCOPE,
                fresh,
                required_permission=permission,
            ).values_list("employee_number", flat=True)
        )

    def client_as_admin(self) -> APIClient:
        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

        client.force_authenticate(user=self.admin)

        return client

    def assertTouchesNoLegacySchema(self, queries, label):
        """
        Nol sentuhan ke tabel lama, nol **`UPDATE`** ke kolom lama.

        `SELECT` sengaja tidak dihitung untuk kolomnya, dan itu bukan
        kelonggaran: selama kolomnya masih ada di model, `SELECT`
        apa pun atas `accounts_role` menyebut namanya — Django memilih
        kolom satu per satu, bukan `*`. Menuntut nol sebutan berarti
        menuntut skemanya sudah hilang, jadi penjaganya tidak bisa
        hijau sebelum gelombang C selesai, dan penjaga yang tidak bisa
        hijau tidak menjaga apa pun.

        Yang benar-benar bisa berubah tanpa siapa pun sadar tertangkap
        di sini: **tabel** lama disentuh sama sekali, atau kolom lama
        ditulisi. Sesudah gelombang C, sisi tabelnya yang bertahan jadi
        penjaga sungguhan — nama tabelnya literal, jadi menuliskan
        ulang tabel lama dengan nama yang sama akan merah.
        """
        sql = [entry["sql"] for entry in queries]

        tables = [statement for statement in sql
                  if LEGACY_TABLES.search(statement)]

        writes = [statement for statement in sql
                  if LEGACY_COLUMNS.search(statement)
                  and UPDATE.match(statement)]

        self.assertEqual(
            tables, [],
            f"{label} menyentuh tabel kewenangan lama:\n"
            + "\n".join(statement[:200] for statement in tables[:5]),
        )

        self.assertEqual(
            writes, [],
            f"{label} menulis kolom cakupan lama:\n"
            + "\n".join(statement[:200] for statement in writes[:5]),
        )


# ----------------------------------------------------------------------
# 1-3. Gagal-tertutup, dari tiap arah
# ----------------------------------------------------------------------


class FailClosedTests(AuthorityContractTestCase):
    """
    Lubang yang dicatat Stage 4F, dan tetap dijaga sesudah sebabnya
    dihapus.

    Rangkaiannya dulu pendek dan seluruhnya normal: role baru lahir
    tanpa satu pun baris cakupan, penugasan lahir dengan kewenangan
    kosong, kosong berarti "ikut Role", dan arti lama "ditentukan
    sendiri tanpa satu pun baris" adalah **tanpa batasan**. Hasilnya:
    role yang dibuat lewat layar dan diberikan lewat layar membuka
    seluruh tenant.

    Stage 4G menutupnya dari dua sisi, dan keduanya masih perlu:
    penugasan tidak lahir kosong lagi, **dan** kosong yang bagaimanapun
    sampai ke runtime berarti tertutup. Sisi pertama bisa dilewati jalur
    baru yang ditulis orang besok; sisi kedua yang menolong baris yang
    sudah telanjur kosong.
    """

    def test_a_brand_new_role_and_assignment_opens_nothing(self):
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("AC-HOLE", permissions=[self.view_employee])

        assign_roles(holder.user, [role.pk])

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        self.assertEqual(assignment.authority_mode, "")
        self.assertFalse(assignment.authorities.exists())

        self.assertNotIn(
            far.employee_number,
            self.visible(holder.user),
            msg=(
                "Role baru tanpa kewenangan yang dinyatakan tidak boleh "
                "membuka tenant lain. Ini lubang Stage 4F."
            ),
        )

        self.assertEqual(self.visible(holder.user), set())

    def test_blank_authority_that_still_exists_is_denied(self):
        """
        Sisi kedua: penugasan kosong peninggalan tenant lama.

        Dibuat langsung ke tabelnya, melewati setiap jalur normal —
        persis bentuk baris yang tertinggal di tenant yang di-seed
        sebelum Stage 4G. Runtime harus **menutup**, bukan menebak.
        """
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("AC-STALE", permissions=[self.view_employee])

        RoleAssignment.objects.create(user=holder.user, role=role)

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        self.assertEqual(assignment.authority_mode, "")

        self.assertNotIn(far.employee_number, self.visible(holder.user))
        self.assertEqual(self.visible(holder.user), set())

    def test_membership_without_a_stated_where_opens_nothing(self):
        """Jalur `.roles.add()` telanjang — keanggotaan tanpa WHERE."""
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role("AC-CLOSED", permissions=[self.view_employee])

        holder.user.roles.add(role)

        self.assertEqual(self.visible(holder.user), set())

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        self.assertEqual(assignment.authority_mode, "")

    def test_explicit_with_zero_rows_is_denied_not_unrestricted(self):
        """
        Arah kegagalan yang **dibalik dengan sadar**.

        Aturan cakupan yang lama membaca "ditentukan sendiri, tanpa satu
        pun baris" sebagai *tanpa batasan* — dua keadaan berlawanan
        dinyatakan sama. Di sini artinya **tanpa kewenangan**, dan itu
        dikunci dari dua sisi: himpunan yang terlihat kosong, dan
        `DataScopeService` menyatakannya `denied`, bukan `unrestricted`.

        Membedakan keduanya penting: `unrestricted` yang salah terbaca
        sebagai layar penuh, `denied` yang salah terbaca sebagai layar
        kosong. Cuma satu dari keduanya yang jadi insiden keamanan.
        """
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("AC-EXP-ZERO", permissions=[self.view_employee])

        grant_role(
            holder.user, role, mode=AuthorityMode.EXPLICIT, authorities=[])

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        self.assertEqual(assignment.authority_mode, AuthorityMode.EXPLICIT)
        self.assertFalse(assignment.authorities.exists())

        self.assertNotIn(far.employee_number, self.visible(holder.user))
        self.assertEqual(self.visible(holder.user), set())

        self.clear_caches()

        scope = DataScopeService.for_user(
            get_user_model().objects.get(pk=holder.user.pk),
            permission="hr.view_employee",
        )

        self.assertTrue(scope.denied)
        self.assertFalse(scope.unrestricted)


# ----------------------------------------------------------------------
# 4. Tidak ada peminjaman antar role
# ----------------------------------------------------------------------


class NoCrossRoleBorrowingTests(AuthorityContractTestCase):
    def test_a_wide_role_does_not_widen_another_roles_permission(self):
        """
        Kewenangan satu penugasan tidak berjalan untuk izin role lain.

        Ini kebocoran yang ditutup Stage 4D: izin dan cakupan dulu
        disusun terpisah lalu dipertemukan di akhir, jadi keduanya tidak
        pernah tahu berasal dari role yang mana. Satu role luas untuk
        kemampuan lain membuat **setiap** izin ikut selebar itu.
        """
        holder = self.make_employee(self.company_a, self.site_a)
        outsider = self.make_employee(self.company_b, self.site_b)

        narrow = self.make_role("AC-NARROW", permissions=[self.view_employee])
        wide = self.make_role("AC-WIDE", permissions=[self.view_payslip])

        grant_role(
            holder.user, narrow,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("company", self.company_a.pk)],
        )

        # Luas, tapi untuk kemampuan yang sama sekali lain.
        grant_role(holder.user, wide, mode=AuthorityMode.UNRESTRICTED)

        self.assertNotIn(
            outsider.employee_number,
            self.visible(holder.user),
            "kewenangan role payroll bocor ke izin hr.view_employee",
        )

        # Sisi positifnya, supaya kegagalan "menyempitkan semua" juga
        # terlihat: yang memang dalam jangkauan tetap terlihat.
        self.assertIn(
            holder.employee_number, self.visible(holder.user))


# ----------------------------------------------------------------------
# 5 & 8. Skema lama tidak disentuh, baik saat membuat maupun membaca
# ----------------------------------------------------------------------


class RoleAssignmentIsTheOnlyRuntimeWhereTests(AuthorityContractTestCase):
    def test_creation_touches_no_legacy_schema(self):
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role("AC-CREATE", permissions=[self.view_employee])

        with CaptureQueriesContext(connection) as ctx:
            assign_roles(holder.user, [{
                "role": role.pk,
                "authority_mode": AuthorityMode.EXPLICIT,
                "authorities": [
                    {"resource_type": "company",
                     "resource_id": self.company_a.pk},
                ],
            }])

        self.assertTouchesNoLegacySchema(ctx.captured_queries, "assign_roles")

    def test_reading_data_touches_no_legacy_schema(self):
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role("AC-READ", permissions=[self.view_employee])

        grant_role(
            holder.user, role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("company", self.company_a.pk)],
        )

        self.clear_caches()

        fresh = get_user_model().objects.get(pk=holder.user.pk)

        with CaptureQueriesContext(connection) as ctx:
            list(
                DataScopeService.filter(
                    Employee.objects.filter(is_deleted=False),
                    EMPLOYEE_SCOPE,
                    fresh,
                    required_permission="hr.view_employee",
                )
            )

        self.assertTouchesNoLegacySchema(
            ctx.captured_queries, "DataScopeService.filter")

    def test_the_assignment_authority_decides_what_is_visible(self):
        """
        Pernyataan **positif** yang melengkapi dua penjaga SQL di atas.

        Keduanya membuktikan sesuatu tidak dibaca. Yang ini membuktikan
        yang menggantikannya benar-benar yang menentukan: menyempitkan
        kewenangan penugasan menyempitkan yang terlihat, dan
        melebarkannya melebarkannya — orang yang sama, role yang sama.
        """
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("AC-TRUTH", permissions=[self.view_employee])

        grant_role(
            holder.user, role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("company", self.company_a.pk)],
        )

        self.assertNotIn(far.employee_number, self.visible(holder.user))

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        RoleAssignmentAuthority.objects.create(
            assignment=assignment,
            resource_type="company",
            resource_id=self.company_b.pk,
        )

        self.assertIn(far.employee_number, self.visible(holder.user))


# ----------------------------------------------------------------------
# 6. API kewenangan tetap bekerja
# ----------------------------------------------------------------------


class AuthorityApiTests(AuthorityContractTestCase):
    def test_the_authority_api_saves_membership_and_authority(self):
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role("AC-API", permissions=[self.view_employee])

        response = self.client_as_admin().post(
            "/api/accounts/user-roles/save/",
            {
                "user": holder.user.pk,
                "roles": [{
                    "role": role.pk,
                    "authority_mode": AuthorityMode.EXPLICIT,
                    "authorities": [
                        {"resource_type": "company",
                         "resource_id": self.company_a.pk},
                    ],
                }],
            },
            format="json",
        )

        self.assertIn(response.status_code, (200, 201), response.content[:300])

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        self.assertEqual(assignment.authority_mode, AuthorityMode.EXPLICIT)

        self.assertEqual(
            RoleAssignmentAuthority.objects
            .filter(assignment=assignment).count(),
            1,
        )


# ----------------------------------------------------------------------
# 7. Permukaan administrasi lama tetap tidak tersedia
# ----------------------------------------------------------------------


class LegacyAdminSurfaceStaysGoneTests(AuthorityContractTestCase):
    """
    Tiga penjaga yang **masih bisa merah** sesudah skemanya hilang.

    Rute, modul schema, dan field serializer tidak butuh tabelnya untuk
    hidup kembali: satu baris `include()`, satu berkas schema, atau satu
    nama di `fields` sudah cukup. Yang dijaga di sini bukan tabelnya
    melainkan permukaannya — dan angka yang tidak menentukan apa pun,
    ditampilkan di tempat kebijakan diatur, akan dibaca sebagai
    kebijakan.
    """

    def test_the_data_permission_tree_route_is_gone(self):
        role = self.make_role("AC-SURF")

        response = self.client_as_admin().get(
            f"/api/accounts/data-permissions/tree/?role={role.pk}")

        self.assertEqual(response.status_code, 404)

    def test_the_framework_schema_module_is_gone(self):
        """
        Rutenya dibuang **dan** modul schema-nya ikut hilang. Kalau cuma
        rutenya, generator frontend masih menawarkan layarnya.
        """
        response = self.client_as_admin().get(
            "/api/framework/schema/administration/security/data-permission/")

        self.assertEqual(response.status_code, 404)

    def test_the_role_api_exposes_no_scope_fields(self):
        role = self.make_role("AC-ROLEAPI")

        response = self.client_as_admin().get(
            f"/api/accounts/roles/{role.pk}/")

        self.assertEqual(response.status_code, 200, response.content[:200])

        body = response.json()

        payload = body.get("data", body)

        for key in (
            "data_scope_mode",
            "data_scope_level",
            "data_scope_mode_label",
            "data_scope_level_label",
        ):
            self.assertNotIn(key, payload, f"{key} masih dikirim Role API")
