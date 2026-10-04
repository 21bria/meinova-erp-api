"""
Kontrak pembuatan penugasan: WHERE dinyatakan, tidak diturunkan.

Apa yang berubah di Stage 4H
----------------------------
Sampai 4G, penugasan baru mewarisi kewenangannya dari konfigurasi
`Role` — `data_scope_mode`, `data_scope_level`, dan baris
`RoleDataPermission`. Itu menutup lubang "kosong berarti terbuka", tapi
menyisakan satu ketergantungan: model kewenangan lama masih menentukan
akses, cuma pada satu momen yang lebih sempit.

Sekarang `Role` menjawab **WHAT** saja. WHERE dinyatakan pemanggil saat
penugasannya dibuat, dan yang tidak dinyatakan berakhir **tertutup**.

Kenapa "tertutup" adalah jawaban yang benar untuk "belum diatur"
----------------------------------------------------------------
Karena dua arah kegagalan tidak setara. Penugasan yang terlalu sempit
ditemukan dalam hitungan menit — orangnya melapor ia tidak bisa bekerja.
Penugasan yang terlalu luas tidak ditemukan sama sekali; tidak ada yang
melapor bahwa ia melihat lebih banyak daripada seharusnya.

Berkas ini menjaga keduanya sekaligus: bahwa jalur normal **tidak
membaca** model lama (dibuktikan dari query yang benar-benar
dijalankan), dan bahwa konfigurasi yang belum lengkap berakhir menutup.
"""

from __future__ import annotations

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
    DataScopeLevel,
    Role,
    RoleAssignment,
    RoleAssignmentAuthority,
)
from apps.accounts.scoping import DataScopeService
from apps.accounts.services.role_assignment import (
    AuthorityValidationError,
    assign_roles,
    grant_role,
)
from apps.administration.models import Company, Department, Location, Position
from apps.hr.models import Employee, OrganizationAssignment


JOIN = date(2022, 5, 2)

EMPLOYEE_SCOPE = {
    "company": "organization__company",
    "location": "organization__location",
    "own": "user_id",
}

# Tabel yang **tidak boleh** disentuh jalur pembuatan normal.
#
# Ditulis sebagai **literal**, bukan lewat `Model._meta.db_table`, dan
# itu yang membuat penjaga ini selamat dari penghapusan modelnya:
# penjaga yang mengambil namanya dari model yang dihapus ikut hilang
# bersama model itu, persis di rilis ketika seseorang paling mungkin
# menuliskan ulang tabel lama dengan nama yang sama.
LEGACY_TABLES = (
    "accounts_role_data_permission",
    "accounts_user_data_permission",
)

LEGACY_COLUMNS = ("data_scope_mode", "data_scope_level")


