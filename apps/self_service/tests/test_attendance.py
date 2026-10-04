"""
`GET /api/me/attendance/` — identitas, isolasi, kontrak rentang, dan
bukti bahwa penyaringannya memang terjadi di database.

Empat hal diuji, dan keempatnya harus benar bersamaan:

1. **Subjeknya tidak bisa digeser.** Enam ejaan parameter identitas
   dicoba; tidak satu pun mengubah siapa yang dilaporkan. Yang diuji
   bukan "penjagaannya menolak" melainkan "tidak ada parameternya sama
   sekali".
2. **Tidak ada baris orang lain yang sampai.** Pegawai B diberi presensi
   bernilai **khas** (`4321` menit, shift `SHIFT-BOCOR`), lalu seluruh
   respons A digeledah sampai daun terdalam.
3. **Rentang dan halaman adalah kontrak, bukan saran.** Tanpa parameter
   tujuh hari; lebih dari 90 hari ditolak; `page_size` di luar daftar
   ditolak.
4. **Penyaringan, pengurutan, dan pemotongan terjadi di SQL.** Dibuktikan
   dengan membaca SQL yang benar-benar dijalankan — bukan dengan
   mempercayai bentuk hasilnya, yang akan terlihat sama persis kalau
   seluruh histori ditarik lalu dipotong di Python.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.administration.models import (
    Company,
    Department,
    EmployeeGroup,
    EmploymentStatus,
    EmploymentType,
    Location,
    Position,
    Shift,
)
from apps.hr.models import (
    Employee,
    EmployeeAttendance,
    EmployeeOvertime,
    EmploymentAssignment,
    OrganizationAssignment,
)
from apps.hr.models.overtime import OvertimeStatus
from apps.self_service.services import attendance as service_module
from apps.self_service.services.attendance import (
    DEFAULT_RANGE_DAYS,
    MAX_RANGE_DAYS,
    SelfAttendanceService,
)


User = get_user_model()

URL = "/api/me/attendance/"

# Nama tabel presensi di database. Dipakai uji bukti SQL.
ATTENDANCE_TABLE = "hr_employee_attendance"

# Panggungnya bertanggal tetap. `date.today()` di fixture membuat
# kegagalan besok tidak bisa dibedakan dari kegagalan kode.
AS_OF = date(2026, 9, 16)

# Rentang kerja utama: seluruh Agustus 2026, sebulan penuh sebelum
# `AS_OF`, jadi tidak pernah bersinggungan dengan rentang bawaan.
AUG = ("2026-08-01", "2026-08-31")

FORBIDDEN_KEYS = {
    "approval_status",
    "review_notes",
    "review_decision",
    "reviewed_at",
    "reviewed_by",
    "leave_required_days",
    "leave_required_reason",
    "leave_required_override",
    "leave_required_waived",
    "leave_required_waiver_reason",
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
    "notes",
    "internal_notes",
    "created_by",
    "updated_by",
    "deleted_by",
    "deleted_at",
    "is_deleted",
    "employee",
    "employee_id",
    "user",
    "company",
    "location",
    "branch",
    "first_check_in",
    "last_check_out",
    "scheduled_check_in",
    "scheduled_check_out",
    "basic_salary",
    "net_pay",
}


def walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_keys(item)


def walk_values(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from walk_values(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_values(item)
    else:
        yield node


def utc(day: date, hour: int, minute: int) -> datetime:
    return datetime(
        day.year, day.month, day.day, hour, minute, tzinfo=dt_timezone.utc,
    )


class SelfAttendanceTestCase(TenantTestCase):
    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "self-service-attendance"
        tenant.name = "Self Service Attendance"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(code="SSA", name="Attendance Co")
        cls.site = Location.objects.create(
            company=cls.company, code="SSA-HO", name="Head Office",
        )
        cls.department = Department.objects.create(
            company=cls.company, code="OPS", name="Operations",
        )
        cls.position = Position.objects.create(
            company=cls.company, code="STF", name="Staff",
        )
        cls.status = EmploymentStatus.objects.create(code="ACT", name="Active")
        cls.etype = EmploymentType.objects.create(code="PKWTT", name="Permanent")

        cls.shift = Shift.objects.create(
            code="OFFICE",
            name="Office",
            start_time="08:00",
            end_time="17:00",
        )
        cls.leaked_shift = Shift.objects.create(
            code="BOCOR",
            name="SHIFT-BOCOR",
            start_time="08:00",
            end_time="17:00",
        )

        # Grup yang proses Attendance-nya dimatikan admin. Dipakai
        # membuktikan bahwa "tidak berlaku" terbaca berbeda dari "nol".
        cls.no_attendance_group = EmployeeGroup.objects.create(
            code="NOATT",
            name="Tanpa Presensi",
            attendance_applicable=False,
        )

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
            username=f"att-{n}",
            email=f"att-{n}@example.test",
            password="pw",
        )

    def make_employee(self, *, user=None, first="Bimo", group=None, active=True):
        n = self._next()

        employee = Employee.objects.create(
            user=user,
            employee_number=f"AT{n:04d}",
            first_name=first,
            last_name="Nugroho",
            is_active=active,
            notes="RAHASIA-CATATAN-HR",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=self.company,
            location=self.site,
            department=self.department,
            position=self.position,
            organization_effective_date="2026-01-01",
        )
        EmploymentAssignment.objects.create(
            employee=employee,
            employment_status=self.status,
            employment_type=self.etype,
            employee_group=group,
            join_date="2020-01-06",
            employment_effective_date="2020-01-06",
        )

        return employee

    def linked(self, **kwargs):
        user = self.make_user()

        return user, self.make_employee(user=user, **kwargs)

    def as_user(self, user):
        token = RefreshToken.for_user(user).access_token

        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def get(self, user, query=""):
        return self.http.get(f"{URL}{query}", **self.as_user(user))

    def body(self, user, query=""):
        response = self.get(user, query)

        self.assertEqual(response.status_code, 200, response.content)

        return response.json()

    def data(self, user, query=""):
        return self.body(user, query)["data"]

    def grant(self, user, *names):
        for name in names:
            app_label, _, codename = name.partition(".")

            user.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label=app_label,
                    codename=codename,
                ),
            )

        for attr in ("_perm_cache", "_user_perm_cache", "_role_perm_cache"):
            user.__dict__.pop(attr, None)

    # -- baris presensi ------------------------------------------------

    def attend(
        self,
        employee,
        day,
        *,
        status="present",
        late=0,
        worked=480,
        shift=None,
        leaked=False,
    ):
        return EmployeeAttendance.objects.create(
            employee=employee,
            company=self.company,
            location=self.site,
            work_date=day,
            shift=shift or (self.leaked_shift if leaked else self.shift),
            status=status,
            source="device",
            check_in=utc(day, 1, 52),
            check_out=utc(day, 10, 5),
            worked_minutes=worked,
            late_minutes=late,
            notes="RAHASIA-CATATAN-PRESENSI",
            device_code="MESIN-BOCOR",
            check_in_address="RAHASIA-ALAMAT",
        )

    def fill(self, employee, *, days: int, start=date(2026, 8, 1)):
        """`days` baris berturut-turut mulai `start`."""
        return [
            self.attend(employee, start + timedelta(days=offset))
            for offset in range(days)
        ]

    def dates(self, payload) -> list[str]:
        return [row["work_date"] for row in payload["history"]]


# ======================================================================
# 1. Identitas
# ======================================================================


class IdentityTests(SelfAttendanceTestCase):
    """
    Subjeknya `request.user`, dan tidak ada jalan lain menuju ke sana.
    """

    def setUp(self):
        super().setUp()

        self.user, self.me = self.linked(first="Bimo")
        _, self.other = self.linked(first="Sarah")

        self.attend(self.me, date(2026, 8, 3))
        self.attend(self.other, date(2026, 8, 3), leaked=True, worked=4321)

    def test_tanpa_parameter_mengembalikan_diri_sendiri(self):
        payload = self.data(self.user, f"?date_from={AUG[0]}&date_to={AUG[1]}")

        self.assertEqual(payload["summary"]["present"]["value"], 1)
        self.assertEqual(len(payload["history"]), 1)

    def test_enam_ejaan_parameter_identitas_tidak_menggeser_subjek(self):
        """
        Kalau salah satu ejaan ini pernah dibaca, jawabannya akan berisi
        shift `SHIFT-BOCOR` milik Sarah. Diuji terhadap **nilainya**,
        bukan cuma jumlah barisnya.
        """
        base = f"?date_from={AUG[0]}&date_to={AUG[1]}"

        for spelling in (
            f"employee={self.other.id}",
            f"employee_id={self.other.id}",
            f"user={self.other.user_id}",
            f"id={self.other.id}",
            f"employee__id={self.other.id}",
            f"public_id={self.other.id}",
        ):
            with self.subTest(spelling=spelling):
                payload = self.data(self.user, f"{base}&{spelling}")

                values = set(walk_values(payload))

                self.assertNotIn("SHIFT-BOCOR", values)
                self.assertNotIn(4321, values)
                self.assertEqual(len(payload["history"]), 1)
                self.assertEqual(payload["history"][0]["shift"], "Office")

    def test_rute_berparameter_tidak_ada(self):
        for path in (
            f"{URL}{self.other.id}/",
            f"{URL}employee/{self.other.id}/",
        ):
            with self.subTest(path=path):
                response = self.http.get(path, **self.as_user(self.user))

                self.assertEqual(response.status_code, 404)

    def test_hanya_baca(self):
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                response = getattr(self.http, method)(
                    URL,
                    data={"employee": self.other.id},
                    content_type="application/json",
                    **self.as_user(self.user),
                )

                self.assertEqual(response.status_code, 405)


# ======================================================================
# 2. Isolasi
# ======================================================================


class IsolationTests(SelfAttendanceTestCase):
    def test_tidak_ada_jejak_pegawai_lain(self):
        user, me = self.linked(first="Bimo")
        _, other = self.linked(first="Sarah")

        self.attend(me, date(2026, 8, 3))

        for offset in range(10):
            self.attend(
                other,
                date(2026, 8, 3) + timedelta(days=offset),
                leaked=True,
                worked=4321,
                late=777,
            )

        EmployeeOvertime.objects.create(
            employee=other,
            work_date=date(2026, 8, 4),
            start_time="18:00",
            end_time="22:00",
            duration_minutes=999,
            is_paid=True,
            status=OvertimeStatus.RECORDED,
            reason="RAHASIA-LEMBUR-ORANG-LAIN",
        )

        payload = self.data(user, f"?date_from={AUG[0]}&date_to={AUG[1]}&page_size=50")

        values = set(walk_values(payload))

        for leak in ("SHIFT-BOCOR", "RAHASIA-LEMBUR-ORANG-LAIN", 4321, 777, 999):
            self.assertNotIn(leak, values, f"{leak} bocor ke jawaban Bimo")

        self.assertEqual(len(payload["history"]), 1)
        self.assertEqual(payload["summary"]["overtime_minutes"]["value"], 0)

    def test_tanpa_izin_hr_tetap_melihat_presensinya_sendiri(self):
        """
        Pegawai biasa tidak punya `hr.view_employeeattendance`, dan
        halaman ini justru dibangun untuk mereka. Kalau otorisasinya
        pernah digantung ke izin HR, test ini yang memberitahu.
        """
        user, me = self.linked()

        self.assertFalse(user.has_perm("hr.view_employeeattendance"))
        self.assertFalse(user.has_perm("hr.view_employee"))

        self.fill(me, days=3)

        payload = self.data(user, f"?date_from={AUG[0]}&date_to={AUG[1]}")

        self.assertEqual(len(payload["history"]), 3)

    def test_izin_hr_tidak_melebarkan_jawaban(self):
        """Izin administratif **tidak** membuat baris orang lain ikut."""
        user, me = self.linked()
        _, other = self.linked(first="Sarah")

        self.grant(user, "hr.view_employeeattendance", "hr.view_employee")

        self.fill(me, days=2)
        self.fill(other, days=9)

        payload = self.data(user, f"?date_from={AUG[0]}&date_to={AUG[1]}&page_size=50")

        self.assertEqual(len(payload["history"]), 2)


# ======================================================================
# 3. Akses
# ======================================================================


class AccessTests(SelfAttendanceTestCase):
    def test_tanpa_autentikasi_401(self):
        self.assertEqual(self.http.get(URL).status_code, 401)

    def test_akun_tanpa_pegawai_404(self):
        response = self.get(self.make_user())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["code"], "employee_not_linked")

    def test_pegawai_tidak_aktif_mengikuti_policy_self_service(self):
        user, _ = self.linked(active=False)

        response = self.get(user)

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "employee_inactive")


# ======================================================================
# 4. Kontrak rentang
# ======================================================================


class RangeTests(SelfAttendanceTestCase):
    def setUp(self):
        super().setUp()

        self.user, self.me = self.linked()

    def test_bawaan_tujuh_hari_berakhir_hari_ini(self):
        span = SelfAttendanceService.resolve_range()

        self.assertEqual(span.days, DEFAULT_RANGE_DAYS)
        self.assertEqual(span.end, service_module._today())

    def test_bawaan_tidak_menarik_seluruh_histori(self):
        """
        Baris lama **tidak** ikut saat rentangnya tidak disebut. Ini
        yang membedakan "paginasi 10 baris pertama dari seluruh histori"
        dari "tujuh hari terakhir".
        """
        self.fill(self.me, days=30, start=date(2026, 1, 1))

        payload = self.data(self.user)

        self.assertEqual(payload["history"], [])
        self.assertEqual(self.body(self.user)["meta"]["count"], 0)

    def test_rentang_eksplisit_dipatuhi(self):
        self.fill(self.me, days=20, start=date(2026, 8, 1))

        payload = self.data(self.user, "?date_from=2026-08-05&date_to=2026-08-07")

        self.assertEqual(
            self.dates(payload),
            ["2026-08-07", "2026-08-06", "2026-08-05"],
        )
        self.assertEqual(payload["range"]["days"], 3)

    def test_setengah_rentang_ditolak(self):
        for query in ("?date_from=2026-08-01", "?date_to=2026-08-31"):
            with self.subTest(query=query):
                self.assertEqual(self.get(self.user, query).status_code, 400)

    def test_terbalik_ditolak(self):
        response = self.get(self.user, "?date_from=2026-08-31&date_to=2026-08-01")

        self.assertEqual(response.status_code, 400)

    def test_format_salah_ditolak(self):
        response = self.get(self.user, "?date_from=01/08/2026&date_to=2026-08-31")

        self.assertEqual(response.status_code, 400)

    def test_batas_maksimum_dijaga(self):
        start = date(2026, 6, 1)

        tepat = start + timedelta(days=MAX_RANGE_DAYS - 1)
        lewat = start + timedelta(days=MAX_RANGE_DAYS)

        self.assertEqual(
            self.get(
                self.user,
                f"?date_from={start}&date_to={tepat}",
            ).status_code,
            200,
        )
        self.assertEqual(
            self.get(
                self.user,
                f"?date_from={start}&date_to={lewat}",
            ).status_code,
            400,
        )

    def test_periode_sebelumnya_selebar_periode_ini(self):
        payload = self.data(self.user, "?date_from=2026-08-10&date_to=2026-08-16")

        self.assertEqual(
            payload["range"]["previous"],
            {"date_from": "2026-08-03", "date_to": "2026-08-09"},
        )

    def test_tidak_ada_periode_berikutnya_saat_menyentuh_hari_ini(self):
        today = service_module._today()

        payload = self.data(
            self.user,
            f"?date_from={today - timedelta(days=6)}&date_to={today}",
        )

        self.assertIsNone(payload["range"]["next"])

    def test_periode_berikutnya_ada_saat_masih_di_masa_lalu(self):
        payload = self.data(self.user, f"?date_from={AUG[0]}&date_to={AUG[1]}")

        self.assertIsNotNone(payload["range"]["next"])


# ======================================================================
# 5. Paginasi
# ======================================================================


class PaginationTests(SelfAttendanceTestCase):
    def setUp(self):
        super().setUp()

        self.user, self.me = self.linked()
        self.fill(self.me, days=25, start=date(2026, 8, 1))

        self.query = f"?date_from={AUG[0]}&date_to={AUG[1]}"

    def test_bawaan_sepuluh_baris(self):
        body = self.body(self.user, self.query)

        self.assertEqual(len(body["data"]["history"]), 10)
        self.assertEqual(
            body["meta"],
            {"count": 25, "total_pages": 3, "page": 1, "page_size": 10},
        )

    def test_terbaru_dahulu(self):
        payload = self.data(self.user, self.query)

        self.assertEqual(self.dates(payload)[0], "2026-08-25")
        self.assertEqual(
            self.dates(payload),
            sorted(self.dates(payload), reverse=True),
        )

    def test_halaman_berikutnya_baris_lain(self):
        satu = set(self.dates(self.data(self.user, f"{self.query}&page=1")))
        dua = set(self.dates(self.data(self.user, f"{self.query}&page=2")))

        self.assertEqual(len(satu & dua), 0)
        self.assertEqual(len(satu), 10)
        self.assertEqual(len(dua), 10)

    def test_pilihan_ukuran_halaman(self):
        for size, expected in ((10, 10), (25, 25), (50, 25)):
            with self.subTest(size=size):
                payload = self.data(self.user, f"{self.query}&page_size={size}")

                self.assertEqual(len(payload["history"]), expected)

    def test_ukuran_di_luar_daftar_ditolak(self):
        for size in (1, 15, 100, 1000, "abc"):
            with self.subTest(size=size):
                self.assertEqual(
                    self.get(self.user, f"{self.query}&page_size={size}").status_code,
                    400,
                )

    def test_halaman_melewati_batas_jatuh_ke_halaman_terakhir(self):
        """
        Bukan 404: yang baru saja terjadi biasanya pengguna mempersempit
        rentangnya sementara nomor halamannya masih tertinggal di 9.
        """
        body = self.body(self.user, f"{self.query}&page=99")

        self.assertEqual(body["meta"]["page"], 3)
        self.assertEqual(len(body["data"]["history"]), 5)

    def test_ringkasan_tidak_ikut_berubah_antar_halaman(self):
        satu = self.data(self.user, f"{self.query}&page=1")["summary"]
        dua = self.data(self.user, f"{self.query}&page=2")["summary"]

        self.assertEqual(satu, dua)


# ======================================================================
# 6. Ringkasan mengikuti rentang
# ======================================================================


class SummaryTests(SelfAttendanceTestCase):
    def setUp(self):
        super().setUp()

        self.user, self.me = self.linked()

    def test_mempersempit_rentang_mengubah_ringkasan_dan_tabel(self):
        """
        Sepuluh baris 3–12 Agustus memuat Sabtu 8 dan Minggu 9. Tanpa
        kalender kerja jadwalnya Senin–Jumat, jadi Present menghitung
        **hari terjadwal** (8) — dua baris akhir pekan itu hari off yang
        dikerjakan, bukan Present. Tabelnya tetap menampilkan baris apa
        adanya (10).
        """
        self.fill(self.me, days=10, start=date(2026, 8, 3))

        luas = self.data(self.user, f"?date_from={AUG[0]}&date_to={AUG[1]}")
        sempit = self.data(self.user, "?date_from=2026-08-03&date_to=2026-08-05")

        self.assertEqual(luas["summary"]["present"]["value"], 8)
        self.assertEqual(sempit["summary"]["present"]["value"], 3)

        self.assertEqual(len(luas["history"]), 10)
        self.assertEqual(len(sempit["history"]), 3)

    def test_jam_kerja_dijumlahkan_dari_baris_di_rentang(self):
        self.attend(self.me, date(2026, 8, 3), worked=400)
        self.attend(self.me, date(2026, 8, 4), worked=500)
        self.attend(self.me, date(2026, 7, 1), worked=99999)

        payload = self.data(self.user, f"?date_from={AUG[0]}&date_to={AUG[1]}")

        self.assertEqual(payload["summary"]["worked_minutes"]["value"], 900)

    def test_terlambat_dihitung_dari_hasil_kanonik(self):
        self.attend(self.me, date(2026, 8, 3), status="late", late=59)
        self.attend(self.me, date(2026, 8, 4))

        payload = self.data(self.user, f"?date_from={AUG[0]}&date_to={AUG[1]}")

        self.assertEqual(payload["summary"]["late"]["value"], 1)
        self.assertEqual(payload["summary"]["present"]["value"], 2)

    def test_lembur_dari_dokumen_bukan_dari_kolom_presensi(self):
        """
        `EmployeeAttendance.overtime_minutes` adalah menit melewati
        jadwal menurut mesin; yang dibayar dokumen `EmployeeOvertime`.
        Kolom "Lembur" harus membaca yang kedua — di kartu maupun di
        tabelnya, dan keduanya harus angka yang sama.
        """
        row = self.attend(self.me, date(2026, 8, 3))
        row.overtime_minutes = 145
        row.save(update_fields=["overtime_minutes"])

        EmployeeOvertime.objects.create(
            employee=self.me,
            work_date=date(2026, 8, 3),
            start_time="18:00",
            end_time="19:00",
            duration_minutes=60,
            is_paid=True,
            status=OvertimeStatus.RECORDED,
            reason="lembur tercatat",
        )

        payload = self.data(self.user, f"?date_from={AUG[0]}&date_to={AUG[1]}")

        self.assertEqual(payload["summary"]["overtime_minutes"]["value"], 60)
        self.assertEqual(payload["history"][0]["overtime_minutes"], 60)

    def test_deret_harian_menutup_seluruh_rentang(self):
        self.attend(self.me, date(2026, 8, 3), status="late", late=30)

        payload = self.data(self.user, "?date_from=2026-08-01&date_to=2026-08-07")

        self.assertEqual(len(payload["daily"]), 7)
        self.assertEqual(
            [entry["date"] for entry in payload["daily"]][0],
            "2026-08-01",
        )

        by_day = {entry["date"]: entry["outcome"] for entry in payload["daily"]}

        self.assertEqual(by_day["2026-08-03"], "late")

    def test_deret_harian_dan_kartu_menghitung_hari_yang_sama(self):
        self.fill(self.me, days=5, start=date(2026, 8, 3))
        self.attend(self.me, date(2026, 8, 10), status="late", late=20)

        payload = self.data(self.user, f"?date_from={AUG[0]}&date_to={AUG[1]}")

        outcomes = [entry["outcome"] for entry in payload["daily"]]

        self.assertEqual(
            outcomes.count("late"),
            payload["summary"]["late"]["value"],
        )
        self.assertEqual(
            outcomes.count("present") + outcomes.count("late"),
            payload["summary"]["present"]["value"],
        )

    def test_proses_dimatikan_terbaca_berbeda_dari_nol(self):
        """
        Pegawai yang Employee Group-nya mematikan Attendance tidak punya
        angka hadir — bukan punya angka hadir yang kebetulan nol.
        """
        user, _ = self.linked(group=self.no_attendance_group)

        payload = self.data(user, f"?date_from={AUG[0]}&date_to={AUG[1]}")

        self.assertFalse(payload["summary"]["work_days"]["available"])
        self.assertFalse(payload["summary"]["present"]["available"])
        self.assertEqual(payload["daily"], [])

    def test_pegawai_tanpa_presensi_kosong_bukan_galat(self):
        payload = self.data(self.user, f"?date_from={AUG[0]}&date_to={AUG[1]}")

        self.assertEqual(payload["history"], [])
        self.assertTrue(payload["summary"]["present"]["available"])
        self.assertEqual(payload["summary"]["present"]["value"], 0)


# ======================================================================
# 7. Bentuk baris
# ======================================================================


class RowShapeTests(SelfAttendanceTestCase):
    def setUp(self):
        super().setUp()

        self.user, self.me = self.linked()
        self.attend(self.me, date(2026, 8, 3), status="late", late=59, worked=363)

        self.payload = self.data(self.user, f"?date_from={AUG[0]}&date_to={AUG[1]}")

    def test_tidak_ada_kunci_terlarang_sedalam_apa_pun(self):
        found = set(walk_keys(self.payload)) & FORBIDDEN_KEYS

        self.assertEqual(found, set(), f"kunci administratif ikut terkirim: {found}")

    def test_tidak_ada_catatan_internal_yang_ikut(self):
        values = {
            value for value in walk_values(self.payload) if isinstance(value, str)
        }

        for leak in ("RAHASIA-CATATAN-PRESENSI", "MESIN-BOCOR", "RAHASIA-ALAMAT"):
            self.assertNotIn(leak, values)

    def test_jam_dirender_sebagai_jam_dinding_kantor(self):
        """
        `check_in` disimpan 01:52 UTC. Jam dinding kantor WIB, jadi yang
        terkirim 08:52 — sudah jadi string, supaya tidak ada perangkat
        pembaca yang menggesernya lagi.
        """
        row = self.payload["history"][0]

        self.assertEqual(row["check_in"], "08:52")
        self.assertEqual(row["check_out"], "17:05")

    def test_kunci_baris_persis_yang_disepakati(self):
        self.assertEqual(
            set(self.payload["history"][0]),
            {
                "id",
                "work_date",
                "shift",
                "status",
                "status_label",
                "source",
                "source_label",
                "check_in",
                "check_out",
                "worked_minutes",
                "late_minutes",
                "early_leave_minutes",
                "overtime_minutes",
                "permission_state",
            },
        )


# ======================================================================
# 8. Bukti database
# ======================================================================


class QueryTests(SelfAttendanceTestCase):
    """
    Yang diuji di sini **SQL yang benar-benar dijalankan**.

    Bentuk hasilnya akan terlihat sama persis kalau seluruh histori
    ditarik lalu dipotong di Python — jadi memeriksa panjang daftar saja
    tidak membuktikan apa pun.
    """

    def setUp(self):
        super().setUp()

        self.user, self.me = self.linked()
        self.query = f"?date_from={AUG[0]}&date_to={AUG[1]}"

    def history_sql(self, *, rows: int) -> str:
        self.fill(self.me, days=rows, start=date(2026, 8, 1))

        with CaptureQueriesContext(connection) as captured:
            self.data(self.user, self.query)

        statements = [
            entry["sql"]
            for entry in captured.captured_queries
            # Nama tabelnya `hr_employee_attendance`, bukan nama kelas
            # yang dirapatkan. Ditulis sebagai konstanta di bawah supaya
            # satu ganti nama tabel membuat test ini merah — alih-alih
            # membuatnya hijau karena tidak menemukan apa pun.
            if ATTENDANCE_TABLE in entry["sql"]
            and "COUNT(" not in entry["sql"].upper()
            and "SUM(" not in entry["sql"].upper()
        ]

        self.assertTrue(
            statements,
            "query riwayat tidak ditemukan; yang tertangkap: "
            + repr([entry["sql"][:80] for entry in captured.captured_queries]),
        )

        return statements[-1]

    def test_pemotongan_terjadi_di_database(self):
        sql = self.history_sql(rows=25)

        self.assertIn("LIMIT 10", sql)

    def test_penyaringan_tanggal_terjadi_di_database(self):
        sql = self.history_sql(rows=25)

        self.assertIn("work_date", sql)
        self.assertIn("2026-08-01", sql)
        self.assertIn("2026-08-31", sql)

    def test_pengurutan_terjadi_di_database(self):
        sql = self.history_sql(rows=25)

        self.assertIn("ORDER BY", sql.upper())
        self.assertIn("DESC", sql.upper())

    def test_jumlah_query_tidak_tumbuh_mengikuti_jumlah_baris(self):
        """
        Bukti N+1. Dijalankan dua kali dengan jumlah baris berbeda; yang
        dibandingkan **selisihnya**, bukan angka mutlaknya — angka
        mutlak ikut berubah tiap kali ada `select_related` baru di mana
        pun di jalurnya, dan test yang mengunci angka mutlak akan merah
        karena perbaikan.
        """
        self.fill(self.me, days=10, start=date(2026, 8, 1))

        with CaptureQueriesContext(connection) as sedikit:
            self.data(self.user, f"{self.query}&page_size=10")

        self.fill(self.me, days=15, start=date(2026, 8, 11))

        with CaptureQueriesContext(connection) as banyak:
            self.data(self.user, f"{self.query}&page_size=10")

        self.assertEqual(
            len(sedikit.captured_queries),
            len(banyak.captured_queries),
            "jumlah query ikut tumbuh mengikuti jumlah baris",
        )

    def test_memperlebar_rentang_tidak_menambah_query(self):
        """Ringkasan dibatasi rentang, bukan dijalankan per hari."""
        self.fill(self.me, days=25, start=date(2026, 8, 1))

        with CaptureQueriesContext(connection) as pendek:
            self.data(self.user, "?date_from=2026-08-01&date_to=2026-08-03")

        with CaptureQueriesContext(connection) as panjang:
            self.data(self.user, f"?date_from=2026-06-01&date_to=2026-08-29")

        self.assertEqual(
            len(pendek.captured_queries),
            len(panjang.captured_queries),
        )

    def test_shift_tidak_menghasilkan_query_per_baris(self):
        sedikit = self.fill(self.me, days=25, start=date(2026, 8, 1))

        self.assertTrue(sedikit)

        with CaptureQueriesContext(connection) as captured:
            payload = self.data(self.user, f"{self.query}&page_size=25")

        shift_queries = [
            entry
            for entry in captured.captured_queries
            if "administration_shift" in entry["sql"]
        ]

        self.assertEqual(len(payload["history"]), 25)
        self.assertLessEqual(len(shift_queries), 1)
