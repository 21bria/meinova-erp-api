"""
Kontrak isolasi untuk `ReusableTenantTestCase`.

Berkas ini ditulis **sebelum** satu kelas pun dikonversi, dan gunanya
bukan menguji django-tenants: ia mengunci janji yang membuat pemakaian
ulang schema boleh dipercaya. Kalau salah satunya pecah, yang salah
adalah pemakaian ulangnya — bukan test yang kebetulan menangkapnya.

Urutan kelas di dalam modul menentukan artinya. `ContractA…` menulis,
`ContractB…` membuktikan tak ada yang tertinggal; unittest memuat kelas
sesuai urutan abjad namanya, jadi awalannya sengaja berhuruf.
"""

from __future__ import annotations

import unittest
from datetime import date, time, timedelta

from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from django_tenants.utils import schema_context

from apps.administration.models import Company, LeaveType
from apps.core.testing.tenant import (
    ReusableTenantTestCase,
    applied_tenant_migrations,
    expected_tenant_migrations,
    missing_tenant_migrations,
)
from apps.hr.models import Employee, EmployeeLeave
from apps.hr.models.attendance import AttendanceLog, EmployeeAttendance
from apps.hr.models.attendance.permission import AttendancePermission
from apps.hr.models.overtime import EmployeeOvertime
from apps.workflow.models import (
    WorkflowApproval,
    WorkflowDefinition,
    WorkflowInstance,
    WorkflowStep,
)


SCHEMA = "fast_isolation"

# Ditinggalkan satu kelas, dicari kelas berikutnya. Kalau ketemu,
# schema yang dipakai ulang membocorkan tulisan test.
MARK = "ISO-LEAK-PROBE"

CACHE_KEY = "iso-contract-cache-probe"

LEAK_MODELS = (
    ("EmployeeAttendance", EmployeeAttendance),
    ("AttendanceLog", AttendanceLog),
    ("AttendancePermission", AttendancePermission),
    ("EmployeeLeave", EmployeeLeave),
    ("EmployeeOvertime", EmployeeOvertime),
    ("WorkflowInstance", WorkflowInstance),
    ("WorkflowApproval", WorkflowApproval),
)


class IsolationContractBase(ReusableTenantTestCase):
    reusable_schema_name = SCHEMA

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "isolation-contract"
        tenant.name = "Isolation Contract"

    @classmethod
    def build_baseline(cls):
        """Pondasi tetap. `get_or_create`, karena kelas kedua memakai
        schema yang sama dan `setUpClass` tidak ikut di-rollback."""
        cls.company, _ = Company.objects.get_or_create(
            code="ISO",
            is_deleted=False,
            defaults={"name": "Isolation Co"},
        )

        cls.leave_type, _ = LeaveType.objects.get_or_create(
            code="ISO-ANNUAL",
            is_deleted=False,
            defaults={"name": "Cuti Tahunan"},
        )

        cls.definition, _ = WorkflowDefinition.objects.get_or_create(
            code="ISO-FLOW",
            is_deleted=False,
            defaults={
                "name": "Isolation Flow",
                "module": "hr",
                "document_type": "iso_contract",
            },
        )

        cls.step, _ = WorkflowStep.objects.get_or_create(
            definition=cls.definition,
            sequence=1,
            is_deleted=False,
            defaults={"name": "Approved By"},
        )

    # ------------------------------------------------------------------

    def make_marked_employee(self, suffix: str = "1") -> Employee:
        return Employee.objects.create(
            employee_number=f"{MARK}-{suffix}",
            first_name="Isolation",
            last_name="Probe",
        )

    def make_one_row_per_model(self) -> None:
        """Satu baris bertanda di tiap tabel yang disebut kontrak."""
        employee = self.make_marked_employee()
        today = date(2026, 9, 1)

        EmployeeAttendance.objects.create(
            employee=employee,
            company=self.company,
            work_date=today,
            external_id=MARK,
        )

        AttendanceLog.objects.create(
            company=self.company,
            occurred_at=timezone.now(),
            employee_identifier=MARK,
        )

        AttendancePermission.objects.create(
            employee=employee,
            permission_type="late_arrival",
            date=today,
            reason=MARK,
        )

        EmployeeLeave.objects.create(
            employee=employee,
            leave_type=self.leave_type,
            start_date=today,
            end_date=today,
            notes=MARK,
        )

        EmployeeOvertime.objects.create(
            employee=employee,
            work_date=today,
            start_time=time(18, 0),
            end_time=time(20, 0),
            reason=MARK,
        )

        instance = WorkflowInstance.objects.create(
            definition=self.definition,
            module="hr",
            document_type="iso_contract",
            object_id=MARK,
        )

        WorkflowApproval.objects.create(
            instance=instance,
            step=self.step,
            name=MARK,
            sequence=1,
        )

    @staticmethod
    def marked_counts() -> dict[str, int]:
        return {
            "EmployeeAttendance": EmployeeAttendance.objects.filter(
                external_id=MARK,
            ).count(),
            "AttendanceLog": AttendanceLog.objects.filter(
                employee_identifier=MARK,
            ).count(),
            "AttendancePermission": AttendancePermission.objects.filter(
                reason=MARK,
            ).count(),
            "EmployeeLeave": EmployeeLeave.objects.filter(
                notes=MARK,
            ).count(),
            "EmployeeOvertime": EmployeeOvertime.objects.filter(
                reason=MARK,
            ).count(),
            "WorkflowInstance": WorkflowInstance.objects.filter(
                object_id=MARK,
            ).count(),
            "WorkflowApproval": WorkflowApproval.objects.filter(
                name=MARK,
            ).count(),
        }


