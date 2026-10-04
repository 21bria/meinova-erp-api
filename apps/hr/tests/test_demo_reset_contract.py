"""
Kontrak `reset_demo_data`: yang memegang pegawai harus dilepas dulu.

Perintah ini menghapus pegawai data uji secara **hard delete**, dan
belasan tabel memegang `Employee` lewat FK ber-`PROTECT`. Setiap tabel
yang lupa disebut menghasilkan kegagalan dengan bentuk yang sama dan
sama-sama menyesatkan: `ProtectedError` di langkah terakhir, menyebut
nama tabel yang tidak pernah muncul di perintah itu, berjam-jam
sesudah orang yang menjalankannya pergi.

Tiga tabel di bawah pernah benar-benar tertinggal:

* `AttendancePermission` — tak terlihat selama tabelnya kosong;
* `AttendanceLog` — sama, dan ia juga menunjuk baris presensinya;
* `PayrollRunEmployee` / `Payslip` / `PayrollInput` — yang ini bahkan
  **sudah** memblokir reset di tenant peragaan, karena payroll pernah
  dijalankan di sana.

Satu pagar tambahan diuji di sini: run yang sudah FINALIZED membawa
kejadian akuntansi di modul Finance yang tidak dilihat perintah ini
sama sekali. Membuang barisnya diam-diam meninggalkan jurnal yang
menunjuk perhitungan yang tidak ada lagi, dan itu tidak bisa
diperbaiki dari sisi HR — jadi reset menolak, bukan melanjutkan.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django_tenants.test.cases import TenantTestCase

from apps.administration.models import Company, Location, Shift
from apps.hr.models import (
    AttendanceLog,
    AttendancePermission,
    Employee,
    EmployeeAttendance,
)
from apps.hr.seeds.demo_reset import run
from apps.payroll.models import (
    PayrollGroup,
    PayrollPeriod,
    PayrollRun,
    PayrollRunEmployee,
)


User = get_user_model()


class DemoResetContractTestCase(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "demo-reset"
        tenant.name = "Demo Reset"

    _seq = 0

    def tag(self):
        type(self)._seq += 1

        return f"DR{type(self)._seq:04d}"

    def setUp(self):
        super().setUp()

        tag = self.tag()

        self.company = Company.objects.create(
            code=f"CMP-{tag}",
            name=f"Perusahaan {tag}",
        )

        self.location = Location.objects.create(
            company=self.company,
            code=f"LOC-{tag}",
            name=f"Lokasi {tag}",
        )

        self.shift = Shift.objects.create(
            code=f"SH-{tag}",
            name=f"Shift {tag}",
            start_time="08:00",
            end_time="17:00",
        )

        # Nomor ber-prefix `HO` supaya ia masuk cakupan reset. Prefix
        # itulah satu-satunya penanda data uji yang dipakai perintahnya.
        self.employee = Employee.objects.create(
            employee_number=f"HO{tag}",
            first_name="Uji",
            last_name="Reset",
        )

        # Dan satu pegawai yang **tidak** boleh tersentuh: nomornya di
        # luar prefix data uji. Kalau cakupan resetnya melar, ia yang
        # pertama hilang.
        self.outsider = Employee.objects.create(
            employee_number=f"KW{tag}",
            first_name="Klien",
            last_name="Sungguhan",
        )

    # ------------------------------------------------------------------
    # Bahan
    # ------------------------------------------------------------------

    def make_permission(self, employee=None):
        return AttendancePermission.objects.create(
            employee=employee or self.employee,
            company=self.company,
            location=self.location,
            permission_type="full_day",
            date=date(2026, 9, 1),
            reason="Uji kontrak reset.",
        )

    def make_attendance_log(self, employee=None):
        attendance = EmployeeAttendance.objects.create(
            employee=employee or self.employee,
            company=self.company,
            work_date=date(2026, 9, 1),
        )

        return AttendanceLog.objects.create(
            employee=employee or self.employee,
            attendance=attendance,
            company=self.company,
            occurred_at="2026-09-01T08:00:00Z",
            log_type="in",
        )

    def make_payroll(self, *, status="draft", employee=None):
        group = PayrollGroup.objects.create(
            code=f"PG-{self.tag()}",
            name="Bulanan Uji",
        )

        period = PayrollPeriod.objects.create(
            company=self.company,
            payroll_group=group,
            code=f"PP-{self.tag()}",
            name="Periode Uji",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 30),
        )

        run_ = PayrollRun.objects.create(
            company=self.company,
            period=period,
            document_number=f"PR-{self.tag()}",
            status=status,
        )

        line = PayrollRunEmployee.objects.create(
            run=run_,
            employee=employee or self.employee,
            company=self.company,
            basic_salary=Decimal("1000000.00"),
        )

        return run_, line

    # ------------------------------------------------------------------
    # Yang harus ikut terbuang
    # ------------------------------------------------------------------

    def test_attendance_permission_tidak_memblokir_reset(self):
        self.make_permission()

        run(log=lambda *a, **k: None)

        self.assertFalse(
            Employee.objects.filter(pk=self.employee.pk).exists(),
        )
        self.assertEqual(AttendancePermission.objects.count(), 0)

    def test_izin_yang_sudah_ditandai_terhapus_ikut_dibuang(self):
        """
        Baris bertanda terhapus tetap memegang FK-nya.

        Justru inilah bentuk yang paling sering tertinggal: layar
        menampilkannya sebagai sudah hilang, database tidak.
        """
        permission = self.make_permission()

        permission.is_deleted = True
        permission.save(update_fields=["is_deleted"])

        run(log=lambda *a, **k: None)

        self.assertEqual(AttendancePermission.objects.count(), 0)

    def test_attendance_log_tidak_memblokir_reset(self):
        self.make_attendance_log()

        run(log=lambda *a, **k: None)

        self.assertFalse(
            Employee.objects.filter(pk=self.employee.pk).exists(),
        )
        self.assertEqual(AttendanceLog.objects.count(), 0)
        self.assertEqual(EmployeeAttendance.objects.count(), 0)

    def test_bukti_verifikasi_tap_tidak_memblokir_reset(self):
        """
        ATT-BIO-1B: tap Self Service yang ditolak meninggalkan log + bukti
        verifikasi ber-PROTECT. Reset membuangnya lewat jalur yang dijaga;
        bukti milik pegawai di luar cakupan tetap utuh.
        """
        from apps.hr.models import AttendanceLogVerification

        def evidence(employee):
            log = AttendanceLog.objects.create(
                employee=employee,
                company=self.company,
                occurred_at="2026-09-01T08:00:00Z",
                log_type="in",
                source="mobile",
                external_id=f"self-punch:{employee.employee_number}",
            )
            return AttendanceLogVerification.objects.create(
                log=log,
                decision="rejected",
                reason_code="face_mismatch",
                face_result="fail",
            )

        evidence(self.employee)
        kept = evidence(self.outsider)

        run(log=lambda *a, **k: None)

        self.assertFalse(Employee.objects.filter(pk=self.employee.pk).exists())
        self.assertEqual(
            list(AttendanceLogVerification.objects.values_list("pk", flat=True)),
            [kept.pk],
        )
        self.assertEqual(
            list(AttendanceLog.objects.values_list("employee_id", flat=True)),
            [self.outsider.pk],
        )

    def test_baris_payroll_tidak_memblokir_reset(self):
        run_, _line = self.make_payroll()

        run(log=lambda *a, **k: None)

        self.assertFalse(
            Employee.objects.filter(pk=self.employee.pk).exists(),
        )
        self.assertEqual(PayrollRunEmployee.objects.count(), 0)

        # Kepala run dibiarkan: ia dokumen HR, bukan data uji.
        self.assertTrue(PayrollRun.objects.filter(pk=run_.pk).exists())

    # ------------------------------------------------------------------
    # Pagar
    # ------------------------------------------------------------------

    def test_run_finalized_menghentikan_reset(self):
        self.make_payroll(status="finalized")

        with self.assertRaises(RuntimeError) as caught:
            run(log=lambda *a, **k: None)

        self.assertIn("FINALIZED", str(caught.exception))

        # Dan tidak ada yang terbuang sebagian: seluruh reset berada di
        # satu transaksi.
        self.assertTrue(
            Employee.objects.filter(pk=self.employee.pk).exists(),
        )
        self.assertEqual(PayrollRunEmployee.objects.count(), 1)

    def test_run_finalized_milik_pegawai_lain_tidak_menghentikan(self):
        """
        Pagarnya menagih run terkunci yang **memakai pegawai data uji**,
        bukan run terkunci mana pun di tenant. Tenant yang payroll-nya
        sudah berjalan untuk pegawai sungguhan tidak boleh kehilangan
        kemampuan membangun ulang data uji.
        """
        self.make_payroll(status="finalized", employee=self.outsider)

        run(log=lambda *a, **k: None)

        self.assertFalse(
            Employee.objects.filter(pk=self.employee.pk).exists(),
        )

    # ------------------------------------------------------------------
    # Cakupan
    # ------------------------------------------------------------------

    def test_pegawai_di_luar_prefix_data_uji_selamat(self):
        self.make_permission()

        run(log=lambda *a, **k: None)

        self.assertTrue(
            Employee.objects.filter(pk=self.outsider.pk).exists(),
        )
