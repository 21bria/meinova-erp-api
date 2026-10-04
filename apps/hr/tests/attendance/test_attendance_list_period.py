"""
Attendance List = layar operasional berperiode.

Yang dikunci berkas ini **bukan** aturan presensi — tidak satu pun
hitungan, klasifikasi, atau alur persetujuan disentuh di sini. Yang
dikunci satu hal: **baris mana yang pernah ditanyakan ke database.**

Sebelum ini daftar presensi tidak punya batas tanggal sama sekali.
Gejalanya tidak terlihat di layar — halamannya tetap mengirim 25 baris —
dan justru itu yang membuatnya bertahan lama: yang mahal `COUNT(*)`-nya,
dan biaya itu tumbuh diam-diam bersama jumlah tahun yang sudah dicatat
tenant. Pada tenant 5.000 pegawai, satu tahun saja sudah 1,8 juta baris.

Tiga hal yang paling mudah rusak saat rentang dipasang, dan karena itu
diuji eksplisit di bawah:

1. **Rentang harus berlaku sebelum penyaring lain.** "Status = Present"
   di dalam September, bukan seluruh Present sepanjang masa yang
   kebetulan terpotong halaman pertama.
2. **Rentang tidak boleh menyentuh `retrieve`.** `filter_queryset()`
   juga yang dipakai `get_object()`; rentang yang berlaku di sana
   membuat baris di luar bulan berjalan balas 404 — dokumen yang ada,
   terbaca seperti dokumen yang hilang.
3. **Cakupan data tidak boleh ikut bergeser.** Rentang membatasi baris
   mana yang ditanyakan, bukan siapa yang boleh melihatnya.
"""

from __future__ import annotations

from datetime import date, time, timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from apps.core.testing.tenant import ReusableTenantTestCase
from django_tenants.utils import schema_context

from rest_framework.test import APIClient

from apps.accounts.models import AuthorityMode, Role
from apps.accounts.services.role_assignment import grant_role
from apps.administration.models import (
    Company,
    Department,
    Location,
    Position,
    WorkCalendar,
)
from apps.administration.models.references.hr_attendance import Shift
from apps.framework import list_period
from apps.hr.models import (
    AttendanceSource,
    AttendanceStatus,
    Employee,
    EmployeeAttendance,
    EmploymentAssignment,
    OrganizationAssignment,
)


URL = "/api/hr/attendance/"

JOIN_DATE = date(2020, 1, 6)

# Bulan yang dijangkarkan, dipakai seluruh test rentang eksplisit.
#
# Tidak diturunkan dari hari ini: rentang yang bergerak membuat test
# yang hari ini hijau gagal bulan depan karena kalender, bukan karena
# kode. Yang **memang** harus membaca hari ini cuma test rentang bawaan,
# dan test itu menurunkannya dari helper yang sama dengan produksinya.
ANCHOR_MONTH = date(2026, 3, 1)


def day(number: int) -> date:
    return ANCHOR_MONTH.replace(day=number)