class ContractA_WritesEverything(IsolationContractBase):
    """Kelas yang menulis. Isinya harus tidak tersisa buat kelas B."""

    def test_01_writes_one_row_per_named_model(self):
        self.make_one_row_per_model()

        counts = self.marked_counts()

        self.assertEqual(
            counts,
            {name: 1 for name, _ in LEAK_MODELS},
            "baris bertanda gagal dibuat — sisa kontraknya tidak "
            "menguji apa pun.",
        )

    def test_02_soft_deleted_row_exists_before_rollback(self):
        employee = self.make_marked_employee("soft")
        employee.is_deleted = True
        employee.save(update_fields=["is_deleted"])

        self.assertEqual(
            Employee.objects.filter(
                employee_number=f"{MARK}-soft", is_deleted=True,
            ).count(),
            1,
        )

    def test_03_writes_to_the_process_cache(self):
        cache.set(CACHE_KEY, "written by ContractA")

        self.assertEqual(cache.get(CACHE_KEY), "written by ContractA")

    def test_04_baseline_is_visible(self):
        self.assertEqual(
            Company.objects.filter(code="ISO", is_deleted=False).count(), 1,
        )

    def test_05_sequence_values_are_not_asserted_anywhere(self):
        """Nilai sequence tidak boleh jadi bagian dari kontrak."""
        first = self.make_marked_employee("seq-a")
        second = self.make_marked_employee("seq-b")

        self.assertGreater(second.pk, first.pk)


class ContractB_SeesNoLeak(IsolationContractBase):
    """Kelas berikutnya di schema yang sama."""

    def test_01_no_test_body_row_leaked(self):
        self.assertEqual(
            self.marked_counts(),
            {name: 0 for name, _ in LEAK_MODELS},
            "baris yang ditulis ContractA masih ada — pemakaian ulang "
            "schema membocorkan tulisan test.",
        )

    def test_02_soft_deleted_row_did_not_leak(self):
        # `objects` di sini manager biasa — ia **tidak** menyaring
        # `is_deleted`, jadi baris yang di-soft-delete kelas sebelumnya
        # akan terlihat kalau ia benar-benar bocor.
        self.assertEqual(
            Employee.objects.filter(
                employee_number__startswith=MARK,
            ).count(),
            0,
            "baris yang di-soft-delete kelas sebelumnya masih ada.",
        )

    def test_03_process_cache_was_cleared(self):
        self.assertIsNone(
            cache.get(CACHE_KEY),
            "cache proses membawa nilai dari kelas sebelumnya.",
        )

    def test_04_baseline_survived_and_was_not_duplicated(self):
        self.assertEqual(
            Company.objects.filter(code="ISO", is_deleted=False).count(),
            1,
            "pondasi terduplikasi — `build_baseline()` tidak idempoten.",
        )

    def test_05_connection_sits_on_the_reusable_schema(self):
        self.assertEqual(connection.schema_name, SCHEMA)

    def test_06_tenant_data_is_not_visible_from_public(self):
        self.make_one_row_per_model()

        with schema_context("public"):
            self.assertFalse(
                EmployeeAttendance._meta.db_table
                in connection.introspection.table_names(),
                "tabel presensi ada di schema public — data tenant "
                "bisa dibaca dari luar tenant.",
            )

    def test_07_a_failing_test_still_leaves_the_next_one_clean(self):
        """
        Test yang gagal tetap membayar rollback-nya.

        Dibuktikan dengan menjalankan kelas sekali pakai di dalam test
        ini: kalau rollback hanya berjalan di jalur sukses, baris yang
        ditulisnya akan terlihat sesudahnya.
        """
        outer = self

        class Exploding(IsolationContractBase):
            def test_write_then_raise(self):
                outer.make_marked_employee("boom")

                raise RuntimeError("sengaja gagal")

        result = unittest.TestResult()
        Exploding.setUpClass()

        try:
            # `__call__`, bukan `run()`: transaksi fixture Django
            # dipasang di `__call__`. Lewat `run()` tulisan test
            # mendarat di transaksi test luar dan buktinya palsu.
            Exploding("test_write_then_raise")(result)
        finally:
            # `tearDownClass` memindahkan koneksi ke public. Tanpa
            # dikembalikan, assertion di bawah membaca schema yang
            # tidak punya tabelnya dan gagal dengan sebab yang salah.
            Exploding.tearDownClass()
            connection.set_tenant(self.tenant)

        self.assertEqual(len(result.errors), 1, "test bantunya harus gagal")
        self.assertEqual(
            Employee.objects.filter(
                employee_number=f"{MARK}-boom",
            ).count(),
            0,
            "baris dari test yang gagal tetap tertinggal.",
        )


