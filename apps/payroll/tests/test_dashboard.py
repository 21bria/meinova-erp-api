"""
Payroll Dashboard — pusat kendali operasional.

Yang diuji di sini **bukan** perhitungan payroll. Tidak ada satu
assertion pun yang menegaskan berapa gaji seseorang seharusnya; itu
pekerjaan `test_proration`, `test_attendance_deduction`, `test_overtime`,
dan `test_payroll_policy`, dan dashboard tidak boleh punya pendapat
sendiri tentangnya.

Yang diuji cuma empat janji layar ini:

1. **Angkanya milik run, bukan milik dashboard.** Total di kartu selalu
   sama dengan jumlah baris `PayrollRunEmployee` yang ditampilkan
   tabelnya, dan run yang sudah Finalized tidak bergerak sesudah master
   berubah.
2. **Cakupan datanya benar.** Yang cuma boleh melihat satu perusahaan
   tidak menemukan perusahaan lain di KPI, tabel, chart, rincian,
   maupun jumlah temuan.
3. **Harian dan bulanan berdampingan.** Dasar upah pegawai harian yang
   tampil adalah upah yang benar-benar terbentuk, bukan gaji sebulan
   yang tidak pernah dipakai menghitung apa pun.
4. **Kosong tetap terbaca.** Tidak ada periode, tidak ada run, run
   belum dihitung — ketiganya menghasilkan bentuk data yang sah, bukan
   pengecualian.

Fixture-nya dipakai ulang dari `test_payroll_policy` supaya keadaan
awalnya persis sama dengan seluruh test payroll lainnya — termasuk
pabrik pegawai hariannya.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Sum

from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.accounts.models import (
    AuthorityMode,
    Role,
)
from apps.accounts.services.role_assignment import grant_role

from .access_helpers import grant_payroll_read
from apps.administration.models import Company, Department, Location
from apps.hr.models import (
    Employee,
    EmployeeOvertime,
    EmploymentAssignment,
    OrganizationAssignment,
    PayrollAssignment,
)
from apps.hr.models.overtime import OvertimeStatus
from apps.payroll.api.dashboard.services import (
    COMPANY_DEFAULT_LABEL,
    UNASSIGNED_LABEL,
    PayrollDashboardService,
)
from apps.payroll.api.dashboard.views import PayrollDashboardAPIView
from apps.payroll.models import (
    PayrollComponentSource,
    PayrollPeriod,
    PayrollRunComponent,
    PayrollRunEmployee,
    PayrollRunEmployeeStatus,
    PayrollRunStatus,
)
from apps.payroll.services import PayrollRunService

from .test_payroll_policy import PolicyTestCase


User = get_user_model()


class DashboardTestCase(PolicyTestCase):
    """
    Panggung yang sama dengan test payroll lain, plus dua alat.

    `context()` merakit konteks lewat view yang sebenarnya, bukan
    dengan menyusun dict sendiri: pembacaan query string, pemisahan
    filter bercentang banyak, dan pengosongan periode tanggal semuanya
    milik `BaseDashboardAPIView`, dan test yang melewatinya akan tetap
    hijau saat bagian itu yang rusak.
    """

    factory = APIRequestFactory()

    # ------------------------------------------------------------------
    # Alat
    # ------------------------------------------------------------------

    def context(self, user=None, **params) -> dict:
        request = Request(
            self.factory.get("/api/payroll/dashboard/", params),
        )
        request.user = user or self.open_user()

        view = PayrollDashboardAPIView()
        view.request = request

        return view.get_context(request)

    def widget(self, key: str, context: dict):
        """Satu widget, lewat jalur resolver yang dipakai HTTP."""
        view = PayrollDashboardAPIView()
        view.request = context["request"]

        declared = next(
            item
            for item in view.get_widgets()
            if item.get("key") == key
        )

        return view.resolve_widget(declared, context)

    def render(self, context: dict) -> dict:
        """
        Seluruh widget sekaligus — bentuk yang benar-benar dikirim ke
        layar. Dipakai test empty state: yang dicari di sana bukan satu
        angka melainkan bahwa **tidak satu pun** widget meledak.
        """
        view = PayrollDashboardAPIView()
        view.request = context["request"]

        return {
            item["key"]: view.resolve_widget(item, context)
            for item in view.get_widgets()
        }

    def rows_of(self, data, key: str) -> dict:
        """Baris tabel/daftar di-key kolom identitasnya."""
        return {row[key]: row for row in data["items"]}

    def open_user(self):
        """
        Akun tanpa batasan cakupan, dipakai kalau test tidak menyebut
        siapa yang membuka layarnya.

        **Bukan `None`.** Dua lapis cakupan mengartikan `None` secara
        berlawanan: `DataScopeService` memperlakukannya sebagai tanpa
        batas, sementara `EmployeeDataVisibility.visible_employees_q`
        mengembalikan `Q(pk__in=[])` — tidak seorang pun. Test yang
        melewatkan `None` karena itu membaca dashboard yang seluruh
        angkanya nol dan menyalahkan kode yang benar.

        Di produksi keadaan itu tidak ada: view-nya `IsAuthenticated`,
        jadi `request.user` selalu akun sungguhan.

        **Bukan lagi akun tanpa role.** Sampai Stage 3B, akun tanpa role
        berarti tanpa batasan — dan itu yang dipakai di sini. Sejak
        dashboard menghitung cakupannya per izin, akun tanpa role tidak
        memegang izin payroll apa pun, jadi ia membaca nol baris: benar
        sebagai keamanan, dan tidak menguji apa pun sebagai fixture. Di
        tenant sungguhan keadaan itu tidak ada — setiap akun memegang
        setidaknya role EMPLOYEE, dan meja payroll memegang izin baca
        payroll.

        Yang dipakai sekarang akun ber-role **tanpa baris cakupan**:
        tanpa batasan organisasi, dengan izin payroll yang memang
        dipegang meja payroll di produksi.
        """
        cached = getattr(type(self), "_open_user", None)

        if cached is not None:
            return cached

        user = self.make_user(username="dashboard-open")

        type(self)._open_user = user

        return user

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    def isolate(self, run, *keep):
        """
        Mengeluarkan semua pegawai kecuali yang disebut, lalu
        memvalidasi ulang.

        `TenantTestCase` tidak me-rollback antar test, jadi run
        berikutnya menarik **seluruh** pegawai yang pernah dibuat kelas
        ini — dan test yang menghitung "berapa pegawai yang kekurangan
        X" ikut menghitung pegawai milik test sebelumnya. Yang
        dikembalikan ke keadaan semula bukan datanya melainkan
        lingkupnya.
        """
        keep_ids = [employee.pk for employee in keep]

        PayrollRunEmployee.objects.filter(run=run).exclude(
            employee_id__in=keep_ids,
        ).update(
            is_excluded=True,
            status=PayrollRunEmployeeStatus.EXCLUDED,
            exclusion_reason="Di luar lingkup test.",
        )

        PayrollRunService._refresh_totals(run=run)
        PayrollRunService.validate(run=run)

        run.refresh_from_db()

        return run

    def add_overtime(self, employee, *, period, day, minutes):
        """
        Satu lembur yang **sah menurut modul sumbernya** — disetujui
        dan dibayar. Payroll memang cuma mengonsumsi yang begitu, dan
        test yang membuat lembur mentah tidak akan menghasilkan satu
        rupiah pun.
        """
        return EmployeeOvertime.objects.create(
            employee=employee,
            company=self.company,
            work_date=period.start_date.replace(day=day),
            start_time="18:00",
            end_time="20:00",
            duration_minutes=minutes,
            status=OvertimeStatus.APPROVED,
            is_paid=True,
        )

    def finalize(self, run, *, keep):
        """
        Mengunci run, menyisakan satu pegawai.

        Sisanya dikeluarkan lebih dulu karena `TenantTestCase` tidak
        me-rollback antar test: run berikutnya menarik seluruh pegawai
        yang pernah dibuat kelas ini, dan satu di antaranya sudah
        cukup untuk membuat Finalize ditolak karena temuan yang tidak
        ada hubungannya dengan yang sedang diuji.
        """
        self.isolate(run, keep)

        PayrollRunService.acknowledge(run=run)

        run.refresh_from_db()
        run.status = PayrollRunStatus.APPROVED
        run.save(update_fields=["status"])

        PayrollRunService.finalize(run=run)
        run.refresh_from_db()

        return run

    # ------------------------------------------------------------------
    # Pabrik akun bercakupan
    # ------------------------------------------------------------------

    def make_user(self, *, username, companies=()):
        """
        Akun bercakupan, **dinyatakan pada penugasannya**.

        `companies` kosong berarti tanpa batasan, dan itu dinyatakan
        (`UNRESTRICTED`) alih-alih disimpulkan dari daftar yang
        kebetulan kosong: pada penugasan, nol baris berarti tanpa
        kewenangan.
        """
        type(self)._counter += 1

        user = User.objects.create_user(
            username=f"{username}-{type(self)._counter}",
            email=f"{username}-{type(self)._counter}@uji.local",
            password="Uji#12345",
        )

        role = Role.objects.create(
            code=f"ROLE-{username.upper()}-{type(self)._counter}",
            name=f"Role {username}",
        )

        # Dashboard payroll menghitung cakupannya per izin (Stage 3B).
        # Di produksi setiap meja payroll memegang ketiga izin ini;
        # fixture tanpa izin menguji keadaan yang tidak pernah ada.
        grant_payroll_read(role)

        if companies:
            grant_role(
                user, role,
                mode=AuthorityMode.EXPLICIT,
                authorities=[
                    ("company", company.pk) for company in companies
                ],
            )
        else:
            grant_role(user, role, mode=AuthorityMode.UNRESTRICTED)

        return user


# ----------------------------------------------------------------------
# A. Pemilihan periode & run
# ----------------------------------------------------------------------


class SelectionTest(DashboardTestCase):
    """
    Tidak ada company, tahun, atau bulan yang ditulis di kode. Yang
    dipilih saat layar dibuka datang dari data.
    """

    def test_tanpa_filter_memilih_run_terbaru_di_periode_terbaru(self):
        old_period = self.make_month(2040, 1, 31)
        new_period = self.make_month(2040, 2, 29)

        employee = self.make_employee(basic_salary="9000000")

        _, old_run = self.run_payroll(period=old_period, employee=employee)
        _, new_run = self.run_payroll(period=new_period, employee=employee)

        user = self.make_user(username="scoped", companies=[self.company])

        selection = PayrollDashboardService.selection(self.context(user))

        self.assertEqual(selection["period"].pk, new_period.pk)
        self.assertEqual(selection["run"].pk, new_run.pk)
        self.assertNotEqual(selection["run"].pk, old_run.pk)

    def test_periode_terbaru_yang_belum_punya_run_dilewati(self):
        """
        Periode berikutnya lazim dibuka lebih awal. Kalau ia yang
        dipilih sebagai bawaan, layar ini kosong setiap kali ada yang
        menyiapkan bulan depan — padahal payroll bulan berjalan justru
        yang sedang dikerjakan.
        """
        period = self.make_month(2041, 3, 31)
        employee = self.make_employee(basic_salary="9000000")
        _, run = self.run_payroll(period=period, employee=employee)

        self.make_month(2041, 4, 30)  # dibuka, belum ada run-nya

        user = self.make_user(username="scoped", companies=[self.company])

        selection = PayrollDashboardService.selection(self.context(user))

        self.assertEqual(selection["run"].pk, run.pk)
        self.assertEqual(selection["period"].pk, period.pk)

    def test_run_yang_dipilih_menentukan_periodenya(self):
        first = self.make_month(2042, 5, 31)
        second = self.make_month(2042, 6, 30)

        employee = self.make_employee(basic_salary="9000000")

        _, old_run = self.run_payroll(period=first, employee=employee)
        self.run_payroll(period=second, employee=employee)

        user = self.make_user(username="scoped", companies=[self.company])

        selection = PayrollDashboardService.selection(
            self.context(user, payroll_run=old_run.pk),
        )

        self.assertEqual(selection["run"].pk, old_run.pk)
        self.assertEqual(selection["period"].pk, first.pk)

    def test_run_di_luar_cakupan_tidak_bisa_dipaksa_lewat_query(self):
        """
        Menyebut id run milik perusahaan lain di query string tidak
        membukanya. Filter mempersempit; ia tidak pernah menambah.
        """
        period = self.make_month(2043, 7, 31)
        employee = self.make_employee(basic_salary="9000000")
        _, run = self.run_payroll(period=period, employee=employee)

        outsider = Company.objects.create(code="OUT", name="Luar Cakupan")
        stranger = self.make_user(username="stranger", companies=[outsider])

        selection = PayrollDashboardService.selection(
            self.context(stranger, payroll_run=run.pk),
        )

        self.assertIsNone(selection["run"])


# ----------------------------------------------------------------------
# B. Kartu KPI
# ----------------------------------------------------------------------


class KpiTest(DashboardTestCase):
    def test_kartu_menjumlahkan_baris_run_apa_adanya(self):
        """
        Kartu KPI **bukan** perhitungan kedua. Angkanya harus sama
        persis dengan jumlah kolom hasil di `PayrollRunEmployee` —
        kalau bisa berbeda, salah satunya salah dan tidak ada yang
        memberi tahu yang mana.
        """
        period = self.make_month(2044, 1, 31)

        first = self.make_employee(basic_salary="9000000")
        second = self.make_employee(basic_salary="7000000")

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        context = self.context(payroll_run=run.pk)

        lines = PayrollRunEmployee.objects.filter(
            run=run, is_deleted=False, is_excluded=False,
        )

        self.assertEqual(
            self.widget("employees", context)["value"],
            lines.count(),
        )
        self.assertEqual(
            Decimal(str(self.widget("gross_payroll", context)["value"])),
            sum(line.gross_earning for line in lines),
        )
        self.assertEqual(
            Decimal(str(self.widget("total_deduction", context)["value"])),
            sum(line.total_deduction for line in lines),
        )
        self.assertEqual(
            Decimal(str(self.widget("net_payroll", context)["value"])),
            sum(line.net_pay for line in lines),
        )

        self.assertIn(first.pk, {line.employee_id for line in lines})
        self.assertIn(second.pk, {line.employee_id for line in lines})

    def test_kartu_lembur_membaca_komponen_bukan_jam_kali_tarif(self):
        """
        Upah lembur diambil dari komponen ber-sumber OVERTIME — angka
        yang benar-benar masuk gross. Mengalikan `overtime_hours`
        dengan tarif di dashboard berarti menghitung ulang lembur, dan
        hasilnya akan berbeda dari slip begitu kelompoknya bertingkat.
        """
        period = self.make_month(2044, 3, 31)

        employee = self.make_employee(
            basic_salary="8650000", overtime_eligible=True,
        )
        self.add_overtime(employee, period=period, day=5, minutes=600)

        _, run = self.run_payroll(period=period, employee=employee)

        line = self.line_for(run, employee)

        context = self.context(payroll_run=run.pk)

        recorded = PayrollRunComponent.objects.filter(
            run_employee__run=run,
            run_employee__is_excluded=False,
            source=PayrollComponentSource.OVERTIME,
            is_deleted=False,
        ).aggregate(total=Sum("amount"))["total"]

        self.assertEqual(
            Decimal(str(self.widget("overtime", context)["value"])),
            recorded,
        )
        self.assertEqual(recorded, self.component(line, "OT").amount)
        self.assertGreater(line.overtime_hours, 0)

    def test_kartu_alpa_menjumlahkan_dua_kolom_potongan(self):
        period = self.make_month(2044, 5, 31)

        employee = self.make_employee(basic_salary="9000000")
        self.make_absence(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 11),
        )

        _, run = self.run_payroll(period=period, employee=employee)

        line = self.line_for(run, employee)

        context = self.context(payroll_run=run.pk)

        lines = PayrollRunEmployee.objects.filter(
            run=run, is_deleted=False, is_excluded=False,
        )

        self.assertEqual(
            Decimal(str(self.widget("absence_unpaid", context)["value"])),
            sum(
                item.absence_deduction + item.unpaid_leave_deduction
                for item in lines
            ),
        )
        self.assertGreater(line.absence_deduction, 0)

    def test_pegawai_yang_dikecualikan_tidak_ikut_dihitung(self):
        """
        Barisnya sengaja tetap ada di dokumen — "kenapa si A tidak
        dibayar" harus punya jawaban. Tapi ia bukan bagian dari angka
        yang dibayarkan, jadi tidak boleh ikut di kartu maupun tabel.
        """
        period = self.make_month(2044, 7, 31)

        kept = self.make_employee(basic_salary="9000000")
        dropped = self.make_employee(basic_salary="9000000")

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)

        line = self.line_for(run, dropped)
        line.is_excluded = True
        line.status = PayrollRunEmployeeStatus.EXCLUDED
        line.save(update_fields=["is_excluded", "status"])

        PayrollRunService.calculate(run=run)

        context = self.context(payroll_run=run.pk)

        table = self.widget("run_employees", context)

        numbers = {row["employee_number"] for row in table["items"]}

        self.assertIn(kept.employee_number, numbers)
        self.assertNotIn(dropped.employee_number, numbers)
        self.assertEqual(
            self.widget("employees", context)["value"],
            table["total"],
        )


# ----------------------------------------------------------------------
# C. Harian dan bulanan dalam satu run
# ----------------------------------------------------------------------


class MixedBasisTest(DashboardTestCase):
    def test_harian_menampilkan_upah_yang_terbentuk_bukan_gaji_sebulan(self):
        """
        §9. Dasar Upah pegawai harian = tarif sehari x hari yang
        dibayar, dibaca dari komponen BASIC. `basic_salary` di barisnya
        nol dan memang tidak pernah dipakai menghitung apa pun;
        menampilkannya berarti layar ini mengarang gaji bulanan untuk
        orang yang tidak punya.
        """
        period = self.make_month(2045, 1, 31)

        policy = self.make_daily_policy()
        employee = self.make_daily_employee(policy=policy, daily_rate="200000")

        # Upah harian dibentuk dari **absensi**, bukan dari kalender
        # kerja: hari kerja yang tidak ditempuh tidak menghasilkan upah,
        # dan itu justru bedanya dengan pegawai bulanan
        # (`PayrollRunService._payable_days`). Tanpa baris hadir,
        # pegawai harian memang berupah nol — dan test yang lupa
        # membuatnya menyalahkan dashboard atas angka yang benar.
        self.make_present(
            employee,
            *[self.day_in(period, day) for day in range(1, 21)],
        )

        _, run = self.run_payroll(period=period, employee=employee)

        line = self.line_for(run, employee)

        table = self.widget("run_employees", self.context(payroll_run=run.pk))
        row = self.rows_of(table, "employee_number")[employee.employee_number]

        self.assertEqual(line.basic_salary, Decimal("0.00"))
        self.assertEqual(
            Decimal(str(row["base_earning"])),
            self.component(line, "BASIC").amount,
        )
        self.assertEqual(
            Decimal(str(row["base_earning"])),
            line.daily_rate * line.paid_days,
        )

        # 20 hari x Rp 200.000 — angka yang sama dengan baseline UAT
        # kebijakan harian, dan **bukan** gaji sebulan mana pun.
        self.assertEqual(line.paid_days, Decimal("20.00"))
        self.assertEqual(
            Decimal(str(row["base_earning"])),
            Decimal("4000000.00"),
        )

    def test_harian_dan_bulanan_tampil_berdampingan_dengan_label_manusia(self):
        """
        §8/§9. Satu run, dua dasar perhitungan, dua kebijakan — dan
        yang tampil di kolomnya nama kebijakan serta label dasarnya,
        bukan "MONTHLY"/"DAILY" mentah. Tidak ada nama kebijakan yang
        ditulis di kode: yang keluar adalah apa yang diketik tenant.
        """
        period = self.make_month(2045, 3, 31)

        monthly_policy = self.make_policy(name="HO Bulanan")
        daily_policy = self.make_daily_policy(name="Lokal Harian")

        monthly = self.make_employee(basic_salary="9000000")
        self.assign_policy(monthly, monthly_policy)

        daily = self.make_daily_employee(
            policy=daily_policy, daily_rate="200000",
        )

        plain = self.make_employee(basic_salary="9000000")

        _, run = self.run_payroll(period=period, employee=monthly)

        rows = self.rows_of(
            self.widget("run_employees", self.context(payroll_run=run.pk)),
            "employee_number",
        )

        self.assertEqual(
            rows[monthly.employee_number]["policy"], "HO Bulanan",
        )
        self.assertEqual(
            rows[monthly.employee_number]["pay_basis"], "Bulanan",
        )

        self.assertEqual(
            rows[daily.employee_number]["policy"], "Lokal Harian",
        )
        self.assertEqual(rows[daily.employee_number]["pay_basis"], "Harian")

        # Yang tidak membawa kebijakan **mengikuti** perusahaan — itu
        # keadaan yang sah, dan bedanya dengan "punya kebijakan yang
        # kebetulan sama" harus tetap terbaca di kolomnya.
        self.assertEqual(
            rows[plain.employee_number]["policy"], COMPANY_DEFAULT_LABEL,
        )

    def test_baris_tabel_menjumlah_persis_gross_barisnya(self):
        """
        Dasar Upah + Tunjangan & Input + Lembur = Gross Earning, untuk
        tiap baris. Kalau tidak, ada komponen yang jatuh di luar
        seluruh kolom dan pembacanya mencari selisih yang tidak punya
        sebab di layar.
        """
        period = self.make_month(2045, 5, 31)

        employee = self.make_employee(
            basic_salary="8650000", overtime_eligible=True,
        )
        self.add_overtime(employee, period=period, day=4, minutes=300)
        self.make_present(
            employee,
            *[self.day_in(period, day) for day in range(1, 11)],
        )

        _, run = self.run_payroll(period=period, employee=employee)

        line = self.line_for(run, employee)

        rows = self.rows_of(
            self.widget("run_employees", self.context(payroll_run=run.pk)),
            "employee_number",
        )
        row = rows[employee.employee_number]

        total = (
            Decimal(str(row["base_earning"]))
            + Decimal(str(row["allowance"]))
            + Decimal(str(row["overtime"]))
        )

        self.assertEqual(total, line.gross_earning)
        self.assertEqual(Decimal(str(row["net_pay"])), line.net_pay)


# ----------------------------------------------------------------------
# D. Cakupan data
# ----------------------------------------------------------------------


class CompanyScopeTest(DashboardTestCase):
    """
    Dua perusahaan yang masing-masing punya periode, run, dan
    pegawainya sendiri.

    Yang diperiksa bukan cuma KPI. Kebocoran cakupan paling sering
    lewat pintu yang tidak dijaga siapa pun — chart tren, baris
    rincian, dan jumlah temuan — karena ketiganya merakit querysetnya
    sendiri.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.other_company = Company.objects.create(
            code="PAY2", name="Payroll Test Dua",
        )
        cls.other_location = Location.objects.create(
            company=cls.other_company, code="SITE", name="Site Dua",
        )
        cls.other_department = Department.objects.create(
            company=cls.other_company, code="PRD", name="Produksi",
        )

    # ------------------------------------------------------------------

    def make_other_employee(self, *, basic_salary="5000000"):
        type(self)._counter += 1

        employee = Employee.objects.create(
            employee_number=f"OTH{type(self)._counter:04d}",
            first_name="Perusahaan",
            last_name=f"Dua {type(self)._counter}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=self.other_company,
            location=self.other_location,
            department=self.other_department,
            organization_effective_date=date(2025, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee, join_date=date(2025, 1, 1),
        )

        PayrollAssignment.objects.create(
            employee=employee,
            payroll_group=self.payroll_group,
            currency=self.currency,
            tax_status=self.tax_status,
            basic_salary=Decimal(basic_salary),
            allowance_template=self.allowance_template,
            deduction_template=self.deduction_template,
            effective_from=date(2025, 1, 1),
        )

        return Employee.objects.get(pk=employee.pk)

    def make_other_run(self, *, year, month, last_day):
        type(self)._counter += 1

        period = PayrollPeriod.objects.create(
            company=self.other_company,
            payroll_group=self.payroll_group,
            code=f"OTH-{year}-{month:02d}-{type(self)._counter}",
            name=f"{month:02d}/{year} Dua",
            start_date=date(year, month, 1),
            end_date=date(year, month, last_day),
            payment_date=date(year, month, last_day),
        )

        run = PayrollRunService.create(
            data={"period": period, "run_type": "regular"},
        )

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        return period, run

    # ------------------------------------------------------------------

    def test_akun_satu_perusahaan_tidak_menemukan_perusahaan_lain(self):
        """
        §C. Cakupan Company A: tidak ada angka, baris, temuan, atau
        titik chart milik Company B — di pintu mana pun.
        """
        mine = self.make_employee(basic_salary="9000000")
        theirs = self.make_other_employee(basic_salary="5000000")

        period = self.make_month(2046, 1, 31)
        _, run = self.run_payroll(period=period, employee=mine)

        other_period, other_run = self.make_other_run(
            year=2046, month=1, last_day=31,
        )

        user = self.make_user(username="only-a", companies=[self.company])
        context = self.context(user)

        # Run terbaru dalam **cakupannya**, bukan run terbaru di tenant.
        selection = PayrollDashboardService.selection(context)
        self.assertEqual(selection["run"].pk, run.pk)

        table = self.widget("run_employees", context)
        numbers = {row["employee_number"] for row in table["items"]}

        self.assertIn(mine.employee_number, numbers)
        self.assertNotIn(theirs.employee_number, numbers)

        trend = self.widget("cost_trend", self.context(user))
        self.assertNotIn(other_period.code, trend["categories"])

        # Run milik perusahaan lain tidak bisa dibuka lewat query string.
        forced = self.context(user, payroll_run=other_run.pk)
        self.assertIsNone(PayrollDashboardService.selection(forced)["run"])
        self.assertEqual(self.widget("employees", forced)["value"], 0)

    def test_all_allowed_companies_hanya_menjumlah_yang_boleh(self):
        """
        §D. Tanpa satu pun company dicentang, yang dijumlahkan adalah
        **seluruh company dalam cakupan** — bukan seluruh tenant.
        Dibuktikan dengan membandingkan chart tren dua akun: yang
        bercakupan dua perusahaan menemukan kedua periodenya, yang
        bercakupan satu tidak.
        """
        self.make_employee(basic_salary="9000000")
        self.make_other_employee(basic_salary="5000000")

        mine_period = self.make_month(2047, 2, 28)
        self.run_payroll(
            period=mine_period,
            employee=self.make_employee(basic_salary="9000000"),
        )

        other_period, _ = self.make_other_run(
            year=2047, month=2, last_day=28,
        )

        both = self.make_user(
            username="a-and-b",
            companies=[self.company, self.other_company],
        )
        only_a = self.make_user(username="a-only", companies=[self.company])

        both_categories = self.widget(
            "cost_trend", self.context(both),
        )["categories"]
        a_categories = self.widget(
            "cost_trend", self.context(only_a),
        )["categories"]

        self.assertIn(other_period.code, both_categories)
        self.assertNotIn(other_period.code, a_categories)

    def test_filter_company_mempersempit_tapi_tidak_pernah_membuka(self):
        """
        Mencentang perusahaan di luar cakupan tidak menampilkan satu
        baris pun darinya: filter dan cakupan bertumpuk, bukan saling
        menggantikan.
        """
        self.make_other_employee(basic_salary="5000000")

        _, other_run = self.make_other_run(year=2048, month=3, last_day=31)

        only_a = self.make_user(username="a-strict", companies=[self.company])

        context = self.context(
            only_a,
            company=str(self.other_company.pk),
            payroll_run=str(other_run.pk),
        )

        self.assertIsNone(PayrollDashboardService.selection(context)["run"])
        self.assertEqual(self.widget("employees", context)["value"], 0)
        self.assertEqual(
            self.widget("run_employees", context)["items"], [],
        )

    def test_temuan_pegawai_di_luar_cakupan_tidak_ikut_terbaca(self):
        """
        `validation_summary` dibekukan atas **seluruh** run — ia tidak
        tahu siapa yang membacanya, dan pesannya menyebut nama serta
        nomor pegawai. Menampilkannya apa adanya membocorkan daftar
        orang yang barisnya sendiri sudah disembunyikan.
        """
        broken = self.make_other_employee(basic_salary="5000000")

        PayrollAssignment.objects.filter(employee=broken).update(
            basic_salary=Decimal("0"),
        )

        _, other_run = self.make_other_run(year=2049, month=4, last_day=30)

        summary = other_run.validation_summary or {}
        named = [
            item
            for item in (summary.get("errors") or [])
            if item.get("employee")
        ]

        self.assertTrue(named, "run pembanding harus punya temuan berpegawai")

        only_a = self.make_user(
            username="a-findings",
            companies=[self.company],
        )

        findings = PayrollDashboardService._visible_findings(
            self.context(only_a),
            other_run,
        )

        self.assertEqual(
            [item for item in findings if item.get("employee")],
            [],
        )


# ----------------------------------------------------------------------
# E. Run yang sudah dikunci
# ----------------------------------------------------------------------


class FinalizedRunTest(DashboardTestCase):
    def test_angka_run_final_tidak_bergerak_saat_master_berubah(self):
        """
        §F/§15. Sesudah Finalize, mengganti kebijakan dan menaikkan
        gaji di master tidak boleh menggeser satu rupiah pun di layar
        run lama. Dashboard membaca baris run — dan baris run memang
        sudah tidak bergantung pada master.
        """
        period = self.make_month(2050, 6, 30)

        policy = self.make_policy(name="Sebelum Diubah")
        employee = self.make_employee(basic_salary="9000000")
        self.assign_policy(employee, policy)

        _, run = self.run_payroll(period=period, employee=employee)

        run = self.finalize(run, keep=employee)

        self.assertEqual(run.status, PayrollRunStatus.FINALIZED)

        context = self.context(payroll_run=run.pk)

        before = {
            "gross": self.widget("gross_payroll", context)["value"],
            "net": self.widget("net_payroll", context)["value"],
            "policy": self.rows_of(
                self.widget("run_employees", context), "employee_number",
            )[employee.employee_number]["policy"],
        }

        # Master digeser sesudah kunci: nama kebijakan, gaji pokok, dan
        # tarif hariannya.
        policy.name = "Sesudah Diubah"
        policy.save(update_fields=["name"])

        PayrollAssignment.objects.filter(employee=employee).update(
            basic_salary=Decimal("25000000"),
            daily_rate=Decimal("999999"),
        )

        after_context = self.context(payroll_run=run.pk)

        after = {
            "gross": self.widget("gross_payroll", after_context)["value"],
            "net": self.widget("net_payroll", after_context)["value"],
            "policy": self.rows_of(
                self.widget("run_employees", after_context),
                "employee_number",
            )[employee.employee_number]["policy"],
        }

        self.assertEqual(before["gross"], after["gross"])
        self.assertEqual(before["net"], after["net"])

        # Nama kebijakan **ikut** berubah, dan itu benar: yang dibekukan
        # di baris run adalah kebijakan mana yang dipakai, bukan
        # ejaannya. Yang tidak boleh bergerak angkanya.
        self.assertEqual(after["policy"], "Sesudah Diubah")
        self.assertNotEqual(before["policy"], after["policy"])

    def test_progress_run_final_menandai_seluruh_tahap_selesai(self):
        period = self.make_month(2051, 8, 31)
        employee = self.make_employee(basic_salary="9000000")

        _, run = self.run_payroll(period=period, employee=employee)

        run = self.finalize(run, keep=employee)

        progress = self.widget(
            "run_progress", self.context(payroll_run=run.pk),
        )

        stages = {row["id"]: row for row in progress["items"]}

        self.assertEqual(stages["finalized"]["state"], "success")
        self.assertEqual(stages["calculated"]["state"], "success")
        self.assertEqual(stages["finalized"]["count"], 1)
        self.assertTrue(stages["run"]["link"].endswith(f"/{run.pk}"))


# ----------------------------------------------------------------------
# F. Perlu ditindaklanjuti
# ----------------------------------------------------------------------


class AttentionTest(DashboardTestCase):
    def test_temuan_sejenis_dikelompokkan_dan_dihitung(self):
        """
        §6/§7. Dua orang yang kekurangan hal yang sama jadi **satu
        baris berhitung dua**, bukan dua baris yang harus dibaca satu
        per satu. Yang dibaca `validation_summary` — ringkasan yang
        sama persis yang mengunci Finalize.
        """
        period = self.make_month(2052, 9, 30)

        first = self.make_employee(basic_salary="0")
        second = self.make_employee(basic_salary="0")

        _, run = self.run_payroll(period=period, employee=first)

        # Hanya dua pegawai ini yang dihitung — kelas ini sudah membuat
        # pegawai bergaji nol di test sebelumnya, dan "2 pegawai" yang
        # sebenarnya tiga bukan kegagalan pengelompokannya.
        self.isolate(run, first, second)

        attention = self.widget("attention", self.context(payroll_run=run.pk))

        rows = self.rows_of(attention, "id")

        self.assertIn("basic_salary_missing", rows)

        row = rows["basic_salary_missing"]

        self.assertEqual(row["count"], 2)
        self.assertEqual(row["state"], "danger")
        self.assertEqual(row["level"], "Error")
        self.assertTrue(row["link"].endswith(f"/{run.pk}"))

        # Keterangannya menyebut orangnya — tanpa itu, "2 pegawai
        # belum punya gaji pokok" mengharuskan pembacanya membuka run
        # dan mencarinya sendiri.
        self.assertIn(first.employee_number, row["hint"])
        self.assertIn(second.employee_number, row["hint"])

    def test_error_berdiri_di_atas_peringatan(self):
        period = self.make_month(2053, 10, 31)

        self.make_employee(basic_salary="0")
        employee = self.make_employee(basic_salary="9000000")

        _, run = self.run_payroll(period=period, employee=employee)

        attention = self.widget("attention", self.context(payroll_run=run.pk))

        states = [row["state"] for row in attention["items"]]

        self.assertIn("danger", states)
        self.assertEqual(states, sorted(states, key=lambda s: s != "danger"))

    def test_run_yang_belum_pernah_dihitung_tetap_menagih(self):
        """
        Run yang belum divalidasi tidak punya `validation_summary`, dan
        diam bukan jawaban yang benar untuknya: statusnya sendiri sudah
        cukup untuk menyebutkan apa yang kurang.
        """
        period = self.make_month(2054, 11, 30)
        self.make_employee(basic_salary="9000000")

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)

        attention = self.widget("attention", self.context(payroll_run=run.pk))

        rows = self.rows_of(attention, "id")

        self.assertIn("not_calculated", rows)
        self.assertEqual(rows["not_calculated"]["state"], "danger")
        self.assertGreater(rows["not_calculated"]["count"], 0)

    def test_run_menunggu_persetujuan_muncul_sebagai_peringatan(self):
        period = self.make_month(2055, 1, 31)
        employee = self.make_employee(basic_salary="9000000")

        _, run = self.run_payroll(period=period, employee=employee)

        run.status = PayrollRunStatus.SUBMITTED
        run.save(update_fields=["status"])

        attention = self.widget("attention", self.context(payroll_run=run.pk))

        rows = self.rows_of(attention, "id")

        self.assertIn("approval_pending", rows)
        self.assertEqual(rows["approval_pending"]["state"], "warning")