class AttendanceListPeriodBase(ReusableTenantTestCase):
    _counter = 0

    # Schema dan domain bernama sendiri, bukan bawaan django-tenants.
    #
    # Bawaannya **nama tetap**, jadi dua run test yang jalan bersamaan —
    # termasuk dua sesi yang mengerjakan modul berbeda — bertabrakan di
    # `tenants_client_schema_name_key` dan saling menjatuhkan dengan
    # pesan yang tidak menyebut sebabnya.
    #
    # Sejak TEST-ISO-HR-0C schema-nya juga **dipakai ulang**: dibangun
    # sekali lalu hidup lintas run. Jaminan bentuk yang diuji berkas ini
    # tidak berubah karenanya — tabel presensi tetap milik schema tenant
    # dan tetap tidak ada di `public`, dan dua test di bawah
    # membuktikannya di atas schema yang dipakai ulang itu sendiri.
    reusable_schema_name = "fast_attendance_period"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "attendance-period"
        tenant.name = "Attendance Period"

    @classmethod
    def build_baseline(cls):
        cls.company, _ = Company.objects.get_or_create(
            code="APD", is_deleted=False, defaults={"name": "Period Co"},
        )

        cls.head_office, _ = Location.objects.get_or_create(
            code="APD-HO",
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": "Jakarta Head Office",
            },
        )

        cls.site, _ = Location.objects.get_or_create(
            code="APD-SITE",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Gebe Site"},
        )

        cls.department, _ = Department.objects.get_or_create(
            code="APD-OPS",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Operations"},
        )

        cls.calendar, _ = WorkCalendar.objects.get_or_create(
            code="APD-OFFICE",
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": "Office Mon-Fri",
                "monday": True,
                "tuesday": True,
                "wednesday": True,
                "thursday": True,
                "friday": True,
                "is_default": True,
            },
        )

        cls.shift, _ = Shift.objects.get_or_create(
            code="APD-DAY",
            is_deleted=False,
            defaults={
                "name": "Day 08-17",
                "start_time": time(8, 0),
                "end_time": time(17, 0),
                "crosses_midnight": False,
            },
        )

        User = get_user_model()

        # Akun superuser panggung: konfigurasi, bukan data transaksi.
        # `get_or_create` supaya kelas kedua di schema yang sama tidak
        # menabrak unique username.
        cls.admin, created = User.objects.get_or_create(
            username="apd.admin",
            defaults={
                "email": "apd.admin@example.test",
                "is_staff": True,
                "is_superuser": True,
            },
        )

        if created:
            cls.admin.set_password("Test-Only#Pw1")
            cls.admin.save(update_fields=["password"])

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(cls, *, location=None, with_user=False) -> Employee:
        User = get_user_model()

        cls._counter += 1

        position = Position.objects.create(
            company=cls.company,
            department=cls.department,
            code=f"APD-POS{cls._counter}",
            name=f"Jabatan {cls._counter}",
        )

        user = None

        if with_user:
            user = User.objects.create_user(
                username=f"apd.user{cls._counter}",
                email=f"apd.user{cls._counter}@example.test",
                password="Test-Only#Pw1",
            )

        employee = Employee.objects.create(
            employee_number=f"APD-{cls._counter:03d}",
            first_name="Period",
            last_name=f"Employee {cls._counter}",
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=location or cls.head_office,
            department=cls.department,
            position=position,
            organization_effective_date=JOIN_DATE,
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=JOIN_DATE,
            working_calendar=cls.calendar,
            shift=cls.shift,
        )

        return Employee.objects.get(pk=employee.pk)

    def make_row(
        self,
        employee,
        work_date: date,
        *,
        status=AttendanceStatus.PRESENT,
        source=AttendanceSource.MANUAL,
        location=None,
    ) -> EmployeeAttendance:
        """
        Baris presensi lewat ORM langsung, bukan lewat service.

        Disengaja: yang diuji berkas ini **penyaringan query**, dan
        service akan ikut menjalankan resolver jadwal, kebijakan, dan
        izin — puluhan query per baris yang tidak satu pun menentukan
        hasil test ini, plus angka yang ditimpa aturan dan membuat
        assertion soal `status` menguji aturan, bukan penyaringnya.
        """
        return EmployeeAttendance.objects.create(
            employee=employee,
            company=self.company,
            location=location or employee.organization.location,
            work_date=work_date,
            shift=self.shift,
            status=status,
            source=source,
        )

    # ------------------------------------------------------------------
    # Klien
    # ------------------------------------------------------------------

    def api(self, user=None) -> APIClient:
        """
        Klien yang benar-benar mendarat di schema tenant.

        `APIClient` bawaan mengirim `Host: testserver`, dan
        `TenantMainMiddleware` tidak mengenali nama itu — permintaannya
        dilayani dari schema **public**, tempat tabel tenant tidak ada.
        Gejalanya `relation ... does not exist`, yang terbaca seperti
        migration yang belum jalan padahal yang salah alamat host-nya.
        """
        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

        client.force_authenticate(user=user or self.admin)

        return client

    def payload(self, query: str = "", *, user=None) -> dict:
        response = self.api(user).get(f"{URL}{query}")

        self.assertEqual(response.status_code, 200, response.data)

        return response.data

    def dates(self, query: str = "", *, user=None) -> list[str]:
        return [row["work_date"] for row in self.payload(query, user=user)["data"]]

    def numbers(self, query: str = "", *, user=None) -> set[str]:
        return {
            row["employee_number"]
            for row in self.payload(query, user=user)["data"]
        }

    @staticmethod
    def span(start: date, end: date) -> str:
        return f"?date_from={start}&date_to={end}&page_size=100"

    def setUp(self):
        super().setUp()

        # Meja dibersihkan sendiri, sebagai sabuk kedua.
        #
        # Catatan lama di sini menyatakan `TenantTestCase` tidak
        # melakukan rollback antar test. **Itu keliru**, dan sudah
        # diukur di TEST-ISO-HR-0B: `_pre_setup` milik `TransactionTest
        # Case` tetap memanggil `TestCase._fixture_setup()`, jadi tiap
        # test berjalan di dalam transaksi dan di-rollback sesudahnya.
        # Yang memang tidak pernah jalan adalah `setUpTestData()`,
        # karena `TenantTestCase.setUpClass()` tidak memanggil
        # `super().setUpClass()` — dan data yang dibuat di `setUpClass`
        # memang **tidak** ikut di-rollback.
        #
        # Barisnya tetap dibuang di sini karena hampir setiap assertion
        # di bawah membandingkan **daftar tanggal yang persis**, dan
        # panggung yang isinya diwarisi dari tempat lain akan gagal
        # dengan sebab yang menunjuk ke penyaring — padahal yang salah
        # panggungnya.
        #
        # Yang dibuang cuma barisnya, bukan pegawainya: yang diuji
        # penyaringan presensi, dan membangun ulang organisasi tiap test
        # cuma memperlambat tanpa menambah satu pun jaminan.
        EmployeeAttendance.objects.all().delete()

        self.employee = self.make_employee()

        for attribute in ("_role_perm_cache", "_data_scope_cache"):
            if hasattr(self.admin, attribute):
                delattr(self.admin, attribute)


