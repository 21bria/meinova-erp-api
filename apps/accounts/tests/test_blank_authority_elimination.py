"""
Kewenangan kosong berarti **tertutup** — di setiap jalur, tanpa kecuali.

Rangkaian yang ditutup
----------------------
Dulu: `Role.data_scope_mode` bawaannya `explicit`, jadi role baru lahir
tanpa baris cakupan. Penugasan lahir `authority_mode` kosong. Kosong
berarti "ikut `Role`", dan arti **lama** `explicit` tanpa baris adalah
**tanpa batasan**. Hasilnya role yang dibuat dari layar dan diberikan
dari layar membuka **seluruh tenant** sampai ada yang menjalankan
backfill.

Stage 4G menutupnya dengan menurunkan kewenangan dari `Role` saat
penugasan dibuat. Stage 4H membuang turunan itu juga: `Role` menjawab
**WHAT** saja, WHERE dinyatakan pemanggil, dan yang tidak dinyatakan
tidak ada.

Yang dijaga berkas ini
----------------------
Sisi **tertutupnya**. Tidak ada satu pun jalur pembuatan yang memberi
kewenangan tanpa diminta, penugasan yang bertahan tidak tergeser oleh
suntingan `Role` kemudian, dan model kewenangan lama tidak punya jalan
ke runtime sama sekali.

Sisi sebaliknya — bagaimana WHERE **dinyatakan** saat penugasan dibuat —
diuji di `test_assignment_creation_contract`.

Kenapa dua sisi itu dipisah: yang satu menjawab "apa yang terjadi kalau
konfigurasinya belum selesai", yang lain "apa yang terjadi kalau sudah".
Jawaban pertama harus tetap benar meskipun jawaban kedua berubah bentuk,
dan menggabungkannya membuat perubahan kontrak pembuatan diam-diam ikut
melonggarkan penjagaan kegagalannya.
"""

from __future__ import annotations

import inspect

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings

from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts import scoping
from apps.accounts.models import (
    AuthorityMode,
    Role,
    RoleAssignment,
    RoleAssignmentAuthority,
)
from apps.accounts.scoping import DataScopeService
from apps.accounts.services.role_assignment import assign_roles
from apps.administration.models import Company, Department, Location, Position
from apps.hr.models import Employee, OrganizationAssignment


JOIN = date(2021, 3, 1)

EMPLOYEE_SCOPE = {
    "company": "organization__company",
    "location": "organization__location",
    "own": "user_id",
}


