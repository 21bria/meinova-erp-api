"""
`GET /api/me/workspace/` — identitas, isolasi, kejujuran kartu.

Empat hal diuji dan keempatnya harus benar bersamaan:

1. **Subjeknya tidak bisa digeser.** Tidak lewat query, path, body, atau
   header. Yang diuji bukan "penjagaannya menolak" melainkan "tidak ada
   parameternya sama sekali" — lihat `test_identitas_*`.
2. **Tidak ada data orang lain yang sampai.** Pegawai B diberi presensi,
   saldo cuti, izin, lembur, dan slip gaji yang **nilainya khas**, lalu
   seluruh respons A digeledah sampai ke daun terdalam. Uji terhadap
   nilai, bukan cuma nama kunci: kebocoran yang paling sunyi adalah yang
   bersarang.
3. **Kartu yang kosong berkata kosong.** `empty` bukan nol, dan nol
   bukan "belum tersedia".
4. **Tidak ada nilai rupiah, catatan internal, atau metadata audit** yang
   ikut terbawa — sedalam apa pun letaknya.

Fixture-nya **selalu** memakai nilai yang tidak mungkin muncul kebetulan
(`RAHASIA-…`, `987654321`, `HO-BOCOR`). Test yang mencari `0` atau `""`
akan hijau untuk alasan yang salah.
"""

from __future__ import annotations

import json
from unittest import mock
from datetime import date, datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.accounts.models import Menu, Role, RoleMenuPermission
from apps.administration.models import (
    Company,
    Department,
    EmploymentStatus,
    EmploymentType,
    LeaveType,
    Location,
    Position,
)
from apps.hr.models import (
    Employee,
    EmployeeAttendance,
    EmployeeOvertime,
    EmploymentAssignment,
    LeaveBalance,
    OrganizationAssignment,
)
from apps.hr.models.attendance.permission import (
    AttendancePermission,
    AttendancePermissionStatus,
    AttendancePermissionType,
)
from apps.hr.models.overtime import OvertimeStatus
from apps.payroll.models import (
    PayrollGroup,
    Payslip,
    PayrollPeriod,
    PayrollRun,
    PayrollRunEmployee,
)
from apps.payroll.models.choices import PayslipStatus
from apps.self_service.services.workspace import SelfWorkspaceService


User = get_user_model()

WORKSPACE = "/api/me/workspace/"

# Hari yang dipakai seluruh test. Ditetapkan, bukan `date.today()`:
# panggung yang bergeser tiap hari membuat kegagalan besok tidak bisa
# dibedakan dari kegagalan kode.
AS_OF = date(2026, 9, 16)

SECTIONS = {
    "identity",
    "hero",
    "as_of",
    "schedule",
    "attendance",
    "requests",
    "leave",
    "permission",
    "overtime",
    "payslip",
    "quick_actions",
}

# Tidak boleh muncul sebagai **kunci**, sedalam apa pun.
FORBIDDEN_KEYS = {
    # Uang, dalam bentuk apa pun.
    "basic_salary",
    "gross_earning",
    "total_deduction",
    "tax_amount",
    "net_pay",
    "employer_contribution",
    "snapshot",
    "salary_grade",
    "salary_level",
    "payroll_group",
    "bank_account",
    "tax_status",
    "tax_number",
    "bpjs_kesehatan_number",
    "bpjs_ketenagakerjaan_number",
    # Catatan kerja HR.
    "notes",
    "review_notes",
    "review_decision",
    "adjustment_reason",
    "leave_required_reason",
    "leave_required_days",
    "leave_required_waiver_reason",
    "outside_shift_reason",
    "reason",
    "organization_notes",
    "employment_notes",
    # Jejak perangkat dan lokasi fisik.
    "check_in_latitude",
    "check_in_longitude",
    "check_out_latitude",
    "check_out_longitude",
    "check_in_address",
    "check_out_address",
    "device_code",
    "external_id",
    "import_batch_id",
    "is_geofence_valid",
    # Metadata audit dan penghapusan.
    "created_by",
    "updated_by",
    "deleted_by",
    "deleted_at",
    "is_deleted",
    "approved_by",
    "published_by",
    # Internal engine dan role.
    "can_configure",
    "can_monitor_all",
    "current_step",
    "approver",
    "approvals",
    "user",
    "public_id",
    "storage_path",
}


def walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_keys(item)


def utc(day: date, hour: int, minute: int) -> datetime:
    return datetime(
        day.year, day.month, day.day, hour, minute, tzinfo=dt_timezone.utc,
    )


class SelfWorkspaceTestCase(TenantTestCase):
    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "self-service-workspace"
        tenant.name = "Self Service Workspace"

    @classmethod
    def setUpClass(cls):
        """
        Jam dibekukan di `AS_OF`, dan itu **hanya** di test.

        Tanpa ini seluruh berkas ini adalah bom waktu: fixture-nya
        bertanggal tetap sementara servicenya membaca hari berjalan, jadi
        besok "presensi hari ini" jadi presensi kemarin dan enam test
        merah tanpa satu baris kode pun berubah. Yang dibekukan seam yang
        memang disediakan service — bukan `timezone.localdate` global,
        yang akan ikut menggeser mesin kalender di bawahnya.
        """
        clock = mock.patch.object(
            SelfWorkspaceService,
            "today",
            classmethod(lambda cls: AS_OF),
        )
        clock.start()
        cls.addClassCleanup(clock.stop)

        super().setUpClass()

        cls.company = Company.objects.create(code="SSW", name="Workspace Co")
        cls.site = Location.objects.create(
            company=cls.company, code="SSW-HO", name="Head Office",
        )
        cls.department = Department.objects.create(
            company=cls.company, code="FIN", name="Finance",
        )
        cls.position = Position.objects.create(
            company=cls.company, code="STF", name="Staff",
        )
        cls.status = EmploymentStatus.objects.create(code="ACT", name="Active")
        cls.etype = EmploymentType.objects.create(code="PKWTT", name="Permanent")

        cls.payroll_group = PayrollGroup.objects.create(
            code="SSW-MONTH", name="Monthly",
        )

        cls.annual = LeaveType.objects.create(code="ANNUAL", name="Cuti Tahunan")
        cls.unpaid = LeaveType.objects.create(code="UNPAID", name="Cuti Tanpa Gaji")

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
            username=f"ws-{n}",
            email=f"ws-{n}@example.test",
            password="pw",
        )

    def make_employee(self, *, user=None, first="Bimo", placed=True):
        n = self._next()

        employee = Employee.objects.create(
            user=user,
            employee_number=f"WS{n:04d}",
            first_name=first,
            last_name="Nugroho",
            notes="RAHASIA-CATATAN-HR",
        )

        if placed:
            OrganizationAssignment.objects.create(
                employee=employee,
                company=self.company,
                location=self.site,
                department=self.department,
                position=self.position,
                organization_effective_date="2026-01-01",
                organization_notes="RAHASIA-CATATAN-ORG",
            )
            EmploymentAssignment.objects.create(
                employee=employee,
                employment_status=self.status,
                employment_type=self.etype,
                join_date="2020-01-06",
                employment_effective_date="2020-01-06",
                employment_notes="RAHASIA-CATATAN-KEPEGAWAIAN",
            )

        return employee

    def linked(self, **kwargs):
        user = self.make_user()

        return user, self.make_employee(user=user, **kwargs)

    def as_user(self, user):
        token = RefreshToken.for_user(user).access_token

        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def get(self, user, query=""):
        return self.http.get(f"{WORKSPACE}{query}", **self.as_user(user))

    def data(self, user, query=""):
        response = self.get(user, query)

        self.assertEqual(response.status_code, 200, response.content)

        return response.json()["data"]

    def grant(self, user, *names):
        for name in names:
            app_label, _, codename = name.partition(".")

            permission = Permission.objects.get(
                content_type__app_label=app_label,
                codename=codename,
            )

            user.user_permissions.add(permission)

        # `ModelBackend` menyimpan hasilnya pada instance; tanpa
        # pembuangan ini, izin yang baru ditambahkan tidak terbaca pada
        # request berikutnya di test yang sama.
        for attr in ("_perm_cache", "_user_perm_cache", "_role_perm_cache"):
            user.__dict__.pop(attr, None)

    # -- data transaksi ------------------------------------------------

    def attendance_for(self, employee, *, day=AS_OF, status="late"):
        return EmployeeAttendance.objects.create(
            employee=employee,
            # Kolomnya NOT NULL — presensi selalu terjadi di sebuah
            # badan usaha, dan itu didenormalisasi saat barisnya dibuat.
            company=self.company,
            location=self.site,
            work_date=day,
            status=status,
            check_in=utc(day, 1, 52),
            check_out=utc(day, 10, 5),
            late_minutes=7,
            notes="RAHASIA-CATATAN-PRESENSI",
            device_code="MESIN-BOCOR",
            check_in_address="RAHASIA-ALAMAT",
        )

    def balance_for(self, employee, *, remaining, year=2026, leave_type=None):
        return LeaveBalance.objects.create(
            employee=employee,
            leave_type=leave_type or self.annual,
            year=year,
            entitlement=Decimal(str(remaining)),
            notes="RAHASIA-CATATAN-SALDO",
        )

    def permission_for(self, employee, *, day=AS_OF, status=None):
        return AttendancePermission.objects.create(
            employee=employee,
            date=day,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time="09:30",
            reason="RAHASIA-ALASAN-IZIN",
            status=status or AttendancePermissionStatus.APPROVED,
        )

    def overtime_for(
        self,
        employee,
        *,
        day=AS_OF,
        minutes=240,
        status=None,
        is_paid=True,
    ):
        return EmployeeOvertime.objects.create(
            employee=employee,
            work_date=day,
            start_time="18:00",
            end_time="22:00",
            duration_minutes=minutes,
            is_paid=is_paid,
            status=status or OvertimeStatus.APPROVED,
            reason="RAHASIA-ALASAN-LEMBUR",
        )

    def payslip_for(self, employee, *, net=Decimal("987654321.00"), published=True):
        n = self._next()

        period = PayrollPeriod.objects.create(
            company=self.company,
            payroll_group=self.payroll_group,
            code=f"P{n:04d}",
            name=f"Agustus {2026 + n}",
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
        )
        run = PayrollRun.objects.create(period=period, company=self.company)
        run_employee = PayrollRunEmployee.objects.create(
            run=run,
            employee=employee,
        )

        return Payslip.objects.create(
            run_employee=run_employee,
            run=run,
            period=period,
            employee=employee,
            document_number=f"SLP-{n:06d}",
            issue_date=date(2026, 9, 1),
            net_pay=net,
            basic_salary=net,
            gross_earning=net,
            status=(
                PayslipStatus.PUBLISHED if published else PayslipStatus.DRAFT
            ),
            notes="RAHASIA-CATATAN-SLIP",
        )

    # ==================================================================
    # Identitas
    # ==================================================================

    def test_tanpa_login(self):
        self.assertEqual(self.http.get(WORKSPACE).status_code, 401)

    def test_akun_tanpa_kartu_pegawai(self):
        response = self.get(self.make_user())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "employee_not_linked")

    def test_kartu_nonaktif(self):
        user, employee = self.linked()

        employee.is_active = False
        employee.save(update_fields=["is_active"])

        response = self.get(user)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "employee_inactive")

    def test_kartu_terhapus_terbaca_seperti_tidak_pernah_ada(self):
        user, employee = self.linked()

        employee.is_deleted = True
        employee.save(update_fields=["is_deleted"])

        self.assertEqual(self.get(user).status_code, 404)

    def test_identitas_tidak_bergeser_lewat_query(self):
        """
        Enam ejaan parameter yang lazim dipakai orang menebak. Semuanya
        harus dijawab dengan kartu **miliknya sendiri** — bukan ditolak,
        karena yang benar bukan "ditolak" melainkan "tidak pernah
        dibaca".
        """
        user, employee = self.linked(first="Bimo")
        _other_user, other = self.linked(first="Sasmita")

        self.attendance_for(other)

        for query in (
            f"?employee={other.pk}",
            f"?employee_id={other.pk}",
            f"?id={other.pk}",
            f"?public_id={other.pk}",
            f"?pk={other.pk}",
            f"?employee_number={other.employee_number}",
        ):
            with self.subTest(query=query):
                data = self.data(user, query)

                self.assertEqual(data["identity"]["id"], employee.pk)
                self.assertEqual(data["attendance"]["state"], "empty")

    def test_tidak_ada_varian_berparameter_di_path(self):
        user, _employee = self.linked()
        _other_user, other = self.linked()

        for path in (
            f"{WORKSPACE}{other.pk}/",
            f"{WORKSPACE}employee/{other.pk}/",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    self.http.get(path, **self.as_user(user)).status_code,
                    404,
                )

    def test_body_tidak_dibaca_sama_sekali(self):
        """POST tidak dilayani; tidak ada jalur tulis yang bisa lupa."""
        user, _employee = self.linked()
        _other_user, other = self.linked()

        response = self.http.post(
            WORKSPACE,
            data=json.dumps({"employee": other.pk}),
            content_type="application/json",
            **self.as_user(user),
        )

        self.assertEqual(response.status_code, 405)

    # ==================================================================
    # Nol izin administratif
    # ==================================================================

    def test_tanpa_satu_pun_izin_tetap_melihat_dirinya(self):
        """
        Inti Self Service. Akun ini tidak punya role, tidak punya
        `hr.view_employee`, tidak punya cakupan data — dan tetap
        mendapat ringkasannya sendiri.
        """
        user, employee = self.linked()

        self.assertEqual(user.roles.count(), 0)
        self.assertFalse(user.has_perm("hr.view_employee"))
        self.assertFalse(user.has_perm("hr.view_employeeattendance"))

        self.attendance_for(employee)
        self.balance_for(employee, remaining=9)

        data = self.data(user)

        self.assertEqual(set(data), SECTIONS)
        self.assertEqual(data["identity"]["id"], employee.pk)
        self.assertEqual(data["attendance"]["state"], "ready")
        self.assertEqual(data["leave"]["balances"][0]["remaining"], 9.0)

    # ==================================================================
    # Isolasi antar pegawai
    # ==================================================================

    def test_tidak_ada_jejak_pegawai_lain(self):
        """
        B diberi **seluruh** jenis data, semuanya bernilai khas. Respons
        A diratakan jadi satu string dan digeledah.
        """
        user, _employee = self.linked(first="Bimo")
        _other_user, other = self.linked(first="Sasmita")

        other.employee_number = "HO-BOCOR"
        other.save(update_fields=["employee_number"])

        self.attendance_for(other)
        self.balance_for(other, remaining=7777)
        self.permission_for(other)
        self.overtime_for(other, minutes=3333)
        self.payslip_for(other)

        body = json.dumps(self.data(user))

        for jejak in (
            "HO-BOCOR",
            "Sasmita",
            "RAHASIA",
            "987654321",
            "7777",
            "3333",
        ):
            with self.subTest(jejak=jejak):
                self.assertNotIn(jejak, body)

    def test_angka_sendiri_yang_muncul_bukan_gabungan(self):
        user, employee = self.linked()
        _other_user, other = self.linked()

        self.overtime_for(employee, minutes=120)
        self.overtime_for(other, minutes=999)

        self.assertEqual(self.data(user)["overtime"]["total_minutes"], 120)

    # ==================================================================
    # Daftar putih
    # ==================================================================

    def test_tidak_ada_kunci_terlarang(self):
        user, employee = self.linked()

        self.attendance_for(employee)
        self.balance_for(employee, remaining=9)
        self.permission_for(employee)
        self.overtime_for(employee)
        self.payslip_for(employee)

        self.grant(user, "payroll.view_payslip")

        keys = set(walk_keys(self.data(user)))

        self.assertEqual(keys & FORBIDDEN_KEYS, set())

    def test_slip_gaji_hanya_metadata(self):
        user, employee = self.linked()

        self.payslip_for(employee, net=Decimal("987654321.00"))
        self.grant(user, "payroll.view_payslip")

        payslip = self.data(user)["payslip"]

        self.assertEqual(payslip["state"], "ready")
        self.assertEqual(set(payslip["latest"]), {
            "period",
            "period_start",
            "issue_date",
            "document_number",
        })
        self.assertNotIn("987654321", json.dumps(payslip))

    def test_slip_gaji_tanpa_izin_model_tertutup(self):
        """
        Satu-satunya seksi yang bisa `restricted`, dan sebabnya milik
        domainnya: `PayslipViewSet` menyatakan `require_view_permission`.
        """
        user, employee = self.linked()

        self.payslip_for(employee)

        payslip = self.data(user)["payslip"]

        self.assertEqual(payslip["state"], "restricted")
        self.assertIsNone(payslip["latest"])
        self.assertIsNone(payslip["action"])

    def test_slip_draft_belum_diterbitkan(self):
        user, employee = self.linked()

        self.payslip_for(employee, published=False)
        self.grant(user, "payroll.view_payslip")

        self.assertEqual(self.data(user)["payslip"]["state"], "empty")

    # ==================================================================
    # Keadaan kosong
    # ==================================================================

    def test_pegawai_baru_semua_kartu_kosong_tapi_utuh(self):
        user, _employee = self.linked()

        data = self.data(user)

        self.assertEqual(set(data), SECTIONS)

        for section in ("attendance", "requests", "leave", "permission", "overtime"):
            with self.subTest(section=section):
                self.assertEqual(data[section]["state"], "empty")

        self.assertEqual(data["attendance"]["check_in"], None)
        self.assertEqual(data["leave"]["balances"], [])
        self.assertIsNone(data["permission"]["latest"])

    def test_nol_menit_lembur_adalah_kosong_bukan_nol_yang_dipajang(self):
        user, employee = self.linked()

        self.overtime_for(employee, minutes=0)

        overtime = self.data(user)["overtime"]

        self.assertEqual(overtime["state"], "empty")
        self.assertEqual(overtime["total_minutes"], 0)

    def test_tanpa_penempatan_tetap_200(self):
        """Pegawai yang penempatannya belum diisi tidak boleh 500."""
        user, _employee = self.linked(placed=False)

        data = self.data(user)

        self.assertIsNone(data["hero"]["company"])
        self.assertIsNone(data["hero"]["position"])
        self.assertIsNone(data["hero"]["employment_status"])

    # ==================================================================
    # Isi kartu
    # ==================================================================

    def test_presensi_hari_ini_saja(self):
        user, employee = self.linked()

        self.attendance_for(employee, day=AS_OF - timedelta(days=1))

        self.assertEqual(self.data(user)["attendance"]["state"], "empty")

    def test_jam_presensi_dirender_jam_dinding_kantor(self):
        """
        `check_in` disimpan UTC. Yang dikirim harus jam kantor — bukan
        jam penyimpanan, dan bukan jam perangkat pembacanya.
        """
        user, employee = self.linked()

        self.attendance_for(employee)

        attendance = self.data(user)["attendance"]

        # 01:52 UTC = 08:52 WIB.
        self.assertEqual(attendance["check_in"], "08:52")
        self.assertEqual(attendance["check_out"], "17:05")
        self.assertEqual(attendance["late_minutes"], 7)
        self.assertEqual(attendance["status"], "late")

    def test_saldo_cuti_tahun_berjalan_saja(self):
        user, employee = self.linked()

        self.balance_for(employee, remaining=9, year=2026)
        self.balance_for(employee, remaining=12, year=2027)

        balances = self.data(user)["leave"]["balances"]

        self.assertEqual(len(balances), 1)
        self.assertEqual(balances[0]["year"], 2026)
        self.assertEqual(balances[0]["remaining"], 9.0)

    def test_saldo_memakai_properti_domain_bukan_hitungan_sendiri(self):
        user, employee = self.linked()

        row = self.balance_for(employee, remaining=10)

        row.used = Decimal("4.0")
        row.save(update_fields=["used"])

        self.assertEqual(
            self.data(user)["leave"]["balances"][0]["remaining"],
            float(row.remaining),
        )

    def test_izin_menunggu_memakai_status_domain(self):
        user, employee = self.linked()

        self.permission_for(employee, status=AttendancePermissionStatus.SUBMITTED)
        self.permission_for(
            employee,
            day=AS_OF - timedelta(days=2),
            status=AttendancePermissionStatus.REJECTED,
        )

        permission = self.data(user)["permission"]

        self.assertEqual(permission["pending_count"], 1)
        self.assertEqual(permission["latest"]["status"], "submitted")

    def test_lembur_mengikuti_aturan_payroll(self):
        """
        Yang dihitung: `is_paid` dan berstatus RECORDED/APPROVED, bulan
        berjalan saja. Aturan yang sama dengan sumber payroll.
        """
        user, employee = self.linked()

        self.overtime_for(employee, minutes=60, status=OvertimeStatus.APPROVED)
        self.overtime_for(employee, minutes=30, status=OvertimeStatus.RECORDED)

        # Tidak boleh ikut: belum diputuskan, tidak dibayar, bulan lain.
        self.overtime_for(employee, minutes=500, status=OvertimeStatus.SUBMITTED)
        self.overtime_for(employee, minutes=500, is_paid=False)
        self.overtime_for(employee, minutes=500, day=date(2026, 8, 10))

        self.assertEqual(self.data(user)["overtime"]["total_minutes"], 90)

    def test_jadwal_membawa_keadaan_hari_ini(self):
        user, _employee = self.linked()

        schedule = self.data(user)["schedule"]

        self.assertIn(schedule["state"], {"ready", "empty"})
        self.assertIn("rotation_state", schedule)
        self.assertIn("time_label", schedule)

    # ==================================================================
    # Tombol
    # ==================================================================

    def test_tombol_tanpa_izin_model_tidak_tampil(self):
        user, _employee = self.linked()

        data = self.data(user)

        self.assertIsNone(data["overtime"]["action"])
        self.assertIsNone(data["leave"]["action"])
        self.assertEqual(
            [item["code"] for item in data["quick_actions"]],
            ["profile"],
        )

    def test_tombol_muncul_begitu_izinnya_ada(self):
        user, _employee = self.linked()

        self.grant(
            user,
            "hr.add_employeeleave",
            "hr.add_attendancepermission",
            "hr.add_employeeovertime",
        )

        data = self.data(user)

        self.assertEqual(
            data["leave"]["action"],
            {"code": "leave_request", "route": "/hr/leave/create?mode=my"},
        )
        self.assertEqual(
            [item["code"] for item in data["quick_actions"]],
            [
                "profile",
                "leave_request",
                "permission_request",
                "overtime_request",
            ],
        )

    def test_tombol_hilang_saat_menunya_dicabut(self):
        """
        Menu bukan penjagaan — halamannya tetap menegakkan izinnya
        sendiri. Yang diuji: dashboard tidak menyodorkan pintu yang di
        layar orang ini memang tidak ada.
        """
        user, _employee = self.linked()

        self.grant(user, "hr.add_employeeleave")

        role = Role.objects.create(code="WS-ROLE", name="Workspace Role")
        user.roles.add(role)

        # Satu baris menu saja yang dicentang: seluruh rute lain jadi
        # tidak terlihat untuk role ini.
        menu = Menu.objects.create(
            code="ws.profile", title="My Profile", route="/me/profile",
        )
        RoleMenuPermission.objects.create(role=role, menu=menu, can_view=True)

        data = self.data(user)

        self.assertIsNone(data["leave"]["action"])
        self.assertIsNone(data["schedule"]["action"])
        self.assertEqual(
            [item["code"] for item in data["quick_actions"]],
            ["profile"],
        )

    # ==================================================================
    # Bentuk
    # ==================================================================

    def test_bentuk_stabil(self):
        user, _employee = self.linked()

        data = self.data(user)

        self.assertEqual(set(data), SECTIONS)
        self.assertEqual(set(data["hero"]), {
            "position",
            "department",
            "company",
            "location",
            "employment_status",
            "employment_type",
        })
        self.assertEqual(set(data["identity"]), {
            "id",
            "employee_number",
            "full_name",
            "is_active",
            "avatar",
        })

    def test_tidak_memakai_endpoint_hr_lama(self):
        """
        `/api/hr/employees/me/` masih hidup demi kompatibilitas, tapi
        Self Service tidak berdiri di atasnya: akun tanpa
        `hr.view_employee` tetap mendapat workspace-nya.
        """
        user, _employee = self.linked()

        self.assertFalse(user.has_perm("hr.view_employee"))
        self.assertEqual(self.get(user).status_code, 200)
