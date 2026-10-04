"""
Mengunci Feature Applicability: Employee Group yang memutuskan proses HR
mana yang berlaku untuk pegawainya.

Yang dijaga di sini tiga hal, dan ketiganya pernah jadi cara fitur
seperti ini gagal:

1. **Yang dimatikan benar-benar keluar dari prosesnya** — bukan cuma
   hilang dari dropdown sementara endpoint-nya tetap menerima.
2. **Yang belum dikonfigurasi tidak berubah apa-apa.** Group tanpa
   penanda, dan pegawai tanpa group sama sekali, harus tetap diproses
   persis seperti sebelum migrasi.
3. **Yang dimatikan tetap Employee.** Direksi tidak absen, tapi tetap
   terbit di Employee Master dan tetap terhitung sebagai kepala.

`TenantTestCase` django-tenants tidak memanggil `super().setUpClass()`,
jadi tidak ada rollback per-test: tiap test membuat pegawainya sendiri
dan hanya membaca miliknya.
"""

from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase

from apps.administration.models import Company, Location, RosterPolicy
from apps.administration.models.references.hr import (
    EmployeeGroup,
    HRFeature,
    applicability_field,
)
from apps.administration.seeds.numbering import seed_numbering
from apps.hr.api.attendance.schedule import (
    scheduled_work_days,
    scheduled_work_days_bulk,
)
from apps.hr.api.roster.setup_service import RosterSetupService
from apps.hr.api.site_rotation.services import SiteRotationService
from apps.hr.api.travel_request.services import TravelRequestService
from apps.hr.applicability import (
    all_applicable,
    any_applicable,
    applicable_features,
    exclude_none_applicable,
    filter_employees,
    is_applicable,
)
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    OrganizationAssignment,
)


AS_OF = date(2026, 8, 1)


class FeatureApplicabilityTestCase(TenantTestCase):
    """Satu company, satu site — plus tiga group dengan sikap berbeda."""

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "feature-applicability"
        tenant.name = "Feature Applicability"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        seed_numbering()

        cls.company = Company.objects.create(code="FAP", name="Applicability")

        cls.site = Location.objects.create(
            company=cls.company,
            code="FAP-SITE",
            name="Site",
        )

        cls.policy = RosterPolicy.objects.create(
            company=cls.company,
            location=cls.site,
            code="FAP-6-2",
            name="Roster 6:2",
            cycle_work_days=42,
            cycle_off_days=14,
            default_travel_out_days=1,
            default_travel_in_days=1,
            rolling_horizon_months=12,
        )

        # Direksi: tetap Employee, tapi seluruh proses operasionalnya
        # dimatikan. Leave sengaja dibiarkan menyala — itu yang memang
        # "configurable" pada contoh kebijakannya.
        cls.board = EmployeeGroup.objects.create(
            code="BOARD",
            name="Board of Directors",
            attendance_applicable=False,
            roster_applicable=False,
            shift_applicable=False,
            overtime_applicable=False,
            field_break_applicable=False,
        )

        # Kru lapangan: semuanya berlaku.
        cls.field = EmployeeGroup.objects.create(
            code="FIELD",
            name="Field Crew",
        )

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(cls, *, group=None, policy=None):
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"FAP{cls._counter:04d}",
            first_name="Fap",
            last_name=f"Employee {cls._counter}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=cls.site,
            organization_effective_date=date(2026, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=date(2025, 1, 1),
            employee_group=group,
            roster_policy=policy,
        )

        return Employee.objects.get(pk=employee.pk)


# ----------------------------------------------------------------------
# Master & bawaan
# ----------------------------------------------------------------------


