"""
Keanggotaan user-role sesudah jadi model eksplisit — buktinya.

Yang dijaga berkas ini satu kalimat: **mengubah status model tidak
boleh mengubah satu baris pun.** `auth_users_roles` sudah dipakai sejak
`User.roles` masih M2M implisit; `RoleAssignment` cuma mengambil alih
deklarasinya supaya Stage 4C punya tempat menempelkan kewenangan per
penugasan. Kalau ada satu keanggotaan yang hilang, bertambah, atau
berpindah PK karena perubahan ini, test di sini yang harus merah —
bukan pengguna yang menemukan role-nya raib.

Satu koreksi yang perlu berdiri di depan, karena dugaan awal Stage 4A
salah dan salahnya menentukan bentuk stage ini: **`.set()` milik Django
tidak pernah membuang lalu membuat ulang baris yang tetap dipegang.**
Dengan `clear=False` (bawaannya) ia menghitung selisihnya sendiri.
`RetainedRowTests` mengunci fakta itu, jadi kalau suatu saat Django
mengubahnya, yang memberi tahu adalah test — bukan kehilangan data.

Yang memang rapuh dan diperbaiki di stage ini bukan `.set()`-nya,
melainkan jalan id sampai ke sana: daftar yang dikirim layar adalah
daftar **utuh**, jadi id yang dibuang diam-diam terbaca sebagai
perintah mencabut role. `StrictResolutionTests` yang menjaganya.

Tiap kelompok punya assertion negatifnya. Test yang cuma memeriksa
"yang seharusnya ada memang ada" akan tetap hijau pada penyimpanan yang
tidak pernah menghapus apa pun.
"""

from __future__ import annotations

import inspect

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import IntegrityError, transaction
from django.test import override_settings

from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.models import (
    AuthorityMode,
    DataScopeLevel,
    Role,
    RoleAssignment,
)
from apps.accounts.scoping import DataScopeService
from apps.accounts.services.role_assignment import (
    UnknownRoleError,
    assign_roles,
)
from apps.administration.models import Company, Department, Location, Position
from apps.hr.models import Employee, OrganizationAssignment


JOIN = date(2020, 1, 6)

SAVE_URL = "/api/accounts/user-roles/save/"