class AttendanceListPeriodTestCase(AttendanceListPeriodBase):
    """
    Satu kelas, satu schema tenant.

    Dipecah jadi sembilan kelas lebih enak dibaca, dan itu memang bentuk
    pertamanya. Yang membatalkannya biaya panggungnya: `TenantTestCase`
    membangun **satu schema tenant penuh** — ratusan tabel, ratusan
    migration — di `setUpClass` tiap kelas, lalu menjatuhkannya lagi di
    `tearDownClass`. Sembilan kelas berarti sembilan kali pekerjaan itu
    untuk panggung yang isinya sama persis, dan `DROP SCHEMA CASCADE`
    sebanyak itu juga yang menghabiskan tabel lock PostgreSQL.

    Pengelompokannya tidak hilang — tiap bagian di bawah masih menyebut
    pertanyaannya sendiri, dan panggung yang dulu ditulis di `setUp`
    sekarang jadi helper `seed_*` yang dipanggil test yang memang
    membutuhkannya. Itu juga membuat setiap test menyebutkan panggungnya
    sendiri alih-alih mewarisinya diam-diam.
    """

    def seed_default_period(self):
        self.today = list_period.today()
        self.first = self.today.replace(day=1)

        # Satu hari di bulan sebelumnya: di luar rentang bawaan, dan
        # satu-satunya baris yang membedakan "bulan berjalan" dari
        # "semua waktu".
        self.before = self.first - timedelta(days=1)

        self.make_row(self.employee, self.today)
        self.make_row(self.employee, self.before)

        if self.first != self.today:
            self.make_row(self.employee, self.first)

    def seed_anchor_month(self):
        for number in (1, 5, 10, 15, 20):
            self.make_row(self.employee, day(number))

    def seed_filter_stage(self):
        self.other = self.make_employee(location=self.site)

        # Di dalam periode uji (5-15 Maret).
        self.make_row(
            self.employee,
            day(10),
            status=AttendanceStatus.PRESENT,
            source=AttendanceSource.DEVICE,
        )

        # Di luar periode, sengaja cocok dengan setiap penyaring di bawah.
        self.make_row(
            self.employee,
            day(25),
            status=AttendanceStatus.PRESENT,
            source=AttendanceSource.DEVICE,
        )

        self.make_row(
            self.other,
            day(26),
            status=AttendanceStatus.PRESENT,
            source=AttendanceSource.DEVICE,
            location=self.site,
        )

        self.period = self.span(day(5), day(15))

    def seed_five_days(self):
        for number in range(1, 6):
            self.make_row(self.employee, day(number))

        self.period = f"?date_from={day(1)}&date_to={day(5)}"

    def seed_two_locations(self):
        self.site_employee = self.make_employee(
            location=self.site,
            with_user=True,
        )

        self.office_employee = self.make_employee(
            location=self.head_office,
        )

        self.make_row(self.site_employee, day(10), location=self.site)
        self.make_row(self.office_employee, day(10), location=self.head_office)

        # Kewenangan dinyatakan saat penugasan dibuat: `roles.add()`
        # tidak memberi akses data apa pun.
        role = Role.objects.create(
            code=f"APD-SITE-HR-{self._counter}",
            name="Site HR",
        )

        grant_role(
            self.site_employee.user,
            role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("location", self.site.pk)],
        )

        self.period = self.span(day(1), day(20))

    def seed_old_row(self):
        self.old = self.make_row(
            self.employee,
            list_period.today() - timedelta(days=400),
        )

    def seed_in_and_out(self):
        self.make_row(self.employee, day(10))
        self.make_row(self.employee, day(25))

    def seed_single_row(self):
        self.make_row(self.employee, day(10))

    # ------------------------------------------------------------------
    # Tanpa parameter, daftarnya membuka **bulan berjalan sampai hari
    # ini** — bukan seluruh histori.
    #
    # ------------------------------------------------------------------

    def test_default_is_current_month_to_today(self):
        self.seed_default_period()
        rows = self.dates("?page_size=100")

        self.assertIn(str(self.today), rows)
        self.assertNotIn(
            str(self.before),
            rows,
            "Tanpa parameter daftarnya masih membuka bulan sebelumnya — "
            "artinya rentang bawaannya tidak berlaku.",
        )

    def test_default_includes_first_day_of_month(self):
        self.seed_default_period()
        if self.first == self.today:
            self.skipTest("Hari ini tanggal 1 — batas awalnya sama dengan akhir.")

        self.assertIn(str(self.first), self.dates("?page_size=100"))

    def test_default_matches_backend_policy(self):
        """Layar dan API menurunkan bawaan yang sama."""
        self.seed_default_period()
        period = list_period.default_period()

        self.assertEqual(period.start, self.first)
        self.assertEqual(period.end, self.today)

    # ------------------------------------------------------------------
    # Rentang eksplisit: batasnya ikut, di luarnya tidak.
    # ------------------------------------------------------------------

    def test_range_filters_rows(self):
        self.seed_anchor_month()
        self.assertEqual(
            self.dates(self.span(day(5), day(15))),
            ["2026-03-15", "2026-03-10", "2026-03-05"],
        )

    def test_start_and_end_are_inclusive(self):
        """
        Batasnya ikut. Rentang eksklusif di salah satu ujung menghilangkan
        tepat satu hari per periode — dan yang hilang selalu hari yang
        paling sering ditanyakan, yaitu hari ini.
        """
        self.seed_anchor_month()
        self.assertEqual(
            self.dates(self.span(day(5), day(5))),
            ["2026-03-05"],
        )

    def test_boundary_dates_survive(self):
        self.seed_anchor_month()
        rows = self.dates(self.span(day(1), day(20)))

        self.assertIn("2026-03-01", rows)
        self.assertIn("2026-03-20", rows)

    def test_empty_period_returns_valid_empty_page(self):
        self.seed_anchor_month()
        data = self.payload(self.span(day(21), day(25)))

        self.assertEqual(data["data"], [])
        self.assertEqual(data["meta"]["count"], 0)
        self.assertEqual(data["meta"]["total_pages"], 1)

    def test_count_is_bounded_by_range(self):
        """
        `meta.count` menghitung di dalam rentang, bukan seluruh tabel.

        Ini bagian yang paling mudah luput: baris yang dikirim memang
        sudah dibatasi pagination sejak dulu, tapi `COUNT(*)`-nya tidak —
        dan itulah yang mahal.
        """
        self.seed_anchor_month()
        self.assertEqual(
            self.payload(self.span(day(5), day(15)))["meta"]["count"],
            3,
        )

    def reject(self, query: str) -> None:
        response = self.api().get(f"{URL}{query}")

        self.assertEqual(response.status_code, 400, response.data)

    def test_reversed_range_rejected(self):
        self.reject(f"?date_from={day(20)}&date_to={day(5)}")

    def test_half_range_rejected(self):
        """
        Rentang setengah terisi tidak dilengkapi diam-diam.

        `date_from` sendirian yang dilengkapi hari ini membuat daftarnya
        menjawab pertanyaan yang tidak diajukan, dan yang membacanya
        tidak punya cara tahu batas satunya datang dari mana.
        """
        self.reject(f"?date_from={day(1)}")
        self.reject(f"?date_to={day(20)}")

    def test_bad_format_rejected(self):
        self.reject("?date_from=01/03/2026&date_to=2026-03-20")

    def test_maximum_range_enforced(self):
        start = day(1)

        exact = start + timedelta(days=list_period.MAX_RANGE_DAYS - 1)
        beyond = start + timedelta(days=list_period.MAX_RANGE_DAYS)

        self.assertEqual(
            self.api().get(f"{URL}?date_from={start}&date_to={exact}").status_code,
            200,
        )

        self.reject(f"?date_from={start}&date_to={beyond}")

    def test_maximum_range_is_configurable(self):
        """
        Batasnya kebijakan terpusat, bukan angka yang ditanam di viewset.
        """
        original = list_period.MAX_RANGE_DAYS

        try:
            list_period.MAX_RANGE_DAYS = 7

            self.reject(f"?date_from={day(1)}&date_to={day(20)}")
        finally:
            list_period.MAX_RANGE_DAYS = original

    # ------------------------------------------------------------------
    # Penyaring lain berlaku **di dalam** rentang.
    #
    # Tiap test di bawah menaruh baris yang cocok dengan penyaringnya di
    # **luar** periode — kalau rentangnya dipasang belakangan (atau tidak
    # dipasang sama sekali), baris itulah yang muncul.
    #
    # ------------------------------------------------------------------

    def test_status_filter_respects_range(self):
        self.seed_filter_stage()
        self.assertEqual(
            self.dates(f"{self.period}&status={AttendanceStatus.PRESENT}"),
            ["2026-03-10"],
        )

    def test_source_filter_respects_range(self):
        self.seed_filter_stage()
        self.assertEqual(
            self.dates(f"{self.period}&source={AttendanceSource.DEVICE}"),
            ["2026-03-10"],
        )

    def test_advanced_lookup_filter_respects_range(self):
        """Penyaring Advanced (Employee, Location) ikut aturan yang sama."""
        self.seed_filter_stage()
        self.assertEqual(
            self.dates(f"{self.period}&employee={self.employee.pk}"),
            ["2026-03-10"],
        )

        self.assertEqual(
            self.dates(f"{self.period}&location={self.site.pk}"),
            [],
            "Baris site di luar periode ikut terbawa — rentangnya tidak "
            "berlaku lebih dulu.",
        )

    def test_search_respects_range(self):
        self.seed_filter_stage()
        self.assertEqual(
            self.dates(f"{self.period}&search={self.employee.employee_number}"),
            ["2026-03-10"],
        )

    def test_search_does_not_reach_outside_period(self):
        self.seed_filter_stage()
        self.assertEqual(
            self.dates(f"{self.period}&search={self.other.employee_number}"),
            [],
        )

    def test_exact_work_date_filter_still_works(self):
        """
        Penyaring `work_date` lama tidak dicabut — API-nya tetap
        backward-safe untuk pemanggil yang belum diregenerate.
        """
        self.seed_filter_stage()
        self.assertEqual(
            self.dates(f"{self.period}&work_date={day(10)}"),
            ["2026-03-10"],
        )

    def test_default_sorting_is_newest_first(self):
        self.seed_five_days()
        self.assertEqual(
            self.dates(f"{self.period}&page_size=100"),
            [
                "2026-03-05",
                "2026-03-04",
                "2026-03-03",
                "2026-03-02",
                "2026-03-01",
            ],
        )

    def test_ascending_sorting_is_server_side(self):
        self.seed_five_days()
        rows = self.dates(f"{self.period}&page_size=100&ordering=work_date")

        self.assertEqual(rows, sorted(rows))

    def test_sorting_holds_across_pages(self):
        """
        Urutan ditentukan database, bukan JavaScript atas satu halaman.

        Bedanya cuma terlihat lintas halaman: pengurutan sisi klien
        mengurutkan **halaman**, jadi halaman 2 dimulai lagi dari nilai
        yang lebih besar daripada akhir halaman 1.
        """
        self.seed_five_days()
        first = self.dates(f"{self.period}&page_size=2&ordering=work_date")
        second = self.dates(f"{self.period}&page_size=2&page=2&ordering=work_date")

        self.assertEqual(first, ["2026-03-01", "2026-03-02"])
        self.assertEqual(second, ["2026-03-03", "2026-03-04"])

    def test_pagination_meta_counts_within_range(self):
        self.seed_five_days()
        meta = self.payload(f"{self.period}&page_size=2")["meta"]

        self.assertEqual(meta["count"], 5)
        self.assertEqual(meta["total_pages"], 3)
        self.assertEqual(meta["page_size"], 2)

    def test_narrower_range_changes_count(self):
        self.seed_five_days()
        self.assertEqual(
            self.payload(self.span(day(1), day(2)))["meta"]["count"],
            2,
        )

    # ------------------------------------------------------------------
    # Rentang membatasi **baris mana yang ditanyakan**, bukan siapa yang
    # boleh melihatnya. Kedua lapisnya harus tetap berlaku utuh.
    #
    # ------------------------------------------------------------------

    def test_data_scope_still_limits_rows(self):
        self.seed_two_locations()
        self.assertEqual(
            self.numbers(self.period, user=self.site_employee.user),
            {self.site_employee.employee_number},
        )

    def test_account_without_any_assignment_is_unscoped(self):
        """
        Akun **tanpa satu pun penugasan** membaca seluruh baris presensi.

        Ini mengunci perilaku yang **sudah ada**, bukan yang diinginkan
        berkas ini — dan ditulis justru supaya perubahannya tidak lolos
        tanpa disadari. Jalurnya:

        `EmployeeAttendanceViewSet.require_view_permission` bernilai
        `False`, jadi `required_view_permission()` mengembalikan `None`;
        dengan `permission=None`, `DataScopeService._build()` mengambil
        **seluruh** penugasan orangnya, dan daftar yang kosong dijawab
        `DataScope(unrestricted=True)` (`apps/accounts/scoping.py`).

        "Kosong = tidak ada kewenangan" di dokumentasi cakupan berlaku
        untuk penugasan yang `authority_mode`-nya kosong, **bukan** untuk
        orang yang tidak punya penugasan sama sekali. Dua keadaan yang
        mudah tertukar, dan bedanya baru terlihat di sini.

        Task rentang tanggal tidak menyentuhnya sama sekali: yang
        dibatasi baris mana yang ditanyakan, bukan siapa yang boleh
        melihatnya.
        """
        self.seed_two_locations()
        User = get_user_model()

        stranger = User.objects.create_user(
            username="apd.stranger",
            email="apd.stranger@example.test",
            password="Test-Only#Pw1",
        )

        self.assertEqual(
            self.numbers(self.period, user=stranger),
            {
                self.site_employee.employee_number,
                self.office_employee.employee_number,
            },
        )

    def test_unscoped_reader_is_still_bound_by_the_period(self):
        """
        Dan inilah yang **memang** ditambahkan task ini.

        Pembaca yang cakupan datanya tidak membatasi apa pun tetap tidak
        bisa menarik seluruh histori: rentang berlaku lebih dulu, untuk
        siapa pun. Kalau tidak, satu akun tanpa penugasan sudah cukup
        untuk membuka jutaan baris sekaligus.
        """
        self.seed_two_locations()
        User = get_user_model()

        stranger = User.objects.create_user(
            username="apd.stranger.period",
            email="apd.stranger.period@example.test",
            password="Test-Only#Pw1",
        )

        self.make_row(self.office_employee, day(25))

        self.assertEqual(
            self.dates(self.span(day(1), day(20)), user=stranger),
            ["2026-03-10", "2026-03-10"],
        )

    def test_anonymous_is_rejected(self):
        self.seed_two_locations()
        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

        self.assertEqual(client.get(URL).status_code, 401)

    def test_scope_holds_when_range_widens(self):
        """
        Melebarkan rentang tidak pernah melebarkan cakupan. Kalau kedua
        hal itu tercampur, memilih "Bulan Lalu" akan membuka baris orang
        lain — kebocoran yang tidak pernah terbaca sebagai kebocoran.
        """
        self.seed_two_locations()
        wide = self.span(day(1), day(1) + timedelta(days=60))

        self.assertEqual(
            self.numbers(wide, user=self.site_employee.user),
            {self.site_employee.employee_number},
        )

    # ------------------------------------------------------------------
    # `filter_queryset()` juga yang dipakai `get_object()`.
    #
    # Rentang yang ikut berlaku di sana membuat setiap baris di luar bulan
    # berjalan balas 404 — dokumen yang ada, terbaca seperti dokumen yang
    # hilang, persis saat orang mengkliknya dari hasil pencarian atau dari
    # tautan yang dikirim orang lain.
    #
    # ------------------------------------------------------------------

    def test_retrieve_ignores_the_list_period(self):
        self.seed_old_row()
        response = self.api().get(f"{URL}{self.old.pk}/")

        self.assertEqual(response.status_code, 200, response.data)

    def test_patch_ignores_the_list_period(self):
        self.seed_old_row()
        response = self.api().patch(
            f"{URL}{self.old.pk}/",
            {"notes": "Dikoreksi HR"},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)

    def test_list_still_hides_it(self):
        self.seed_old_row()
        self.assertNotIn(str(self.old.work_date), self.dates("?page_size=100"))

    def test_export_respects_range(self):
        """
        Export memakai `filter_queryset()` yang sama **dan** mengiterasi
        seluruh hasilnya — jadi justru di sanalah rentang tanpa batas
        paling mahal.
        """
        self.seed_in_and_out()
        response = self.api().get(
            f"{URL}export/?date_from={day(5)}&date_to={day(15)}",
        )

        self.assertEqual(response.status_code, 200)

        body = response.content.decode()

        self.assertIn("2026-03-10", body)
        self.assertNotIn("2026-03-25", body)

    def test_list_query_count_does_not_grow_with_rows(self):
        """
        Tidak ada N+1 di jalur daftar.

        Satu baris dan lima baris harus menghabiskan jumlah query yang
        **sama**. Dulu tidak: `permissions` menanyakan dokumen izin
        sebaris satu, jadi tiap halaman membayar satu perjalanan ke
        database per baris — jumlahnya memang dibatasi pagination, tapi
        tidak pernah ada alasannya.
        """
        self.seed_in_and_out()
        client = self.api()

        one = f"?date_from={day(10)}&date_to={day(10)}&page_size=50"

        for number in (11, 12, 13, 14):
            self.make_row(self.employee, day(number))

        many = f"?date_from={day(10)}&date_to={day(14)}&page_size=50"

        # Pemanasan: izin, cakupan data, dan schema tenant di-cache pada
        # permintaan pertama, dan tanpa ini selisihnya terbaca sebagai
        # N+1 padahal cuma cache dingin.
        client.get(f"{URL}{one}")

        single = self.query_count(client, one)
        multiple = self.query_count(client, many)

        self.assertEqual(
            len(self.payload(many)["data"]),
            5,
        )

        self.assertEqual(
            single,
            multiple,
            f"Jumlah query tumbuh bersama jumlah baris "
            f"({single} -> {multiple}) — ada N+1 di jalur daftar.",
        )

    @staticmethod
    def query_count(client, query: str) -> int:
        from django.test.utils import CaptureQueriesContext

        with CaptureQueriesContext(connection) as captured:
            client.get(f"{URL}{query}")

        return len(captured)

    def test_rows_live_only_in_the_tenant_schema(self):
        """
        Presensi bukan tabel bersama.

        Dibuktikan dari sisi yang paling langsung: tabelnya ada di schema
        tenant dan **tidak ada** di `public`, jadi tidak ada rentang,
        penyaring, atau cakupan yang bisa dilewati untuk sampai ke
        barisnya dari luar tenant.

        Diperiksa lewat `information_schema`, bukan dengan memancing
        `ProgrammingError`: query yang gagal meninggalkan koneksi dalam
        keadaan rusak, dan test **berikutnya** yang membayar — dengan
        pesan yang tidak menyebut sebabnya.
        """
        self.seed_single_row()
        table = EmployeeAttendance._meta.db_table

        def exists(schema: str) -> bool:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = %s",
                    [schema, table],
                )

                return cursor.fetchone() is not None

        with schema_context(self.tenant.schema_name):
            self.assertTrue(exists(self.tenant.schema_name))

        with schema_context("public"):
            self.assertFalse(
                exists("public"),
                f"{table} ada di schema public — presensi jadi tabel "
                "bersama antar tenant.",
            )

    def test_list_runs_inside_the_tenant_schema(self):
        self.seed_single_row()
        self.api().get(f"{URL}{self.span(day(1), day(20))}")

        self.assertEqual(connection.schema_name, self.tenant.schema_name)