class DefaultsTests(FeatureApplicabilityTestCase):
    def test_group_baru_menyalakan_semua_proses(self):
        """
        Backward compatibility, dan ini yang paling mudah rusak: group
        yang sudah ada sebelum migrasi tidak boleh kehilangan satu
        proses pun. `default=True` yang menjaganya.
        """
        group = EmployeeGroup.objects.create(code="NEW", name="New Group")

        for feature in HRFeature:
            with self.subTest(feature=feature.value):
                self.assertTrue(
                    group.applies_to(feature),
                    f"{feature.value} seharusnya menyala secara bawaan",
                )

    def test_setiap_feature_punya_kolomnya(self):
        """
        Menambah anggota `HRFeature` tanpa kolomnya adalah kegagalan
        yang tidak berbunyi: `applies_to()` melempar `AttributeError`
        di tengah query modul lain. Dijaga di sini supaya ketahuan di
        test, bukan di layar.
        """
        for feature in HRFeature:
            with self.subTest(feature=feature.value):
                self.assertTrue(
                    hasattr(EmployeeGroup, applicability_field(feature)),
                )

    def test_pegawai_tanpa_group_tetap_berlaku(self):
        employee = self.make_employee(group=None)

        for feature in HRFeature:
            with self.subTest(feature=feature.value):
                self.assertTrue(is_applicable(employee, feature))

    def test_konfigurasi_berubah_tanpa_ubah_kode(self):
        """
        Inti fiturnya: kebijakan pindah cukup dengan mengubah satu baris
        master. Kalau test ini butuh perubahan kode untuk lulus, yang
        dibangun bukan konfigurasi.
        """
        group = EmployeeGroup.objects.create(
            code="EXEC",
            name="Executive",
            roster_applicable=False,
        )

        employee = self.make_employee(group=group)

        self.assertFalse(is_applicable(employee, HRFeature.ROSTER))

        group.roster_applicable = True
        group.save(update_fields=["roster_applicable"])

        employee = Employee.objects.get(pk=employee.pk)

        self.assertTrue(is_applicable(employee, HRFeature.ROSTER))


# ----------------------------------------------------------------------
# Penyaring queryset
# ----------------------------------------------------------------------


class QuerysetFilterTests(FeatureApplicabilityTestCase):
    def test_membuang_yang_dimatikan_saja(self):
        board = self.make_employee(group=self.board)
        crew = self.make_employee(group=self.field)
        no_group = self.make_employee(group=None)

        mine = Employee.objects.filter(
            pk__in=[board.pk, crew.pk, no_group.pk],
        )

        result = set(
            filter_employees(mine, HRFeature.ROSTER)
            .values_list("pk", flat=True)
        )

        self.assertEqual(result, {crew.pk, no_group.pk})

    def test_feature_tak_dikenal_tidak_mengosongkan(self):
        """
        `?feature=typo` harus membiarkan daftarnya utuh. Penyaring yang
        salah tulis mengosongkan dropdown adalah kegagalan yang terbaca
        seperti "tidak ada datanya".
        """
        crew = self.make_employee(group=self.field)

        mine = Employee.objects.filter(pk=crew.pk)

        self.assertEqual(
            filter_employees(mine, "tidak-ada").count(),
            1,
        )

    def test_employee_master_tetap_utuh(self):
        """
        Applicability bukan penyaring visibilitas. Direksi tetap terbit
        di daftar pegawai — kalau tidak, Org Chart, Reporting Line, dan
        Headcount ikut kehilangan mereka.
        """
        board = self.make_employee(group=self.board)

        self.assertTrue(
            Employee.objects
            .filter(pk=board.pk, is_deleted=False)
            .exists(),
        )


# ----------------------------------------------------------------------
# Attendance
# ----------------------------------------------------------------------