# ----------------------------------------------------------------------
# G. Chart
# ----------------------------------------------------------------------


class TrendTest(DashboardTestCase):
    def test_enam_periode_terakhir_urut_dari_yang_paling_lama(self):
        periods = []

        # Panjang bulannya harus benar. `make_month` menggeser tahunnya
        # sampai bulan itu punya jumlah hari yang diminta — dan April
        # tidak pernah punya 31 hari, jadi angka yang asal membuat
        # test-nya menggantung selamanya alih-alih gagal.
        for month, last_day in (
            (1, 31), (3, 31), (5, 31), (7, 31),
            (8, 31), (10, 31), (12, 31), (2, 28),
        ):
            period = self.make_month(2060, month, last_day)
            employee = self.make_employee(basic_salary="9000000")

            self.run_payroll(period=period, employee=employee)
            periods.append(period)

        # Diurutkan seperti dashboard mengurutkannya — bukan seperti
        # urutan pembuatannya. Februari sengaja dibuat terakhir supaya
        # kedua urutan itu tidak kebetulan sama.
        periods.sort(key=lambda item: (item.start_date, item.pk))

        user = self.make_user(username="trend", companies=[self.company])

        trend = self.widget("cost_trend", self.context(user))

        self.assertEqual(len(trend["categories"]), 6)
        self.assertEqual(
            trend["categories"],
            [period.code for period in periods[-6:]],
        )

        labels = [dataset["label"] for dataset in trend["datasets"]]

        self.assertEqual(labels, ["Gross Payroll", "Net Payroll", "Lembur"])

        for dataset in trend["datasets"]:
            self.assertEqual(len(dataset["data"]), 6)

    def test_komposisi_memakai_sumber_komponen_bukan_nama(self):
        """
        §11. Kategorinya lahir dari pasangan (`component_type`,
        `source`) yang ditulis mesin hitung, bukan dari mencocokkan
        kode "BPJS" atau "TAX" di nama komponen. Konsekuensinya sisi
        penghasilan menjumlah tepat Gross.
        """
        period = self.make_month(2061, 3, 31)

        employee = self.make_employee(
            basic_salary="8650000", overtime_eligible=True,
        )
        self.add_overtime(employee, period=period, day=6, minutes=240)
        self.make_present(
            employee,
            *[self.day_in(period, day) for day in range(1, 13)],
        )

        _, run = self.run_payroll(period=period, employee=employee)

        context = self.context(payroll_run=run.pk)

        composition = self.widget("composition", context)
        series = {
            item["label"]: item["value"]
            for item in composition["series"]
        }

        self.assertIn("Gaji Pokok", series)
        self.assertIn("Lembur", series)

        earning = sum(
            value
            for label, value in series.items()
            if label in ("Gaji Pokok", "Tunjangan", "Lembur", "Input Variabel")
        )

        self.assertEqual(
            Decimal(str(earning)),
            Decimal(str(self.widget("gross_payroll", context)["value"])),
        )

        deduction = sum(
            value
            for label, value in series.items()
            if label in ("Potongan", "PPh21")
        )

        self.assertEqual(
            Decimal(str(deduction)),
            Decimal(str(self.widget("total_deduction", context)["value"])),
        )

    def test_ketidakhadiran_punya_kotak_sendiri_dan_totalnya_rekonsiliasi(
        self,
    ):
        """
        Business Decision #2 di sisi tampilan.

        Pengurang ketidakhadiran **tidak** boleh ikut di kotak
        "Potongan": ia gaji yang tidak pernah terbentuk, bukan uang
        yang ditahan, dan ikut di sana membuat `Potongan` berhenti sama
        dengan kartu Total Deduction — pembacanya melihat pegawai
        ditagih dua kali.

        Tiga kesamaan yang diperiksa sekaligus, karena ketiganya yang
        membuat grafik dan kartu tidak bisa berbeda pendapat:

            penghasilan - ketidakhadiran = Gross Payroll
            potongan                     = Total Deduction
            gross - potongan             = Net Payroll
        """
        period = self.make_month(2061, 5, 31)

        employee = self.make_employee(basic_salary="9000000")

        self.make_absence(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 11),
        )

        line, run = self.run_payroll(period=period, employee=employee)

        context = self.context(payroll_run=run.pk)

        series = {
            item["label"]: Decimal(str(item["value"]))
            for item in self.widget("composition", context)["series"]
        }

        # Kotaknya ada, nilainya positif, dan angkanya sama dengan
        # kolom jejak di barisnya — dicocokkan ke sana, bukan ke angka
        # yang ditulis di test, supaya ia tidak diam-diam bergantung
        # pada pembagi hari bawaan periode.
        self.assertIn("Ketidakhadiran", series)
        self.assertGreater(line.absence_deduction, 0)
        self.assertEqual(
            series["Ketidakhadiran"],
            line.absence_deduction + line.unpaid_leave_deduction,
        )

        earning = sum(
            value
            for label, value in series.items()
            if label in ("Gaji Pokok", "Tunjangan", "Lembur", "Input Variabel")
        )

        deduction = sum(
            value
            for label, value in series.items()
            if label in ("Potongan", "PPh21")
        )

        gross = Decimal(str(self.widget("gross_payroll", context)["value"]))
        total = Decimal(str(self.widget("total_deduction", context)["value"]))
        net = Decimal(str(self.widget("net_payroll", context)["value"]))

        self.assertEqual(earning - series["Ketidakhadiran"], gross)
        self.assertEqual(deduction, total)
        self.assertEqual(gross - total, net)


