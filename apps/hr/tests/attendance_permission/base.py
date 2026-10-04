"""
Pabrik data bersama untuk test Attendance Permission.

Tiap test membuat pegawainya sendiri dan hanya membaca miliknya.
Alasan yang dulu ditulis di sini — bahwa `TenantTestCase` tidak
me-rollback antar test — **keliru**, dan sudah diukur di
TEST-ISO-HR-0B: rollback per-test tetap berjalan. Yang memang tidak
pernah jalan `setUpTestData()`, karena `setUpClass()` django-tenants
tidak memanggil `super().setUpClass()` — dan data yang dibuat di
`setUpClass` **tidak** ikut di-rollback. Disiplinnya tetap dipakai:
ia yang membuat schema bisa dipakai ulang tanpa urutan eksekusi
menentukan hasil. Pola yang sama dengan
test Roster, Travel Request, dan Attendance Import — kalau tidak, urutan
eksekusi yang menentukan hasilnya.

Panggungnya sengaja memuat **dua shift**: 08:00–17:00 untuk kantor dan
20:00–05:00 untuk site. Yang kedua bukan pelengkap — separuh keputusan
di modul ini (penambatan jam ke jendela shift, validasi di luar shift,
izin keluar yang melewati tengah malam) hanya bisa salah pada shift yang
menyeberang tanggal, dan panggung yang cuma punya shift siang akan tetap
hijau sepenuhnya.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django_tenants.test.cases import TenantTestCase

from apps.core.testing.tenant import ReusableTenantTestCase

from apps.accounts.models import Role
from apps.administration.models import (
    Company,
    Department,
    Location,
    Position,
    WorkCalendar,
)
from apps.administration.models.references.hr_attendance import Shift
from apps.administration.seeds.numbering import seed_numbering
from apps.hr.api.attendance.services import EmployeeAttendanceService
from apps.hr.api.attendance_permission.services import (
    AttendancePermissionService,
)
from apps.hr.models import (
    AttendancePermissionStatus,
    AttendancePermissionType,
    Employee,
    EmployeeAttendance,
    EmploymentAssignment,
    OrganizationAssignment,
)
from apps.workflow.seeds import workflows as workflow_seed


WALL = ZoneInfo("Asia/Jakarta")

JOIN_DATE = date(2020, 1, 6)

# Selasa. Dijangkarkan supaya jumlah hari kerjanya tidak bergantung
# pada hari apa test dijalankan.
TRIAL_DATE = date(2026, 9, 8)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    """Jam dinding Asia/Jakarta pada sebuah tanggal."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=WALL)