class ContractC_Identity(IsolationContractBase):
    """
    Identitas tenant yang dipakai ulang: schema, kode, domain.

    Ketiganya unique di basis data, dan baris tenant yang dipakai ulang
    **tidak pernah dihapus**. Satu identitas yang ditempati selamanya
    berarti kelas sekali pakai yang memakai identitas yang sama gagal
    di `setUpClass` — jauh dari berkas yang menyebabkannya.
    """

    def test_01_schema_code_and_domain_are_unique(self):
        from django_tenants.utils import get_tenant_domain_model, get_tenant_model

        with schema_context("public"):
            tenants = list(get_tenant_model().objects.all())
            domains = list(get_tenant_domain_model().objects.all())

        for label, values in (
            ("schema_name", [t.schema_name for t in tenants]),
            ("code", [t.code for t in tenants if t.code]),
            ("domain", [d.domain for d in domains]),
        ):
            self.assertEqual(
                len(values), len(set(values)),
                f"{label} terduplikasi antar tenant: {values}",
            )

    def test_02_domain_is_a_legal_hostname(self):
        """
        Garis bawah sah di nama schema, **tidak sah** di nama host.

        Kalau ia lolos ke domain, `request.get_host()` melempar
        `DisallowedHost`, middleware pulang 404 dan meninggalkan
        koneksi di public — dan test yang memang mengharapkan 404 lulus
        karena alasan yang salah.
        """
        from django.http.request import host_validation_re

        domain = self.get_test_tenant_domain()

        self.assertNotIn("_", domain)
        self.assertRegex(domain, host_validation_re)

    def test_03_the_stored_domain_matches_the_declaration(self):
        stored = self.tenant.get_primary_domain()

        self.assertIsNotNone(stored)
        self.assertEqual(stored.domain, self.get_test_tenant_domain())
        self.assertTrue(stored.is_primary)

    def test_04_a_tenant_client_request_keeps_the_tenant_schema(self):
        """
        Request lewat `TenantClient` harus **pulang ke schema tenant**.

        `TenantMainMiddleware.process_request()` selalu mulai dengan
        `set_schema_to_public()`; kalau host-nya tidak terselesaikan ia
        berhenti di situ. Jadi schema sesudah request adalah cara
        paling langsung membaca apakah host-nya sah.
        """
        from django_tenants.test.client import TenantClient

        TenantClient(self.tenant).get("/api/hr/attendance-permissions/")

        self.assertEqual(
            connection.schema_name,
            SCHEMA,
            "koneksi tertinggal di public sesudah request — host tenant "
            "tidak terselesaikan.",
        )


class ContractD_MigrationGuard(IsolationContractBase):
    """Penjaga kebasian schema."""

    def test_01_disk_expectation_is_not_empty(self):
        self.assertGreater(
            len(expected_tenant_migrations()),
            50,
            "daftar migrasi tenant dari disk kosong — penjaganya akan "
            "menganggap setiap schema mutakhir.",
        )

    def test_02_live_schema_reports_no_missing_migration(self):
        self.assertEqual(
            missing_tenant_migrations(SCHEMA),
            set(),
            "schema yang baru dibangun sudah tertinggal migrasi.",
        )

    def test_03_absent_schema_counts_as_fully_stale(self):
        self.assertEqual(
            missing_tenant_migrations("schema_yang_tidak_pernah_ada"),
            expected_tenant_migrations(),
        )

    def test_04_applied_is_a_subset_of_expected(self):
        applied = applied_tenant_migrations(SCHEMA)

        self.assertTrue(applied)
        self.assertTrue(applied.issubset(expected_tenant_migrations()))

    def test_05_guard_notices_a_removed_migration_record(self):
        """
        Satu catatan migrasi dihapus → schema terbaca basi.

        Penghapusannya terjadi di dalam transaksi test dan ikut
        di-rollback, jadi schema-nya sendiri tidak pernah benar-benar
        rusak oleh test ini.
        """
        from django.db.migrations.recorder import MigrationRecorder

        victim = sorted(applied_tenant_migrations(SCHEMA))[0]

        with schema_context(SCHEMA):
            MigrationRecorder.Migration.objects.filter(
                app=victim[0], name=victim[1],
            ).delete()

            self.assertIn(victim, missing_tenant_migrations(SCHEMA))