@override_settings(ROLE_AWARE_DATA_SCOPE=True)
class CreationContractTestCase(TenantTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company_a = Company.objects.create(code="CC-A", name="CC A")
        cls.company_b = Company.objects.create(code="CC-B", name="CC B")

        cls.site_a = Location.objects.create(
            code="CC-LOC-A", name="CC Site A", company=cls.company_a)

        cls.site_b = Location.objects.create(
            code="CC-LOC-B", name="CC Site B", company=cls.company_b)

        cls.department = Department.objects.create(
            code="CC-DEP", name="CC Dept", company=cls.company_a)

        cls.position = Position.objects.create(
            code="CC-POS", name="CC Pos", company=cls.company_a)

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

        number = f"CC{cls.counter:04d}"

        user = get_user_model().objects.create_user(
            username=f"cc.user{cls.counter}",
            email=f"cc{cls.counter}@example.com",
            password="x",
        )

        employee = Employee.objects.create(
            employee_number=number, first_name="CC", last_name=number,
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
        Role yang menjawab WHAT, dan tidak menyatakan WHERE sama sekali.

        Versi sebelumnya menerima `mode=`/`rows=` supaya role bisa
        dibuat **sengaja longgar**: kalau ada jalur yang masih
        menurunkan WHERE dari `Role`, hasilnya tanpa batasan dan
        testnya berbunyi keras.

        Umpan itu tidak bisa dipasang lagi, karena tempat
        menyimpannya tidak ada. Yang menggantikannya bukan assertion
        yang lebih lemah melainkan yang lebih langsung: tiap test di
        bawah menuntut kewenangan penugasannya **kosong** dan yang
        terlihat **nol baris**, padahal izin bacanya diberikan. Role
        yang tidak memberi izin akan hijau karena sebab yang salah,
        jadi izinnya selalu diberikan.
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

    def assertReadsNoLegacy(self, queries):
        """
        Tidak satu pun query menyentuh model kewenangan lama.

        Diperiksa dari SQL yang **benar-benar dijalankan**, bukan dari
        impor atau dari membaca kode. Itu bedanya bukti dengan janji:
        impor bisa ada tanpa dipakai, dan pemakaian bisa ada tanpa
        impor yang kelihatan.
        """
        offending = [
            sql for sql in queries
            if any(table in sql for table in LEGACY_TABLES)
            or any(column in sql for column in LEGACY_COLUMNS)
        ]

        self.assertEqual(
            offending, [],
            msg=(
                "Jalur pembuatan penugasan membaca model kewenangan "
                "lama:\n" + "\n".join(offending[:5])
            ),
        )


# ----------------------------------------------------------------------
# Jalur normal tidak membaca model lama
# ----------------------------------------------------------------------


class NoLegacyReadOnCreationTests(CreationContractTestCase):
    def test_assign_roles_touches_no_legacy_table_or_column(self):
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role(
            "CC-NOREAD",
            permissions=[self.view_employee],
        )

        with CaptureQueriesContext(connection) as captured:
            assign_roles(holder.user, [role.pk])

        self.assertReadsNoLegacy([query["sql"] for query in captured])

    def test_assign_roles_with_authority_touches_no_legacy_either(self):
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role(
            "CC-NOREAD-2",
            permissions=[self.view_employee],
        )

        with CaptureQueriesContext(connection) as captured:
            assign_roles(holder.user, [{
                "role": role.pk,
                "authority_mode": AuthorityMode.EXPLICIT,
                "authorities": [
                    {"resource_type": "company",
                     "resource_id": self.company_a.pk},
                ],
            }])

        self.assertReadsNoLegacy([query["sql"] for query in captured])

        # Dan yang tertulis memang yang diminta, persis.
        self.assertEqual(
            self.authority_of(holder.user, role),
            (AuthorityMode.EXPLICIT, "", [("company", self.company_a.pk)]),
        )

    def test_an_unstated_assignment_opens_nothing(self):
        """
        Pembeda yang paling tajam: izin baca penuh, nol baris terlihat.

        Role-nya memberi `hr.view_employee` dan penugasannya dibuat
        lewat jalur biasa tanpa menyebut kewenangan apa pun. Yang
        dituntut di bawah bukan cuma "tidak melihat orang jauh" tapi
        **himpunan kosong** — assertion pertama saja akan tetap hijau
        pada mesin yang menyaring terlalu sedikit asal orang jauhnya
        kebetulan tidak lolos.
        """
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role(
            "CC-WOULD-BE-ALL",
            permissions=[self.view_employee],
        )

        assign_roles(holder.user, [role.pk])

        self.assertEqual(
            self.authority_of(holder.user, role), ("", "", []))

        self.assertNotIn(far.employee_number, self.visible(holder.user))
        self.assertEqual(self.visible(holder.user), set())

    # `test_role_data_permission_rows_are_not_copied_any_more` dihapus
    # bersama tabelnya: ia membuat baris cakupan pada role lalu
    # menuntut baris itu tidak tersalin ke penugasan. Tanpa tabelnya
    # tidak ada yang bisa dibuat, dan yang tersisa cuma bentuk kosong.
    #
    # Pernyataan yang sebenarnya dijaga — penugasan yang dibuat tanpa
    # menyebut kewenangan berakhir kosong dan tidak melihat apa pun —
    # ada di `test_an_unstated_assignment_opens_nothing` di atas, dan
    # itu tetap bisa merah.


# ----------------------------------------------------------------------
# Tiap mode, dinyatakan
# ----------------------------------------------------------------------


class ExplicitCreationTests(CreationContractTestCase):
    def test_unrestricted_is_written_when_asked_for(self):
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("CC-UNR", permissions=[self.view_employee])

        assign_roles(holder.user, [{
            "role": role.pk,
            "authority_mode": AuthorityMode.UNRESTRICTED,
        }])

        self.assertEqual(
            self.authority_of(holder.user, role),
            (AuthorityMode.UNRESTRICTED, "", []),
        )

        self.assertIn(far.employee_number, self.visible(holder.user))

    def test_placement_is_written_with_its_level(self):
        holder = self.make_employee(self.company_a, self.site_a)
        neighbour = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("CC-PLC", permissions=[self.view_employee])

        assign_roles(holder.user, [{
            "role": role.pk,
            "authority_mode": AuthorityMode.PLACEMENT,
            "authority_level": DataScopeLevel.LOCATION,
        }])

        self.assertEqual(
            self.authority_of(holder.user, role),
            (AuthorityMode.PLACEMENT, DataScopeLevel.LOCATION, []),
        )

        visible = self.visible(holder.user)

        self.assertIn(neighbour.employee_number, visible)
        self.assertNotIn(far.employee_number, visible)

    def test_explicit_rows_are_written(self):
        holder = self.make_employee(self.company_a, self.site_a)
        neighbour = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("CC-EXP", permissions=[self.view_employee])

        assign_roles(holder.user, [{
            "role": role.pk,
            "authority_mode": AuthorityMode.EXPLICIT,
            "authorities": [
                {"resource_type": "company",
                 "resource_id": self.company_a.pk},
            ],
        }])

        visible = self.visible(holder.user)

        self.assertIn(neighbour.employee_number, visible)
        self.assertNotIn(far.employee_number, visible)

    def test_explicit_zero_is_accepted_and_denies(self):
        """
        **Sengaja tanpa kewenangan**, dan itu berbeda dari belum diatur.

        Keduanya menutup hari ini. Bedanya tercatat: `EXPLICIT` tanpa
        baris adalah keputusan yang bisa dibaca gerbang cutover dan
        layar administrasi, sedangkan kosong adalah pekerjaan yang belum
        selesai. Menyamakan keduanya berarti kehilangan satu-satunya
        cara membedakan "memang begitu" dari "terlupakan".
        """
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("CC-EXP0", permissions=[self.view_employee])

        assign_roles(holder.user, [{
            "role": role.pk,
            "authority_mode": AuthorityMode.EXPLICIT,
            "authorities": [],
        }])

        self.assertEqual(
            self.authority_of(holder.user, role),
            (AuthorityMode.EXPLICIT, "", []),
        )

        self.assertNotIn(far.employee_number, self.visible(holder.user))
        self.assertEqual(self.visible(holder.user), set())

    def test_own_can_be_stated_by_non_interactive_callers(self):
        """
        `own` tidak disunting dari layar, tapi harus bisa di-seed.

        Sesudah turunan dari `Role` dibuang, tidak ada lagi yang
        menuliskan baris `own` kalau seed-nya tidak menyebut — dan
        tanpa baris itu pegawai biasa tidak bisa membuka pengajuannya
        sendiri.
        """
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("CC-OWN", permissions=[self.view_employee])

        grant_role(
            holder.user,
            role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("own", None)],
        )

        self.assertEqual(
            self.authority_of(holder.user, role),
            (AuthorityMode.EXPLICIT, "", [("own", None)]),
        )

        visible = self.visible(holder.user)

        self.assertIn(holder.employee_number, visible)
        self.assertNotIn(far.employee_number, visible)

    def test_an_invalid_combination_is_refused_and_nothing_is_written(self):
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role("CC-BAD", permissions=[self.view_employee])

        with self.assertRaises(AuthorityValidationError):
            assign_roles(holder.user, [{
                "role": role.pk,
                # `placement` tanpa tingkat organisasi.
                "authority_mode": AuthorityMode.PLACEMENT,
            }])

        # Transaksinya dibatalkan seluruhnya: tidak ada penugasan
        # setengah jadi yang tertinggal.
        self.assertFalse(
            RoleAssignment.objects.filter(
                user=holder.user, role=role).exists()
        )


# ----------------------------------------------------------------------
# Tidak ada jendela waktu yang melebar
# ----------------------------------------------------------------------


class NoTransientWideningTests(CreationContractTestCase):
    def test_membership_and_authority_land_in_one_transaction(self):
        """
        Satu `assign_roles()`, satu transaksi.

        Yang dijaga bukan cuma hasil akhirnya melainkan tidak adanya
        keadaan antara yang lebih luas. Arah kegagalannya pun sudah
        aman: kalau transaksinya gagal di tengah, yang tersisa bukan
        penugasan tanpa batas melainkan tidak ada penugasan sama
        sekali.
        """
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role(
            "CC-ATOMIC",
            permissions=[self.view_employee],
        )

        assign_roles(holder.user, [{
            "role": role.pk,
            "authority_mode": AuthorityMode.EXPLICIT,
            "authorities": [
                {"resource_type": "company",
                 "resource_id": self.company_a.pk},
            ],
        }])

        assignment = RoleAssignment.objects.get(user=holder.user, role=role)

        # Tidak pernah `unrestricted`, tidak pernah kosong-lalu-melebar.
        self.assertEqual(assignment.authority_mode, AuthorityMode.EXPLICIT)

    def test_plain_add_creates_no_implicit_broad_authority(self):
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role(
            "CC-ADD",
            permissions=[self.view_employee],
        )

        holder.user.roles.add(role)

        self.assertEqual(
            self.authority_of(holder.user, role), ("", "", []))

        self.assertNotIn(far.employee_number, self.visible(holder.user))

    def test_plain_set_creates_no_implicit_broad_authority(self):
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role(
            "CC-SET",
            permissions=[self.view_employee],
        )

        holder.user.roles.set([role])

        self.assertEqual(
            self.authority_of(holder.user, role), ("", "", []))

        self.assertNotIn(far.employee_number, self.visible(holder.user))


# ----------------------------------------------------------------------
# Yang bertahan, dan yang tidak ikut berubah
# ----------------------------------------------------------------------


class RetainedAndFrozenTests(CreationContractTestCase):
    def test_retained_assignment_keeps_its_pk_and_its_authority(self):
        holder = self.make_employee(self.company_a, self.site_a)

        first = self.make_role("CC-KEEP-1", permissions=[self.view_employee])
        second = self.make_role("CC-KEEP-2", permissions=[self.view_employee])

        assign_roles(holder.user, [{
            "role": first.pk,
            "authority_mode": AuthorityMode.EXPLICIT,
            "authorities": [
                {"resource_type": "company",
                 "resource_id": self.company_a.pk},
            ],
        }])

        pk = RoleAssignment.objects.get(user=holder.user, role=first).pk

        # Role kedua ditambahkan; yang pertama bertahan.
        assign_roles(holder.user, [first.pk, second.pk])

        self.assertEqual(
            RoleAssignment.objects.get(user=holder.user, role=first).pk, pk)

        # Kewenangannya **tidak** ditulis ulang jadi kosong meski
        # entrinya dikirim sebagai id telanjang: id telanjang cuma
        # berarti "tanpa kewenangan" untuk penugasan yang **baru**.
        self.assertEqual(
            self.authority_of(holder.user, first),
            (AuthorityMode.EXPLICIT, "", [("company", self.company_a.pk)]),
        )

        self.assertEqual(
            self.authority_of(holder.user, second), ("", "", []))

    # `test_later_legacy_role_edits_change_nothing` dihapus bersama
    # kolom dan tabel yang disuntingnya. Bentuk yang bertahan —
    # menyunting `Role` sesudah penugasannya ada tidak menggeser
    # kewenangan penugasan itu — dijaga di
    # `test_blank_authority_elimination.RetainedAssignmentTests`, di
    # sana yang disunting izinnya, satu-satunya yang tersisa di `Role`.

    def test_grant_role_does_not_overwrite_an_existing_assignment(self):
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role("CC-REGRANT", permissions=[self.view_employee])

        grant_role(
            holder.user, role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("company", self.company_a.pk)],
        )

        pk = RoleAssignment.objects.get(user=holder.user, role=role).pk

        # Disunting orang sesudahnya.
        assignment = RoleAssignment.objects.get(user=holder.user, role=role)
        assignment.authorities.all().delete()

        RoleAssignmentAuthority.objects.create(
            assignment=assignment,
            resource_type="company",
            resource_id=self.company_b.pk,
        )

        # Seed dijalankan ulang.
        grant_role(
            holder.user, role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("company", self.company_a.pk)],
        )

        self.assertEqual(
            RoleAssignment.objects.get(user=holder.user, role=role).pk, pk)

        self.assertEqual(
            self.authority_of(holder.user, role),
            (AuthorityMode.EXPLICIT, "", [("company", self.company_b.pk)]),
        )

    def test_no_cross_role_borrowing(self):
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        wide = self.make_role("CC-WIDE", permissions=[self.view_employee])
        narrow = self.make_role("CC-NARROW", permissions=[self.view_payslip])

        assign_roles(holder.user, [
            {"role": wide.pk, "authority_mode": AuthorityMode.UNRESTRICTED},
            {
                "role": narrow.pk,
                "authority_mode": AuthorityMode.EXPLICIT,
                "authorities": [
                    {"resource_type": "company",
                     "resource_id": self.company_a.pk},
                ],
            },
        ])

        self.assertIn(far.employee_number, self.visible(holder.user))

        self.assertNotIn(
            far.employee_number,
            self.visible(holder.user, permission="payroll.view_payslip"),
        )