class RoleAssignmentTestCase(TenantTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(code="RA-CO", name="RA Company")

        cls.site_a = Location.objects.create(
            code="RA-LOC-A", name="RA Site A", company=cls.company)

        cls.site_b = Location.objects.create(
            code="RA-LOC-B", name="RA Site B", company=cls.company)

        cls.department = Department.objects.create(
            code="RA-DEP", name="RA Department", company=cls.company)

        cls.position = Position.objects.create(
            code="RA-POS", name="RA Position", company=cls.company)

        cls.view_employee = Permission.objects.get(
            content_type__app_label="hr", codename="view_employee")

        cls.counter = 0

    @classmethod
    def make_employee(cls, location, *, username=None):
        cls.counter += 1

        number = f"RA{cls.counter:04d}"

        user = get_user_model().objects.create_user(
            username=username or f"ra.user{cls.counter}",
            email=f"ra{cls.counter}@example.com",
            password="x",
        )

        employee = Employee.objects.create(
            employee_number=number,
            first_name="RA",
            last_name=number,
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=location,
            department=cls.department,
            position=cls.position,
            organization_effective_date=JOIN,
        )

        return employee

    # Tidak ada `grant()` di berkas ini, dan itu disengaja: tiap test
    # di bawah menyebut kewenangannya sendiri lewat `assign_roles()` —
    # yang justru kontrak yang diuji. Helper yang menyimpulkan WHERE
    # dari `Role` akan menyembunyikan persis apa yang seharusnya
    # terbaca di setiap skenario.

    @classmethod
    def make_role(cls, code, *, permissions=()):
        """
        `Role` menjawab WHAT saja.

        Tidak ada kolom cakupan yang diisi di sini — sejak Stage 4H
        WHERE tidak diturunkan dari `Role`, dan sejak gelombang C
        kolomnya tidak ada lagi.
        """
        role = Role.objects.create(code=code, name=code.title())

        if permissions:
            role.permissions.add(*permissions)

        return role

    @staticmethod
    def rows_for(user) -> dict[int, int]:
        """`{role_id: pk baris}` — PK-nya yang jadi bukti, bukan cuma isinya."""
        return {
            role_id: row_id
            for row_id, role_id in RoleAssignment.objects
            .filter(user=user)
            .values_list("id", "role_id")
        }

    def setUp(self):
        super().setUp()

        for user in get_user_model().objects.all():
            for attribute in ("_role_perm_cache", "_data_scope_cache"):
                if hasattr(user, attribute):
                    delattr(user, attribute)

    def api_client(self, user) -> APIClient:
        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

        client.force_authenticate(user=user)

        return client


# ----------------------------------------------------------------------
# 1 — model melalui tabel yang sudah ada
# ----------------------------------------------------------------------


class ThroughModelTests(RoleAssignmentTestCase):
    def test_through_model_uses_the_existing_table(self):
        """
        Tabelnya `auth_users_roles`, bukan tabel kedua.

        Diperiksa dari `_meta`, bukan dari migration: yang menentukan
        ke mana baris ditulis adalah model, dan migration bisa saja
        benar sementara modelnya menunjuk tempat lain.
        """
        self.assertEqual(RoleAssignment._meta.db_table, "auth_users_roles")

        self.assertIs(get_user_model().roles.through, RoleAssignment)

    def test_the_membership_table_has_exactly_the_expected_shape(self):
        """
        Batas yang **digeser dengan sadar**, bukan yang bergeser sendiri.

        Versi Stage 4B menuntut bentuknya persis `{id, user, role}` dan
        menolak `authority_*` — dan ia **gagal** begitu Stage 4C
        menambahkannya. Itu memang tugasnya: memaksa penambahan kolom
        jadi keputusan yang tercatat, bukan penemuan belakangan.

        Sekarang batasnya dinyatakan ulang di tempat Stage 4C
        meletakkannya. Yang dijaga tetap sama — tidak ada kolom yang
        menyelinap masuk tanpa ada yang menyatakannya lebih dulu.
        """
        columns = {field.name for field in RoleAssignment._meta.get_fields()}

        self.assertEqual(
            columns,
            {
                "id",
                "user",
                "role",
                # Stage 4C: disimpan, belum dibaca siapa pun.
                "authority_mode",
                "authority_level",
                # Relasi balik dari `RoleAssignmentAuthority`.
                "authorities",
            },
        )

    def test_datascope_reads_assignment_authority(self):
        """
        Batas Stage 4C yang **digeser dengan sadar** di Stage 4D.

        Versi sebelumnya menuntut `DataScopeService` belum menyebut
        kewenangan penugasan sama sekali — supaya peralihan pembacanya
        jadi keputusan yang tercatat, bukan penemuan belakangan. Ia
        gagal tepat ketika peralihannya dikerjakan, dan itu memang
        tugasnya.

        Diperiksa dari **namespace modul**, bukan dari teks sumbernya.
        Versi pertama penjaga ini mencari kata "UserDataPermission" di
        `inspect.getsource()` dan merah karena docstring yang justru
        menjelaskan bahwa modelnya **tidak** dibaca lagi — penjaga yang
        menguji prosa, bukan kode.

        Sisi negatifnya — "model cakupan lama tidak diimpor kembali" —
        **dibuang di gelombang C**: modelnya tidak ada lagi, jadi
        assertion itu selalu hijau tanpa menguji apa pun, dan penjaga
        yang tidak bisa merah tidak menjaga. Yang tersisa pernyataan
        positif tentang satu-satunya sumber WHERE yang berlaku, dan itu
        masih bisa merah.
        """
        from apps.accounts import scoping

        self.assertTrue(hasattr(scoping, "RoleAssignment"))

        source = inspect.getsource(scoping.DataScopeService._build)

        self.assertIn("authority_mode", source)


# ----------------------------------------------------------------------
# 2 — baris yang bertahan tidak berpindah PK
# ----------------------------------------------------------------------


class RetainedRowTests(RoleAssignmentTestCase):
    """
    Inti Stage 4B: kewenangan Stage 4C akan menempel pada PK ini.

    Kalau menyimpan layar role memindahkan PK baris yang tetap
    dipegang, kewenangan yang menempel padanya ikut hilang tiap kali
    ada orang menekan Simpan — dan hilangnya tidak berbunyi.
    """

    def scenario(self, apply):
        employee = self.make_employee(self.site_a)

        first = self.make_role("RA-KEEP-1")
        second = self.make_role("RA-KEEP-2")
        third = self.make_role("RA-KEEP-3")

        apply(employee.user, [first.pk, second.pk])

        before = self.rows_for(employee.user)

        self.assertEqual(set(before), {first.pk, second.pk})

        # Tambah satu.
        apply(employee.user, [first.pk, second.pk, third.pk])

        after_add = self.rows_for(employee.user)

        self.assertEqual(set(after_add), {first.pk, second.pk, third.pk})

        self.assertEqual(after_add[first.pk], before[first.pk])
        self.assertEqual(after_add[second.pk], before[second.pk])

        # Buang yang di tengah.
        apply(employee.user, [first.pk, third.pk])

        after_remove = self.rows_for(employee.user)

        self.assertEqual(set(after_remove), {first.pk, third.pk})

        self.assertEqual(after_remove[first.pk], before[first.pk])
        self.assertEqual(after_remove[third.pk], after_add[third.pk])

        # Assertion negatifnya: yang dibuang benar-benar hilang.
        self.assertFalse(
            RoleAssignment.objects.filter(
                user=employee.user, role_id=second.pk).exists(),
        )

        return employee, (first, second, third)

    def test_service_path_preserves_retained_rows(self):
        self.scenario(lambda user, ids: assign_roles(user, ids))

    def test_djangos_own_set_also_preserves_retained_rows(self):
        """
        Koreksi terhadap dugaan Stage 4A, dikunci sebagai fakta.

        `.set()` **tidak** membuang lalu membuat ulang baris yang tetap
        dipegang. Kalau suatu saat Django mengubahnya, ini yang memberi
        tahu lebih dulu.
        """
        self.scenario(
            lambda user, ids: user.roles.set(Role.objects.filter(pk__in=ids)),
        )

    def test_identical_save_changes_nothing(self):
        employee = self.make_employee(self.site_a)

        first = self.make_role("RA-IDEM-1")
        second = self.make_role("RA-IDEM-2")

        assign_roles(employee.user, [first.pk, second.pk])

        before = self.rows_for(employee.user)

        delta = assign_roles(employee.user, [first.pk, second.pk])

        self.assertEqual(self.rows_for(employee.user), before)

        self.assertEqual(delta.added, [])
        self.assertEqual(delta.removed, [])
        self.assertEqual(delta.kept, sorted([first.pk, second.pk]))

    def test_add_touches_only_the_new_row(self):
        employee = self.make_employee(self.site_a)

        first = self.make_role("RA-ADD-1")
        second = self.make_role("RA-ADD-2")

        assign_roles(employee.user, [first.pk])

        before = self.rows_for(employee.user)

        delta = assign_roles(employee.user, [first.pk, second.pk])

        self.assertEqual(delta.added, [second.pk])
        self.assertEqual(delta.removed, [])

        self.assertEqual(
            self.rows_for(employee.user)[first.pk], before[first.pk])

    def test_remove_touches_only_the_removed_row(self):
        employee = self.make_employee(self.site_a)

        first = self.make_role("RA-RM-1")
        second = self.make_role("RA-RM-2")

        assign_roles(employee.user, [first.pk, second.pk])

        before = self.rows_for(employee.user)

        delta = assign_roles(employee.user, [first.pk])

        self.assertEqual(delta.added, [])
        self.assertEqual(delta.removed, [second.pk])

        self.assertEqual(
            self.rows_for(employee.user)[first.pk], before[first.pk])


# ----------------------------------------------------------------------
# 3 — id yang tidak dikenal ditolak, bukan dibuang diam-diam
# ----------------------------------------------------------------------


class StrictResolutionTests(RoleAssignmentTestCase):
    """
    Daftar yang dikirim adalah daftar **utuh**.

    Karena itu membuang satu id bukan "mengabaikan sebagian input",
    melainkan "mencabut role itu". Yang sebelumnya terjadi diam-diam
    dan tetap menjawab sukses.
    """

    def test_unknown_id_is_rejected_and_nothing_is_removed(self):
        employee = self.make_employee(self.site_a)

        role = self.make_role("RA-STRICT-1")

        assign_roles(employee.user, [role.pk])

        before = self.rows_for(employee.user)

        with self.assertRaises(UnknownRoleError):
            assign_roles(employee.user, [role.pk, 10**9])

        self.assertEqual(self.rows_for(employee.user), before)

    def test_non_numeric_id_is_rejected_and_nothing_is_removed(self):
        employee = self.make_employee(self.site_a)

        role = self.make_role("RA-STRICT-2")

        assign_roles(employee.user, [role.pk])

        before = self.rows_for(employee.user)

        with self.assertRaises(UnknownRoleError):
            assign_roles(employee.user, ["bukan-angka"])

        self.assertEqual(self.rows_for(employee.user), before)

    def test_soft_deleted_role_is_rejected_not_silently_dropped(self):
        """
        Yang paling mungkin terjadi di lapangan.

        Role di-soft-delete sementara layarnya terbuka; daftar yang
        dikirim masih memuat id lamanya. Dulu id itu dibuang dan
        rolenya ikut tercabut dengan jawaban sukses.
        """
        employee = self.make_employee(self.site_a)

        kept = self.make_role("RA-STRICT-KEEP")
        gone = self.make_role("RA-STRICT-GONE")

        assign_roles(employee.user, [kept.pk, gone.pk])

        before = self.rows_for(employee.user)

        gone.is_deleted = True
        gone.save(update_fields=["is_deleted"])

        with self.assertRaises(UnknownRoleError):
            assign_roles(employee.user, [kept.pk, gone.pk])

        self.assertEqual(self.rows_for(employee.user), before)

    def test_empty_list_removes_everything(self):
        """Daftar kosong memang berarti mencabut semua — itu disengaja."""
        employee = self.make_employee(self.site_a)

        role = self.make_role("RA-STRICT-EMPTY")

        assign_roles(employee.user, [role.pk])

        delta = assign_roles(employee.user, [])

        self.assertEqual(delta.removed, [role.pk])
        self.assertEqual(self.rows_for(employee.user), {})


# ----------------------------------------------------------------------
# 4 — kontrak API tidak berubah
# ----------------------------------------------------------------------


class ApiContractTests(RoleAssignmentTestCase):
    def test_save_endpoint_still_accepts_roles_id_list(self):
        admin = self.make_employee(self.site_a, username="ra.secadmin")

        admin.user.is_superuser = True
        admin.user.save(update_fields=["is_superuser"])

        target = self.make_employee(self.site_b)

        first = self.make_role("RA-API-1")
        second = self.make_role("RA-API-2")

        response = self.api_client(admin.user).post(
            SAVE_URL,
            {"user": target.user.pk, "roles": [str(first.pk), str(second.pk)]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content[:300])

        self.assertEqual(
            set(self.rows_for(target.user)), {first.pk, second.pk})

        before = self.rows_for(target.user)

        # Simpan lagi tanpa yang kedua: PK yang pertama harus bertahan.
        response = self.api_client(admin.user).post(
            SAVE_URL,
            {"user": target.user.pk, "roles": [str(first.pk)]},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content[:300])

        after = self.rows_for(target.user)

        self.assertEqual(set(after), {first.pk})
        self.assertEqual(after[first.pk], before[first.pk])

    def test_save_endpoint_rejects_unknown_role_instead_of_removing(self):
        admin = self.make_employee(self.site_a, username="ra.secadmin2")

        admin.user.is_superuser = True
        admin.user.save(update_fields=["is_superuser"])

        target = self.make_employee(self.site_b)

        role = self.make_role("RA-API-STRICT")

        assign_roles(target.user, [role.pk])

        before = self.rows_for(target.user)

        response = self.api_client(admin.user).post(
            SAVE_URL,
            {"user": target.user.pk, "roles": [str(role.pk), "999999"]},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content[:300])

        self.assertEqual(self.rows_for(target.user), before)

    def test_user_serializer_path_preserves_rows(self):
        from apps.accounts.api.users.serializers import UserSerializer

        employee = self.make_employee(self.site_a)

        first = self.make_role("RA-SER-1")
        second = self.make_role("RA-SER-2")

        assign_roles(employee.user, [first.pk, second.pk])

        before = self.rows_for(employee.user)

        serializer = UserSerializer(
            instance=employee.user,
            data={"roles": [first.pk]},
            partial=True,
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)

        serializer.save()

        after = self.rows_for(employee.user)

        self.assertEqual(set(after), {first.pk})
        self.assertEqual(after[first.pk], before[first.pk])


# ----------------------------------------------------------------------
# 5 — perilaku yang membaca keanggotaan tidak berubah
# ----------------------------------------------------------------------


class UnchangedBehaviourTests(RoleAssignmentTestCase):
    def test_forward_and_reverse_accessors_still_work(self):
        employee = self.make_employee(self.site_a)

        role = self.make_role("RA-ACC")

        assign_roles(employee.user, [role.pk])

        self.assertEqual(
            list(employee.user.roles.all().values_list("pk", flat=True)),
            [role.pk],
        )

        self.assertIn(
            employee.user.pk,
            role.users.values_list("pk", flat=True),
        )

        # Accessor baru dari through model — ada, dan menunjuk baris
        # yang sama.
        self.assertEqual(
            employee.user.role_assignments.count(), 1)

        self.assertEqual(role.role_assignments.count(), 1)

    def test_permission_resolution_unchanged(self):
        employee = self.make_employee(self.site_a)

        role = self.make_role("RA-PERM", permissions=[self.view_employee])

        assign_roles(employee.user, [role.pk])

        user = get_user_model().objects.get(pk=employee.user.pk)

        self.assertTrue(user.has_perm("hr.view_employee"))

        # Negatifnya: mencabut role mencabut izinnya juga.
        assign_roles(employee.user, [])

        user = get_user_model().objects.get(pk=employee.user.pk)

        self.assertFalse(user.has_perm("hr.view_employee"))

    @override_settings(ROLE_AWARE_DATA_SCOPE=True)
    def test_data_scope_visibility_unchanged(self):
        insider = self.make_employee(self.site_a)

        self.make_employee(self.site_b)

        role = self.make_role(
            "RA-SCOPE",
            permissions=[self.view_employee],
        )

        # WHERE-nya disebut: sejak Stage 4H `assign_roles()` dengan id
        # telanjang berarti "tanpa kewenangan". Yang diuji di sini
        # penyaringannya, bukan kontrak pembuatannya.
        assign_roles(insider.user, [{
            "role": role.pk,
            "authority_mode": AuthorityMode.PLACEMENT,
            "authority_level": DataScopeLevel.LOCATION,
        }])

        user = get_user_model().objects.get(pk=insider.user.pk)

        visible = DataScopeService.filter(
            Employee.objects.filter(is_deleted=False),
            {"location": "organization__location"},
            user,
            required_permission="hr.view_employee",
        )

        numbers = set(visible.values_list("employee_number", flat=True))

        self.assertIn(insider.employee_number, numbers)

        # Assertion negatifnya — tanpa ini, cakupan yang tidak menyaring
        # apa pun juga lulus.
        for outsider in Employee.objects.filter(
            organization__location=self.site_b,
        ):
            self.assertNotIn(outsider.employee_number, numbers)

    def test_workflow_role_holder_resolution_unchanged(self):
        """
        Resolver approval membaca keanggotaan lewat `user__roles=role`.

        Itu jalur yang paling mudah putus tanpa berbunyi kalau melalui
        through model: querysetnya tetap jalan, hasilnya saja kosong,
        dan gejalanya dokumen yang tidak punya approver.
        """
        from apps.workflow.models import ApproverScope
        from apps.workflow.resolver import _role_holders

        here = self.make_employee(self.site_a)
        there = self.make_employee(self.site_b)

        role = self.make_role("RA-WF")

        assign_roles(here.user, [role.pk])
        assign_roles(there.user, [role.pk])

        holders = _role_holders(
            role,
            scope=ApproverScope.LOCATION,
            organization=here.organization,
        )

        numbers = {holder.employee_number for holder in holders}

        self.assertIn(here.employee_number, numbers)

        self.assertNotIn(there.employee_number, numbers)