# ----------------------------------------------------------------------
# H. Rincian
# ----------------------------------------------------------------------


class BreakdownTest(DashboardTestCase):
    def test_rincian_per_kebijakan_memisahkan_yang_ikut_perusahaan(self):
        period = self.make_month(2070, 4, 30)

        policy = self.make_policy(name="Kebijakan Rincian")

        with_policy = self.make_employee(basic_salary="9000000")
        self.assign_policy(with_policy, policy)

        self.make_employee(basic_salary="7000000")

        _, run = self.run_payroll(period=period, employee=with_policy)

        context = self.context(payroll_run=run.pk)

        rows = self.rows_of(self.widget("by_policy", context), "policy")

        self.assertIn("Kebijakan Rincian", rows)
        self.assertIn(COMPANY_DEFAULT_LABEL, rows)

        self.assertEqual(
            sum(row["employees"] for row in rows.values()),
            self.widget("employees", context)["value"],
        )
        self.assertEqual(
            Decimal(str(sum(row["net"] for row in rows.values()))),
            Decimal(str(self.widget("net_payroll", context)["value"])),
        )

    def test_rincian_per_unit_organisasi_menjumlah_utuh(self):
        period = self.make_month(2071, 6, 30)
        employee = self.make_employee(basic_salary="9000000")

        _, run = self.run_payroll(period=period, employee=employee)

        context = self.context(payroll_run=run.pk)

        for key, widget_key in (
            ("department", "by_department"),
            ("location", "by_location"),
        ):
            data = self.widget(widget_key, context)

            self.assertEqual(
                sum(row["employees"] for row in data["items"]),
                self.widget("employees", context)["value"],
            )
            self.assertEqual(
                data["totals"]["gross"],
                self.widget("gross_payroll", context)["value"],
            )

            # Baris tanpa unit tetap punya nama, bukan menghilang.
            for row in data["items"]:
                self.assertTrue(row[key])

    def test_baris_tanpa_unit_tetap_dihitung(self):
        """
        Membuang baris tanpa departemen membuat jumlah rincian tidak
        pernah sama dengan KPI, dan selisih tanpa sebab lebih buruk
        daripada satu baris bernama "(belum ditentukan)".
        """
        period = self.make_month(2072, 8, 31)
        employee = self.make_employee(basic_salary="9000000")

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)

        PayrollRunEmployee.objects.filter(run=run, employee=employee).update(
            department=None,
        )

        PayrollRunService.calculate(run=run)

        context = self.context(payroll_run=run.pk)

        rows = self.rows_of(
            self.widget("by_department", context),
            "department",
        )

        self.assertIn(UNASSIGNED_LABEL, rows)


