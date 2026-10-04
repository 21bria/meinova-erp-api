"""
Katalog role sesudah konsolidasi `*-SITE`.

Apa yang sebenarnya dijaga di sini
----------------------------------
Role `*-SITE` lahir waktu WHERE masih tinggal di `Role`, dan bedanya
dengan kembarannya memang **cuma cakupan**. Sesudah kolom cakupan itu
dihapus, keduanya tidak bisa dibedakan sama sekali — jadi keduanya
digabung.

Bagian yang paling mudah salah bukan penggabungannya melainkan
**kewenangannya**: kalau konsolidasi ini dikerjakan dengan memindahkan
orang ke role target lalu membiarkan kewenangannya diturunkan ulang dari
katalog, pemegang `HR-ADMIN-SITE` (sebatas lokasinya) akan mendarat di
`HR-ADMIN` (seluruh tenant) dan **melihat seluruh tenant**. Itu bukan
pembersihan katalog, itu pelebaran akses yang tidak diminta siapa pun.

Yang membuatnya aman: WHERE menempel pada `RoleAssignment`. Memindahkan
penugasan cuma mengganti `role_id`; mode, level, dan baris kewenangannya
menggantung di penugasan itu, jadi semuanya ikut apa adanya. Tiap test di
bawah memeriksa tepat itu — dan yang paling penting yang **negatif**:
tidak ada yang melihat lebih banyak sesudahnya.

Kelas terakhir menguji cabang yang **tidak bisa** diperagakan data demo:
orang yang memegang role sumber **dan** targetnya sekaligus.
"""

from __future__ import annotations

import importlib

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model

from django_tenants.test.cases import TenantTestCase

from apps.accounts.models import (
    AuthorityMode,
    DataScopeLevel,
    Role,
    RoleAssignment,
    RoleAssignmentAuthority,
)
from apps.administration.models import Company


MIGRATION = "apps.accounts.migrations.0014_consolidate_site_roles"

RETIRED = ("HR-ADMIN-SITE", "HR-MANAGER-SITE", "EXECUTIVE-SITE")


def _migration():
    return importlib.import_module(MIGRATION)


class CatalogueDeclarationTests(TenantTestCase):
    """
    Diperiksa dari **tabel seed**, bukan dari baris di database.

    Tenant test membawa rantai migration tapi **tidak** di-seed, jadi
    katalog role-nya kosong. Penjaga yang bertanya "apakah role X aktif
    di database" akan lulus karena tidak ada satu pun role — lulus karena
    sebab yang salah, dan itu lebih buruk daripada tidak ada penjaga.
    Yang dibaca di sini deklarasinya, dan deklarasinya bisa salah.

    Keadaan tenant sungguhan diperiksa terpisah, dengan membandingkan cap
    keanggotaan sebelum dan sesudah migrasi.
    """

    def test_no_seed_table_declares_a_name_that_promises_a_scope(self):
        """
        Nama role tidak boleh menjanjikan cakupan.

        `Role` tidak punya kolom cakupan lagi, dan satu role sekarang
        boleh dipegang dengan kewenangan yang berbeda-beda: `EXECUTIVE`
        dipegang GM kantor pusat (lintas company) **dan** GM site
        (sebatas lokasinya). Nama seperti "Executive — Sesuai Company
        Penempatan" jadi salah untuk separuh pemegangnya — dan nama di
        layar administrasi dibaca sebagai kebijakan.
        """
        from apps.accounts.management.commands import seed_data_scopes as sds
        from apps.hr.seeds.demo_org_scope import SCOPE_ROLES
        from apps.workflow.seeds.workflows import REQUIRED_ROLES

        names = (
            [(row["code"], row["name"]) for row in sds.SCOPED_ROLES]
            + [(row["code"], row["name"]) for row in SCOPE_ROLES]
            + [(code, label) for code, label in REQUIRED_ROLES]
        )

        offenders = [
            (code, name) for code, name in names
            if "Sesuai Company Penempatan" in name
            or "Sesuai Lokasi Penempatan" in name
            or "Sesuai Penempatan" in name
            or name.endswith("— Site")
        ]

        self.assertEqual(
            offenders, [],
            msg=f"nama role menjanjikan cakupan: {offenders}",
        )


