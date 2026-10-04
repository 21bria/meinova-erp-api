"""
Employee Reporting Audit — laporan master organisasi.

Yang dijaga berkas ini bukan angka melainkan **kelengkapan**: laporan
audit yang diam-diam menghilangkan barisnya sendiri lebih buruk
daripada laporan yang gagal, karena yang membacanya akan menyimpulkan
strukturnya sudah rapi. Empat baris yang paling mudah hilang, dan
masing-masing punya testnya sendiri:

* pegawai **tanpa akun** — justru temuan yang dicari
* pegawai **tanpa Report To** — direksi yang memang sah begitu
* pegawai yang **Feature Applicability-nya mati** — BOD, yang justru
  paling penting ikut diaudit
* pegawai di **luar cakupan** yang tidak boleh ikut, walau id-nya
  disebutkan sendiri di query string

`TenantTestCase` django-tenants tidak memanggil rollback per-test dan
`setUpTestData` tidak pernah jalan, jadi seluruh panggung dibuat sekali
di `setUpClass` dan tidak ada test yang mengubahnya — pola yang sama
dengan `apps/reports/tests/hr/base.py`.
"""

from __future__ import annotations

from datetime import date
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
    Position,
    Section,
)
from apps.administration.models.references.hr import (
    EmployeeGroup,
    EmploymentType,
)
from apps.framework.tables import TablePage
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    OrganizationAssignment,
)
from apps.reports.api.hr.employee_reporting_audit.schema import (
    HR_EMPLOYEE_REPORTING_AUDIT_SCHEMA,
    TABLE_WIDGET,
)
from apps.reports.api.hr.employee_reporting_audit.services import (
    EmployeeReportingAuditPresenter,
    EmployeeReportingAuditService,
    tenure_label,
)
from apps.reports.api.hr.employee_reporting_audit.statuses import (
    AccountStatus,
    ReportingStatus,
)


User = get_user_model()

JOIN_DATE = date(2020, 3, 10)