# ----------------------------------------------------------------------
# I. Keadaan kosong
# ----------------------------------------------------------------------


class EmptyStateTest(DashboardTestCase):
    """
    §16. Tidak ada yang boleh meledak, dan tidak ada angka yang boleh
    lahir dari ketiadaan. Nol berarti nol; yang belum ada tetap kosong.
    """

    def test_perusahaan_tanpa_periode_menghasilkan_dashboard_kosong(self):
        empty_company = Company.objects.create(
            code="EMPTY", name="Belum Payroll",
        )
        user = self.make_user(username="empty", companies=[empty_company])

        context = self.context(user)

        selection = PayrollDashboardService.selection(context)

        self.assertIsNone(selection["period"])
        self.assertIsNone(selection["run"])

        widgets = self.render(context)

        self.assertEqual(widgets["employees"]["value"], 0)
        self.assertEqual(widgets["gross_payroll"]["value"], 0.0)
        self.assertEqual(widgets["run_progress"]["items"], [])
        self.assertEqual(widgets["attention"]["items"], [])
        self.assertEqual(widgets["run_employees"]["items"], [])
        self.assertEqual(widgets["run_employees"]["total"], 0)
        self.assertEqual(widgets["cost_trend"]["categories"], [])
        self.assertEqual(widgets["composition"]["series"], [])
        self.assertEqual(widgets["by_policy"]["items"], [])
        self.assertIsNone(widgets["by_policy"]["totals"])

    def test_periode_tanpa_run_tidak_menampilkan_run_periode_lain(self):
        """
        Periode dipilih sendiri, run-nya tidak ada. Yang salah di sini
        bukan angka kosong melainkan angka run **lain** yang mendarat
        di layar karena pemilihannya mundur diam-diam.
        """
        used = self.make_month(2080, 1, 31)
        employee = self.make_employee(basic_salary="9000000")
        self.run_payroll(period=used, employee=employee)

        empty = self.make_month(2080, 2, 28)

        context = self.context(payroll_period=empty.pk)

        selection = PayrollDashboardService.selection(context)

        self.assertEqual(selection["period"].pk, empty.pk)
        self.assertIsNone(selection["run"])

        widgets = self.render(context)

        self.assertEqual(widgets["employees"]["value"], 0)
        self.assertEqual(widgets["run_employees"]["items"], [])

    def test_run_yang_belum_dihitung_tetap_menampilkan_pegawainya(self):
        """
        Run yang baru di-generate punya pegawai tapi belum punya angka.
        Yang benar bukan layar kosong: orangnya sudah masuk run, dan
        nol di kolom uangnya memang nol.
        """
        period = self.make_month(2081, 3, 31)
        employee = self.make_employee(basic_salary="9000000")

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)

        context = self.context(payroll_run=run.pk)
        widgets = self.render(context)

        rows = self.rows_of(widgets["run_employees"], "employee_number")

        self.assertIn(employee.employee_number, rows)
        self.assertEqual(rows[employee.employee_number]["net_pay"], 0.0)
        self.assertEqual(rows[employee.employee_number]["status"], "Pending")
        self.assertEqual(widgets["composition"]["series"], [])

        stages = {row["id"]: row for row in widgets["run_progress"]["items"]}

        self.assertEqual(stages["generated"]["state"], "success")
        self.assertEqual(stages["calculated"]["state"], "warning")

    def test_pencarian_yang_tidak_menemukan_apa_pun_tidak_menggeser_kpi(self):
        """
        Kotak cari hanya menyaring tabel. KPI menjawab pertanyaan yang
        berbeda, dan menggesernya berarti pembacanya kehilangan
        pembanding tepat saat ia butuh.
        """
        period = self.make_month(2082, 5, 31)
        employee = self.make_employee(basic_salary="9000000")

        _, run = self.run_payroll(period=period, employee=employee)

        context = self.context(
            payroll_run=run.pk,
            search="tidak-ada-orang-ini",
        )

        table = self.widget("run_employees", context)

        self.assertEqual(table["items"], [])
        self.assertEqual(table["matched"], 0)
        self.assertGreater(table["total"], 0)
        self.assertEqual(
            self.widget("employees", context)["value"],
            table["total"],
        )