@override_settings(ROLE_AWARE_DATA_SCOPE=True)
class BlankAuthorityTestCase(TenantTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company_a = Company.objects.create(code="BA-A", name="BA A")
        cls.company_b = Company.objects.create(code="BA-B", name="BA B")

        cls.site_a = Location.objects.create(
            code="BA-LOC-A", name="BA Site A", company=cls.company_a)

        cls.site_b = Location.objects.create(
            code="BA-LOC-B", name="BA Site B", company=cls.company_b)

        cls.department = Department.objects.create(
            code="BA-DEP", name="BA Dept", company=cls.company_a)

        cls.position = Position.objects.create(
            code="BA-POS", name="BA Pos", company=cls.company_a)

        cls.view_employee = Permission.objects.get(
            content_type__app_label="hr", codename="view_employee")

        cls.view_payslip = Permission.objects.get(
            content_type__app_label="payroll", codename="view_payslip")

        cls.counter = 0

        cls.admin = cls.make_employee(cls.company_a, cls.site_a).user

        cls.admin.is_superuser = True
        cls.admin.save(update_fields=["is_superuser"])

    @classmethod
    def make_employee(cls, company, location):
        cls.counter += 1

        number = f"BA{cls.counter:04d}"

        user = get_user_model().objects.create_user(
            username=f"ba.user{cls.counter}",
            email=f"ba{cls.counter}@example.com",
            password="x",
        )

        employee = Employee.objects.create(
            employee_number=number, first_name="BA", last_name=number,
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

        Tidak ada parameter cakupan di sini, dan itu bukan penyederhanaan
        kosmetik: tidak ada lagi tempat di `Role` untuk menyimpannya.
        WHERE dinyatakan saat penugasan dibuat, dan tiap test di bawah
        menyebutnya sendiri.
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

    def visible(self, user, permission="hr.view_employee"):
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

    @classmethod
    def grant(cls, user, role, *, mode, level="", rows=()):
        """
        Memberi role **berikut** WHERE-nya.

        Sejak Stage 4H tidak ada yang menurunkan WHERE dari `Role`, jadi
        test yang ingin pemegangnya benar-benar melihat sesuatu harus
        menyebutkannya — sama seperti jalur produksi.
        """
        return assign_roles(user, [{
            "role": role.pk,
            "authority_mode": mode,
            "authority_level": level,
            "authorities": [
                {"resource_type": resource_type, "resource_id": resource_id}
                for resource_type, resource_id in rows
            ],
        }])

    @staticmethod
    def authority_of(user, role):
        assignment = RoleAssignment.objects.get(user=user, role=role)

        return (
            assignment.authority_mode,
            assignment.authority_level,
            sorted(
                assignment.authorities.values_list(
                    "resource_type", "resource_id")
            ),
        )


# ----------------------------------------------------------------------
# Turunan saat dibuat — satu kasus per mode Role
# ----------------------------------------------------------------------


# ----------------------------------------------------------------------
# Tiap jalur pembuatan berakhir tertutup
# ----------------------------------------------------------------------


class EveryCreationPathFailsClosedTests(BlankAuthorityTestCase):
    """
    Tidak ada jalur yang memberi kewenangan tanpa diminta.

    Sampai Stage 4G jalur-jalur ini **menurunkan** WHERE dari
    konfigurasi `Role`. Itu menutup lubang "kosong berarti terbuka",
    tapi menyisakan model kewenangan lama sebagai penentu akses — cuma
    pada momen yang lebih sempit. Stage 4H membuangnya: `Role` menjawab
    WHAT, dan WHERE yang tidak dinyatakan tidak ada.

    Tiap jalur di bawah memberi role yang **memberi izin baca** lalu
    menuntut hasilnya tetap nol baris. Itu bentuk yang benar: kalau
    yang diperiksa role tanpa izin, testnya akan hijau karena izinnya
    yang menolak, bukan karena kewenangannya kosong.

    Kontrak pembuatan yang **menyatakan** WHERE diuji terpisah, di
    `test_assignment_creation_contract`.
    """

    def _role(self, code):
        return self.make_role(code, permissions=[self.view_employee])

    def expect_closed(self, user, role):
        self.assertEqual(
            self.authority_of(user, role), ("", "", []),
            msg="Penugasan ini menerima kewenangan yang tidak diminta.",
        )

        self.assertEqual(self.visible(user), set())

    def test_assign_roles_service(self):
        holder = self.make_employee(self.company_a, self.site_a)
        role = self._role("BA-P-SERVICE")

        assign_roles(holder.user, [role.pk])

        self.expect_closed(holder.user, role)

    def test_plain_m2m_add(self):
        holder = self.make_employee(self.company_a, self.site_a)
        role = self._role("BA-P-ADD")

        holder.user.roles.add(role)

        self.expect_closed(holder.user, role)

    def test_plain_m2m_set(self):
        holder = self.make_employee(self.company_a, self.site_a)
        role = self._role("BA-P-SET")

        holder.user.roles.set([role])

        self.expect_closed(holder.user, role)

    def test_reverse_m2m_add(self):
        """`role.users.add(user)` membuat baris yang sama dari sisi lain."""
        holder = self.make_employee(self.company_a, self.site_a)
        role = self._role("BA-P-REVERSE")

        role.users.add(holder.user)

        self.expect_closed(holder.user, role)

    def test_user_role_save_api(self):
        holder = self.make_employee(self.company_a, self.site_a)
        role = self._role("BA-P-API")

        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)
        client.force_authenticate(user=self.admin)

        response = client.post(
            "/api/accounts/user-roles/save/",
            {"user": holder.user.pk, "roles": [role.pk]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content[:300])

        self.expect_closed(holder.user, role)

    def test_user_serializer_api(self):
        role = self._role("BA-P-USER")

        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)
        client.force_authenticate(user=self.admin)

        response = client.post(
            "/api/accounts/users/",
            {
                "username": "ba.created",
                "email": "ba.created@example.com",
                "password": "Sandi!2345",
                "roles": [role.pk],
            },
            format="json",
        )

        self.assertIn(
            response.status_code, (200, 201), response.content[:300])

        created = get_user_model().objects.get(username="ba.created")

        self.expect_closed(created, role)

    def test_direct_row_creation_is_closed_too(self):
        """
        Baris yang dibuat langsung ke tabelnya — melewati setiap jalur.

        Bentuk yang sama dengan peninggalan tenant yang di-seed sebelum
        peralihan. Runtime harus **menutup**, bukan menebak.
        """
        holder = self.make_employee(self.company_a, self.site_a)
        role = self._role("BA-P-DIRECT")

        RoleAssignment.objects.create(user=holder.user, role=role)

        self.expect_closed(holder.user, role)


class RetainedAssignmentTests(BlankAuthorityTestCase):
    def test_later_role_edits_do_not_move_an_existing_assignment(self):
        """
        Inti arsitekturnya: WHERE milik pasangan (orang, role).

        Kalau menyunting `Role` menggeser kewenangan setiap
        pemegangnya, kita kembali ke keadaan yang justru diperbaiki —
        satu perubahan konfigurasi menggeser akses banyak orang
        sekaligus, tanpa ada yang memintanya.

        Yang disunting di bawah **izinnya**, karena itu satu-satunya
        yang tersisa di `Role` — dan itu justru pasangan yang paling
        perlu dijaga terpisah: menambah izin menambah WHAT, bukan
        WHERE.
        """
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("BA-FROZEN", permissions=[self.view_employee])

        self.grant(
            holder.user, role,
            mode=AuthorityMode.EXPLICIT,
            rows=[("company", self.company_a.pk)],
        )

        before = self.authority_of(holder.user, role)

        # Role dilonggarkan **sesudah** penugasannya ada. Yang tersisa
        # untuk dilonggarkan izinnya — dan itu justru pasangan yang
        # harus dipisah: melebarkan WHAT tidak boleh melebarkan WHERE.
        role.permissions.add(self.view_payslip)

        role.name = "Ba Frozen (diperluas)"

        role.save(update_fields=["name"])

        self.assertEqual(self.authority_of(holder.user, role), before)

        self.assertNotIn(far.employee_number, self.visible(holder.user))

    def test_saving_the_same_role_list_again_changes_nothing(self):
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role("BA-RESAVE", permissions=[self.view_employee])

        self.grant(
            holder.user, role,
            mode=AuthorityMode.EXPLICIT,
            rows=[("company", self.company_a.pk)],
        )

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        # Kewenangannya disunting orang sesudah penugasannya dibuat.
        assignment.authorities.all().delete()

        RoleAssignmentAuthority.objects.create(
            assignment=assignment,
            resource_type="company",
            resource_id=self.company_b.pk,
        )

        pk = assignment.pk

        for _ in range(3):
            assign_roles(holder.user, [role.pk])

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        # PK bertahan, dan suntingan orangnya tidak tertimpa.
        self.assertEqual(assignment.pk, pk)

        self.assertEqual(
            self.authority_of(holder.user, role),
            (AuthorityMode.EXPLICIT, "", [("company", self.company_b.pk)]),
        )

class RuntimeHasNoLegacyPathTests(BlankAuthorityTestCase):
    def test_the_legacy_helpers_are_gone_from_the_module(self):
        """
        Diperiksa di namespace modulnya, bukan di teks sumbernya.

        Versi sebelumnya penjaga ini menggrep `inspect.getsource()` dan
        justru lulus karena mencocokkan docstring yang **menjelaskan**
        bahwa modelnya tidak dibaca. Yang tidak bisa ditipu prosa:
        nama yang benar-benar ada di modulnya.
        """
        for name in (
            "_legacy_authority",
            "_legacy_bucket",
        ):
            self.assertFalse(
                hasattr(DataScopeService, name),
                msg=f"DataScopeService.{name} harus sudah dibuang.",
            )

        # Daftar nama model lama **dibuang dari penjaga ini**, bukan
        # dilupakan: sesudah gelombang C tidak ada satu pun modul yang
        # bisa mengimpornya, jadi assertion itu selalu hijau tanpa
        # menguji apa pun. Penjaga yang tidak bisa merah tidak menjaga.
        #
        # Yang menggantikannya pernyataan **positif** tentang satu-satunya
        # sumber WHERE yang tersisa — itu bisa merah, dan merahnya
        # berarti sesuatu.
        self.assertTrue(hasattr(scoping, "RoleAssignment"))

        source = inspect.getsource(DataScopeService._build)

        self.assertIn(
            "authority_mode", source,
            msg=(
                "`DataScopeService._build` tidak lagi membaca "
                "`authority_mode` — WHERE runtime datang dari tempat "
                "lain, dan itu harus jadi keputusan yang tercatat."
            ),
        )

    # Dua test dihapus di sini bersama tabelnya:
    #
    #   test_role_data_permission_cannot_move_runtime_visibility
    #   test_user_data_permission_cannot_move_runtime_visibility
    #
    # Keduanya membuat baris cakupan lama **sesudah** penugasannya ada
    # lalu membuktikan barisnya tidak menggeser satu pun baris yang
    # terlihat. Sesudah tabelnya tidak ada, tidak ada lagi yang bisa
    # dibuat, dan mengarang assertion pengganti yang tidak menguji apa
    # pun lebih buruk daripada tidak ada test.
    #
    # Yang mereka jaga tetap dijaga, dari sisi yang masih bisa merah:
    # `test_later_role_edits_do_not_move_an_existing_assignment` di
    # atas (menyunting Role tidak menggeser kewenangan penugasan) dan
    # `test_no_cross_role_borrowing` di bawah.

    def test_no_cross_role_borrowing(self):
        """
        Kewenangan satu penugasan tidak berjalan untuk izin role lain.

        Ini kebocoran yang ditutup Stage 4D, dan ia harus tetap tertutup
        sesudah turunannya otomatis: role yang luas tapi tidak memberi
        `view_payslip` tidak boleh memperlebar `view_payslip` yang
        datang dari role lain yang sempit.
        """
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        wide = self.make_role("BA-WIDE", permissions=[self.view_employee])

        narrow = self.make_role("BA-NARROW", permissions=[self.view_payslip])

        assign_roles(holder.user, [
            {
                "role": wide.pk,
                "authority_mode": AuthorityMode.UNRESTRICTED,
            },
            {
                "role": narrow.pk,
                "authority_mode": AuthorityMode.EXPLICIT,
                "authorities": [
                    {"resource_type": "company",
                     "resource_id": self.company_a.pk},
                ],
            },
        ])

        # `view_employee` datang dari role tanpa batasan: melihat semua.
        self.assertIn(far.employee_number, self.visible(holder.user))

        # `view_payslip` datang dari role sempit: hanya company A —
        # kewenangan `BA-WIDE` tidak bisa dipinjam.
        self.assertNotIn(
            far.employee_number,
            self.visible(holder.user, permission="payroll.view_payslip"),
        )


# ----------------------------------------------------------------------
# Administrasi kewenangan tetap jalan
# ----------------------------------------------------------------------


class AuthorityAdminStillWorksTests(BlankAuthorityTestCase):
    def client_as_admin(self) -> APIClient:
        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

        client.force_authenticate(user=self.admin)

        return client

    def test_reading_and_writing_authority_through_the_api(self):
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("BA-ADMIN", permissions=[self.view_employee])

        assign_roles(holder.user, [role.pk])

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        client = self.client_as_admin()

        response = client.get(
            f"/api/accounts/user-roles/authority/?user={holder.user.pk}",
        )

        self.assertEqual(response.status_code, 200, response.content[:300])

        payload = response.json()

        self.assertTrue(payload["assignments"])

        # Kosong terbaca apa adanya. Bedanya dengan `explicit` tanpa
        # baris penting dan harus tetap terlihat di layar: yang satu
        # "belum diatur", yang lain "sengaja tanpa kewenangan".
        row = next(
            item for item in payload["assignments"]
            if item["role"] == role.pk
        )

        self.assertEqual(row["authority_mode"], "")
        self.assertEqual(row["authorities"], [])

        response = client.post(
            "/api/accounts/user-roles/authority/",
            {
                "user": holder.user.pk,
                "role": role.pk,
                "authority_mode": AuthorityMode.EXPLICIT,
                "authorities": [
                    {"resource_type": "company", "resource_id": self.company_b.pk},
                ],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content[:300])

        # PK penugasannya tidak berubah — kewenangan menempel pada
        # keanggotaan yang sama, bukan membuat yang baru.
        self.assertEqual(
            RoleAssignment.objects.get(user=holder.user, role=role).pk,
            assignment.pk,
        )

        self.assertIn(far.employee_number, self.visible(holder.user))


# ----------------------------------------------------------------------
# Jebakan urutan yang lahir dari perbaikan ini
# ----------------------------------------------------------------------