class SeedCatalogueAgreementTests(TenantTestCase):
    """Tabel seed tidak boleh menyebut role yang sudah tidak ada."""

    def test_no_seed_table_names_a_retired_code(self):
        from apps.accounts.management.commands import seed_data_scopes as sds
        from apps.accounts.seeds.role_authority import SEED_ROLE_AUTHORITY
        from apps.accounts.seeds.security_roles import READ_GRANTS
        from apps.hr.seeds.demo_org_scope import SCOPE_ROLES

        declared = (
            set(sds.COMPANY_WIDE_CODES)
            | set(sds.SITE_DESK_CODES)
            | {row["code"] for row in sds.SCOPED_ROLES}
            | {row["code"] for row in sds.DECLARED_SCOPES}
            | set(SEED_ROLE_AUTHORITY)
            | set(READ_GRANTS)
            | {row["code"] for row in SCOPE_ROLES}
        )

        still_named = sorted(declared & (set(RETIRED) | {"KTT-SITE"}))

        self.assertEqual(
            still_named, [],
            msg=("tabel seed masih menyebut role yang ditarik — seed berikutnya "
                 f"akan membuatnya kembali: {still_named}"),
        )

    def test_the_workflow_seed_names_the_renamed_role(self):
        """
        Seed alur mencari role-nya **lewat kode**, bukan lewat FK.

        FK yang sudah tersimpan selamat dari rename dengan sendirinya —
        yang berubah isi kolom, bukan barisnya. Yang **tidak** selamat
        pencarian berdasarkan kode: seed yang masih menyebut `KTT-SITE`
        akan membuat role kedua bernama lama, lalu memasangnya sebagai
        approver — dan meja itu jadi kosong tanpa satu pun pesan.
        """
        from apps.workflow.seeds import workflows as wf

        catalogue = {code for code, _label in wf.REQUIRED_ROLES}

        self.assertIn("KTT", catalogue)
        self.assertNotIn("KTT-SITE", catalogue)

        # Daftar step-nya tersebar di beberapa konstanta modul
        # (`LEAVE_STEPS`, `SITE_STEPS`, ...). Dikumpulkan dari atribut
        # modulnya, bukan disebut satu per satu: daftar yang ditulis
        # tangan akan ketinggalan begitu ada alur baru, dan
        # ketinggalannya tidak berbunyi.
        referenced: set[str] = set()

        for name in dir(wf):
            if not name.endswith("_STEPS"):
                continue

            value = getattr(wf, name)

            if not isinstance(value, list):
                continue

            for step in value:
                if not isinstance(step, dict):
                    continue

                for key in ("approver_role", "fallback_role"):
                    code = step.get(key)

                    if code:
                        referenced.add(code)

        self.assertIn(
            "KTT", referenced,
            msg="tidak ada step yang menyebut KTT — penjaganya tidak menguji apa pun",
        )

        dangling = sorted(referenced - catalogue)

        self.assertEqual(
            dangling, [],
            msg=f"step menyebut role yang tidak ada di katalog seed: {dangling}",
        )


