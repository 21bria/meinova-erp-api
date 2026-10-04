"""
Contract Expiry — kontrak yang sudah atau akan habis.

Yang dijaga berkas ini adalah **invariant angkanya**, dan yang paling
mudah rusak diam-diam ada empat:

* populasi yang ditentukan **nama** jenis kepegawaian, bukan
  `requires_contract` — tenant yang menamai jenisnya sendiri kehilangan
  seluruh laporannya tanpa satu pun pesan;
* ambang bucket yang bergeser satu hari; 30/31 dan 90/91 adalah tepat
  batas yang menentukan surat perpanjangan dikirim minggu ini atau bulan
  depan;
* KPI, dua chart, dan tabel yang berangkat dari populasi berbeda —
  keempatnya tetap tampil, cuma tidak lagi menjumlahkan ke angka yang
  sama;
* kontrak tanpa tanggal akhir yang hilang diam-diam, padahal baris
  seperti itu justru yang paling perlu diperbaiki.

`TenantTestCase` django-tenants tidak memanggil rollback per-test dan
`setUpTestData` tidak pernah jalan, jadi seluruh panggung dibuat sekali
di `setUpClass` dan tidak ada test yang mengubahnya secara permanen —
pola yang sama dengan `test_manpower_summary.py`.

Seluruh tanggal kontrak panggung ditulis **relatif terhadap hari ini**
(`timezone.localdate()`), sama seperti laporannya menghitung. Tanggal
tetap akan membuat berkas ini lulus hari ini dan gagal besok.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
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
    ContractType,
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
    OrganizationAssignment,
)
from apps.reports.api.hr.contract_expiry import services as expiry_services
from apps.reports.api.hr.contract_expiry import views as expiry_views
from apps.reports.api.hr.contract_expiry.schema import (
    HR_CONTRACT_EXPIRY_SCHEMA,
    TABLE_WIDGET,
)
from apps.reports.api.hr.contract_expiry.services import (
    MAX_CHART_SEGMENTS,
    NO_END_LABEL,
    OTHER_LABEL,
    PAST_LABEL,
    UNASSIGNED_LABEL,
    ContractExpiryPresenter,
    ContractExpiryService,
    month_label,
)
from apps.reports.api.hr.contract_expiry.statuses import (
    EXPIRY_LABELS,
    EXPIRY_STATUS_OPTIONS,
    RENEWAL_STATUS_OPTIONS,
    ExpiryStatus,
    RenewalStatus,
    expiry_status,
    expiry_status_code,
    renewal_status_code,
)
from apps.reports.api.hr.contract_expiry.views import HRContractExpiryAPIView


User = get_user_model()

TODAY = timezone.localdate()


def code_only(source: str) -> str:
    """
    Buang komentar dan docstring, sisakan **kode**.

    Prosa harus boleh menyebut "PKWT" atau "Permanent" — justru di situ
    alasan kenapa nama itu tidak boleh dibaca kodenya dijelaskan. Yang
    dilarang adalah literalnya benar-benar dieksekusi. String biasa
    **tidak** dibuang: `if employment_type.code == "CONT"` harus tetap
    tertangkap.

    Bentuknya sama dengan `NoHardcodedContextTests.code_only` di
    `apps/hr/tests/attendance/test_attendance_import.py`.
    """
    import ast
    import io
    import tokenize

    tokens = [
        token
        for token in tokenize.generate_tokens(io.StringIO(source).readline)
        if token.type != tokenize.COMMENT
    ]

    lines = tokenize.untokenize(tokens).splitlines()

    for node in ast.walk(ast.parse("\n".join(lines))):
        if not isinstance(node, ast.Expr):
            continue

        if not isinstance(node.value, ast.Constant):
            continue

        if not isinstance(node.value.value, str):
            continue

        for index in range(node.lineno - 1, node.end_lineno):
            lines[index] = ""

    return "\n".join(lines)


class ContractExpiryTestCase(TenantTestCase):
    """
    Panggung: dua company, tiga lokasi, tiga department, dan pegawai
    yang **tiap bucket-nya diwakili tepat satu orang**, ditambah
    beberapa keadaan yang harus justru tidak muncul.

    Jenis kepegawaian berkontrak di sini sengaja **tidak** bernama
    "Contract": kalau ada satu baris di laporan yang menebak dari nama,
    panggung ini yang lebih dulu menjatuhkannya.
    """

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "reports-contract"
        tenant.name = "Reports Contract"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(code="CTE1", name="Kontrak Satu")
        cls.other_company = Company.objects.create(
            code="CTE2",
            name="Kontrak Dua",
        )

        cls.ho = Location.objects.create(
            company=cls.company,
            code="CTE-HO",
            name="Kontrak Head Office",
        )
        cls.site = Location.objects.create(
            company=cls.company,
            code="CTE-SITE",
            name="Kontrak Site",
        )
        cls.other_ho = Location.objects.create(
            company=cls.other_company,
            code="CTE2-HO",
            name="Kontrak Dua Head Office",
        )

        cls.hrd = Department.objects.create(
            company=cls.company,
            location=cls.ho,
            code="CTE-HRD",
            name="Human Resources",
        )
        cls.ops = Department.objects.create(
            company=cls.company,
            location=cls.site,
            code="CTE-OPS",
            name="Operations",
        )

        cls.hrd_section = Section.objects.create(
            company=cls.company,
            location=cls.ho,
            department=cls.hrd,
            code="CTE-HRD-GEN",
            name="HR General",
        )

        # Seluruh proses HR dimatikan — bentuk yang sama dengan group
        # direksi di tenant peragaan. Kodenya sengaja bukan BOARD/BOD:
        # kalau ada satu baris di laporan yang menebak dari kode, group
        # ini yang akan lolos dari tebakannya.
        cls.board_group = EmployeeGroup.objects.create(
            code="CTE-DEWAN",
            name="Dewan Direksi",
            attendance_applicable=False,
            leave_applicable=False,
            roster_applicable=False,
            shift_applicable=False,
            overtime_applicable=False,
            field_break_applicable=False,
        )
        cls.staff_group = EmployeeGroup.objects.create(
            code="CTE-STAFF",
            name="Office Employee",
        )

        cls.permanent = EmploymentType.objects.create(
            code="CTE-TETAP",
            name="Karyawan Tetap",
            requires_contract=False,
        )
        # Berkontrak, dan **namanya bukan** "Contract". Yang memutuskan
        # populasi laporan adalah `requires_contract`.
        cls.fixed_term = EmploymentType.objects.create(
            code="CTE-PROYEK",
            name="Kontrak Proyek",
            requires_contract=True,
        )
        cls.daily = EmploymentType.objects.create(
            code="CTE-HARIAN",
            name="Harian Lepas",
            requires_contract=True,
        )

        cls.active_status = EmploymentStatus.objects.create(
            code="CTE-ACTIVE",
            name="Active",
        )
        cls.probation_status = EmploymentStatus.objects.create(
            code="CTE-PROB",
            name="Probation",
        )

        cls.contract_type = ContractType.objects.create(
            code="CTE-TERM",
            name="Perjanjian Waktu Tertentu",
        )

        cls.manager = cls.make_employee(
            number="MGR001",
            department=cls.hrd,
            employment_type=cls.permanent,
            end_offset=None,
        )

        # --------------------------------------------------------------
        # Satu orang per bucket
        # --------------------------------------------------------------

        cls.long_expired = cls.make_employee(
            number="EXP001",
            department=cls.hrd,
            end_offset=-45,
        )
        cls.just_expired = cls.make_employee(
            number="EXP002",
            department=cls.ops,
            end_offset=-1,
        )
        cls.ends_today = cls.make_employee(
            number="D000",
            department=cls.ops,
            end_offset=0,
        )
        cls.day_30 = cls.make_employee(
            number="D030",
            department=cls.ops,
            end_offset=30,
        )
        cls.day_31 = cls.make_employee(
            number="D031",
            department=cls.hrd,
            end_offset=31,
        )
        cls.day_60 = cls.make_employee(
            number="D060",
            department=cls.hrd,
            end_offset=60,
        )
        cls.day_61 = cls.make_employee(
            number="D061",
            department=cls.ops,
            end_offset=61,
        )
        cls.day_90 = cls.make_employee(
            number="D090",
            department=cls.ops,
            end_offset=90,
        )
        cls.day_91 = cls.make_employee(
            number="D091",
            department=cls.hrd,
            end_offset=91,
        )

        # Kontrak tanpa tanggal akhir. `EmploymentAssignment.clean()`
        # menolaknya, tapi seed dan importer massal menulis lewat
        # `save()` — baris seperti ini ada di data hidup.
        cls.no_end = cls.make_employee(
            number="NOEND1",
            department=cls.hrd,
            end_offset=None,
            start_offset=-200,
            employment_type=cls.fixed_term,
        )

        # --------------------------------------------------------------
        # Yang justru tidak boleh muncul
        # --------------------------------------------------------------

        cls.permanent_employee = cls.make_employee(
            number="PRM001",
            department=cls.hrd,
            employment_type=cls.permanent,
            end_offset=None,
        )

        # Jenisnya menuntut kontrak, tapi kolom kontraknya sama sekali
        # kosong: kelengkapan master, bukan masa kontrak yang habis.
        cls.contract_without_record = cls.make_employee(
            number="KOSONG1",
            department=cls.hrd,
            employment_type=cls.fixed_term,
            end_offset=None,
        )

        cls.resigned = cls.make_employee(
            number="OUT001",
            department=cls.ops,
            end_offset=-3,
            is_active=False,
        )

        # --------------------------------------------------------------
        # Applicability & cakupan
        # --------------------------------------------------------------

        cls.director = cls.make_employee(
            number="BOD001",
            department=None,
            group=cls.board_group,
            end_offset=10,
        )

        cls.other = cls.make_employee(
            number="CO001",
            company=cls.other_company,
            location=cls.other_ho,
            department=None,
            end_offset=20,
        )

        cls.daily_worker = cls.make_employee(
            number="HRN001",
            department=cls.ops,
            employment_type=cls.daily,
            end_offset=5,
        )

        # --------------------------------------------------------------
        # Renewal
        # --------------------------------------------------------------

        cls.make_action(
            cls.just_expired,
            status=EmployeeActionStatus.SUBMITTED,
            document_number="EA-SUB-1",
        )
        cls.make_action(
            cls.day_30,
            status=EmployeeActionStatus.DRAFT,
            document_number="EA-DRF-1",
        )
        cls.make_action(
            cls.day_61,
            status=EmployeeActionStatus.APPROVED,
            document_number="EA-APR-1",
            action_type=EmployeeActionType.CONTRACT_CHANGE,
        )
        # Sudah diterapkan — bukan perpanjangan yang sedang berjalan.
        cls.make_action(
            cls.day_90,
            status=EmployeeActionStatus.APPLIED,
            document_number="EA-APL-1",
        )
        cls.make_action(
            cls.day_91,
            status=EmployeeActionStatus.REJECTED,
            document_number="EA-REJ-1",
        )

    # ------------------------------------------------------------------
    # Pabrik
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(
        cls,
        *,
        number: str,
        department,
        end_offset: int | None,
        start_offset: int = -365,
        employment_type=None,
        group=None,
        company=None,
        location=None,
        section=None,
        status=None,
        reports_to=None,
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
            location=location or (
                cls.ho if department is None else
                (cls.site if department == cls.ops else cls.ho)
            ),
            department=department,
            section=section,
            reports_to=reports_to or getattr(cls, "manager", None),
            organization_effective_date=TODAY - timedelta(days=400),
        )

        employment_type = employment_type or cls.fixed_term

        has_contract = end_offset is not None or (
            employment_type.requires_contract
            and number.startswith("NOEND")
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            employee_group=group or cls.staff_group,
            employment_type=employment_type,
            employment_status=status or cls.active_status,
            join_date=TODAY - timedelta(days=400),
            contract_type=cls.contract_type if has_contract else None,
            contract_start=(
                TODAY + timedelta(days=start_offset) if has_contract else None
            ),
            contract_end=(
                TODAY + timedelta(days=end_offset)
                if end_offset is not None
                else None
            ),
        )

        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def make_action(
        cls,
        employee,
        *,
        status,
        document_number,
        action_type=EmployeeActionType.CONTRACT_EXTENSION,
        effective_offset: int = 1,
    ) -> EmployeeAction:
        return EmployeeAction.objects.create(
            employee=employee,
            document_number=document_number,
            action_type=action_type,
            status=status,
            effective_date=TODAY + timedelta(days=effective_offset),
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
    def context(**filters) -> dict:
        return {"user": None, **filters}

    @classmethod
    def report(cls, **filters):
        return ContractExpiryService.report(cls.context(**filters))

    @classmethod
    def numbers(cls, **filters) -> list[str]:
        """Nomor pegawai yang masuk populasi laporan."""
        return sorted(row.employee_number for row in cls.report(**filters).rows)

    @staticmethod
    def bars(chart: dict) -> dict:
        """Chart batang → {kategori: nilai}."""
        data = chart["datasets"][0]["data"]

        return dict(zip(chart["categories"], data))

    @classmethod
    def table(cls, context, **params) -> dict:
        request = SimpleNamespace(query_params=params)

        return ContractExpiryPresenter.contract_table(
            context,
            page=TablePage.from_request(request, TABLE_WIDGET),
        )

    @classmethod
    def row_for(cls, number: str, **filters):
        for row in cls.report(**filters).rows:
            if row.employee_number == number:
                return row

        return None


# ======================================================================
# Populasi
# ======================================================================

class PopulationTests(ContractExpiryTestCase):
    """Siapa yang masuk laporan, dan atas dasar apa."""

    def test_pegawai_berkontrak_masuk(self):
        self.assertIn("D030", self.numbers())

    def test_jenis_berkontrak_yang_namanya_bukan_contract_tetap_masuk(self):
        """
        Yang memutuskan `requires_contract`, bukan nama master. Dua
        jenis berkontrak di panggung ini bernama "Kontrak Proyek" dan
        "Harian Lepas".
        """
        self.assertIn("HRN001", self.numbers())

        self.assertEqual(
            self.row_for("HRN001").employment_type,
            "Harian Lepas",
        )

    def test_pegawai_tetap_tidak_masuk(self):
        self.assertNotIn("PRM001", self.numbers())
        self.assertNotIn("MGR001", self.numbers())

    def test_jenis_berkontrak_tanpa_catatan_kontrak_tidak_masuk(self):
        """
        Jenisnya menuntut kontrak tapi kolom kontraknya kosong sama
        sekali: itu kelengkapan master, bukan masa kontrak yang habis.
        """
        self.assertNotIn("KOSONG1", self.numbers())

    def test_pegawai_nonaktif_tidak_masuk(self):
        self.assertNotIn("OUT001", self.numbers())

    def test_pegawai_terhapus_tidak_masuk(self):
        """Soft delete tidak boleh menyisakan baris di laporan."""
        employee = self.make_employee(
            number="TMP999",
            department=self.hrd,
            end_offset=15,
        )

        try:
            self.assertIn("TMP999", self.numbers())

            employee.is_deleted = True
            employee.save(update_fields=["is_deleted"])

            self.assertNotIn("TMP999", self.numbers())
        finally:
            Employee.objects.filter(pk=employee.pk).delete()

    def test_kontrak_tanpa_tanggal_akhir_tetap_masuk(self):
        """
        Ia tidak punya sisa hari, jadi tidak bisa masuk bucket mana pun
        — tapi menghilangkannya berarti satu-satunya layar yang bisa
        menemukannya justru yang menyembunyikannya.
        """
        row = self.row_for("NOEND1")

        self.assertIsNotNone(row)
        self.assertIsNone(row.contract_end)
        self.assertIsNone(row.days_remaining)
        self.assertEqual(row.expiry_status, ExpiryStatus.NO_END_DATE)

    def test_tanpa_filter_berarti_seluruh_cakupan(self):
        self.assertEqual(
            self.numbers(),
            [
                "BOD001", "CO001", "D000", "D030", "D031", "D060",
                "D061", "D090", "D091", "EXP001", "EXP002", "HRN001",
                "NOEND1",
            ],
        )


# ======================================================================
# Sisa hari & bucket
# ======================================================================

class DaysRemainingTests(ContractExpiryTestCase):
    """`contract_end - as_of`, dan ambang yang lahir darinya."""

    def test_sisa_hari_dihitung_dari_tanggal_acuan(self):
        self.assertEqual(self.row_for("D030").days_remaining, 30)
        self.assertEqual(self.row_for("EXP002").days_remaining, -1)

    def test_habis_hari_ini_nol_hari(self):
        row = self.row_for("D000")

        self.assertEqual(row.days_remaining, 0)
        self.assertEqual(row.expiry_status, ExpiryStatus.EXPIRING_30)

    def test_kontrak_lewat_berstatus_expired(self):
        self.assertEqual(
            self.row_for("EXP002").expiry_status,
            ExpiryStatus.EXPIRED,
        )
        self.assertEqual(
            self.row_for("EXP001").expiry_status,
            ExpiryStatus.EXPIRED,
        )

    def test_batas_30_dan_31(self):
        self.assertEqual(
            self.row_for("D030").expiry_status,
            ExpiryStatus.EXPIRING_30,
        )
        self.assertEqual(
            self.row_for("D031").expiry_status,
            ExpiryStatus.EXPIRING_60,
        )

    def test_batas_60_dan_61(self):
        self.assertEqual(
            self.row_for("D060").expiry_status,
            ExpiryStatus.EXPIRING_60,
        )
        self.assertEqual(
            self.row_for("D061").expiry_status,
            ExpiryStatus.EXPIRING_90,
        )

    def test_batas_90_dan_91(self):
        self.assertEqual(
            self.row_for("D090").expiry_status,
            ExpiryStatus.EXPIRING_90,
        )
        self.assertEqual(
            self.row_for("D091").expiry_status,
            ExpiryStatus.FUTURE,
        )

    def test_fungsi_ambang_murni(self):
        """
        Ambangnya diperiksa langsung juga, bukan cuma lewat panggung:
        yang tergeser satu hari di sini menggeser seluruh laporan.
        """
        cases = {
            -100: ExpiryStatus.EXPIRED,
            -1: ExpiryStatus.EXPIRED,
            0: ExpiryStatus.EXPIRING_30,
            30: ExpiryStatus.EXPIRING_30,
            31: ExpiryStatus.EXPIRING_60,
            60: ExpiryStatus.EXPIRING_60,
            61: ExpiryStatus.EXPIRING_90,
            90: ExpiryStatus.EXPIRING_90,
            91: ExpiryStatus.FUTURE,
            None: ExpiryStatus.NO_END_DATE,
        }

        for days, expected in cases.items():
            with self.subTest(days=days):
                self.assertEqual(expiry_status(days), expected)


# ======================================================================
# As-of
# ======================================================================

class AsOfTests(ContractExpiryTestCase):
    """Tanggal acuan: hari ini, dan tidak bisa digeser dari luar."""

    def test_bawaan_hari_ini(self):
        self.assertEqual(
            ContractExpiryService.as_of(self.context()),
            timezone.localdate(),
        )

    def test_tanpa_filter_periode_di_schema(self):
        self.assertEqual(
            [
                item["key"]
                for item in HR_CONTRACT_EXPIRY_SCHEMA["filters"]
                if item.get("type") == "period"
            ],
            [],
        )

    def test_periode_tidak_ikut_terkirim(self):
        view = HRContractExpiryAPIView()

        self.assertEqual(
            view.get_period(SimpleNamespace(query_params={})),
            {},
        )

    def test_query_param_as_of_tidak_menggeser_laporan(self):
        """
        `as_of` bukan filter yang dideklarasikan schema, jadi
        `get_context()` tidak pernah menyalinnya dari query string.
        """
        view = HRContractExpiryAPIView()

        request = SimpleNamespace(
            query_params=FakeParams({"as_of": "2020-01-01"}),
            user=None,
        )

        context = view.get_context(request)

        self.assertNotIn("as_of", context)
        self.assertEqual(
            ContractExpiryService.as_of(context),
            timezone.localdate(),
        )

    def test_pemanggil_internal_boleh_menentukan_tanggal_acuan(self):
        """
        Seam untuk test dan pemanggil internal — objek `date`, bukan
        teks dari query string.
        """
        future = TODAY + timedelta(days=95)

        context = self.context(as_of=future)

        rows = {
            row.employee_number: row.expiry_status
            for row in ContractExpiryService.report(context).rows
        }

        self.assertEqual(rows["D091"], ExpiryStatus.EXPIRED)
        self.assertEqual(rows["EXP002"], ExpiryStatus.EXPIRED)


class FakeParams(dict):
    """`QueryDict` seadanya — hanya `get` dan `getlist` yang dipakai."""

    def getlist(self, key):
        value = self.get(key)

        return [] if value is None else [value]


# ======================================================================
# KPI
# ======================================================================

class KPITests(ContractExpiryTestCase):
    """Lima kartu, dan invariant yang menghubungkannya."""

    def test_angka_tiap_bucket(self):
        context = self.context()

        self.assertEqual(ContractExpiryPresenter.expired(context)["value"], 2)
        # D000 (0), HRN001 (+5), BOD001 (+10), CO001 (+20), D030 (+30)
        self.assertEqual(
            ContractExpiryPresenter.expiring_30(context)["value"],
            5,
        )
        self.assertEqual(
            ContractExpiryPresenter.expiring_60(context)["value"],
            2,
        )
        self.assertEqual(
            ContractExpiryPresenter.expiring_90(context)["value"],
            2,
        )

    def test_total_kontrak_aktif_sama_dengan_populasi(self):
        context = self.context()

        self.assertEqual(
            ContractExpiryPresenter.active_contracts(context)["value"],
            len(self.report().rows),
        )

    def test_invariant_seluruh_bucket_menjumlah_ke_total(self):
        report = self.report()

        totals = report.status_totals()

        self.assertEqual(sum(totals.values()), report.total)

    def test_kpi_mengikuti_filter(self):
        context = self.context(department=[self.hrd.id])

        self.assertEqual(
            ContractExpiryPresenter.active_contracts(context)["value"],
            len(self.numbers(department=[self.hrd.id])),
        )


# ======================================================================
# Chart
# ======================================================================

class TimelineTests(ContractExpiryTestCase):
    """Chart utama: berapa kontrak berakhir bulan apa."""

    def test_batang_menjumlah_ke_total_kontrak_aktif(self):
        report = self.report()

        chart = ContractExpiryPresenter.expiry_timeline(self.context())

        self.assertEqual(
            sum(chart["datasets"][0]["data"]),
            report.total,
        )

    def test_bulan_berjalan_ikut_dan_diberi_label_bulan(self):
        chart = ContractExpiryPresenter.expiry_timeline(self.context())

        self.assertIn(month_label(TODAY), chart["categories"])

    def test_dua_belas_bulan_ke_depan(self):
        chart = ContractExpiryPresenter.expiry_timeline(self.context())

        first = TODAY.replace(day=1)

        for index in range(12):
            with self.subTest(index=index):
                self.assertIn(
                    month_label(expiry_services.add_months(first, index)),
                    chart["categories"],
                )

    def test_kontrak_bulan_lalu_masuk_ember_sudah_lewat(self):
        chart = self.bars(
            ContractExpiryPresenter.expiry_timeline(self.context())
        )

        past = sum(
            1
            for row in self.report().rows
            if row.contract_end and row.contract_end < TODAY.replace(day=1)
        )

        if past:
            self.assertEqual(chart[PAST_LABEL], past)
        else:
            self.assertNotIn(PAST_LABEL, chart)

    def test_kontrak_tanpa_tanggal_akhir_punya_ember_sendiri(self):
        chart = self.bars(
            ContractExpiryPresenter.expiry_timeline(self.context())
        )

        self.assertEqual(chart[NO_END_LABEL], 1)

    def test_ember_kosong_tidak_muncul(self):
        """
        `Sudah Lewat`, `> 12 Bulan`, dan `Tanpa Tanggal Akhir` cuma
        berdiri kalau ada isinya — legenda yang selalu nol cuma derau.
        """
        chart = self.bars(
            ContractExpiryPresenter.expiry_timeline(
                self.context(employee_group=[self.board_group.id])
            )
        )

        self.assertNotIn(PAST_LABEL, chart)
        self.assertNotIn(NO_END_LABEL, chart)

    def test_timeline_mengikuti_filter_dan_cakupan(self):
        user = self.make_user(
            username="expiry.timeline.scope",
            locations=[self.site],
        )

        context = {"user": user}

        self.assertEqual(
            sum(
                ContractExpiryPresenter.expiry_timeline(context)
                ["datasets"][0]["data"]
            ),
            ContractExpiryPresenter.active_contracts(context)["value"],
        )


class DepartmentChartTests(ContractExpiryTestCase):
    """Chart kedua: siapa yang harus menindaklanjuti berapa banyak."""

    def test_hanya_yang_perlu_ditindaklanjuti(self):
        chart = self.bars(
            ContractExpiryPresenter.expiring_by_department(self.context())
        )

        follow_up = len(self.report().follow_up_rows())

        self.assertEqual(sum(chart.values()), follow_up)

    def test_yang_lebih_dari_90_hari_tidak_ikut(self):
        report = self.report()

        follow_up = {row.employee_number for row in report.follow_up_rows()}

        self.assertNotIn("D091", follow_up)
        self.assertNotIn("NOEND1", follow_up)

    def test_terbanyak_lebih_dulu(self):
        chart = ContractExpiryPresenter.expiring_by_department(self.context())

        values = chart["datasets"][0]["data"]

        self.assertEqual(values, sorted(values, reverse=True))

    def test_department_kosong_tetap_disebut(self):
        """
        Direksi tanpa department tetap orang yang kontraknya habis;
        barisnya berdiri sebagai kelompok tersendiri, bukan hilang.
        """
        chart = self.bars(
            ContractExpiryPresenter.expiring_by_department(self.context())
        )

        self.assertIn(UNASSIGNED_LABEL, chart)

    def test_chart_mengikuti_filter(self):
        context = self.context(department=[self.ops.id])

        chart = self.bars(
            ContractExpiryPresenter.expiring_by_department(context)
        )

        self.assertEqual(list(chart), ["Operations"])

    def test_ekor_di_luar_delapan_besar_jadi_satu_kelompok(self):
        """
        Sepuluh department menghasilkan **sembilan** potongan: delapan
        terbesar apa adanya, sisanya satu "Lainnya".

        Yang dijaga bukan sekadar jumlah potongannya. Chart ini
        digambar sebagai donut, dan tiap potongan mengambil satu slot
        palet kategori — palet itu panjangnya nol koma sekian lebih
        dari sembilan, jadi ekor yang tidak dilipat akan memutar
        warnanya dan memberi dua department warna yang sama persis.
        Jumlahnya juga tetap harus sama dengan seluruh baris yang perlu
        ditindaklanjuti; ekor yang dipotong diam-diam terbaca sebagai
        chart yang lengkap.
        """
        extras = []

        for index in range(10):
            department = Department.objects.create(
                company=self.company,
                location=self.ho,
                code=f"CTE-EKOR-{index:02d}",
                name=f"Ekor {index:02d}",
            )
            extras.append(department)

            # Yang di depan sengaja lebih gemuk, supaya urutan
            # "terbanyak dulu" menentukan siapa yang masuk delapan
            # besar dan siapa yang jatuh ke ekor.
            for seat in range(10 - index):
                self.make_employee(
                    number=f"EKOR{index:02d}{seat:02d}",
                    department=department,
                    end_offset=10,
                )

        chart = ContractExpiryPresenter.expiring_by_department(self.context())
        categories = chart["categories"]
        values = chart["datasets"][0]["data"]

        self.assertEqual(len(categories), MAX_CHART_SEGMENTS + 1)
        self.assertEqual(categories[-1], OTHER_LABEL)
        self.assertEqual(len(set(categories)), len(categories))

        follow_up = len(self.report().follow_up_rows())
        self.assertEqual(sum(values), follow_up)

        # "Lainnya" adalah sisanya, bukan angka yang dikarang.
        self.assertEqual(values[-1], follow_up - sum(values[:-1]))

        Employee.objects.filter(employee_number__startswith="EKOR").delete()
        Department.objects.filter(code__startswith="CTE-EKOR-").delete()


# ======================================================================
# Tabel
# ======================================================================

class TableTests(ContractExpiryTestCase):
    """Daftar orang yang harus dihubungi, yang paling mendesak dulu."""

    def test_urutan_paling_mendesak_dulu(self):
        table = self.table(self.context(), page_size=100)

        numbers = [row["employee_number"] for row in table["items"]]

        self.assertEqual(
            numbers,
            [
                "EXP001", "EXP002", "D000", "HRN001", "BOD001", "CO001",
                "D030", "D031", "D060", "D061", "D090", "D091", "NOEND1",
            ],
        )

    def test_kontrak_tanpa_tanggal_akhir_paling_akhir(self):
        table = self.table(self.context(), page_size=100)

        self.assertEqual(table["items"][-1]["employee_number"], "NOEND1")

    def test_kolom_yang_dijanjikan_ada_isinya(self):
        table = self.table(self.context(), page_size=100)

        row = next(
            item for item in table["items"]
            if item["employee_number"] == "D030"
        )

        self.assertEqual(row["employee_name"], "Uji D030")
        self.assertEqual(row["company"], "Kontrak Satu")
        self.assertEqual(row["location"], "Kontrak Site")
        self.assertEqual(row["department"], "Operations")
        self.assertEqual(row["employee_group"], "Office Employee")
        self.assertEqual(row["employment_type"], "Kontrak Proyek")
        self.assertEqual(row["contract_type"], "Perjanjian Waktu Tertentu")
        self.assertEqual(
            row["contract_end"],
            (TODAY + timedelta(days=30)).isoformat(),
        )
        self.assertEqual(row["days_remaining"], 30)
        self.assertEqual(row["expiry_status"], EXPIRY_LABELS[
            ExpiryStatus.EXPIRING_30
        ])
        self.assertEqual(row["report_to_name"], "Uji MGR001")

    def test_sisa_hari_kosong_bukan_nol(self):
        """
        Nol hari berarti habis **hari ini**. Kolom angka yang menuliskan
        nol untuk "tidak diketahui" mengarang jawaban paling mendesak
        dari data yang tidak ada.
        """
        table = self.table(self.context(), page_size=100)

        row = next(
            item for item in table["items"]
            if item["employee_number"] == "NOEND1"
        )

        self.assertEqual(row["days_remaining"], "")
        self.assertEqual(row["contract_end"], "")

    def test_baris_total_menjumlahkan_bucket(self):
        table = self.table(self.context(), page_size=25)

        self.assertEqual(
            sum(table["totals"].values()),
            table["total"],
        )

    def test_kotak_cari_nomor_pegawai(self):
        table = self.table(self.context(), search="EXP00", page_size=100)

        self.assertEqual(
            sorted(row["employee_number"] for row in table["items"]),
            ["EXP001", "EXP002"],
        )

    def test_kotak_cari_nama_pegawai(self):
        table = self.table(self.context(), search="Uji D031", page_size=100)

        self.assertEqual(
            [row["employee_number"] for row in table["items"]],
            ["D031"],
        )

    def test_kotak_cari_tidak_menggeser_total(self):
        full = self.table(self.context(), page_size=100)
        searched = self.table(self.context(), search="EXP00", page_size=100)

        self.assertEqual(searched["total"], full["total"])
        self.assertEqual(searched["totals"], full["totals"])
        self.assertEqual(searched["matched"], 2)

    def test_paginasi_dibatasi_page_size_options(self):
        table = self.table(self.context(), page_size=99999)

        self.assertEqual(table["page_size"], 25)

    def test_id_baris_adalah_pegawainya(self):
        table = self.table(self.context(), page_size=100)

        ids = [row["id"] for row in table["items"]]

        self.assertEqual(len(ids), len(set(ids)))


# ======================================================================
# Renewal
# ======================================================================

class RenewalTests(ContractExpiryTestCase):
    """Dibacakan dari dokumen, tidak pernah disimpulkan."""

    def test_tanpa_dokumen_berarti_tidak_ada_catatan(self):
        row = self.row_for("D000")

        self.assertEqual(row.renewal_status, RenewalStatus.NONE)
        self.assertEqual(row.renewal_label, "No Renewal Record")
        self.assertEqual(row.renewal_document, "")

    def test_dokumen_menunggu_persetujuan(self):
        row = self.row_for("EXP002")

        self.assertEqual(row.renewal_status, RenewalStatus.SUBMITTED)
        self.assertEqual(row.renewal_document, "EA-SUB-1")

    def test_dokumen_draft(self):
        self.assertEqual(
            self.row_for("D030").renewal_status,
            RenewalStatus.DRAFT,
        )

    def test_contract_change_ikut_dibaca(self):
        """Perpanjangan bukan satu-satunya dokumen kontrak."""
        self.assertEqual(
            self.row_for("D061").renewal_status,
            RenewalStatus.APPROVED,
        )

    def test_dokumen_yang_sudah_diterapkan_bukan_renewal_berjalan(self):
        """
        `APPLIED` berarti tanggalnya sudah ikut berpindah — barisnya
        sendiri sudah berada di bucket yang lebih jauh. Menyebutnya
        "sudah diperpanjang" di baris yang masih mendesak adalah
        memberi tahu HR bahwa pekerjaan yang belum selesai sudah
        selesai.
        """
        self.assertEqual(
            self.row_for("D090").renewal_status,
            RenewalStatus.NONE,
        )

    def test_dokumen_ditolak_bukan_renewal_berjalan(self):
        self.assertEqual(
            self.row_for("D091").renewal_status,
            RenewalStatus.NONE,
        )

    def test_filter_renewal_status(self):
        code = next(
            option["id"]
            for option in RENEWAL_STATUS_OPTIONS
            if option["code"] == RenewalStatus.SUBMITTED
        )

        self.assertEqual(self.numbers(renewal_status=code), ["EXP002"])

    def test_filter_renewal_status_tanpa_catatan(self):
        code = next(
            option["id"]
            for option in RENEWAL_STATUS_OPTIONS
            if option["code"] == RenewalStatus.NONE
        )

        numbers = self.numbers(renewal_status=code)

        self.assertNotIn("EXP002", numbers)
        self.assertIn("D090", numbers)


# ======================================================================
# Filter
# ======================================================================

class FilterTests(ContractExpiryTestCase):
    """Filter hanya mempersempit; nilai asing tidak mematikan laporan."""

    def test_filter_company(self):
        self.assertEqual(
            self.numbers(company=[self.other_company.id]),
            ["CO001"],
        )

    def test_filter_location(self):
        numbers = self.numbers(location=[self.site.id])

        self.assertIn("D030", numbers)
        self.assertNotIn("D031", numbers)

    def test_filter_department(self):
        numbers = self.numbers(department=[self.hrd.id])

        self.assertIn("D031", numbers)
        self.assertNotIn("D030", numbers)

    def test_filter_section(self):
        self.assertEqual(self.numbers(section=[self.hrd_section.id]), [])

    def test_filter_employee_group(self):
        self.assertEqual(
            self.numbers(employee_group=[self.board_group.id]),
            ["BOD001"],
        )

    def test_filter_employment_type(self):
        self.assertEqual(
            self.numbers(employment_type=[self.daily.id]),
            ["HRN001"],
        )

    def test_filter_employment_status(self):
        self.assertEqual(
            self.numbers(employment_status=[self.active_status.id]),
            self.numbers(),
        )

    def test_filter_expiry_status(self):
        code = next(
            option["id"]
            for option in EXPIRY_STATUS_OPTIONS
            if option["code"] == ExpiryStatus.EXPIRED
        )

        self.assertEqual(
            self.numbers(expiry_status=code),
            ["EXP001", "EXP002"],
        )

    def test_filter_expiry_status_ikut_menggeser_kpi(self):
        """
        Filter laporan menyaring **populasi**, bukan cuma tabelnya.
        Kartu dan tabel di satu layar harus menghitung daftar yang sama.
        """
        code = next(
            option["id"]
            for option in EXPIRY_STATUS_OPTIONS
            if option["code"] == ExpiryStatus.EXPIRED
        )

        context = self.context(expiry_status=code)

        self.assertEqual(
            ContractExpiryPresenter.active_contracts(context)["value"],
            2,
        )
        self.assertEqual(
            ContractExpiryPresenter.expiring_30(context)["value"],
            0,
        )

    def test_nilai_filter_status_asing_diabaikan(self):
        self.assertIsNone(expiry_status_code("apa-saja"))
        self.assertIsNone(renewal_status_code(""))

        self.assertEqual(
            self.numbers(expiry_status="apa-saja"),
            self.numbers(),
        )

    def test_filter_bercentang_banyak(self):
        numbers = self.numbers(
            department=[self.hrd.id, self.ops.id],
        )

        self.assertIn("D030", numbers)
        self.assertIn("D031", numbers)


# ======================================================================
# Organization Scope
# ======================================================================

class OrganizationScopeTests(ContractExpiryTestCase):
    """
    Cakupan bukan filter — ia membatasi populasinya, dan tidak ada satu
    query param pun yang bisa melewatinya.
    """

    def test_cakupan_satu_company(self):
        user = self.make_user(
            username="expiry.scope.company",
            companies=[self.other_company],
        )

        self.assertEqual(
            sorted(
                row.employee_number
                for row in ContractExpiryService.report({"user": user}).rows
            ),
            ["CO001"],
        )

    def test_cakupan_satu_lokasi(self):
        user = self.make_user(
            username="expiry.scope.location",
            locations=[self.site],
        )

        numbers = sorted(
            row.employee_number
            for row in ContractExpiryService.report({"user": user}).rows
        )

        self.assertNotIn("CO001", numbers)
        self.assertNotIn("D031", numbers)
        self.assertIn("D030", numbers)

    def test_query_param_tidak_bisa_memperluas_cakupan(self):
        user = self.make_user(
            username="expiry.scope.bypass",
            companies=[self.company],
        )

        # Company lain disebut sendiri di query string.
        self.assertEqual(
            ContractExpiryPresenter.active_contracts(
                {"user": user, "company": [self.other_company.id]}
            )["value"],
            0,
        )

        # Disebut bersama company yang memang dicakupnya: yang di luar
        # cakupan tetap tidak ikut.
        both = ContractExpiryPresenter.active_contracts(
            {
                "user": user,
                "company": [self.company.id, self.other_company.id],
            }
        )["value"]

        self.assertEqual(both, len(self.numbers()) - 1)

        # Lokasi milik company lain, disebut langsung.
        self.assertEqual(
            ContractExpiryPresenter.active_contracts(
                {"user": user, "location": [self.other_ho.id]}
            )["value"],
            0,
        )

    def test_cakupan_membatasi_kpi_chart_dan_tabel_bersamaan(self):
        user = self.make_user(
            username="expiry.scope.widget",
            locations=[self.site],
        )

        context = {"user": user}

        table = self.table(context, page_size=100)

        total = ContractExpiryPresenter.active_contracts(context)["value"]

        self.assertEqual(table["total"], total)
        self.assertEqual(
            sum(
                ContractExpiryPresenter.expiry_timeline(context)
                ["datasets"][0]["data"]
            ),
            total,
        )
        self.assertEqual(
            {row["location"] for row in table["items"]},
            {"Kontrak Site"},
        )


# ======================================================================
# Feature Applicability
# ======================================================================

class FeatureApplicabilityTests(ContractExpiryTestCase):
    """
    **Feature Applicability tidak menyaring laporan ini.**

    Contract Expiry adalah laporan kepegawaian, bukan laporan proses.
    Direksi yang seluruh proses HR-nya dimatikan tetap orang yang
    kontraknya bisa habis — dan kontrak itu justru yang paling mahal
    kalau terlewat.
    """

    def test_group_dengan_seluruh_applicability_mati_tetap_muncul(self):
        self.assertIn("BOD001", self.numbers())

    def test_angka_tidak_berubah_saat_applicability_diubah(self):
        before = self.numbers()

        EmployeeGroup.objects.filter(pk=self.staff_group.pk).update(
            attendance_applicable=False,
            leave_applicable=False,
            roster_applicable=False,
        )

        try:
            self.assertEqual(self.numbers(), before)
        finally:
            EmployeeGroup.objects.filter(pk=self.staff_group.pk).update(
                attendance_applicable=True,
                leave_applicable=True,
                roster_applicable=True,
            )

    def test_laporan_tidak_memanggil_resolver_applicability(self):
        source = Path(expiry_services.__file__).read_text()

        self.assertNotIn("applicability", source.replace("Applicability", ""))
        self.assertNotIn("exclude_none_applicable", source)

    def test_tidak_ada_nama_atau_kode_master_yang_di_hardcode(self):
        """
        Yang memutuskan populasi cuma `requires_contract`. Nama atau
        kode jenis kepegawaian yang ditulis di laporan membuat tenant
        yang menamai masternya sendiri kehilangan aturannya tanpa satu
        pun pesan.
        """
        module = Path(expiry_services.__file__).parent

        forbidden = (
            "PKWT",
            "PKWTT",
            "CONT",
            "PERM",
            "Permanent",
            "Daily Worker",
            "Outsourcing",
            "BOARD",
            "BOD",
            "MANAGEMENT",
        )

        for path in sorted(module.glob("*.py")):
            code = code_only(path.read_text())

            for token in forbidden:
                with self.subTest(path=path.name, token=token):
                    self.assertNotIn(f'"{token}"', code)
                    self.assertNotIn(f"'{token}'", code)


# ======================================================================
# Konsistensi populasi
# ======================================================================

class PopulationConsistencyTests(ContractExpiryTestCase):
    """KPI, dua chart, dan tabel membaca hasil yang sama persis."""

    def test_satu_populasi_untuk_seluruh_widget(self):
        context = self.context(department=[self.ops.id])

        total = ContractExpiryPresenter.active_contracts(context)["value"]
        table = self.table(context, page_size=100)
        timeline = ContractExpiryPresenter.expiry_timeline(context)

        self.assertEqual(table["total"], total)
        self.assertEqual(sum(timeline["datasets"][0]["data"]), total)

        self.assertEqual(
            sum(
                ContractExpiryPresenter.expired(context)["value"]
                + ContractExpiryPresenter.expiring_30(context)["value"]
                + ContractExpiryPresenter.expiring_60(context)["value"]
                + ContractExpiryPresenter.expiring_90(context)["value"]
                for _ in [0]
            ),
            len(
                ContractExpiryService.report(context).follow_up_rows()
            ),
        )

    def test_dihitung_sekali_per_request(self):
        context = self.context()

        first = ContractExpiryService.report(context)
        second = ContractExpiryService.report(context)

        self.assertIs(first, second)

    def test_dua_query_untuk_seluruh_populasi(self):
        """
        Satu untuk pegawainya, satu untuk dokumen renewal-nya. Bukan
        satu per baris — halaman 25 baris yang menembak 26 query adalah
        laporan yang melambat sendiri begitu tenantnya tumbuh.
        """
        context = self.context()

        with CaptureQueriesContext(connection) as captured:
            ContractExpiryService.report(context)

        self.assertLessEqual(len(captured), 2)


# ======================================================================
# Schema & read-only
# ======================================================================

class SchemaTests(ContractExpiryTestCase):
    """Kontrak layar: widget, filter, endpoint, dan tidak adanya tulis."""

    def test_widget_lengkap_dan_punya_resolver(self):
        keys = [
            widget["key"] for widget in HR_CONTRACT_EXPIRY_SCHEMA["widgets"]
        ]

        self.assertEqual(
            keys,
            [
                "expired",
                "expiring_30",
                "expiring_60",
                "expiring_90",
                "active_contracts",
                "expiry_timeline",
                "expiring_by_department",
                "contract_table",
            ],
        )

        for key in keys:
            with self.subTest(key=key):
                self.assertTrue(
                    hasattr(HRContractExpiryAPIView, f"resolve_{key}"),
                    key,
                )

    def test_filter_yang_dijanjikan_tersedia(self):
        keys = {
            item["key"]: item
            for item in HR_CONTRACT_EXPIRY_SCHEMA["filters"]
        }

        self.assertEqual(
            set(keys),
            {
                "company",
                "branch",
                "location",
                "department",
                "section",
                "employee_group",
                "employment_type",
                "employment_status",
                "expiry_status",
                "renewal_status",
            },
        )

        for key in ("company", "location", "department"):
            self.assertEqual(keys[key]["placement"], "quick")

        for key in ("expiry_status", "renewal_status"):
            self.assertEqual(keys[key]["placement"], "advanced")

    def test_kolom_tabel_yang_dijanjikan(self):
        columns = [item["key"] for item in TABLE_WIDGET["columns"]]

        for key in (
            "employee_number",
            "employee_name",
            "company",
            "location",
            "department",
            "section",
            "position",
            "employee_group",
            "employment_type",
            "contract_start",
            "contract_end",
            "days_remaining",
            "expiry_status",
            "renewal_status",
            "report_to_name",
        ):
            with self.subTest(key=key):
                self.assertIn(key, columns)

    def test_kartu_kpi_tanpa_tren(self):
        for widget in HR_CONTRACT_EXPIRY_SCHEMA["widgets"]:
            if widget["type"] != "stat":
                continue

            with self.subTest(key=widget["key"]):
                self.assertFalse(widget.get("trend"))

    def test_endpoint_dan_module(self):
        self.assertEqual(
            HR_CONTRACT_EXPIRY_SCHEMA["endpoint"],
            "/api/reports/hr/contract-expiry/",
        )
        self.assertEqual(
            HR_CONTRACT_EXPIRY_SCHEMA["module"],
            "reports/hr/contract-expiry",
        )

    def test_read_only(self):
        """Tidak ada satu pun method tulis di view laporan."""
        for method in ("post", "put", "patch", "delete"):
            with self.subTest(method=method):
                self.assertFalse(
                    hasattr(HRContractExpiryAPIView, method),
                    method,
                )

        source = Path(expiry_views.__file__).read_text()

        self.assertNotIn("ServiceWriteMixin", source)

        service_source = Path(expiry_services.__file__).read_text()

        for token in (".save(", ".create(", ".update(", ".delete("):
            with self.subTest(token=token):
                self.assertNotIn(token, service_source)

    def test_dropdown_status_berid_angka(self):
        """
        `MLookupSelect` meng-`Number()` nilai filter satu-pilihan; id
        berupa teks mendarat sebagai `null` dan dropdown-nya terlihat
        kosong padahal isinya terkirim.
        """
        for option in (*EXPIRY_STATUS_OPTIONS, *RENEWAL_STATUS_OPTIONS):
            with self.subTest(option=option):
                self.assertIsInstance(option["id"], int)
                self.assertTrue(option["code"])
                self.assertTrue(option["name"])