class AttendancePermissionFixture:
    """
    Panggung izin kehadiran, **tanpa** menyebut kelas dasar test-nya.

    Dipisahkan dari kelas dasarnya supaya satu kelas bisa dipindah ke
    schema yang dipakai ulang tanpa memindahkan 21 saudaranya
    sekaligus: keduanya memakai pabrik yang sama, bedanya cuma dari
    mana schema-nya datang. Lihat dua kelas konkret di bawah berkas
    ini.

    `build_permission_baseline()` **idempoten**, karena pemakainya yang
    memakai ulang schema memanggilnya sekali per kelas di atas isi yang
    mungkin sudah ada.
    """

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "attendance-permission"
        tenant.name = "Attendance Permission"

    @classmethod
    def build_permission_baseline(cls):
        # Tenant test lahir kosong. Tanpa deret nomor, `document_number`
        # terbit kosong — perilaku yang memang benar (dokumen tetap
        # tersimpan), tapi membuat assertion soal nomornya tidak menguji
        # apa pun.
        seed_numbering()

        cls.company, _ = Company.objects.get_or_create(
            code="APM",
            is_deleted=False,
            defaults={"name": "Permission Co"},
        )

        cls.head_office, _ = Location.objects.get_or_create(
            code="APM-HO",
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": "Jakarta Head Office",
            },
        )

        cls.site, _ = Location.objects.get_or_create(
            code="APM-SITE",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Gebe Site"},
        )

        cls.department, _ = Department.objects.get_or_create(
            code="APM-OPS",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Operations"},
        )

        cls.calendar, _ = WorkCalendar.objects.get_or_create(
            code="APM-OFFICE",
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": "Office Mon-Fri",
                "monday": True,
                "tuesday": True,
                "wednesday": True,
                "thursday": True,
                "friday": True,
                "saturday": False,
                "sunday": False,
                "is_default": True,
            },
        )

        cls.day_shift, _ = Shift.objects.get_or_create(
            code="APM-DAY",
            is_deleted=False,
            defaults={
                "name": "Day 08-17",
                "start_time": time(8, 0),
                "end_time": time(17, 0),
                "crosses_midnight": False,
            },
        )

        cls.night_shift, _ = Shift.objects.get_or_create(
            code="APM-NIGHT",
            is_deleted=False,
            defaults={
                "name": "Night 20-05",
                "start_time": time(20, 0),
                "end_time": time(5, 0),
                "crosses_midnight": True,
            },
        )

        # Alur dari seed sungguhan, bukan rantai yang disusun tangan di
        # test: rantai yang disalin akan tetap hijau setelah seed-nya
        # berubah, dan itu kebalikan dari yang dibutuhkan berkas ini.
        #
        # `workflow_seed.seed()` memakai `update_or_create`, jadi
        # memanggilnya ulang di schema yang sama aman.
        cls.seed_result = workflow_seed.seed()

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(
        cls,
        *,
        shift=None,
        reports_to=None,
        roles=None,
        location=None,
        with_user: bool = True,
    ) -> Employee:
        User = get_user_model()

        cls._counter += 1

        position = Position.objects.create(
            company=cls.company,
            department=cls.department,
            code=f"APM-POS{cls._counter}",
            name=f"Jabatan {cls._counter}",
        )

        user = None

        if with_user:
            username = f"apm.user{cls._counter}"

            user = User.objects.create_user(
                username=username,
                email=f"{username}@example.test",
                password="Test-Only#Pw1",
                first_name="Permission",
                last_name=f"Employee {cls._counter}",
            )

            if roles:
                user.roles.set(
                    Role.objects.filter(code__in=roles, is_deleted=False),
                )

        employee = Employee.objects.create(
            employee_number=f"EMP-HO-{cls._counter:03d}",
            first_name="Permission",
            last_name=f"Employee {cls._counter}",
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=location or cls.head_office,
            department=cls.department,
            position=position,
            reports_to=reports_to,
            organization_effective_date=JOIN_DATE,
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=JOIN_DATE,
            working_calendar=cls.calendar,
            shift=shift or cls.day_shift,
        )

        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def make_permission(
        cls,
        employee,
        *,
        permission_type=AttendancePermissionType.LATE_ARRIVAL,
        work_date: date = TRIAL_DATE,
        start_time=None,
        end_time=None,
        reason: str = "Urusan keluarga",
        user=None,
        **extra,
    ):
        return AttendancePermissionService.create(
            data={
                "employee": employee,
                "permission_type": permission_type,
                "date": work_date,
                "start_time": start_time,
                "end_time": end_time,
                "reason": reason,
                **extra,
            },
            user=user,
        )

    @classmethod
    def approve_directly(cls, permission, *, user=None):
        """
        Menyetujui tanpa menembus rantai approver.

        Dipakai test yang menguji **efeknya terhadap presensi**, bukan
        alurnya. Alurnya sendiri diuji terpisah lewat approver
        sungguhan di `test_permission_workflow.py` — mencampurnya
        membuat test klasifikasi gagal karena data organisasi, bukan
        karena hitungannya.
        """
        AttendancePermissionService._set_status(
            permission=permission,
            status=AttendancePermissionStatus.APPROVED,
            user=user,
        )

        AttendancePermissionService.recalculate_attendance(
            permission=permission,
        )

        permission.refresh_from_db()

        return permission

    @classmethod
    def make_attendance(
        cls,
        employee,
        *,
        work_date: date = TRIAL_DATE,
        check_in=None,
        check_out=None,
        status=None,
        shift=None,
        crosses_midnight: bool = False,
    ) -> EmployeeAttendance:
        """
        Baris presensi beserta jadwalnya, lewat service — bukan lewat
        ORM langsung.

        Lewat service karena justru di situlah `apply_policy` dan
        `apply_permissions` dipasang: baris yang dibuat lewat ORM
        melewati keduanya dan seluruh test klasifikasi akan menguji
        angka yang diisi tangan oleh test-nya sendiri.
        """
        shift = shift or cls.day_shift

        scheduled_in = at(
            work_date,
            shift.start_time.hour,
            shift.start_time.minute,
        )

        end_day = (
            work_date + timedelta(days=1)
            if crosses_midnight or shift.crosses_midnight
            else work_date
        )

        scheduled_out = at(
            end_day,
            shift.end_time.hour,
            shift.end_time.minute,
        )

        data = {
            "employee": employee,
            "work_date": work_date,
            "shift": shift,
            "scheduled_check_in": scheduled_in,
            "scheduled_check_out": scheduled_out,
            "check_in": check_in,
            "check_out": check_out,
        }

        if status is not None:
            data["status"] = status

        return EmployeeAttendanceService.create(data=data)

    @staticmethod
    def refreshed(row):
        row.refresh_from_db()

        return row


# ======================================================================
# Kelas konkret
# ======================================================================


class AttendancePermissionTestCase(
    AttendancePermissionFixture,
    ReusableTenantTestCase,
):
    """
    Panggung izin kehadiran di atas schema yang **dipakai ulang**.

    Sebelum TEST-ISO-HR-0C kelas ini menurunkan `TenantTestCase`, dan
    22 kelas yang memakainya membayar satu pembangunan schema tenant
    (~230 tabel, ~90 detik) masing-masing. Sekarang schema
    `fast_attperm` dibangun sekali lalu dipakai bersama; isolasi
    antar-test tetap dijaga rollback transaksi per test, yang memang
    selalu berjalan.
    """

    reusable_schema_name = "fast_attperm"

    @classmethod
    def build_baseline(cls):
        cls.build_permission_baseline()