class AttendanceApplicabilityTests(FeatureApplicabilityTestCase):
    START = date(2026, 8, 3)
    END = date(2026, 8, 7)

    def test_board_tidak_pernah_dijadwalkan(self):
        board = self.make_employee(group=self.board)

        self.assertEqual(
            scheduled_work_days(board, self.START, self.END),
            set(),
        )

    def test_group_lain_tetap_dijadwalkan(self):
        crew = self.make_employee(group=self.field)

        self.assertTrue(
            scheduled_work_days(crew, self.START, self.END),
            "pegawai dengan Attendance menyala harus tetap punya hari "
            "terjadwal",
        )

    def test_jalur_borongan_sepakat_dengan_jalur_satuan(self):
        """
        Dua jalur yang harus tetap sama. Kalau hanya salah satu yang
        tahu applicability, laporan Period Summary dan penutup hari
        mulai menyebut angka yang berbeda untuk orang yang sama.
        """
        board = self.make_employee(group=self.board)
        crew = self.make_employee(group=self.field)

        bulk = scheduled_work_days_bulk(
            [board, crew],
            self.START,
            self.END,
        )

        self.assertEqual(bulk[board.id], set())

        self.assertEqual(
            bulk[crew.id],
            scheduled_work_days(crew, self.START, self.END),
        )

    def test_kunci_tetap_terbit_untuk_yang_dimatikan(self):
        """
        Pemanggil membaca `result[employee.id]` tanpa tahu apa pun soal
        applicability. Kunci yang hilang berarti `KeyError` di tengah
        penutupan bulan.
        """
        board = self.make_employee(group=self.board)

        self.assertIn(
            board.id,
            scheduled_work_days_bulk([board], self.START, self.END),
        )


# ----------------------------------------------------------------------
# Roster
# ----------------------------------------------------------------------


class RosterApplicabilityTests(FeatureApplicabilityTestCase):
    def test_board_bukan_kandidat_roster_setup(self):
        board = self.make_employee(group=self.board)
        crew = self.make_employee(group=self.field)

        candidates = set(
            RosterSetupService.candidates(
                location=self.site,
                queryset=Employee.objects.filter(
                    pk__in=[board.pk, crew.pk],
                ),
            )
            .values_list("pk", flat=True)
        )

        self.assertEqual(candidates, {crew.pk})

    def test_roster_assignment_menolak_board(self):
        """
        Dropdown yang menyaring bukan penjagaan. Yang menolak service —
        id yang dikirim langsung ke endpoint tetap harus mental.
        """
        board = self.make_employee(group=self.board)

        with self.assertRaises(ValidationError) as ctx:
            SiteRotationService.prepare_create_data(
                data={"employee": board},
            )

        self.assertIn("employee", ctx.exception.message_dict)

    def test_roster_assignment_menerima_field_crew(self):
        crew = self.make_employee(group=self.field, policy=self.policy)

        data = SiteRotationService.prepare_create_data(
            data={"employee": crew},
        )

        self.assertEqual(data["employee"], crew)


# ----------------------------------------------------------------------
# Shift
# ----------------------------------------------------------------------


class ShiftApplicabilityTests(FeatureApplicabilityTestCase):
    def test_board_tidak_memakai_shift(self):
        board = self.make_employee(group=self.board)

        self.assertFalse(is_applicable(board, HRFeature.SHIFT))

    def test_field_crew_memakai_shift(self):
        crew = self.make_employee(group=self.field)

        self.assertTrue(is_applicable(crew, HRFeature.SHIFT))

    def test_selector_shift_membuang_board(self):
        board = self.make_employee(group=self.board)
        crew = self.make_employee(group=self.field)

        mine = Employee.objects.filter(pk__in=[board.pk, crew.pk])

        self.assertEqual(
            set(
                filter_employees(mine, HRFeature.SHIFT)
                .values_list("pk", flat=True)
            ),
            {crew.pk},
        )


# ----------------------------------------------------------------------
# Field Break
# ----------------------------------------------------------------------


class FieldBreakApplicabilityTests(FeatureApplicabilityTestCase):
    def test_travel_request_menolak_board(self):
        board = self.make_employee(group=self.board)

        with self.assertRaises(ValidationError) as ctx:
            TravelRequestService.prepare_create_data(
                data={
                    "employee": board,
                    "start_date": date(2026, 9, 22),
                    "end_date": date(2026, 10, 5),
                },
            )

        self.assertIn("employee", ctx.exception.message_dict)

    def test_travel_request_menerima_field_crew(self):
        crew = self.make_employee(group=self.field)

        data = TravelRequestService.prepare_create_data(
            data={
                "employee": crew,
                "start_date": date(2026, 9, 22),
                "end_date": date(2026, 10, 5),
            },
        )

        self.assertEqual(data["employee"], crew)


# ----------------------------------------------------------------------
# Semantik banyak proses sekaligus
# ----------------------------------------------------------------------


