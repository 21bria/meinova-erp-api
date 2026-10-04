"""
Manpower Movement — perubahan tenaga kerja dalam satu periode.

Yang dijaga berkas ini adalah **satu persamaan**:

```
Opening + Join + Transfer In − Transfer Out − Exit = Closing
```

dan tiga cara persamaan itu pecah tanpa satu pun error muncul di layar:

* **Batas tanggal yang dihitung sebagai hari, bukan sebagai detik.**
  Orang yang bergabung tepat tanggal 1 terhitung di Opening *dan* di
  Join; orang yang hari terakhirnya tepat tanggal 31 terhitung di Exit
  *dan* di Closing. Keduanya menghasilkan angka yang terbaca wajar dan
  meleset satu.
* **Penempatan lampau yang dibaca dari master hari ini.** Orang yang
  pindah keluar lokasi di tengah periode akan hilang dari Opening
  lokasinya sendiri, sementara Transfer Out tetap mengurangi satu —
  Opening yang berubah surut tiap ada mutasi baru, padahal bulan
  lampau sudah lewat.
* **`is_active` yang ikut menyaring.** Ia masih bisa dimatikan langsung
  dari form Employee tanpa `termination_date`, jadi headcount yang
  membacanya akan kehilangan orang tanpa pernah menerbitkan Exit.

`TenantTestCase` django-tenants tidak memanggil rollback per-test dan
`setUpTestData` tidak pernah jalan, jadi seluruh panggung dibuat sekali
di `setUpClass` dan **tidak ada test yang mengubahnya** — pola yang sama
dengan `test_manpower_summary.py` di sebelah. Yang dibedakan antar-test
adalah periodenya dan filternya, bukan datanya.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django_tenants.test.cases import TenantTestCase

from apps.hr.tests.access_helpers import grant_employee_read
from apps.accounts.services.role_assignment import grant_role
from apps.accounts.models import (
    AuthorityMode,
    DataScopeLevel,
    Role,
)
from apps.administration.models import (
    Company,
    Department,
    Location,
    Position,
    TerminationReason,
)
from apps.administration.models.references.hr import (
    EmployeeGroup,
    EmploymentStatus,
    EmploymentType,
)
from apps.framework.tables import TablePage
from apps.hr.models import (
    Employee,
    EmployeeAction,
    EmployeeActionStatus,
    EmployeeActionType,
    EmploymentAssignment,
    ORGANIZATION_ACTION_TYPES,
    OrganizationAssignment,
)
from apps.reports.api.hr.manpower_movement.movements import (
    MOVEMENT_LABELS,
    MOVEMENT_ORDER,
    MOVEMENT_SIGNS,
    MovementType,
)
from apps.reports.api.hr.manpower_movement.schema import (
    HR_MANPOWER_MOVEMENT_SCHEMA,
    TABLE_WIDGET,
)
from apps.reports.api.hr.manpower_movement.services import (
    ManpowerMovementPresenter,
    ManpowerMovementService,
)
from apps.reports.api.hr.manpower_movement.views import (
    HRManpowerMovementAPIView,
)


User = get_user_model()


MARCH_START = date(2026, 3, 1)
MARCH_END = date(2026, 3, 31)

LONG_AGO = date(2020, 1, 1)


class ManpowerMovementTestCase(TenantTestCase):
    """
    Panggung: satu company dengan dua lokasi, plus satu company kedua
    yang tidak pernah ikut dihitung.

    Castnya sengaja berisi setiap kasus batas sekaligus — bergabung di
    hari pertama periode, keluar di hari terakhir, masuk dan keluar di
    periode yang sama, nonaktif tanpa tanggal berhenti, dan tanpa
    tanggal bergabung sama sekali.
    """

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "reports-movement"
        tenant.name = "Reports Movement"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(code="MMV1", name="Gerak Satu")
        cls.other_company = Company.objects.create(
            code="MMV2",
            name="Gerak Dua",
        )

        cls.ho = Location.objects.create(
            company=cls.company,
            code="MMV-HO",
            name="Gerak Head Office",
        )
        cls.site = Location.objects.create(
            company=cls.company,
            code="MMV-SITE",
            name="Gerak Site",
        )
        cls.outside = Location.objects.create(
            company=cls.other_company,
            code="MMV2-HO",
            name="Gerak Dua Head Office",
        )

        cls.ho_dept = Department.objects.create(
            company=cls.company,
            location=cls.ho,
            code="MMV-HO-ADM",
            name="Administration",
        )
        cls.site_dept = Department.objects.create(
            company=cls.company,
            location=cls.site,
            code="MMV-SITE-OPS",
            name="Operations",
        )

        cls.ho_position = Position.objects.create(
            company=cls.company,
            code="MMV-HO-STAFF",
            name="Staff",
        )
        cls.site_position = Position.objects.create(
            company=cls.company,
            code="MMV-SITE-OP",
            name="Operator",
        )

        cls.group = EmployeeGroup.objects.create(
            code="MMV-STAFF",
            name="Office Employee",
        )
        # Seluruh proses HR dimatikan — bentuk yang sama dengan BOARD di
        # tenant peragaan. Kodenya sengaja bukan BOARD/BOD: kalau ada
        # baris yang menebak dari kode, group ini yang lolos.
        cls.board_group = EmployeeGroup.objects.create(
            code="MMV-DEWAN",
            name="Dewan Direksi",
            attendance_applicable=False,
            leave_applicable=False,
            roster_applicable=False,
            shift_applicable=False,
            overtime_applicable=False,
            field_break_applicable=False,
        )

        cls.employment_type = EmploymentType.objects.create(
            code="MMV-PERM",
            name="Permanent",
            requires_contract=False,
        )
        cls.status = EmploymentStatus.objects.create(
            code="MMV-ACTIVE",
            name="Active",
        )

        cls.resign_reason = TerminationReason.objects.create(
            code="MMV-RESIGN",
            name="Resignation",
        )
        cls.contract_end_reason = TerminationReason.objects.create(
            code="MMV-CONTRACT-END",
            name="Contract Ended",
        )

        # ------------------------------------------------------------------
        # Cast — tetap sepanjang periode
        # ------------------------------------------------------------------

        cls.staying = cls.make_employee("MMV001", cls.ho, join=LONG_AGO)

        # Direksi. Feature Applicability sengaja **tidak** menyaring
        # laporan ini; ia tetap kepala yang harus terhitung.
        cls.director = cls.make_employee(
            "MMV002",
            cls.ho,
            join=LONG_AGO,
            group=cls.board_group,
        )

        # Nonaktif **tanpa** tanggal berhenti — kebocoran `is_active`
        # yang masih terbuka di form Employee. Laporan tidak boleh
        # membacanya.
        cls.deactivated = cls.make_employee(
            "MMV003",
            cls.site,
            join=LONG_AGO,
            is_active=False,
        )

        # Tanpa tanggal bergabung sama sekali — tidak bisa ditempatkan
        # di periode mana pun, jadi dikeluarkan dan dihitung tersendiri.
        cls.undated = cls.make_employee("MMV004", cls.ho, join=None)

        # ------------------------------------------------------------------
        # Cast — batas tanggal
        # ------------------------------------------------------------------

        # Bergabung tepat di hari **pertama** periode.
        cls.joined_first_day = cls.make_employee(
            "MMV010",
            cls.site,
            join=MARCH_START,
        )

        # Bergabung tepat di hari **terakhir** periode.
        cls.joined_last_day = cls.make_employee(
            "MMV011",
            cls.ho,
            join=MARCH_END,
        )

        # Keluar di tengah periode.
        cls.left_midway = cls.make_employee(
            "MMV012",
            cls.ho,
            join=LONG_AGO,
            termination=date(2026, 3, 15),
            reason=cls.resign_reason,
        )

        # Hari terakhir bekerja tepat di hari **terakhir** periode.
        cls.left_last_day = cls.make_employee(
            "MMV013",
            cls.site,
            join=LONG_AGO,
            termination=MARCH_END,
            reason=cls.contract_end_reason,
        )

        # Masuk **dan** keluar di periode yang sama.
        cls.in_and_out = cls.make_employee(
            "MMV014",
            cls.site,
            join=date(2026, 3, 10),
            termination=date(2026, 3, 20),
            reason=cls.resign_reason,
        )

        # ------------------------------------------------------------------
        # Cast — mutasi
        # ------------------------------------------------------------------
        #
        # Penempatan **sekarang** adalah tujuan mutasinya; dokumennya
        # yang menyimpan asalnya. Itu persis bentuk data sungguhan
        # sesudah `EmployeeActionService.apply()` berjalan.

        cls.moved_out = cls.make_employee("MMV020", cls.ho, join=LONG_AGO)
        cls.move_out_doc = cls.make_transfer(
            cls.moved_out,
            source=cls.site,
            destination=cls.ho,
            effective=date(2026, 3, 5),
        )

        cls.moved_in = cls.make_employee("MMV021", cls.site, join=LONG_AGO)
        cls.move_in_doc = cls.make_transfer(
            cls.moved_in,
            source=cls.ho,
            destination=cls.site,
            effective=date(2026, 3, 25),
        )

        # ------------------------------------------------------------------
        # Cast — dokumen yang **tidak** boleh terhitung
        # ------------------------------------------------------------------

        cls.draft_move = cls.make_employee("MMV030", cls.ho, join=LONG_AGO)
        cls.make_transfer(
            cls.draft_move,
            source=cls.site,
            destination=cls.ho,
            effective=date(2026, 3, 12),
            status=EmployeeActionStatus.DRAFT,
        )

        # Alurnya selesai tapi penerapannya belum/gagal. Data pegawainya
        # sama sekali belum berubah.
        cls.approved_move = cls.make_employee("MMV031", cls.ho, join=LONG_AGO)
        cls.make_transfer(
            cls.approved_move,
            source=cls.site,
            destination=cls.ho,
            effective=date(2026, 3, 12),
            status=EmployeeActionStatus.APPROVED,
        )

        # Diterapkan, tapi berlaku di periode **berikutnya**.
        cls.future_move = cls.make_employee("MMV032", cls.ho, join=LONG_AGO)
        cls.make_transfer(
            cls.future_move,
            source=cls.site,
            destination=cls.ho,
            effective=date(2026, 4, 10),
        )

        # Diterapkan di periode ini, tapi **bukan** perubahan organisasi.
        cls.salary_change = cls.make_employee("MMV033", cls.ho, join=LONG_AGO)
        EmployeeAction.objects.create(
            employee=cls.salary_change,
            action_type=EmployeeActionType.SALARY_CHANGE,
            status=EmployeeActionStatus.APPLIED,
            effective_date=date(2026, 3, 18),
            document_number="MMV-SAL-1",
            company=cls.company,
            location=cls.ho,
        )

        cls.scoped_user = cls.make_user(
            username="mmv-site",
            locations=[cls.site],
        )

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(
        cls,
        number: str,
        location,
        *,
        join,
        termination=None,
        reason=None,
        group=None,
        is_active: bool = True,
    ) -> Employee:
        employee = Employee.objects.create(
            employee_number=number,
            first_name="Uji",
            last_name=number,
            is_active=is_active,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=location,
            department=(
                cls.ho_dept if location == cls.ho else cls.site_dept
            ),
            position=(
                cls.ho_position if location == cls.ho else cls.site_position
            ),
            organization_effective_date=LONG_AGO,
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            employee_group=group or cls.group,
            employment_type=cls.employment_type,
            employment_status=cls.status,
            join_date=join,
            termination_date=termination,
            termination_reason=reason,
        )

        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def make_transfer(
        cls,
        employee,
        *,
        source,
        destination,
        effective,
        status=EmployeeActionStatus.APPLIED,
        action_type=EmployeeActionType.TRANSFER,
    ) -> EmployeeAction:
        """
        Dokumen mutasi dengan **kedua ujungnya** terisi.

        `company`/`location` adalah sisi lama — didenormalisasi saat
        dokumen dibuat, jalur yang sama dengan
        `OrganizationDenormalizationMixin`. `proposed_*` adalah sisi
        barunya.
        """
        return EmployeeAction.objects.create(
            employee=employee,
            action_type=action_type,
            status=status,
            effective_date=effective,
            document_number=f"MMV-{employee.employee_number}-{effective:%m%d}",
            reason="Mutasi data uji",
            company=cls.company,
            location=source,
            proposed_location=destination,
        )

    @classmethod
    def make_user(cls, *, username, companies=(), locations=()):
        """
        Akun bercakupan, **dinyatakan pada penugasannya**.

        Ada `companies`/`locations` berarti `EXPLICIT` berisi baris itu;
        tidak ada keduanya berarti cakupan ikut penempatan pemegangnya
        sedalam Location.
        """
        user = User.objects.create_user(
            username=username,
            password="Uji#12345",
            email=f"{username}@contoh.test",
        )

        # `Role` menjawab WHAT saja. Cakupannya dinyatakan pada
        # penugasan di bawah — dan sejak Wave C itu satu-satunya
        # tempatnya, karena kolom cakupan pada `Role` sudah tidak ada.
        role = Role.objects.create(
            code=f"ROLE-{username.upper()}",
            name=f"Role {username}",
        )

        # Laporan menuntut `hr.view_employee`, sama dengan tabel
        # Employee. Di produksi setiap role yang diseed memegangnya
        # (`READ_GRANTS`), jadi fixture yang tidak memberikannya
        # menguji keadaan yang tidak pernah ada — dan gagal karena
        # sebab yang bukan sedang diujinya.
        grant_employee_read(role)

        if companies or locations:
            grant_role(
                user, role,
                mode=AuthorityMode.EXPLICIT,
                authorities=(
                    [("company", company.id) for company in companies]
                    + [("location", location.id) for location in locations]
                ),
            )
        else:
            grant_role(
                user, role,
                mode=AuthorityMode.PLACEMENT,
                level=DataScopeLevel.LOCATION,
            )

        return user

    # ------------------------------------------------------------------
    # Bantu
    # ------------------------------------------------------------------

    @staticmethod
    def context(start=MARCH_START, end=MARCH_END, user=None, **filters):
        return {
            "user": user,
            "period": {"start": start, "end": end},
            **filters,
        }

    @classmethod
    def report(cls, **kwargs):
        return ManpowerMovementService.report(cls.context(**kwargs))

    @staticmethod
    def numbers(report, movement_type=None) -> set[str]:
        return {
            row.employee_number
            for row in report.rows
            if movement_type is None or row.movement_type == movement_type
        }


# ----------------------------------------------------------------------
# Identitas
# ----------------------------------------------------------------------


class IdentityTests(ManpowerMovementTestCase):
    def test_identitas_tertutup_tanpa_filter(self):
        report = self.report()

        self.assertEqual(
            report.expected_closing,
            report.closing,
            "Opening + Join + In − Out − Exit harus sama dengan Closing",
        )
        self.assertEqual(report.variance, 0)

    def test_identitas_tertutup_per_lokasi(self):
        """
        Yang paling mudah pecah, dan pecahnya diam: mutasi mengubah
        keanggotaan populasi di tengah periode.
        """
        for label, location in (
            ("head office", self.ho),
            ("site", self.site),
        ):
            with self.subTest(location=label):
                report = self.report(location=[location.pk])

                self.assertEqual(report.variance, 0)

    def test_identitas_tertutup_untuk_akun_bercakupan(self):
        report = self.report(user=self.scoped_user)

        self.assertEqual(report.variance, 0)

    def test_identitas_tertutup_pada_periode_tanpa_pergerakan(self):
        report = self.report(
            start=date(2026, 6, 1),
            end=date(2026, 6, 30),
        )

        self.assertEqual(report.rows, [])
        self.assertEqual(report.opening, report.closing)
        self.assertEqual(report.variance, 0)

    def test_net_change_sama_dengan_jumlah_bertanda(self):
        report = self.report()

        self.assertEqual(
            report.net_change,
            sum(row.sign for row in report.rows),
        )


# ----------------------------------------------------------------------
# Batas tanggal
# ----------------------------------------------------------------------


class BoundaryTests(ManpowerMovementTestCase):
    def test_bergabung_di_hari_pertama_tidak_ikut_opening(self):
        """
        Dengan `join_date <= start`, orang ini terhitung di Opening
        **dan** di Join sekaligus — dan Closing meleset satu.
        """
        report = self.report()

        self.assertIn("MMV010", self.numbers(report, MovementType.JOIN))

        opening_only = ManpowerMovementService.headcount_at(
            self.context(),
            MARCH_START,
        )
        without = ManpowerMovementService.headcount_at(
            self.context(),
            MARCH_START + timedelta(days=1),
        )

        self.assertEqual(without - opening_only, 1)

    def test_bergabung_di_hari_terakhir_ikut_closing(self):
        report = self.report()

        self.assertIn("MMV011", self.numbers(report, MovementType.JOIN))

        # Ia bergabung 31 Maret dan tidak keluar, jadi ia harus ada di
        # Closing — kalau Closing dibaca pada `end` alih-alih `end + 1`,
        # ia hilang.
        after = ManpowerMovementService.headcount_at(
            self.context(),
            MARCH_END + timedelta(days=1),
        )
        before = ManpowerMovementService.headcount_at(
            self.context(),
            MARCH_END,
        )

        self.assertGreater(after, before - 2)
        self.assertEqual(report.closing, after)

    def test_hari_terakhir_bekerja_di_akhir_periode_tidak_ikut_closing(self):
        """
        Orang yang berhenti tanggal 31 tetap bekerja tanggal 31, tapi
        sudah tidak ada saat periode berikutnya dibuka. Terhitung Exit,
        **tidak** terhitung Closing.
        """
        report = self.report()

        self.assertIn("MMV013", self.numbers(report, MovementType.EXIT))

        closing_ids = set(
            ManpowerMovementService._dated(
                ManpowerMovementService.employee_queryset(self.context()),
                MARCH_END + timedelta(days=1),
            ).values_list("employee_number", flat=True)
        )

        self.assertNotIn("MMV013", closing_ids)

    def test_masuk_dan_keluar_di_periode_yang_sama(self):
        report = self.report()

        self.assertIn("MMV014", self.numbers(report, MovementType.JOIN))
        self.assertIn("MMV014", self.numbers(report, MovementType.EXIT))

        # Dua baris, saling meniadakan. Bukan satu baris, dan bukan nol.
        rows = [
            row for row in report.rows if row.employee_number == "MMV014"
        ]

        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(row.sign for row in rows), 0)

    def test_keluar_sebelum_periode_tidak_ikut_opening(self):
        """Periode sesudah kepergiannya: ia tidak boleh muncul lagi."""
        report = self.report(
            start=date(2026, 4, 1),
            end=date(2026, 4, 30),
        )

        self.assertNotIn("MMV012", self.numbers(report))

    def test_keluar_tetap_terhitung_di_opening_periodenya_sendiri(self):
        """
        Opening bulan Maret harus tetap memuat orang yang keluar
        pertengahan Maret. Kalau tidak, laporan Maret yang dibuka bulan
        Juni menunjukkan angka berbeda dari yang dicetak bulan April.
        """
        report = self.report()

        opening_ids = set(
            ManpowerMovementService._dated(
                ManpowerMovementService.employee_queryset(self.context()),
                MARCH_START,
            ).values_list("employee_number", flat=True)
        )

        self.assertIn("MMV012", opening_ids)
        self.assertIn("MMV013", opening_ids)
        self.assertIn("MMV012", self.numbers(report, MovementType.EXIT))


# ----------------------------------------------------------------------
# Populasi
# ----------------------------------------------------------------------


class PopulationTests(ManpowerMovementTestCase):
    def test_is_active_tidak_dibaca(self):
        """
        `Employee.is_active` masih bisa dimatikan dari form tanpa
        mengisi `termination_date`. Kalau headcount membacanya, orang
        itu hilang dari Closing tanpa pernah terbit sebagai Exit — dan
        identitasnya pecah tanpa sebab yang terlihat.
        """
        self.assertFalse(self.deactivated.is_active)

        numbers = set(
            ManpowerMovementService.employee_queryset(self.context())
            .values_list("employee_number", flat=True)
        )

        self.assertIn("MMV003", numbers)

    def test_tanpa_tanggal_bergabung_dikeluarkan_dan_dihitung(self):
        report = self.report()

        self.assertNotIn("MMV004", self.numbers(report))
        self.assertGreaterEqual(report.missing_join_date, 1)

        undated = set(
            ManpowerMovementService.employee_queryset(self.context())
            .filter(employment__join_date__isnull=True)
            .values_list("employee_number", flat=True)
        )

        self.assertIn("MMV004", undated)

    def test_feature_applicability_tidak_menyaring(self):
        """
        Manpower adalah angka organisasi, bukan angka proses. Direksi
        yang seluruh proses HR-nya dimatikan tetap kepala yang digaji.
        """
        opening_ids = set(
            ManpowerMovementService._dated(
                ManpowerMovementService.employee_queryset(self.context()),
                MARCH_START,
            ).values_list("employee_number", flat=True)
        )

        self.assertIn("MMV002", opening_ids)

    def test_cakupan_tidak_bisa_dilebarkan_lewat_filter(self):
        """
        Filter hanya boleh **mempersempit** Organization Scope. Memaksa
        seluruh id lokasi lewat query string tidak boleh menambah satu
        baris pun.
        """
        scoped = self.report(user=self.scoped_user)

        forced = self.report(
            user=self.scoped_user,
            location=[self.ho.pk, self.site.pk, self.outside.pk],
        )

        self.assertLessEqual(forced.opening, scoped.opening)
        self.assertLessEqual(len(forced.rows), len(scoped.rows))


# ----------------------------------------------------------------------
# Mutasi
# ----------------------------------------------------------------------


class TransferTests(ManpowerMovementTestCase):
    def test_tanpa_filter_mutasi_jadi_internal_move(self):
        """
        Kedua ujungnya di dalam populasi yang dilaporkan, jadi jumlah
        kepalanya tidak berubah sama sekali.
        """
        report = self.report()

        self.assertEqual(report.transfers_in, 0)
        self.assertEqual(report.transfers_out, 0)
        self.assertEqual(
            self.numbers(report, MovementType.INTERNAL_MOVE),
            {"MMV020", "MMV021"},
        )

    def test_internal_move_tidak_mengubah_identitas(self):
        report = self.report()

        for row in report.rows:
            if row.movement_type == MovementType.INTERNAL_MOVE:
                self.assertEqual(row.sign, 0)

    def test_transfer_in_dan_out_dinilai_dari_batas_populasi(self):
        site = self.report(location=[self.site.pk])

        self.assertEqual(
            self.numbers(site, MovementType.TRANSFER_OUT),
            {"MMV020"},
        )
        self.assertEqual(
            self.numbers(site, MovementType.TRANSFER_IN),
            {"MMV021"},
        )

        # Dari sisi seberangnya, keduanya bertukar peran.
        ho = self.report(location=[self.ho.pk])

        self.assertEqual(
            self.numbers(ho, MovementType.TRANSFER_IN),
            {"MMV020"},
        )
        self.assertEqual(
            self.numbers(ho, MovementType.TRANSFER_OUT),
            {"MMV021"},
        )

    def test_opening_memuat_yang_kemudian_pindah_keluar(self):
        """
        Inti pemutaran mundur penempatan. MMV020 sekarang berada di
        head office, tapi pada 1 Maret ia masih di site — dan Opening
        site harus memuatnya, kalau tidak Transfer Out mengurangi
        sesuatu yang tidak pernah ada.
        """
        site = self.report(location=[self.site.pk])

        without_rewind = (
            ManpowerMovementService._dated(
                ManpowerMovementService.employee_queryset(
                    self.context(location=[self.site.pk])
                ),
                MARCH_START,
            ).count()
        )

        self.assertEqual(site.opening, without_rewind + 1)
        self.assertEqual(site.variance, 0)

    def test_hanya_dokumen_applied_yang_terhitung(self):
        report = self.report()

        moved = self.numbers(report, MovementType.INTERNAL_MOVE)

        self.assertNotIn("MMV030", moved)
        self.assertNotIn("MMV031", moved)

    def test_effective_date_yang_dipakai_bukan_tanggal_lain(self):
        """Mutasi berlaku April tidak boleh muncul di laporan Maret."""
        march = self.report()

        self.assertNotIn("MMV032", self.numbers(march))

        april = self.report(
            start=date(2026, 4, 1),
            end=date(2026, 4, 30),
        )

        self.assertIn("MMV032", self.numbers(april))

    def test_jenis_non_organisasi_bukan_mutasi(self):
        report = self.report()

        self.assertNotIn("MMV033", self.numbers(report))

    def test_peta_jenis_organisasi_ikut_model(self):
        """
        Menambah jenis action organisasi baru tanpa memikirkan laporan
        ini adalah cara Transfer In/Out berhenti lengkap tanpa satu pun
        test merah.
        """
        self.assertEqual(
            ORGANIZATION_ACTION_TYPES,
            {
                EmployeeActionType.TRANSFER,
                EmployeeActionType.PROMOTION,
                EmployeeActionType.DEMOTION,
                EmployeeActionType.POSITION_CHANGE,
            },
        )

    def test_promosi_lintas_lokasi_juga_transfer(self):
        """
        Yang menentukan Transfer Out adalah **batas yang dilewati**,
        bukan nama dokumennya. `EmployeeAction` sendiri memakai satu
        handler untuk keempat jenis organisasi.
        """
        report = self.report(location=[self.site.pk])

        row = next(
            row for row in report.rows if row.employee_number == "MMV020"
        )

        self.assertEqual(row.movement_type, MovementType.TRANSFER_OUT)


# ----------------------------------------------------------------------
# Jenis pergerakan
# ----------------------------------------------------------------------


class MovementTypeTests(ManpowerMovementTestCase):
    def test_setiap_jenis_punya_label(self):
        for code in MOVEMENT_ORDER:
            with self.subTest(code=code):
                self.assertIn(code, MOVEMENT_LABELS)

    def test_setiap_jenis_punya_tanda(self):
        """
        Jenis tanpa tanda akan diam-diam dianggap nol oleh
        `MOVEMENT_SIGNS.get(..., 0)` — pergerakan yang terbit di tabel
        tapi tidak pernah mengubah Closing.
        """
        for code in MOVEMENT_ORDER:
            with self.subTest(code=code):
                self.assertIn(code, MOVEMENT_SIGNS)

    def test_tidak_ada_jenis_yang_tidak_terdaftar(self):
        self.assertEqual(set(MOVEMENT_SIGNS), set(MOVEMENT_ORDER))
        self.assertEqual(set(MOVEMENT_LABELS), set(MOVEMENT_ORDER))

    def test_tanda_sesuai_identitas(self):
        self.assertEqual(MOVEMENT_SIGNS[MovementType.JOIN], 1)
        self.assertEqual(MOVEMENT_SIGNS[MovementType.TRANSFER_IN], 1)
        self.assertEqual(MOVEMENT_SIGNS[MovementType.TRANSFER_OUT], -1)
        self.assertEqual(MOVEMENT_SIGNS[MovementType.EXIT], -1)
        self.assertEqual(MOVEMENT_SIGNS[MovementType.INTERNAL_MOVE], 0)


# ----------------------------------------------------------------------
# Presenter
# ----------------------------------------------------------------------


class PresenterTests(ManpowerMovementTestCase):
    def test_bridge_membaca_persamaan_kiri_ke_kanan(self):
        context = self.context()
        report = ManpowerMovementService.report(context)

        chart = ManpowerMovementPresenter.headcount_bridge(context)

        self.assertEqual(
            chart["categories"],
            [
                "Opening",
                "Join",
                "Transfer In",
                "Transfer Out",
                "Exit",
                "Closing",
            ],
        )

        data = chart["datasets"][0]["data"]

        self.assertEqual(data[0], report.opening)
        self.assertEqual(data[-1], report.closing)

        # Keluar digambar negatif supaya aritmetikanya terlihat.
        self.assertLessEqual(data[3], 0)
        self.assertLessEqual(data[4], 0)

        self.assertEqual(sum(data[:-1]), report.closing)

    def test_exit_by_reason_berjumlah_sama_dengan_kpi_exit(self):
        context = self.context()
        report = ManpowerMovementService.report(context)

        chart = ManpowerMovementPresenter.exit_by_reason(context)

        self.assertEqual(
            sum(chart["datasets"][0]["data"]),
            report.exits,
        )

    def test_alasan_kosong_tetap_berbunyi(self):
        """
        Sel kosong di tengah chart terbaca seperti gagal dimuat, dan
        potongannya tetap membawa angka yang harus ikut dijumlahkan.
        """
        context = self.context()

        chart = ManpowerMovementPresenter.exit_by_reason(context)

        for label in chart["categories"]:
            self.assertTrue(label)

    def test_tabel_satu_baris_per_peristiwa(self):
        context = self.context()
        report = ManpowerMovementService.report(context)

        table = ManpowerMovementPresenter.movement_table(context)

        self.assertEqual(table["total"], len(report.rows))

    def test_totals_tabel_tidak_bergeser_saat_dipaginasi(self):
        context = self.context()

        full = ManpowerMovementPresenter.movement_table(context)

        class _Request:
            query_params = {"page": "1", "page_size": "25"}

        paged = ManpowerMovementPresenter.movement_table(
            context,
            page=TablePage.from_request(_Request(), TABLE_WIDGET),
        )

        self.assertEqual(full["totals"], paged["totals"])
        self.assertEqual(full["total"], paged["total"])

    def test_totals_memuat_variance(self):
        """
        Selisih yang tidak diterbitkan adalah selisih yang tidak pernah
        ketahuan. Nol di seluruh keadaan yang dijaga test — yang dijaga
        di sini adalah **kuncinya ada**.
        """
        table = ManpowerMovementPresenter.movement_table(self.context())

        self.assertIn("variance", table["totals"])
        self.assertEqual(table["totals"]["variance"], 0)

    def test_baris_tabel_kronologis(self):
        report = self.report()

        dates = [row.movement_date for row in report.rows]

        self.assertEqual(dates, sorted(dates))

    def test_kunci_baris_tabel_cocok_dengan_kolom_schema(self):
        """
        Serializer/presenter yang menyebut kolom satu per satu adalah
        cara kolom baru hilang dari payload sementara seluruh test
        service tetap hijau — persis bug `ShiftCalendarDaySerializer`.
        """
        table = ManpowerMovementPresenter.movement_table(self.context())

        if not table["items"]:
            self.skipTest("tidak ada baris untuk diperiksa")

        payload_keys = set(table["items"][0])

        column_keys = {column["key"] for column in TABLE_WIDGET["columns"]}

        self.assertEqual(
            column_keys - payload_keys,
            set(),
            "Kolom schema yang tidak pernah terisi payload",
        )


# ----------------------------------------------------------------------
# Kontrak layar
# ----------------------------------------------------------------------


class SchemaContractTests(ManpowerMovementTestCase):
    def test_setiap_widget_punya_resolver(self):
        """
        Widget tanpa resolver gagal **diam**: kartunya berdiri kosong
        di layar dan tidak ada satu pun error yang terbit.
        """
        for widget in HR_MANPOWER_MOVEMENT_SCHEMA["widgets"]:
            key = widget["key"]

            with self.subTest(widget=key):
                self.assertTrue(
                    hasattr(HRManpowerMovementAPIView, f"resolve_{key}"),
                    f"resolve_{key}() belum ada",
                )

    def test_punya_pemilih_periode(self):
        """
        Laporan ini **hanya punya arti** sebagai selisih antara dua
        tanggal. Tanpa pemilih periode, seluruh angkanya jatuh ke bulan
        berjalan tanpa ada yang bisa menggesernya.
        """
        types = {
            item.get("type")
            for item in HR_MANPOWER_MOVEMENT_SCHEMA["filters"]
        }

        self.assertIn("period", types)

    def test_tidak_ada_filter_yang_memecah_identitas(self):
        """
        Filter Movement Type sengaja tidak ada: Opening dan Closing
        dihitung dari tanggal, bukan dari baris pergerakan, jadi
        menyisakan satu jenis saja akan mengubah lima kartu dan
        membiarkan dua lainnya.
        """
        keys = {
            item.get("key")
            for item in HR_MANPOWER_MOVEMENT_SCHEMA["filters"]
        }

        self.assertNotIn("movement_type", keys)

    def test_endpoint_dan_module_konsisten(self):
        self.assertEqual(
            HR_MANPOWER_MOVEMENT_SCHEMA["endpoint"],
            "/api/reports/hr/manpower-movement/",
        )
        self.assertEqual(
            HR_MANPOWER_MOVEMENT_SCHEMA["module"],
            "reports/hr/manpower-movement",
        )
        self.assertEqual(
            HRManpowerMovementAPIView.framework_module,
            HR_MANPOWER_MOVEMENT_SCHEMA["module"],
        )

    def test_read_only(self):
        """
        Laporan tidak boleh punya satu pun jalan tulis. Pergerakan
        diperbaiki di layar Employee Action.
        """
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertFalse(
                    hasattr(HRManpowerMovementAPIView, method),
                    f"{method}() tidak boleh ada di laporan",
                )