# ----------------------------------------------------------------------
# API — bentuk lama tetap jalan, bentuk baru menyimpan sekaligus
# ----------------------------------------------------------------------


class SaveApiCompatibilityTests(CreationContractTestCase):
    def client_as_admin(self) -> APIClient:
        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

        client.force_authenticate(user=self.admin)

        return client

    def test_the_old_id_list_still_works_and_fails_closed(self):
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role(
            "CC-API-OLD",
            permissions=[self.view_employee],
        )

        response = self.client_as_admin().post(
            "/api/accounts/user-roles/save/",
            {"user": holder.user.pk, "roles": [str(role.pk)]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content[:300])

        self.assertEqual(
            self.authority_of(holder.user, role), ("", "", []))

        self.assertNotIn(far.employee_number, self.visible(holder.user))

    def test_the_long_form_saves_membership_and_authority_together(self):
        holder = self.make_employee(self.company_a, self.site_a)
        neighbour = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("CC-API-NEW", permissions=[self.view_employee])

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

        self.assertEqual(response.status_code, 200, response.content[:300])

        visible = self.visible(holder.user)

        self.assertIn(neighbour.employee_number, visible)
        self.assertNotIn(far.employee_number, visible)

    def test_a_bad_combination_is_a_400_and_saves_nothing(self):
        holder = self.make_employee(self.company_a, self.site_a)

        role = self.make_role("CC-API-BAD", permissions=[self.view_employee])

        response = self.client_as_admin().post(
            "/api/accounts/user-roles/save/",
            {
                "user": holder.user.pk,
                "roles": [{
                    "role": role.pk,
                    "authority_mode": AuthorityMode.PLACEMENT,
                }],
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content[:300])

        self.assertFalse(
            RoleAssignment.objects.filter(
                user=holder.user, role=role).exists()
        )

    def test_the_authority_screen_still_reads_and_writes(self):
        holder = self.make_employee(self.company_a, self.site_a)
        far = self.make_employee(self.company_b, self.site_b)

        role = self.make_role("CC-API-AUTH", permissions=[self.view_employee])

        assign_roles(holder.user, [role.pk])

        client = self.client_as_admin()

        response = client.get(
            f"/api/accounts/user-roles/authority/?user={holder.user.pk}")

        self.assertEqual(response.status_code, 200, response.content[:300])

        row = next(
            item for item in response.json()["assignments"]
            if item["role"] == role.pk
        )

        # Kosong terbaca apa adanya — layar yang menyebutnya "belum
        # ditentukan" harus bisa membedakannya dari `explicit` tanpa
        # baris.
        self.assertEqual(row["authority_mode"], "")

        response = client.post(
            "/api/accounts/user-roles/authority/",
            {
                "user": holder.user.pk,
                "role": role.pk,
                "authority_mode": AuthorityMode.UNRESTRICTED,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content[:300])

        self.assertIn(far.employee_number, self.visible(holder.user))

    def test_the_user_serializer_grants_without_authority(self):
        role = self.make_role(
            "CC-API-USER",
            permissions=[self.view_employee],
        )

        response = self.client_as_admin().post(
            "/api/accounts/users/",
            {
                "username": "cc.created",
                "email": "cc.created@example.com",
                "password": "Sandi!2345",
                "roles": [role.pk],
            },
            format="json",
        )

        self.assertIn(
            response.status_code, (200, 201), response.content[:300])

        created = get_user_model().objects.get(username="cc.created")

        self.assertEqual(self.authority_of(created, role), ("", "", []))


# ----------------------------------------------------------------------
# Katalog seed
# ----------------------------------------------------------------------


class SeedAuthorityAgreesWithRoleReachTests(CreationContractTestCase):
    """
    Dua pernyataan tentang hal yang sama harus tetap sepakat.

    `seed_data_scopes` mengelompokkan role menurut jangkauannya —
    `COMPANY_WIDE_CODES` se-company, `SITE_DESK_CODES` per lokasi.
    `SEED_ROLE_AUTHORITY` menyatakan WHERE yang sama untuk penugasan
    yang dibuat seed.

    Selama keduanya hidup, keduanya harus berkata sama. Kalau tidak,
    role yang sama berakhir dengan jangkauan berbeda tergantung jalur
    mana yang menyiapkan tenantnya — dan selisihnya cuma ketahuan dari
    keluhan pengguna, bukan dari test.
    """

    def test_every_seeded_role_maps_to_the_same_meaning(self):
        from apps.accounts.management.commands import seed_data_scopes as sds
        from apps.accounts.seeds.role_authority import SEED_ROLE_AUTHORITY

        expected: dict[str, tuple] = {}

        for code in sds.COMPANY_WIDE_CODES:
            expected[code] = (AuthorityMode.UNRESTRICTED, "")

        for code in sds.SITE_DESK_CODES:
            expected[code] = (AuthorityMode.PLACEMENT, DataScopeLevel.LOCATION)

        # Tabel `SCOPED_ROLES`/`DECLARED_SCOPES` **tidak lagi dibaca di
        # sini**: keduanya menyatakan maksudnya dengan kosakata cakupan
        # lama, dan kosakata itu ikut hilang di gelombang C. Yang
        # tersisa dua daftar kode yang bentuknya tidak bergantung pada
        # skema lama — dan keduanya masih bisa berselisih dengan
        # `SEED_ROLE_AUTHORITY`, jadi penjaganya masih bisa merah.

        mismatched = []

        for code, (mode, level) in expected.items():
            declared = SEED_ROLE_AUTHORITY.get(code)

            if declared is None:
                mismatched.append(f"{code}: belum ada di SEED_ROLE_AUTHORITY")

                continue

            actual = (
                declared["authority_mode"],
                declared.get("authority_level", ""),
            )

            if actual != (mode, level):
                mismatched.append(
                    f"{code}: seed_data_scopes={mode}/{level or '-'} "
                    f"tapi SEED_ROLE_AUTHORITY={actual[0]}/{actual[1] or '-'}"
                )

        self.assertEqual(mismatched, [])