class MultiFeatureTests(FeatureApplicabilityTestCase):
    """
    Dipakai laporan yang mewakili beberapa proses sekaligus — HR Period
    Summary yang pertama, dan Payroll nanti lewat resolver yang sama.

    Yang dijaga: **hanya nilai eksplisit False yang mengecualikan.**
    Pegawai tanpa employment atau tanpa Employee Group menghasilkan
    `NULL` di setiap ruas join, dan SQL tiga-nilai membuat `NOT (NULL AND
    NULL)` bukan `TRUE` — tanpa penjagaan eksplisit, seluruh pegawai yang
    masternya belum diisi ikut terbuang.
    """

    ALL = tuple(HRFeature)

    def test_applicable_features_lengkap_untuk_group_penuh(self):
        employee = self.make_employee(group=self.field)

        self.assertEqual(applicable_features(employee), frozenset(HRFeature))

    def test_applicable_features_kosong_untuk_group_mati_total(self):
        group = EmployeeGroup.objects.create(
            code="NOTHING",
            name="Nothing Applies",
            **{
                f"{f.value}_applicable": False
                for f in HRFeature
            },
        )

        employee = self.make_employee(group=group)

        self.assertEqual(applicable_features(employee), frozenset())

    def test_any_dan_all(self):
        group = EmployeeGroup.objects.create(
            code="MIXED",
            name="Mixed",
            attendance_applicable=False,
        )

        employee = self.make_employee(group=group)

        subset = (HRFeature.ATTENDANCE, HRFeature.LEAVE)

        self.assertTrue(any_applicable(employee, subset))
        self.assertFalse(all_applicable(employee, subset))

        self.assertFalse(
            any_applicable(employee, (HRFeature.ATTENDANCE,)),
        )

    def test_exclude_none_applicable_membuang_yang_mati_seluruhnya(self):
        dead = EmployeeGroup.objects.create(
            code="DEAD",
            name="Dead",
            attendance_applicable=False,
            leave_applicable=False,
        )

        mixed = EmployeeGroup.objects.create(
            code="HALF",
            name="Half",
            attendance_applicable=False,
        )

        a = self.make_employee(group=dead)
        b = self.make_employee(group=mixed)
        c = self.make_employee(group=self.field)
        d = self.make_employee(group=None)

        mine = Employee.objects.filter(pk__in=[a.pk, b.pk, c.pk, d.pk])

        result = set(
            exclude_none_applicable(
                mine,
                (HRFeature.ATTENDANCE, HRFeature.LEAVE),
            ).values_list("pk", flat=True)
        )

        # `a` dibuang: dua-duanya mati.
        # `b` bertahan: Leave masih menyala.
        # `d` bertahan: belum dikonfigurasi bukan berarti dimatikan.
        self.assertEqual(result, {b.pk, c.pk, d.pk})

    def test_exclude_none_applicable_menyimpan_pegawai_tanpa_employment(self):
        """
        Pegawai tanpa `EmploymentAssignment` sama sekali — bukan cuma
        tanpa group. Jalur `NULL`-nya berbeda (join gagal lebih awal),
        dan justru inilah yang paling mudah terlewat.
        """
        bare = Employee.objects.create(
            employee_number="FAP-BARE",
            first_name="Tanpa",
            last_name="Employment",
        )

        mine = Employee.objects.filter(pk=bare.pk)

        self.assertEqual(
            exclude_none_applicable(mine, self.ALL).count(),
            1,
        )

    def test_exclude_none_applicable_tanpa_feature_tidak_mengosongkan(self):
        employee = self.make_employee(group=self.field)

        mine = Employee.objects.filter(pk=employee.pk)

        self.assertEqual(exclude_none_applicable(mine, ()).count(), 1)

    def test_exclude_none_applicable_mengabaikan_feature_ngawur(self):
        employee = self.make_employee(group=self.field)

        mine = Employee.objects.filter(pk=employee.pk)

        self.assertEqual(
            exclude_none_applicable(mine, ("tidak-ada",)).count(),
            1,
        )