class ConsolidationBehaviourTests(TenantTestCase):
    """
    Fungsi migration-nya dijalankan langsung, terhadap keadaan buatan.

    Data demo tidak bisa memperagakan cabang yang paling penting —
    bentrokan pemegang ganda — jadi keadaannya disusun di sini.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(code="RC-C", name="RC C")

    def _user(self, name):
        return get_user_model().objects.create_user(
            username=name, email=f"{name}@example.test", password="x")

    def _role(self, code, name=None):
        return Role.objects.create(code=code, name=name or code.title())

    def _run(self):
        _migration().forwards(django_apps, None)

    def test_an_assignment_moves_and_keeps_its_authority_exactly(self):
        source = self._role("HR-ADMIN-SITE")
        target = self._role("HR-ADMIN")

        user = self._user("rc.site")

        assignment = RoleAssignment.objects.create(
            user=user,
            role=source,
            authority_mode=AuthorityMode.PLACEMENT,
            authority_level=DataScopeLevel.LOCATION,
        )

        pk = assignment.pk

        self._run()

        moved = RoleAssignment.objects.get(pk=pk)

        self.assertEqual(moved.role_id, target.pk)

        # **Kewenangannya tidak disentuh.** Ini assertion yang paling
        # penting di berkas ini: kalau ia diturunkan ulang dari katalog,
        # pemegangnya jadi `unrestricted` dan melihat seluruh tenant.
        self.assertEqual(moved.authority_mode, AuthorityMode.PLACEMENT)
        self.assertEqual(moved.authority_level, DataScopeLevel.LOCATION)

        self.assertFalse(
            Role.objects.get(pk=source.pk).is_active)

    def test_authority_rows_travel_with_the_assignment(self):
        source = self._role("EXECUTIVE-SITE")
        target = self._role("EXECUTIVE")

        user = self._user("rc.exec")

        assignment = RoleAssignment.objects.create(
            user=user, role=source, authority_mode=AuthorityMode.EXPLICIT)

        RoleAssignmentAuthority.objects.create(
            assignment=assignment,
            resource_type="company",
            resource_id=self.company.pk,
        )

        self._run()

        moved = RoleAssignment.objects.get(pk=assignment.pk)

        self.assertEqual(moved.role_id, target.pk)

        self.assertEqual(
            sorted(moved.authorities.values_list("resource_type", "resource_id")),
            [("company", self.company.pk)],
        )

        # Nol baris ditulis ulang: jumlah totalnya tetap satu.
        self.assertEqual(RoleAssignmentAuthority.objects.count(), 1)

    def test_a_holder_of_both_is_left_alone_and_the_source_stays_active(self):
        """
        Bentrokan **tidak** ditebak.

        `UNIQUE(user, role)` menolak barisnya, dan memilih salah satu
        kewenangan berarti memilih antara membuang pembatasan yang
        sengaja dipasang dan melebarkan akses. Keduanya keputusan orang.
        Jadi penugasannya dibiarkan **dan** role sumbernya tetap aktif,
        supaya tidak ada yang kehilangan akses sebelum diputuskan.
        """
        source = self._role("HR-MANAGER-SITE")
        target = self._role("HR-MANAGER")

        user = self._user("rc.both")

        narrow = RoleAssignment.objects.create(
            user=user,
            role=source,
            authority_mode=AuthorityMode.PLACEMENT,
            authority_level=DataScopeLevel.LOCATION,
        )

        wide = RoleAssignment.objects.create(
            user=user, role=target, authority_mode=AuthorityMode.UNRESTRICTED)

        self._run()

        narrow.refresh_from_db()
        wide.refresh_from_db()

        self.assertEqual(narrow.role_id, source.pk)
        self.assertEqual(narrow.authority_mode, AuthorityMode.PLACEMENT)

        self.assertEqual(wide.role_id, target.pk)
        self.assertEqual(wide.authority_mode, AuthorityMode.UNRESTRICTED)

        self.assertTrue(
            Role.objects.get(pk=source.pk).is_active,
            msg="role sumber dinonaktifkan padahal masih ada yang memegangnya",
        )

    def test_running_it_twice_changes_nothing(self):
        source = self._role("HR-ADMIN-SITE")
        target = self._role("HR-ADMIN")

        user = self._user("rc.idem")

        assignment = RoleAssignment.objects.create(
            user=user,
            role=source,
            authority_mode=AuthorityMode.PLACEMENT,
            authority_level=DataScopeLevel.LOCATION,
        )

        self._run()

        first = list(
            RoleAssignment.objects
            .values_list("pk", "user_id", "role_id",
                         "authority_mode", "authority_level")
            .order_by("pk")
        )

        self._run()

        self.assertEqual(
            list(
                RoleAssignment.objects
                .values_list("pk", "user_id", "role_id",
                             "authority_mode", "authority_level")
                .order_by("pk")
            ),
            first,
        )

        self.assertEqual(
            RoleAssignment.objects.get(pk=assignment.pk).role_id, target.pk)

    def test_a_missing_target_leaves_the_source_untouched(self):
        """
        Tanpa target, menonaktifkan sumber cuma mencabut akses.

        Bisa terjadi pada tenant yang katalognya tidak lengkap — dan
        jawaban yang benar di situ tidak melakukan apa-apa, bukan
        membersihkan setengah jalan.
        """
        source = self._role("HR-MANAGER-SITE")

        user = self._user("rc.notarget")

        assignment = RoleAssignment.objects.create(
            user=user,
            role=source,
            authority_mode=AuthorityMode.PLACEMENT,
            authority_level=DataScopeLevel.LOCATION,
        )

        self._run()

        assignment.refresh_from_db()

        self.assertEqual(assignment.role_id, source.pk)
        self.assertTrue(Role.objects.get(pk=source.pk).is_active)

    def test_the_rename_keeps_the_same_row(self):
        """
        Rename mengganti **isi kolom**, bukan barisnya — dan itu yang
        membuat setiap FK yang menunjuknya (`WorkflowStep.approver_role`)
        tetap utuh tanpa disentuh.
        """
        role = self._role("KTT-SITE", "Kepala Teknik Tambang — Site")

        pk = role.pk

        self._run()

        renamed = Role.objects.get(pk=pk)

        self.assertEqual(renamed.code, "KTT")
        self.assertEqual(renamed.name, "Kepala Teknik Tambang")

    def test_the_rename_is_skipped_when_the_new_code_is_taken(self):
        existing = self._role("KTT", "KTT yang sudah ada")
        old = self._role("KTT-SITE", "Kepala Teknik Tambang — Site")

        self._run()

        self.assertEqual(Role.objects.get(pk=old.pk).code, "KTT-SITE")
        self.assertEqual(Role.objects.get(pk=existing.pk).code, "KTT")