class EmployeeReportingAuditTestCase(TenantTestCase):
    """
    Panggung: dua company, tiga lokasi, dan enam pegawai yang
    masing-masing mewakili satu bentuk kelengkapan yang berbeda.
    """

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "reports-audit"
        tenant.name = "Reports Audit"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(code="AUD1", name="Audit Satu")
        cls.other_company = Company.objects.create(
            code="AUD2",
            name="Audit Dua",
        )

        cls.ho = Location.objects.create(
            company=cls.company,
            code="AUD-HO",
            name="Audit Head Office",
        )
        cls.site = Location.objects.create(
            company=cls.company,
            code="AUD-SITE",
            name="Audit Mine",
        )
        cls.other_ho = Location.objects.create(
            company=cls.other_company,
            code="AUD-HO",
            name="Audit Dua Head Office",
        )

        cls.department = Department.objects.create(
            company=cls.company,
            location=cls.ho,
            code="AUD-HRD",
            name="Human Resources",
        )
        cls.section = Section.objects.create(
            company=cls.company,
            location=cls.ho,
            department=cls.department,
            code="AUD-HRD-GEN",
            name="HR General",
        )
        cls.position = Position.objects.create(
            company=cls.company,
            location=cls.ho,
            department=cls.department,
            code="AUD-HRM",
            name="HR Manager",
        )

        # Seluruh proses HR dimatikan — bentuk yang sama dengan group
        # BOARD di tenant peragaan. Laporan ini **tetap** harus
        # menerbitkan barisnya.
        cls.board_group = EmployeeGroup.objects.create(
            code="AUD-BOARD",
            name="Board of Directors",
            attendance_applicable=False,
            leave_applicable=False,
            roster_applicable=False,
            shift_applicable=False,
            overtime_applicable=False,
            field_break_applicable=False,
        )

        cls.staff_group = EmployeeGroup.objects.create(
            code="AUD-STAFF",
            name="Office Employee",
        )

        cls.permanent = EmploymentType.objects.create(
            code="AUD-PERM",
            name="Permanent",
        )

        # ------------------------------------------------------------------
        # Pegawai
        # ------------------------------------------------------------------

        cls.director = cls.make_employee(
            number="BOD900",
            first_name="Wira",
            last_name="Direksi",
            location=cls.ho,
            group=cls.board_group,
            username="audit.bod",
        )

        cls.manager = cls.make_employee(
            number="HO900",
            first_name="Sari",
            last_name="Manajer",
            location=cls.ho,
            group=cls.staff_group,
            username="audit.manager",
            reports_to=cls.director,
            with_org_detail=True,
        )

        cls.staff = cls.make_employee(
            number="HO901",
            first_name="Bimo",
            last_name="Staf",
            location=cls.ho,
            group=cls.staff_group,
            username="audit.staff",
            reports_to=cls.manager,
        )

        # Tanpa akun sama sekali — dan atasannya punya akun, jadi kolom
        # "Report To Account" tetap terisi.
        cls.no_account = cls.make_employee(
            number="HO902",
            first_name="Tanpa",
            last_name="Akun",
            location=cls.ho,
            group=cls.staff_group,
            username=None,
            reports_to=cls.manager,
        )

        # Akun ada tapi dimatikan; atasannya justru yang tidak berakun.
        cls.inactive = cls.make_employee(
            number="SITE900",
            first_name="Nonaktif",
            last_name="Situs",
            location=cls.site,
            group=cls.staff_group,
            username="audit.inactive",
            account_active=False,
            reports_to=cls.no_account,
        )

        cls.other = cls.make_employee(
            number="CO900",
            first_name="Perusahaan",
            last_name="Lain",
            company=cls.other_company,
            location=cls.other_ho,
            group=cls.staff_group,
            username="audit.other",
        )

    # ------------------------------------------------------------------
    # Pabrik
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(
        cls,
        *,
        number: str,
        first_name: str,
        last_name: str,
        location,
        group,
        username: str | None,
        company=None,
        reports_to=None,
        account_active: bool = True,
        with_org_detail: bool = False,
        join_date: date = JOIN_DATE,
    ) -> Employee:
        user = None

        if username:
            user = User.objects.create_user(
                username=username,
                password="Uji#12345",
                email=f"{username}@contoh.test",
                is_active=account_active,
            )

        employee = Employee.objects.create(
            employee_number=number,
            first_name=first_name,
            last_name=last_name,
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=company or cls.company,
            location=location,
            department=cls.department if with_org_detail else None,
            section=cls.section if with_org_detail else None,
            position=cls.position if with_org_detail else None,
            reports_to=reports_to,
            organization_effective_date=date(2020, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            employee_group=group,
            employment_type=cls.permanent,
            join_date=join_date,
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
    def rows(cls, **filters) -> list:
        return EmployeeReportingAuditService.rows(cls.context(**filters))

    @classmethod
    def numbers(cls, **filters) -> list[str]:
        return [row.employee_number for row in cls.rows(**filters)]

    @classmethod
    def row_for(cls, employee, **filters):
        for row in cls.rows(**filters):
            if row.employee_id == employee.id:
                return row

        raise AssertionError(
            f"{employee.employee_number} tidak ada di hasil laporan.",
        )

    @staticmethod
    def table(context, **params) -> dict:
        request = SimpleNamespace(query_params=params)

        return EmployeeReportingAuditPresenter.employee_table(
            context,
            page=TablePage.from_request(request, TABLE_WIDGET),
        )


class IdentityAndOrganizationTests(EmployeeReportingAuditTestCase):
    """Kolom identitas dan penempatan — sumbernya master, bukan tebakan."""

    def test_employee_id_dan_nama_tampil(self):
        row = self.row_for(self.manager)

        self.assertEqual(row.employee_number, "HO900")
        self.assertEqual(row.employee_name, "Sari Manajer")

    def test_penempatan_mengikuti_organization_assignment(self):
        row = self.row_for(self.manager)

        self.assertEqual(row.company, "Audit Satu")
        self.assertEqual(row.location, "Audit Head Office")
        self.assertEqual(row.department, "Human Resources")
        self.assertEqual(row.section, "HR General")
        self.assertEqual(row.position, "HR Manager")

    def test_penempatan_kosong_tidak_diam_diam_jadi_string_kosong(self):
        """
        Kolom yang memang belum diisi harus **berbunyi** sebagai belum
        diisi. Sel kosong di tengah tabel audit terbaca seperti
        kolomnya gagal dimuat.
        """
        row = self.row_for(self.staff)

        self.assertEqual(row.department, "Belum Ditentukan")
        self.assertEqual(row.section, "Belum Ditentukan")

    def test_employee_group_dan_employment_type_dari_employment(self):
        row = self.row_for(self.manager)

        self.assertEqual(row.employee_group, "Office Employee")
        self.assertEqual(row.employment_type, "Permanent")
        self.assertEqual(row.join_date, JOIN_DATE)

    def test_masa_kerja_dihitung_bukan_disimpan(self):
        self.assertEqual(
            tenure_label(date(2020, 3, 10), date(2026, 8, 23)),
            "6 th 5 bl",
        )
        self.assertEqual(
            tenure_label(date(2026, 8, 1), date(2026, 8, 23)),
            "0 th 0 bl",
        )

    def test_masa_kerja_kosong_untuk_yang_belum_bergabung(self):
        """Nol bulan kerja untuk yang belum masuk adalah jawaban salah."""
        self.assertEqual(
            tenure_label(date(2027, 1, 1), date(2026, 8, 23)),
            "",
        )
        self.assertEqual(tenure_label(None, date(2026, 8, 23)), "")


class ReportingLineTests(EmployeeReportingAuditTestCase):
    """Report To datang dari `OrganizationAssignment.reports_to`, titik."""

    def test_report_to_id_dan_nama_mengikuti_relasi_master(self):
        row = self.row_for(self.staff)

        self.assertEqual(row.report_to_number, "HO900")
        self.assertEqual(row.report_to_name, "Sari Manajer")
        self.assertEqual(row.reporting_status, ReportingStatus.HAS)

    def test_tanpa_report_to_tetap_tampil(self):
        row = self.row_for(self.director)

        self.assertEqual(row.report_to_number, "")
        self.assertEqual(row.report_to_name, "")
        self.assertEqual(row.reporting_status, ReportingStatus.NONE)

    def test_filter_reporting_status_hanya_mempersempit(self):
        without = self.numbers(reporting_status="2")
        with_line = self.numbers(reporting_status="1")

        self.assertIn("BOD900", without)
        self.assertNotIn("HO900", without)

        self.assertIn("HO900", with_line)
        self.assertNotIn("BOD900", with_line)

        self.assertEqual(
            sorted(without + with_line),
            sorted(self.numbers()),
        )

    def test_reporting_status_tidak_dikenal_diabaikan(self):
        """Satu query param salah ketik tidak menyaring apa pun."""
        self.assertEqual(
            self.numbers(reporting_status="nonsense"),
            self.numbers(),
        )


class AccountTests(EmployeeReportingAuditTestCase):
    """Akun dan emailnya — `Employee.user`, dan atasannya `reports_to.user`."""

    def test_akun_employee_dan_emailnya(self):
        row = self.row_for(self.manager)

        self.assertEqual(row.account, "audit.manager")
        self.assertEqual(row.account_email, "audit.manager@contoh.test")
        self.assertEqual(row.account_status, AccountStatus.CONNECTED)

    def test_akun_atasan_berasal_dari_reports_to(self):
        row = self.row_for(self.staff)

        self.assertEqual(row.report_account, "audit.manager")
        self.assertEqual(
            row.report_account_email,
            "audit.manager@contoh.test",
        )

    def test_tanpa_akun_tetap_tampil_dengan_sel_kosong(self):
        row = self.row_for(self.no_account)

        self.assertEqual(row.account, "")
        self.assertEqual(row.account_email, "")
        self.assertEqual(row.account_status, AccountStatus.NO_ACCOUNT)

        # Barisnya tetap terbit, dan atasannya tetap terbaca.
        self.assertEqual(row.report_to_number, "HO900")

    def test_akun_dimatikan_dibedakan_dari_tidak_punya_akun(self):
        row = self.row_for(self.inactive)

        self.assertEqual(row.account, "audit.inactive")
        self.assertEqual(row.account_status, AccountStatus.INACTIVE)

    def test_atasan_tanpa_akun_menyisakan_kolom_akun_atasan_kosong(self):
        row = self.row_for(self.inactive)

        self.assertEqual(row.report_to_number, "HO902")
        self.assertEqual(row.report_account, "")
        self.assertEqual(row.report_account_email, "")


class ApplicabilityTests(EmployeeReportingAuditTestCase):
    """
    Feature Applicability **tidak** menyaring laporan audit ini.

    Kalau ia ikut, lubang di garis pelaporan justru paling mungkin
    tersembunyi tepat di puncak struktur — tempat yang paling perlu
    diaudit.
    """

    def test_bod_tetap_muncul_walau_seluruh_prosesnya_dimatikan(self):
        self.assertFalse(self.board_group.attendance_applicable)
        self.assertFalse(self.board_group.leave_applicable)

        self.assertIn("BOD900", self.numbers())

    def test_filter_employee_group_tetap_bisa_memilih_group_bod(self):
        self.assertEqual(
            self.numbers(employee_group=[self.board_group.id]),
            ["BOD900"],
        )


class SearchTests(EmployeeReportingAuditTestCase):
    """Kotak cari menyaring tabelnya, bukan populasinya."""

    def matched(self, search: str) -> list[str]:
        result = self.table(self.context(), search=search)

        return [item["employee_number"] for item in result["items"]]

    def test_cari_nomor_pegawai(self):
        self.assertEqual(self.matched("HO901"), ["HO901"])

    def test_cari_nama_pegawai(self):
        # Nama yang tidak dipakai siapa pun sebagai atasan — kalau tidak,
        # yang terjaring ikut para bawahannya, dan itu perilaku yang
        # berbeda (diuji tersendiri di bawah).
        self.assertEqual(self.matched("Bimo Staf"), ["HO901"])

    def test_cari_atasan_mengembalikan_bawahannya(self):
        """
        Mengetik nama atasan menjawab "siapa saja yang melapor padanya",
        dan barisnya sendiri ikut karena namanya juga ada di sana.

        Itu memang yang dicari pengaudit: nomor atau nama satu orang
        menghasilkan seluruh cabang di sekitarnya, bukan satu baris yang
        harus ditelusuri manual ke atas dan ke bawah.
        """
        self.assertEqual(
            sorted(self.matched("Sari Manajer")),
            ["HO900", "HO901", "HO902"],
        )

        self.assertEqual(
            sorted(self.matched("HO900")),
            ["HO900", "HO901", "HO902"],
        )

    def test_cari_akun_dan_email(self):
        self.assertEqual(self.matched("audit.staff"), ["HO901"])
        self.assertEqual(
            self.matched("audit.staff@contoh.test"),
            ["HO901"],
        )

    def test_total_tidak_ikut_menyusut_saat_mencari(self):
        """
        `total` menjawab "berapa seluruhnya pada filter ini", `matched`
        menjawab "berapa yang cocok dengan yang diketik". Menyamakan
        keduanya menghapus satu-satunya petunjuk bahwa laporan
        mencakup lebih banyak orang daripada yang terlihat.
        """
        result = self.table(self.context(), search="HO901")

        self.assertEqual(result["matched"], 1)
        self.assertEqual(result["total"], 6)


class FilterTests(EmployeeReportingAuditTestCase):
    """Filter dropdown hanya mempersempit."""

    def test_filter_company_bercentang_banyak(self):
        self.assertEqual(
            self.numbers(company=[self.company.id]),
            ["BOD900", "HO900", "HO901", "HO902", "SITE900"],
        )

        self.assertEqual(
            self.numbers(company=[self.other_company.id]),
            ["CO900"],
        )

        self.assertEqual(
            len(self.numbers(company=[self.company.id, self.other_company.id])),
            6,
        )

    def test_filter_location(self):
        self.assertEqual(
            self.numbers(location=[self.site.id]),
            ["SITE900"],
        )

    def test_filter_department_dan_section(self):
        self.assertEqual(
            self.numbers(department=[self.department.id]),
            ["HO900"],
        )
        self.assertEqual(
            self.numbers(section=[self.section.id]),
            ["HO900"],
        )

    def test_filter_employee(self):
        self.assertEqual(self.numbers(employee=self.staff.id), ["HO901"])

    def test_tanpa_filter_berarti_seluruh_cakupan(self):
        self.assertEqual(len(self.numbers()), 6)


class OrganizationScopeTests(EmployeeReportingAuditTestCase):
    """
    `Result = Authorized Organization Scope ∩ filter`.

    Menyebut id di luar cakupan lewat query string tidak pernah membuka
    satu baris pun — dan itu satu-satunya penjagaan yang benar-benar
    menyembunyikan baris di laporan ini.
    """

    def counted(self, user, **filters) -> list[str]:
        context = {"user": user, **filters}

        return [
            row.employee_number
            for row in EmployeeReportingAuditService.rows(context)
        ]

    def test_cakupan_satu_company(self):
        user = self.make_user(
            username="audit.scope.satu",
            companies=[self.company],
        )

        self.assertEqual(
            self.counted(user),
            ["BOD900", "HO900", "HO901", "HO902", "SITE900"],
        )

    def test_query_param_tidak_bisa_melewati_cakupan(self):
        user = self.make_user(
            username="audit.scope.bypass",
            companies=[self.company],
        )

        # Company lain disebut sendiri di query string.
        self.assertEqual(
            self.counted(user, company=[self.other_company.id]),
            [],
        )

        # Disebut bersama company yang memang dicakupnya: yang di luar
        # cakupan tetap tidak ikut.
        self.assertEqual(
            len(self.counted(
                user,
                company=[self.company.id, self.other_company.id],
            )),
            5,
        )

        self.assertEqual(
            self.counted(user, location=[self.other_ho.id]),
            [],
        )

    def test_cakupan_site_hanya_melihat_lokasinya(self):
        user = self.make_user(
            username="audit.scope.site",
            locations=[self.site],
        )

        self.assertEqual(self.counted(user), ["SITE900"])

        # Menyebut lokasi lain tidak menambah satu baris pun.
        self.assertEqual(self.counted(user, location=[self.ho.id]), [])


class QueryBudgetTests(EmployeeReportingAuditTestCase):
    """
    Akun, atasan, dan email atasan diambil lewat `select_related`.

    Tanpa itu satu halaman berisi 25 baris menembak ratusan query, dan
    yang paling mahal justru akun atasan — dua lompatan relasi yang
    tidak akan pernah di-prefetch sendiri oleh Django.
    """

    def test_tidak_ada_n_plus_1(self):
        context = self.context()

        with CaptureQueriesContext(connection) as captured:
            rows = EmployeeReportingAuditService.rows(context)

            # Kolom yang paling mudah jadi N+1 disentuh semuanya.
            for row in rows:
                _ = (
                    row.account,
                    row.account_email,
                    row.report_to_name,
                    row.report_account,
                    row.report_account_email,
                )

        self.assertEqual(len(rows), 6)
        self.assertEqual(len(captured), 1)

    def test_dihitung_sekali_per_request(self):
        context = self.context()

        EmployeeReportingAuditService.rows(context)

        with CaptureQueriesContext(connection) as captured:
            EmployeeReportingAuditService.rows(context)

        self.assertEqual(len(captured), 0)


class SchemaTests(EmployeeReportingAuditTestCase):
    """Schema adalah kontrak layarnya; tiga hal yang tidak boleh hilang."""

    def test_tanpa_filter_periode(self):
        types = {
            item.get("type")
            for item in HR_EMPLOYEE_REPORTING_AUDIT_SCHEMA["filters"]
        }

        self.assertNotIn("period", types)

    def test_hanya_satu_widget_tabel(self):
        widgets = HR_EMPLOYEE_REPORTING_AUDIT_SCHEMA["widgets"]

        self.assertEqual(len(widgets), 1)
        self.assertEqual(widgets[0]["type"], "table")

    def test_kolom_lengkap_dan_berlabel_manusiawi(self):
        columns = {
            item["key"]: item["label"]
            for item in TABLE_WIDGET["columns"]
        }

        self.assertEqual(
            list(columns),
            [
                "employee_number",
                "employee_name",
                "company",
                "location",
                "department",
                "section",
                "position",
                "employee_group",
                "employment_type",
                "join_date",
                "tenure",
                "report_to_number",
                "report_to_name",
                "account",
                "account_email",
                "report_account",
                "report_account_email",
                "account_status",
                "reporting_status",
            ],
        )

        # Singkatan terminal (`ACC`, `RPT`, `STATUS`) tidak ikut ke layar.
        self.assertEqual(columns["account_status"], "Account Status")
        self.assertEqual(columns["report_account"], "Report To Account")
        self.assertEqual(columns["reporting_status"], "Reporting Status")

    def test_baris_tabel_memuat_seluruh_kolom_schema(self):
        row = EmployeeReportingAuditPresenter.table_row(
            self.row_for(self.manager),
        )

        for item in TABLE_WIDGET["columns"]:
            self.assertIn(item["key"], row)


class PaginationTests(EmployeeReportingAuditTestCase):
    """Paginasi memakai `TablePage` yang sama dengan laporan lain."""

    def test_halaman_pertama_dibatasi_page_size(self):
        result = self.table(self.context(), page=1, page_size=25)

        self.assertEqual(result["page"], 1)
        self.assertEqual(result["page_size"], 25)
        self.assertEqual(result["total"], 6)
        self.assertEqual(len(result["items"]), 6)

    def test_page_size_di_luar_daftar_jatuh_ke_bawaan(self):
        result = self.table(self.context(), page_size=99999)

        self.assertEqual(result["page_size"], 25)

    def test_tidak_ada_baris_total(self):
        """Menjumlahkan nomor pegawai tidak berarti apa pun."""
        self.assertNotIn("totals", self.table(self.context()))
