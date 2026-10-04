"""
Manpower Summary — ringkasan jumlah dan komposisi tenaga kerja.

Yang dijaga berkas ini adalah **invariant angkanya**, dan yang paling
mudah rusak diam-diam ada tiga:

* headcount yang menyusut karena Feature Applicability ikut menyaring —
  laporan manpower yang tidak menghitung direksi terbaca seperti
  laporan manpower yang benar, cuma lebih kecil;
* KPI, chart, dan tabel yang berangkat dari populasi berbeda — ketiganya
  tetap tampil, cuma tidak lagi menjumlahkan ke angka yang sama;
* `Permanent + Contract = Headcount` yang dianggap berlaku padahal
  master Employment Type hidup berisi enam jenis, dan sebagian pegawai
  belum punya jenis sama sekali.

`TenantTestCase` django-tenants tidak memanggil rollback per-test dan
`setUpTestData` tidak pernah jalan, jadi seluruh panggung dibuat sekali
di `setUpClass` dan tidak ada test yang mengubahnya — pola yang sama
dengan `apps/reports/tests/hr/test_employee_reporting_audit.py`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django_tenants.test.cases import TenantTestCase

from apps.hr.tests.access_helpers import grant_employee_read
from apps.accounts.models import (
    AuthorityMode,
    DataScopeLevel,
    Role,
)
from apps.accounts.services.role_assignment import grant_role
from apps.administration.models import (
    Company,
    Department,
    Location,
    Section,
)
from apps.administration.models.references.hr import (
    EmployeeGroup,
    EmploymentStatus,
    EmploymentType,
)
from apps.framework.tables import TablePage
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    OrganizationAssignment,
)
from apps.reports.api.hr.manpower_summary import services as manpower_services
from apps.reports.api.hr.manpower_summary import views as manpower_views
from apps.reports.api.hr.manpower_summary.schema import (
    HR_MANPOWER_SUMMARY_SCHEMA,
    TABLE_WIDGET,
)
from apps.reports.api.hr.manpower_summary.services import (
    UNASSIGNED_LABEL,
    ManpowerSummaryPresenter,
    ManpowerSummaryService,
)
from apps.reports.api.hr.manpower_summary.views import HRManpowerSummaryAPIView


User = get_user_model()


class ManpowerSummaryTestCase(TenantTestCase):
    """
    Panggung: dua company, tiga lokasi, tiga department, dan sepuluh
    pegawai aktif yang komposisinya sengaja tidak rapi.

    Ketidakrapiannya yang jadi isi test: satu pegawai tanpa jenis
    kepegawaian, satu direksi tanpa department, satu pegawai nonaktif,
    dan satu jenis kepegawaian berkontrak yang **namanya bukan**
    "Contract".
    """

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "reports-manpower"
        tenant.name = "Reports Manpower"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(code="MPW1", name="Manpower Satu")
        cls.other_company = Company.objects.create(
            code="MPW2",
            name="Manpower Dua",
        )

        cls.ho = Location.objects.create(
            company=cls.company,
            code="MPW-HO",
            name="Manpower Head Office",
        )
        cls.site = Location.objects.create(
            company=cls.company,
            code="MPW-SITE",
            name="Manpower Site",
        )
        cls.other_ho = Location.objects.create(
            company=cls.other_company,
            code="MPW2-HO",
            name="Manpower Dua Head Office",
        )

        cls.hrd = Department.objects.create(
            company=cls.company,
            location=cls.ho,
            code="MPW-HRD",
            name="Human Resources",
        )
        cls.finance = Department.objects.create(
            company=cls.company,
            location=cls.ho,
            code="MPW-FIN",
            name="Finance",
        )
        cls.ops = Department.objects.create(
            company=cls.company,
            location=cls.site,
            code="MPW-OPS",
            name="Operations",
        )

        cls.hrd_section = Section.objects.create(
            company=cls.company,
            location=cls.ho,
            department=cls.hrd,
            code="MPW-HRD-GEN",
            name="HR General",
        )

        # Seluruh proses HR dimatikan — bentuk yang sama dengan group
        # BOARD di tenant peragaan. Kodenya sengaja **bukan** BOARD/BOD:
        # kalau ada satu baris di laporan yang menebak dari kode, group
        # ini yang akan lolos dari tebakannya.
        cls.board_group = EmployeeGroup.objects.create(
            code="MPW-DEWAN",
            name="Dewan Direksi",
            attendance_applicable=False,
            leave_applicable=False,
            roster_applicable=False,
            shift_applicable=False,
            overtime_applicable=False,
            field_break_applicable=False,
        )

        cls.staff_group = EmployeeGroup.objects.create(
            code="MPW-STAFF",
            name="Office Employee",
        )

        cls.field_group = EmployeeGroup.objects.create(
            code="MPW-FIELD",
            name="Field Employee",
            # Roster/shift menyala, attendance dimatikan — bentuk
            # setengah-setengah yang tetap harus dihitung utuh.
            attendance_applicable=False,
        )

        cls.permanent = EmploymentType.objects.create(
            code="MPW-PERM",
            name="Permanent",
            requires_contract=False,
        )
        cls.contract = EmploymentType.objects.create(
            code="MPW-CONT",
            name="Contract",
            requires_contract=True,
        )
        # Berkontrak, tapi **namanya bukan** "Contract". Yang memutuskan
        # kolom Contract adalah `requires_contract`, bukan namanya.
        cls.daily = EmploymentType.objects.create(
            code="MPW-DAILY",
            name="Daily Worker",
            requires_contract=True,
        )

        cls.active_status = EmploymentStatus.objects.create(
            code="MPW-ACTIVE",
            name="Active",
        )
        cls.probation_status = EmploymentStatus.objects.create(
            code="MPW-PROB",
            name="Probation",
        )

        # ------------------------------------------------------------------
        # Pegawai
        # ------------------------------------------------------------------

        cls.director = cls.make_employee(
            number="BOD001",
            location=cls.ho,
            department=None,
            group=cls.board_group,
            employment_type=cls.permanent,
        )

        cls.hrd_one = cls.make_employee(
            number="HO001",
            location=cls.ho,
            department=cls.hrd,
            section=cls.hrd_section,
            group=cls.staff_group,
            employment_type=cls.permanent,
        )
        cls.hrd_two = cls.make_employee(
            number="HO002",
            location=cls.ho,
            department=cls.hrd,
            group=cls.staff_group,
            employment_type=cls.permanent,
            status=cls.probation_status,
        )
        cls.hrd_three = cls.make_employee(
            number="HO003",
            location=cls.ho,
            department=cls.hrd,
            group=cls.staff_group,
            employment_type=cls.contract,
        )

        # Tanpa `EmploymentAssignment` sama sekali: tidak Permanent,
        # tidak Contract, tetap manpower.
        cls.hrd_four = cls.make_employee(
            number="HO004",
            location=cls.ho,
            department=cls.hrd,
            group=None,
            employment_type=None,
        )

        cls.finance_one = cls.make_employee(
            number="HO005",
            location=cls.ho,
            department=cls.finance,
            group=cls.staff_group,
            employment_type=cls.permanent,
        )

        cls.ops_one = cls.make_employee(
            number="ST001",
            location=cls.site,
            department=cls.ops,
            group=cls.field_group,
            employment_type=cls.permanent,
        )
        cls.ops_two = cls.make_employee(
            number="ST002",
            location=cls.site,
            department=cls.ops,
            group=cls.field_group,
            employment_type=cls.contract,
        )
        cls.ops_three = cls.make_employee(
            number="ST003",
            location=cls.site,
            department=cls.ops,
            group=cls.field_group,
            employment_type=cls.daily,
        )

        # Sudah keluar — bukan lagi manpower.
        cls.resigned = cls.make_employee(
            number="ST004",
            location=cls.site,
            department=cls.ops,
            group=cls.field_group,
            employment_type=cls.permanent,
            is_active=False,
        )

        cls.other = cls.make_employee(
            number="CO001",
            company=cls.other_company,
            location=cls.other_ho,
            department=None,
            group=cls.staff_group,
            employment_type=cls.permanent,
        )

    # ------------------------------------------------------------------
    # Pabrik
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(
        cls,
        *,
        number: str,
        location,
        department,
        group,
        employment_type,
        company=None,
        section=None,
        status=None,
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
            company=company or cls.company,
            location=location,
            department=department,
            section=section,
            organization_effective_date=date(2020, 1, 1),
        )

        if group is not None or employment_type is not None:
            EmploymentAssignment.objects.create(
                employee=employee,
                employee_group=group,
                employment_type=employment_type,
                employment_status=status or cls.active_status,
                join_date=date(2021, 1, 1),
            )

        return Employee.objects.get(pk=employee.pk)

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
    def context(**filters) -> dict:
        return {"user": None, **filters}

    @classmethod
    def summary(cls, **filters):
        return ManpowerSummaryService.summary(cls.context(**filters))

    @classmethod
    def numbers(cls, **filters) -> list[str]:
        """Nomor pegawai yang masuk populasi — untuk assertion kasar."""
        queryset = ManpowerSummaryService.employee_queryset(
            cls.context(**filters)
        )

        return sorted(queryset.values_list("employee_number", flat=True))

    @staticmethod
    def counts(breakdown: dict) -> dict:
        """Chart batang bertumpuk → {kategori: total}."""
        totals = {}

        for index, label in enumerate(breakdown["categories"]):
            totals[label] = sum(
                dataset["data"][index] for dataset in breakdown["datasets"]
            )

        return totals

    @staticmethod
    def shares(breakdown: dict) -> dict:
        """Donut → {label: nilai}."""
        return {item["label"]: item["value"] for item in breakdown["series"]}

    @classmethod
    def table(cls, context, **params) -> dict:
        request = SimpleNamespace(query_params=params)

        return ManpowerSummaryPresenter.manpower_table(
            context,
            page=TablePage.from_request(request, TABLE_WIDGET),
        )


class HeadcountTests(ManpowerSummaryTestCase):
    """Angka pokok: siapa yang dihitung, siapa yang tidak."""

    def test_total_headcount(self):
        self.assertEqual(
            ManpowerSummaryPresenter.headcount(self.context()),
            {"value": 10},
        )

    def test_headcount_sama_dengan_jumlah_pegawai_populasi(self):
        """Bukan angka lain yang kebetulan mirip."""
        self.assertEqual(
            self.summary().headcount,
            len(self.numbers()),
        )

    def test_pegawai_nonaktif_tidak_dihitung(self):
        self.assertNotIn("ST004", self.numbers())

    def test_pegawai_terhapus_tidak_dihitung(self):
        """Soft delete tidak boleh menyisakan angka di laporan."""
        employee = Employee.objects.create(
            employee_number="TMP999",
            first_name="Sementara",
            last_name="Hapus",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=self.company,
            location=self.ho,
            organization_effective_date=date(2020, 1, 1),
        )

        try:
            self.assertEqual(self.summary().headcount, 11)

            employee.is_deleted = True
            employee.save(update_fields=["is_deleted"])

            self.assertEqual(
                ManpowerSummaryService.summary(self.context()).headcount,
                10,
            )
        finally:
            # Ditinggalkan dalam keadaan terhapus, bukan dihapus keras:
            # baris penempatannya masih menunjuk ke sini, dan panggung
            # dipakai bersama seluruh test di berkas ini.
            Employee.objects.filter(pk=employee.pk).update(is_deleted=True)


class CompositionTests(ManpowerSummaryTestCase):
    """
    Permanent/Contract berasal dari `EmploymentType.requires_contract`,
    bukan dari nama atau kode jenis kepegawaiannya.
    """

    def test_permanent_dan_contract(self):
        context = self.context()

        self.assertEqual(
            ManpowerSummaryPresenter.permanent(context),
            {"value": 6},
        )
        self.assertEqual(
            ManpowerSummaryPresenter.contract(context),
            {"value": 3},
        )

    def test_jenis_berkontrak_yang_namanya_bukan_contract_tetap_contract(self):
        """
        "Daily Worker" berkontrak menurut master, jadi ia Contract.
        Kalau angkanya berubah, ada yang mulai membaca nama jenisnya.
        """
        context = self.context(employment_type=[self.daily.id])

        self.assertEqual(
            ManpowerSummaryPresenter.contract(context),
            {"value": 1},
        )
        self.assertEqual(
            ManpowerSummaryPresenter.permanent(context),
            {"value": 0},
        )

    def test_tanpa_employment_type_tidak_masuk_keduanya(self):
        self.assertEqual(
            ManpowerSummaryPresenter.unspecified_employment_type(
                self.context()
            ),
            {"value": 1},
        )

    def test_invariant_permanent_contract_unspecified(self):
        """
        `Permanent + Contract + Belum Ditentukan = Headcount` **selalu**
        benar; `Permanent + Contract = Headcount` tidak dijamin, dan
        laporan ini tidak boleh berpura-pura sebaliknya.
        """
        composition = self.summary().composition

        self.assertEqual(
            composition.permanent
            + composition.contract
            + composition.unspecified,
            composition.headcount,
        )

        self.assertNotEqual(
            composition.permanent + composition.contract,
            composition.headcount,
        )


class BreakdownTests(ManpowerSummaryTestCase):
    """Lima breakdown, semuanya dari populasi yang sama."""

    def test_breakdown_company(self):
        self.assertEqual(
            self.counts(
                ManpowerSummaryPresenter.company_breakdown(self.context())
            ),
            {"Manpower Satu": 9, "Manpower Dua": 1},
        )

    def test_breakdown_location(self):
        self.assertEqual(
            self.counts(
                ManpowerSummaryPresenter.location_breakdown(self.context())
            ),
            {
                "Manpower Head Office": 6,
                "Manpower Site": 3,
                "Manpower Dua Head Office": 1,
            },
        )

    def test_breakdown_department(self):
        self.assertEqual(
            self.counts(
                ManpowerSummaryPresenter.department_breakdown(self.context())
            ),
            {
                "Human Resources": 4,
                "Operations": 3,
                UNASSIGNED_LABEL: 2,
                "Finance": 1,
            },
        )

    def test_breakdown_employee_group(self):
        self.assertEqual(
            self.shares(
                ManpowerSummaryPresenter.employee_group_breakdown(
                    self.context()
                )
            ),
            {
                "Office Employee": 5,
                "Field Employee": 3,
                "Dewan Direksi": 1,
                UNASSIGNED_LABEL: 1,
            },
        )

    def test_breakdown_employment_type(self):
        self.assertEqual(
            self.shares(
                ManpowerSummaryPresenter.employment_type_breakdown(
                    self.context()
                )
            ),
            {
                "Permanent": 6,
                "Contract": 2,
                "Daily Worker": 1,
                UNASSIGNED_LABEL: 1,
            },
        )

    def test_breakdown_batang_memecah_permanent_dan_contract(self):
        """
        Tinggi batang = headcount kelompoknya; tumpukannya komposisi.
        """
        breakdown = ManpowerSummaryPresenter.location_breakdown(self.context())

        index = breakdown["categories"].index("Manpower Site")

        datasets = {
            dataset["label"]: dataset["data"][index]
            for dataset in breakdown["datasets"]
        }

        self.assertEqual(datasets["Permanent"], 1)
        self.assertEqual(datasets["Contract"], 2)

    def test_tumpukan_belum_ditentukan_hanya_muncul_kalau_ada_isinya(self):
        labels = {
            dataset["label"]
            for dataset in ManpowerSummaryPresenter.location_breakdown(
                self.context()
            )["datasets"]
        }

        self.assertIn(UNASSIGNED_LABEL, labels)

        # Disaring ke lokasi yang semua orangnya punya jenis kepegawaian:
        # legenda ketiga yang selalu nol cuma derau.
        labels = {
            dataset["label"]
            for dataset in ManpowerSummaryPresenter.location_breakdown(
                self.context(location=[self.site.id])
            )["datasets"]
        }

        self.assertNotIn(UNASSIGNED_LABEL, labels)

    def test_donut_totalnya_sama_dengan_headcount(self):
        context = self.context()

        for breakdown in (
            ManpowerSummaryPresenter.employee_group_breakdown(context),
            ManpowerSummaryPresenter.employment_type_breakdown(context),
        ):
            self.assertEqual(
                breakdown["total"],
                ManpowerSummaryPresenter.headcount(context)["value"],
            )

    def test_ekor_chart_dipotong_tanpa_kehilangan_orang(self):
        """
        Kelompok ke-9 dan seterusnya dijumlahkan ke "Lainnya"; totalnya
        tetap sama dengan headcount.
        """
        segments = manpower_services.MAX_CHART_SEGMENTS

        summary = self.summary()

        rows = list(summary.rows)

        extra = [
            manpower_services.ManpowerRow(
                employee_id=1000 + index,
                company_code="ZZZ",
                company=f"Company {index}",
                location_code="ZZZ",
                location=f"Location {index}",
                department_code="ZZZ",
                department=f"Department {index}",
                employee_group=f"Group {index}",
                employment_type="Permanent",
                contract_based=False,
            )
            for index in range(segments + 3)
        ]

        padded = manpower_services.ManpowerSummary(rows + extra)

        context = {"user": None, manpower_services.CONTEXT_KEY: padded}

        breakdown = ManpowerSummaryPresenter.location_breakdown(context)

        self.assertEqual(len(breakdown["categories"]), segments + 1)
        self.assertEqual(
            breakdown["categories"][-1],
            manpower_services.OTHER_LABEL,
        )
        self.assertEqual(
            sum(self.counts(breakdown).values()),
            padded.headcount,
        )


class SummaryTableTests(ManpowerSummaryTestCase):
    """Tabel agregat: satu baris per company → location → department."""

    def test_grouping_dan_urutannya(self):
        rows = self.table(self.context())["items"]

        self.assertEqual(
            [
                (row["company"], row["location"], row["department"])
                for row in rows
            ],
            [
                ("Manpower Satu", "Manpower Head Office", "Finance"),
                ("Manpower Satu", "Manpower Head Office", "Human Resources"),
                ("Manpower Satu", "Manpower Head Office", UNASSIGNED_LABEL),
                ("Manpower Satu", "Manpower Site", "Operations"),
                (
                    "Manpower Dua",
                    "Manpower Dua Head Office",
                    UNASSIGNED_LABEL,
                ),
            ],
        )

    def test_angka_per_baris(self):
        rows = {
            (row["company"], row["location"], row["department"]): row
            for row in self.table(self.context())["items"]
        }

        hrd = rows[
            ("Manpower Satu", "Manpower Head Office", "Human Resources")
        ]

        self.assertEqual(hrd["headcount"], 4)
        self.assertEqual(hrd["permanent"], 2)
        self.assertEqual(hrd["contract"], 1)
        self.assertEqual(hrd["unspecified"], 1)

        ops = rows[("Manpower Satu", "Manpower Site", "Operations")]

        self.assertEqual(ops["headcount"], 3)
        self.assertEqual(ops["permanent"], 1)
        self.assertEqual(ops["contract"], 2)

    def test_bukan_daftar_pegawai(self):
        """
        Sepuluh pegawai menghasilkan lima baris, dan tidak satu pun
        kolom identitas pegawai ikut — kalau berubah, laporan ini mulai
        menduplikasi Employee Master.
        """
        result = self.table(self.context())

        self.assertEqual(result["total"], 5)

        columns = {column["key"] for column in TABLE_WIDGET["columns"]}

        self.assertEqual(
            columns,
            {
                "company",
                "location",
                "department",
                "headcount",
                "permanent",
                "contract",
                "unspecified",
            },
        )

    def test_baris_total_menjumlahkan_pegawai_bukan_baris(self):
        result = self.table(self.context())

        self.assertEqual(
            result["totals"],
            {
                "headcount": 10,
                "permanent": 6,
                "contract": 3,
                "unspecified": 1,
            },
        )

    def test_headcount_baris_sama_dengan_jumlah_pegawainya(self):
        rows = self.table(self.context())["items"]

        self.assertEqual(
            sum(row["headcount"] for row in rows),
            self.summary().headcount,
        )

        for row in rows:
            self.assertEqual(
                row["permanent"] + row["contract"] + row["unspecified"],
                row["headcount"],
            )

    def test_id_baris_unik_walau_namanya_sama(self):
        """
        Dua department bernama sama di company berbeda tetap dua baris
        ber-`id` berbeda. Nama ambigu masih mungkin di master ini, dan
        dua baris ber-`id` sama membuat daftar ber-`:key` di frontend
        merender salah satunya dua kali.
        """
        rows = [
            manpower_services.ManpowerRow(
                employee_id=index,
                company_code=f"C{index}",
                company=f"Perusahaan {index}",
                location_code=f"L{index}",
                location="Head Office",
                department_code=f"D{index}",
                department="Human Resources",
                employee_group="Office Employee",
                employment_type="Permanent",
                contract_based=False,
            )
            for index in (1, 2)
        ]

        context = {
            "user": None,
            manpower_services.CONTEXT_KEY: (
                manpower_services.ManpowerSummary(rows)
            ),
        }

        items = ManpowerSummaryPresenter.manpower_table(context)["items"]

        self.assertEqual(len(items), 2)
        self.assertEqual(len({item["id"] for item in items}), 2)

    def test_kotak_cari_tidak_menggeser_total(self):
        context = self.context()

        result = self.table(context, search="Human Resources")

        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["matched"], 1)

        # `total` dan `totals` tetap seluruh laporan: kotak cari
        # menjawab "di mana barisnya", bukan "berapa seluruhnya".
        self.assertEqual(result["total"], 5)
        self.assertEqual(result["totals"]["headcount"], 10)

    def test_paginasi_dibatasi_page_size_options(self):
        result = self.table(self.context(), page_size="99999")

        self.assertEqual(result["page_size"], TABLE_WIDGET["page_size"])


class FilterTests(ManpowerSummaryTestCase):
    """
    Satu filter harus mempersempit **seluruh** laporan sekaligus. KPI
    yang tidak ikut tersaring adalah cara pembacanya membandingkan
    bagian dengan keseluruhan tanpa tahu ia sedang melakukannya.
    """

    def assert_consistent(self, context, *, headcount: int):
        """KPI, kelima chart, dan tabel harus menjumlahkan ke angka sama."""
        self.assertEqual(
            ManpowerSummaryPresenter.headcount(context)["value"],
            headcount,
        )

        for resolver in (
            ManpowerSummaryPresenter.company_breakdown,
            ManpowerSummaryPresenter.location_breakdown,
            ManpowerSummaryPresenter.department_breakdown,
        ):
            self.assertEqual(
                sum(self.counts(resolver(context)).values()),
                headcount,
                resolver.__name__,
            )

        for resolver in (
            ManpowerSummaryPresenter.employee_group_breakdown,
            ManpowerSummaryPresenter.employment_type_breakdown,
        ):
            self.assertEqual(
                resolver(context)["total"],
                headcount,
                resolver.__name__,
            )

        table = self.table(context)

        self.assertEqual(table["totals"]["headcount"], headcount)
        self.assertEqual(
            sum(row["headcount"] for row in table["items"]),
            headcount,
        )

    def test_filter_company(self):
        context = self.context(company=[self.other_company.id])

        self.assert_consistent(context, headcount=1)

        self.assertEqual(
            self.counts(
                ManpowerSummaryPresenter.company_breakdown(context)
            ),
            {"Manpower Dua": 1},
        )

    def test_filter_location(self):
        context = self.context(location=[self.site.id])

        self.assert_consistent(context, headcount=3)

        self.assertEqual(
            self.counts(
                ManpowerSummaryPresenter.location_breakdown(context)
            ),
            {"Manpower Site": 3},
        )

    def test_filter_department(self):
        context = self.context(department=[self.hrd.id])

        self.assert_consistent(context, headcount=4)

        self.assertEqual(
            self.counts(
                ManpowerSummaryPresenter.department_breakdown(context)
            ),
            {"Human Resources": 4},
        )

    def test_filter_section(self):
        self.assert_consistent(
            self.context(section=[self.hrd_section.id]),
            headcount=1,
        )

    def test_filter_employee_group(self):
        self.assert_consistent(
            self.context(employee_group=[self.field_group.id]),
            headcount=3,
        )

    def test_filter_employment_type(self):
        self.assert_consistent(
            self.context(employment_type=[self.permanent.id]),
            headcount=6,
        )

    def test_filter_employment_status(self):
        self.assert_consistent(
            self.context(employment_status=[self.probation_status.id]),
            headcount=1,
        )

    def test_filter_bercentang_banyak(self):
        self.assert_consistent(
            self.context(location=[self.ho.id, self.site.id]),
            headcount=9,
        )

    def test_tanpa_filter_berarti_seluruh_cakupan(self):
        self.assert_consistent(self.context(), headcount=10)


class OrganizationScopeTests(ManpowerSummaryTestCase):
    """
    `Population = Authorized Organization Scope ∩ filter`.

    Menyebut id di luar cakupan lewat query string tidak pernah
    menambah satu orang pun ke headcount.
    """

    def test_cakupan_satu_company(self):
        user = self.make_user(
            username="manpower.scope.company",
            companies=[self.company],
        )

        context = {"user": user}

        self.assertEqual(
            ManpowerSummaryPresenter.headcount(context)["value"],
            9,
        )

        self.assertEqual(
            self.counts(
                ManpowerSummaryPresenter.company_breakdown(context)
            ),
            {"Manpower Satu": 9},
        )

    def test_cakupan_satu_lokasi(self):
        user = self.make_user(
            username="manpower.scope.location",
            locations=[self.site],
        )

        self.assertEqual(
            ManpowerSummaryPresenter.headcount({"user": user})["value"],
            3,
        )

    def test_query_param_tidak_bisa_memperluas_cakupan(self):
        user = self.make_user(
            username="manpower.scope.bypass",
            companies=[self.company],
        )

        # Company lain disebut sendiri di query string.
        self.assertEqual(
            ManpowerSummaryPresenter.headcount(
                {"user": user, "company": [self.other_company.id]}
            )["value"],
            0,
        )

        # Disebut bersama company yang memang dicakupnya: yang di luar
        # cakupan tetap tidak ikut.
        self.assertEqual(
            ManpowerSummaryPresenter.headcount(
                {
                    "user": user,
                    "company": [self.company.id, self.other_company.id],
                }
            )["value"],
            9,
        )

        # Lokasi milik company lain, disebut langsung.
        self.assertEqual(
            ManpowerSummaryPresenter.headcount(
                {"user": user, "location": [self.other_ho.id]}
            )["value"],
            0,
        )

    def test_cakupan_membatasi_tabel_dan_chart_juga(self):
        """
        Cakupan bukan filter tabel — ia membatasi populasinya, jadi
        seluruh widget ikut menyusut bersamaan.
        """
        user = self.make_user(
            username="manpower.scope.widget",
            locations=[self.site],
        )

        context = {"user": user}

        table = self.table(context)

        self.assertEqual(table["totals"]["headcount"], 3)
        self.assertEqual(
            [row["location"] for row in table["items"]],
            ["Manpower Site"],
        )

        self.assertEqual(
            self.shares(
                ManpowerSummaryPresenter.employee_group_breakdown(context)
            ),
            {"Field Employee": 3},
        )


class FeatureApplicabilityTests(ManpowerSummaryTestCase):
    """
    **Feature Applicability tidak menyaring manpower.**

    Manpower adalah angka organisasi, bukan angka proses. Kalau test di
    berkas ini merah, kemungkinan besar ada yang menyalin
    `exclude_none_applicable` dari HR Period Summary ke sini — dan
    akibatnya headcount organisasi yang diam-diam lebih kecil daripada
    jumlah orang yang benar-benar bekerja.
    """

    def test_group_dengan_seluruh_applicability_mati_tetap_dihitung(self):
        self.assertIn("BOD001", self.numbers())

        self.assertEqual(
            self.shares(
                ManpowerSummaryPresenter.employee_group_breakdown(
                    self.context()
                )
            )["Dewan Direksi"],
            1,
        )

    def test_group_tanpa_attendance_dan_roster_tetap_dihitung(self):
        """
        Field Employee: attendance mati, roster menyala. Setengah
        applicability tidak boleh berarti setengah headcount.
        """
        self.assertEqual(
            ManpowerSummaryPresenter.headcount(
                self.context(employee_group=[self.field_group.id])
            )["value"],
            3,
        )

    def test_headcount_tidak_berubah_saat_applicability_diubah(self):
        """
        Kalau angkanya bergeser, ada resolver applicability yang
        dipanggil di jalur populasi.
        """
        before = self.summary().headcount

        group = EmployeeGroup.objects.get(pk=self.staff_group.pk)

        group.attendance_applicable = False
        group.leave_applicable = False
        group.roster_applicable = False
        group.save()

        try:
            after = ManpowerSummaryService.summary(self.context()).headcount

            self.assertEqual(after, before)
        finally:
            EmployeeGroup.objects.filter(pk=group.pk).update(
                attendance_applicable=True,
                leave_applicable=True,
                roster_applicable=True,
            )

    def test_tidak_ada_kode_employee_group_yang_di_hardcode(self):
        """
        Yang memutuskan komposisi cuma master. Kode group yang ditulis
        di laporan membuat tenant yang menamai group-nya sendiri
        kehilangan aturannya tanpa satu pun pesan.
        """
        module = Path(manpower_services.__file__).parent

        forbidden = ("BOARD", "BOD", "MANAGEMENT", "DIREKSI", "PKWT")

        for path in sorted(module.glob("*.py")):
            source = path.read_text()

            # Docstring dibuang dulu: penjelasan yang menyebut "BOARD"
            # sebagai contoh bukan aturan yang dieksekusi.
            code = "\n".join(
                line.split("#")[0]
                for line in source.splitlines()
            )

            for token in forbidden:
                self.assertNotIn(
                    f'"{token}"',
                    code,
                    f"{path.name} menyebut kode group {token}",
                )
                self.assertNotIn(f"'{token}'", code, path.name)

    def test_laporan_tidak_memanggil_resolver_applicability(self):
        source = Path(manpower_services.__file__).read_text()

        self.assertNotIn("applicability", source.replace("Applicability", ""))
        self.assertNotIn("exclude_none_applicable", source)


class PopulationConsistencyTests(ManpowerSummaryTestCase):
    """KPI, chart, dan tabel membaca hasil yang sama persis."""

    def test_satu_populasi_untuk_seluruh_widget(self):
        context = self.context()

        headcount = ManpowerSummaryPresenter.headcount(context)["value"]

        self.assertEqual(
            sum(
                self.counts(
                    ManpowerSummaryPresenter.company_breakdown(context)
                ).values()
            ),
            headcount,
        )
        self.assertEqual(
            ManpowerSummaryPresenter.employment_type_breakdown(context)[
                "total"
            ],
            headcount,
        )
        self.assertEqual(
            self.table(context)["totals"]["headcount"],
            headcount,
        )

    def test_dihitung_sekali_per_request(self):
        context = self.context()

        ManpowerSummaryService.summary(context)

        with CaptureQueriesContext(connection) as captured:
            ManpowerSummaryPresenter.headcount(context)
            ManpowerSummaryPresenter.company_breakdown(context)
            ManpowerSummaryPresenter.employment_type_breakdown(context)
            self.table(context)

        self.assertEqual(len(captured), 0)

    def test_satu_query_untuk_seluruh_populasi(self):
        context = self.context()

        with CaptureQueriesContext(connection) as captured:
            summary = ManpowerSummaryService.summary(context)

            for row in summary.rows:
                _ = (row.company, row.location, row.employee_group)

        self.assertEqual(summary.headcount, 10)
        self.assertEqual(len(captured), 1)


class SchemaTests(ManpowerSummaryTestCase):
    """Schema adalah kontrak layarnya."""

    def test_tanpa_filter_periode(self):
        types = {
            item.get("type")
            for item in HR_MANPOWER_SUMMARY_SCHEMA["filters"]
        }

        self.assertNotIn("period", types)

    def test_periode_tidak_ikut_terkirim_di_respons(self):
        """
        `get_period()` dikosongkan: rentang tanggal yang ikut terkirim
        untuk laporan yang tidak memakainya terbaca seperti konfigurasi
        hidup.
        """
        view = HRManpowerSummaryAPIView()

        self.assertEqual(view.get_period(request=None), {})

    def test_widget_lengkap_dan_punya_resolver(self):
        keys = [item["key"] for item in HR_MANPOWER_SUMMARY_SCHEMA["widgets"]]

        self.assertEqual(
            set(keys),
            {
                "headcount",
                "permanent",
                "contract",
                "unspecified_employment_type",
                "company_breakdown",
                "location_breakdown",
                "department_breakdown",
                "employee_group_breakdown",
                "employment_type_breakdown",
                "manpower_table",
            },
        )

        for key in keys:
            self.assertTrue(
                hasattr(HRManpowerSummaryAPIView, f"resolve_{key}"),
                f"widget '{key}' tidak punya resolver",
            )

    def test_filter_yang_dijanjikan_tersedia(self):
        keys = {
            item["key"] for item in HR_MANPOWER_SUMMARY_SCHEMA["filters"]
        }

        self.assertEqual(
            keys,
            {
                "company",
                "branch",
                "location",
                "department",
                "section",
                "employee_group",
                "employment_type",
                "employment_status",
            },
        )

        # Seluruh filter harus benar-benar dipakai menyaring populasi —
        # filter yang tampil tapi tidak menyaring adalah kontrol yang
        # berbohong.
        self.assertTrue(
            keys <= set(manpower_services.FILTER_PATHS),
        )

    def test_kartu_kpi_tanpa_tren(self):
        """
        Tidak ada periode berarti tidak ada periode pembanding; "naik
        0% dari bulan lalu" di bawah angka yang tidak dibandingkan cuma
        derau yang terbaca sebagai fakta.
        """
        for widget in HR_MANPOWER_SUMMARY_SCHEMA["widgets"]:
            if widget["type"] == "stat":
                self.assertFalse(widget.get("trend"), widget["key"])

    def test_endpoint_dan_module(self):
        self.assertEqual(
            HR_MANPOWER_SUMMARY_SCHEMA["endpoint"],
            "/api/reports/hr/manpower-summary/",
        )
        self.assertEqual(
            HR_MANPOWER_SUMMARY_SCHEMA["module"],
            "reports/hr/manpower-summary",
        )

    def test_read_only(self):
        """Tidak ada satu pun method tulis di view laporan."""
        for method in ("post", "put", "patch", "delete"):
            self.assertFalse(
                hasattr(HRManpowerSummaryAPIView, method),
                method,
            )

        self.assertNotIn("ServiceWriteMixin", Path(
            manpower_views.__file__
        ).read_text())
