"""
`/api/payroll/payroll-runs/<id>/summary/` — kebocoran cakupan data.

**Cacatnya.** Rekap run menjumlahkan `PayrollRunEmployee` langsung dari
manager dan membaca kolom total yang dibekukan di `PayrollRun`. Tidak
satu pun dari dua lapis penjagaan payroll pernah dilewati: `data_scope`
dan `EmployeeDataPolicy` keduanya dipasang di `filter_queryset()`, dan
action yang merakit agregatnya sendiri tidak memanggilnya.

Akibatnya akun yang membuka `/api/payroll/payroll-run-employees/?run=8`
dan mendapat **nol baris** tetap membaca total Rp 132.378.341 di
`summary/`. Ditemukan saat UAT Payroll Dashboard, pada akun `demo.gmho`
di tenant peragaan.

**Yang diuji di sini bukan angka payroll.** Berapa gaji seseorang
seharusnya sudah dijawab `test_proration`, `test_attendance_deduction`,
`test_overtime`, dan `test_payroll_policy`. Yang diuji cuma satu
pertanyaan: **apakah rekap menjumlahkan baris yang sama dengan yang
boleh dibaca pemanggilnya** — dan itu diperiksa dengan membandingkan
kedua endpoint memakai akun yang sama, bukan dengan menuliskan angka
yang diharapkan.

Panggungnya satu run berisi empat pegawai di dua divisi, dan empat cara
membacanya:

| Akun | Cakupan organisasi | Boleh baca gaji? |
| --- | --- | --- |
| `full` | tanpa batas | ya |
| `partial` | satu divisi | ya |
| `blind` | tanpa batas | **tidak** |
| `superuser` | tanpa batas | ya (dilewati) |

`blind` adalah bentuk cacat aslinya: ia **boleh** membuka dokumen
run-nya (cakupan organisasinya mencakup company), tapi tidak boleh
membaca gaji siapa pun.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission

from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

from apps.accounts.models import (
    AuthorityMode,
    Role,
)
from apps.accounts.services.role_assignment import grant_role
from apps.administration.models import (
    Division,
    EmployeeDataPolicy,
    EmployeeDataSubject,
)
from apps.hr.models import OrganizationAssignment, PayrollAssignment
from apps.payroll.api.payroll_run_employees.views import (
    PayrollRunEmployeeViewSet,
)
from apps.payroll.api.payroll_runs.views import PayrollRunViewSet
from apps.payroll.models import PayrollRunEmployee
from apps.payroll.services import PayrollRunService

from .test_payroll_flow import PayrollFlowTestCase


User = get_user_model()

ZERO = Decimal("0.00")


class RunSummaryScopeTestCase(PayrollFlowTestCase):
    factory = APIRequestFactory()

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.division_a = Division.objects.create(
            company=cls.company, code="DIVA", name="Divisi A",
        )
        cls.division_b = Division.objects.create(
            company=cls.company, code="DIVB", name="Divisi B",
        )

        # Role yang **disebut** aturan `EmployeeDataPolicy` di bawah.
        # Pemegangnya boleh membaca gaji; yang tidak memegangnya tidak.
        #
        # Ia sekaligus dibatasi ke Divisi A, dan itu yang membuat akun
        # `partial` mungkin: cakupan organisasi dan izin baca gaji
        # menempel pada role yang sama, jadi menambah role kedua yang
        # tak berbatas melebarkan cakupannya tanpa mencabut izinnya.
        cls.payroll_reader = Role.objects.create(
            code="PAYROLL-READER",
            name="Payroll Reader",
        )

        # Role tak berbatas. Maksud itu **dinyatakan** pada penugasan
        # lewat `cls.role_authority` di bawah — pada penugasan, nol
        # baris berarti tanpa kewenangan, bukan tanpa batasan.
        cls.open_role = Role.objects.create(
            code="OPEN-SCOPE",
            name="Open Scope",
        )

        # Satu aturan, berlaku untuk semua pegawai. Hanya pemegang
        # `payroll_reader` yang lolos — dan itu bentuk yang sama dengan
        # seed bawaan (`EDP-PAYROLL` menyebut HR-MANAGER).
        EmployeeDataPolicy.objects.create(
            code="EDP-PAYROLL-TEST",
            name="Payroll (test)",
            subject=EmployeeDataSubject.FIELD_PAYROLL,
            role=cls.payroll_reader,
            is_active=True,
        )

        # Izin baca payroll, diberikan ke **kedua** role.
        #
        # Sejak cakupan dihitung per izin (`ROLE_AWARE_DATA_SCOPE`),
        # role yang tidak memberi izinnya tidak menyumbang cakupan.
        # Kalau hanya `payroll_reader` yang dapat, akun `full`
        # kehilangan cakupan tak-berbatas milik `open_role` dan rekapnya
        # menyempit ke Divisi A — yang diuji berkas ini jadi bukan lagi
        # kebocoran cakupan.
        #
        # Keduanya memang meja pembaca payroll di panggung ini; yang
        # membedakannya **cakupan**, bukan boleh-tidaknya membuka run.
        # Itu bentuk yang sama dengan seed sungguhan, di mana
        # `READ_GRANTS` memberi izin ini ke HR-ADMIN, HR-MANAGER, dan
        # kembaran site-nya sekaligus.
        #
        # `blind` tetap buta: yang menutup gaji baginya
        # `EmployeeDataPolicy` di atas, bukan izin model — dan itu
        # justru pemisahan yang diuji di sini.
        payroll_reads = Permission.objects.filter(
            content_type__app_label="payroll",
            codename__in=[
                "view_payrollrun",
                "view_payrollrunemployee",
            ],
        )

        cls.payroll_reader.permissions.add(*payroll_reads)
        cls.open_role.permissions.add(*payroll_reads)

        # ------------------------------------------------------------------
        # WHERE tiap role — dinyatakan, bukan diturunkan
        # ------------------------------------------------------------------
        #
        # Isinya persis maksud yang sudah tertulis di atas berkas ini:
        # `payroll_reader` dibatasi ke Divisi A, `open_role` sengaja tak
        # berbatas. Bukan disimpulkan dari nama role — disalin dari
        # deklarasi fixture-nya sendiri.
        #
        # Role yang tidak disebut di sini memakai `UNRESTRICTED`, yang
        # menyamai perilaku lama "tanpa baris = tanpa batasan" untuk
        # role bikinan subclass (`test_dashboard_authority`).
        cls.role_authority = {
            cls.payroll_reader.pk: (
                AuthorityMode.EXPLICIT, [("division", cls.division_a.pk)],
            ),
            cls.open_role.pk: (AuthorityMode.UNRESTRICTED, []),
        }

        cls.full_user = cls.make_account(
            "full", roles=[cls.payroll_reader, cls.open_role],
        )
        cls.partial_user = cls.make_account(
            "partial", roles=[cls.payroll_reader],
        )
        cls.blind_user = cls.make_account("blind", roles=[cls.open_role])

        cls.root_user = cls.make_account("root", roles=[])
        cls.root_user.is_superuser = True
        cls.root_user.is_staff = True
        cls.root_user.save(update_fields=["is_superuser", "is_staff"])

    # ------------------------------------------------------------------
    # Pabrik
    # ------------------------------------------------------------------

    @classmethod
    def make_account(cls, name, *, roles):
        cls._counter += 1

        # Email wajib unik (`auth_users_email_key`), dan `create_user`
        # tanpa email menyimpan string kosong — akun kedua menabrak
        # yang pertama dengan galat yang tidak menyebut email.
        user = User.objects.create_user(
            username=f"{name}-{cls._counter}",
            email=f"{name}-{cls._counter}@uji.local",
            password="Uji#12345",
        )

        for role in roles or ():
            mode, authorities = getattr(cls, "role_authority", {}).get(
                role.pk, (AuthorityMode.UNRESTRICTED, []),
            )

            grant_role(user, role, mode=mode, authorities=authorities)

        return user

    @classmethod
    def make_employee_in(cls, division, *, basic_salary="9000000"):
        employee = cls.make_employee(basic_salary=basic_salary)

        OrganizationAssignment.objects.filter(employee=employee).update(
            division=division,
        )

        return employee

    # ------------------------------------------------------------------
    # Pemanggilan endpoint
    # ------------------------------------------------------------------

    def summary_for(self, user, run):
        """
        Balasan `summary/` apa adanya, lewat action yang sebenarnya.

        Dipanggil di tingkat view — bukan lewat HTTP — supaya yang
        diuji tetap penjagaan barisnya dan bukan `ModelPermission`,
        yang punya testnya sendiri. `get_object()` tetap jalan, jadi
        cakupan run-nya tetap ditegakkan sebagaimana di produksi.
        """
        view = PayrollRunViewSet()
        view.action = "summary"
        view.format_kwarg = None
        view.kwargs = {"pk": str(run.pk)}

        request = Request(
            self.factory.get(f"/api/payroll/payroll-runs/{run.pk}/summary/"),
        )
        request.user = user

        view.request = request

        return view.summary(request, pk=str(run.pk)).data["data"]

    def listed_for(self, user, run):
        """
        Baris yang benar-benar dikirim `/payroll-run-employees/?run=`.

        Lewat `filter_queryset()` viewset-nya, yaitu tempat kedua lapis
        penjagaan dipasang — bukan lewat queryset yang dirakit test
        sendiri, yang justru akan melewatkan hal yang sedang diuji.
        """
        view = PayrollRunEmployeeViewSet()
        view.action = "list"
        view.format_kwarg = None
        view.kwargs = {}

        request = Request(
            self.factory.get(
                "/api/payroll/payroll-run-employees/",
                {"run": str(run.pk)},
            ),
        )
        request.user = user

        view.request = request

        return view.filter_queryset(view.get_queryset()).filter(
            run=run,
            is_excluded=False,
        )

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    def build_run(self):
        """Satu run: dua pegawai Divisi A, dua Divisi B."""
        type(self)._counter += 1

        inside = [
            self.make_employee_in(self.division_a, basic_salary="9000000"),
            self.make_employee_in(self.division_a, basic_salary="7000000"),
        ]
        outside = [
            self.make_employee_in(self.division_b, basic_salary="11000000"),
            self.make_employee_in(self.division_b, basic_salary="13000000"),
        ]

        period = self.make_period(code=f"SUM-{type(self)._counter}")
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)

        # Hanya empat pegawai ini yang ikut. `TenantTestCase` tidak
        # me-rollback antar test, jadi run berikutnya menarik seluruh
        # pegawai yang pernah dibuat kelas ini — dan "dua dari empat"
        # yang sebenarnya dua dari sebelas tidak menguji apa pun.
        keep = [item.pk for item in inside + outside]

        PayrollRunEmployee.objects.filter(run=run).exclude(
            employee_id__in=keep,
        ).delete()

        PayrollRunService.calculate(run=run)
        run.refresh_from_db()

        return run, inside, outside

    @staticmethod
    def totals_of(lines):
        result = {}

        for field, key in (
            ("gross_earning", "total_earning"),
            ("total_deduction", "total_deduction"),
            ("tax_amount", "total_tax"),
            ("net_pay", "total_net"),
        ):
            result[key] = sum(
                (getattr(line, field) for line in lines), ZERO,
            )

        return result


# ----------------------------------------------------------------------
# 1. Akses penuh
# ----------------------------------------------------------------------


class FullAccessTest(RunSummaryScopeTestCase):
    def test_akses_penuh_tetap_menerima_total_seluruh_run(self):
        """
        Perbaikannya **tidak boleh menggeser satu rupiah pun** untuk
        yang memang berhak membaca semuanya.

        Angkanya sekarang dijumlahkan dari baris, bukan dibaca dari
        kolom total yang dibekukan — dan keduanya harus sama persis,
        karena `_refresh_totals` menjumlahkan baris yang sama.
        """
        run, inside, outside = self.build_run()

        data = self.summary_for(self.full_user, run)

        self.assertEqual(data["run"]["employee_count"], 4)
        self.assertEqual(
            Decimal(data["run"]["total_earning"]), run.total_earning,
        )
        self.assertEqual(
            Decimal(data["run"]["total_deduction"]), run.total_deduction,
        )
        self.assertEqual(Decimal(data["run"]["total_tax"]), run.total_tax)
        self.assertEqual(Decimal(data["run"]["total_net"]), run.total_net)

        self.assertEqual(run.employee_count, 4)
        self.assertGreater(run.total_net, ZERO)

    def test_superuser_dilewati_kedua_lapis(self):
        run, inside, outside = self.build_run()

        data = self.summary_for(self.root_user, run)

        self.assertEqual(data["run"]["employee_count"], 4)
        self.assertEqual(
            Decimal(data["run"]["total_net"]), run.total_net,
        )


# ----------------------------------------------------------------------
# 2. Akses sebagian
# ----------------------------------------------------------------------


class PartialAccessTest(RunSummaryScopeTestCase):
    def test_hanya_menjumlah_pegawai_yang_boleh_dibaca(self):
        """
        Cakupan satu divisi: rekapnya berisi dua pegawai, bukan empat,
        dan angkanya persis jumlah dua baris itu.

        Yang diperiksa **bukan** angka yang ditulis di test melainkan
        jumlah baris yang memang boleh ia baca — kalau angkanya
        dituliskan, test ini akan ikut berubah setiap kali aturan
        perhitungan berubah dan berhenti menguji keamanannya.
        """
        run, inside, outside = self.build_run()

        lines = list(
            PayrollRunEmployee.objects.filter(
                run=run, employee__in=inside, is_excluded=False,
            ),
        )

        expected = self.totals_of(lines)

        data = self.summary_for(self.partial_user, run)

        self.assertEqual(data["run"]["employee_count"], 2)

        for key, value in expected.items():
            self.assertEqual(Decimal(data["run"][key]), value, key)

    def test_total_sebagian_lebih_kecil_dari_total_run(self):
        """
        Penjagaan terhadap perbaikan yang cuma terlihat benar: kalau
        angkanya kebetulan sama dengan total run, tidak ada yang
        tersaring.
        """
        run, inside, outside = self.build_run()

        data = self.summary_for(self.partial_user, run)

        self.assertLess(
            Decimal(data["run"]["total_net"]), run.total_net,
        )
        self.assertLess(
            Decimal(data["run"]["total_earning"]), run.total_earning,
        )
        self.assertGreater(Decimal(data["run"]["total_net"]), ZERO)

    def test_rekap_per_departemen_dan_komponen_ikut_tersaring(self):
        """
        Total di kepala rekap bukan satu-satunya pintu. Rincian per
        komponen dan per departemen dirakit dari queryset tersendiri,
        dan sebelum perbaikan ini keduanya tidak dijaga sama sekali.
        """
        run, inside, outside = self.build_run()

        full = self.summary_for(self.full_user, run)
        partial = self.summary_for(self.partial_user, run)

        full_departments = sum(
            row["employees"] for row in full["by_department"]
        )
        partial_departments = sum(
            row["employees"] for row in partial["by_department"]
        )

        self.assertEqual(full_departments, 4)
        self.assertEqual(partial_departments, 2)

        def component_total(payload):
            return sum(
                Decimal(str(row["total"] or 0))
                for row in payload["earnings"] + payload["deductions"]
            )

        self.assertLess(
            component_total(partial), component_total(full),
        )

    def test_temuan_pegawai_di_luar_cakupan_tidak_ikut_terbaca(self):
        """
        `validation_summary` dibekukan atas seluruh run dan membawa
        nama serta nomor pegawai di pesannya. Mengirimnya apa adanya
        membocorkan daftar orang yang barisnya sendiri sudah
        disembunyikan — dan `counts`-nya membocorkan berapa banyak.
        """
        run, inside, outside = self.build_run()

        # Satu pegawai di luar cakupan dibuat bermasalah, lalu run-nya
        # divalidasi ulang supaya temuannya benar-benar ada.
        PayrollRunEmployee.objects.filter(
            run=run, employee=outside[0],
        ).update(basic_salary=ZERO)

        PayrollRunService.validate(run=run)
        run.refresh_from_db()

        stranger = outside[0].pk

        full = self.summary_for(self.full_user, run)["validation"]
        partial = self.summary_for(self.partial_user, run)["validation"]

        full_ids = {
            item.get("employee")
            for item in full["errors"] + full["warnings"]
        }

        self.assertIn(stranger, full_ids)

        partial_ids = {
            item.get("employee")
            for item in partial["errors"] + partial["warnings"]
        }

        self.assertNotIn(stranger, partial_ids)

        # Cacahnya ikut dihitung ulang. Daftar yang sudah disaring di
        # sebelah angka yang belum adalah bocoran yang sama, cuma
        # berbentuk satu bilangan.
        self.assertEqual(
            partial["counts"]["errors"], len(partial["errors"]),
        )
        self.assertEqual(
            partial["counts"]["warnings"], len(partial["warnings"]),
        )
        self.assertEqual(partial["counts"]["employees"], 2)


# ----------------------------------------------------------------------
# 3. Tanpa akses
# ----------------------------------------------------------------------


class NoAccessTest(RunSummaryScopeTestCase):
    def test_yang_tidak_boleh_membaca_gaji_menerima_nol(self):
        """
        Bentuk cacat aslinya: akun ini **boleh** membuka dokumen
        run-nya — cakupan organisasinya mencakup company — tapi tidak
        boleh membaca gaji siapa pun. Sebelum perbaikan, ia menerima
        total seluruh run.
        """
        run, inside, outside = self.build_run()

        data = self.summary_for(self.blind_user, run)

        self.assertEqual(data["run"]["employee_count"], 0)

        for key in (
            "total_earning",
            "total_deduction",
            "total_tax",
            "total_net",
        ):
            self.assertEqual(Decimal(data["run"][key]), ZERO, key)

        self.assertEqual(data["earnings"], [])
        self.assertEqual(data["deductions"], [])
        self.assertEqual(data["by_department"], [])

        # Temuan **tingkat run** tetap tampil, dan itu disengaja:
        # "perusahaan ini belum punya Payroll Setting" adalah keadaan
        # dokumennya, bukan gaji seseorang. Yang tidak boleh lolos
        # cuma temuan yang menyebut pegawai.
        findings = (
            data["validation"]["errors"] + data["validation"]["warnings"]
        )

        self.assertEqual(
            [item for item in findings if item.get("employee")],
            [],
        )

        self.assertEqual(data["validation"]["counts"]["employees"], 0)
        self.assertEqual(
            data["validation"]["counts"]["errors"],
            len(data["validation"]["errors"]),
        )
        self.assertEqual(
            data["validation"]["counts"]["warnings"],
            len(data["validation"]["warnings"]),
        )

    def test_nomor_dokumen_dan_status_tetap_terbaca(self):
        """
        Yang ditutup gajinya, bukan dokumennya. Run-nya sendiri memang
        berada dalam cakupan organisasi akun ini, dan menyembunyikan
        nomor serta statusnya berarti ia tidak bisa menjawab
        pertanyaan yang memang boleh ia jawab.
        """
        run, inside, outside = self.build_run()

        data = self.summary_for(self.blind_user, run)

        self.assertEqual(data["run"]["id"], run.pk)
        self.assertEqual(data["run"]["document_number"], run.document_number)
        self.assertEqual(data["run"]["status"], run.status)


# ----------------------------------------------------------------------
# 4 & 5. Konsistensi dan penyimpulan
# ----------------------------------------------------------------------


class ScopeConsistencyTest(RunSummaryScopeTestCase):
    def test_daftar_dan_rekap_menyaring_himpunan_yang_sama(self):
        """
        Satu run, empat akun, dua endpoint. Yang dibandingkan bukan
        angkanya melainkan **himpunannya**: rekap harus menjumlahkan
        persis baris yang dikirim endpoint daftar kepada akun yang
        sama.

        Selisih di antara keduanya adalah bentuk cacat aslinya, dan ia
        tidak berbunyi — kedua layar tetap terbuka dan tetap berisi.
        """
        run, inside, outside = self.build_run()

        for label, user in (
            ("penuh", self.full_user),
            ("sebagian", self.partial_user),
            ("tanpa akses", self.blind_user),
            ("superuser", self.root_user),
        ):
            with self.subTest(akun=label):
                listed = list(self.listed_for(user, run))
                data = self.summary_for(user, run)

                self.assertEqual(
                    data["run"]["employee_count"], len(listed), label,
                )

                expected = self.totals_of(listed)

                for key, value in expected.items():
                    self.assertEqual(
                        Decimal(data["run"][key]), value, f"{label}/{key}",
                    )

    def test_tidak_ada_agregat_yang_membocorkan_pegawai_tersembunyi(self):
        """
        §5. Tidak satu pun angka di balasan boleh berbeda antara "run
        ini berisi empat orang" dan "run ini berisi dua orang yang
        boleh saya lihat".

        Diuji dengan membandingkan rekap akun bercakupan sebagian
        terhadap run yang **memang** hanya berisi dua orang itu: kalau
        ada satu saja agregat yang masih menghitung pegawai
        tersembunyi, kedua balasan akan berbeda di situ.
        """
        run, inside, outside = self.build_run()

        partial = self.summary_for(self.partial_user, run)

        # Run pembanding: pegawai di luar divisi dikeluarkan, lalu
        # dibaca akun berakses penuh. Inilah kebenaran yang boleh
        # dilihat akun bercakupan sebagian.
        PayrollRunEmployee.objects.filter(
            run=run, employee__in=outside,
        ).delete()

        PayrollRunService._refresh_totals(run=run)
        PayrollRunService.validate(run=run)
        run.refresh_from_db()

        truth = self.summary_for(self.full_user, run)

        self.assertEqual(partial["run"], truth["run"])
        self.assertEqual(partial["by_department"], truth["by_department"])
        self.assertEqual(partial["earnings"], truth["earnings"])
        self.assertEqual(partial["deductions"], truth["deductions"])

    def test_lembur_tidak_bocor_lewat_agregat_komponen(self):
        """
        Rincian komponen menyebut kode dan nama — termasuk lembur.
        Kalau ia tidak ikut tersaring, keberadaan satu baris "OT"
        memberi tahu bahwa ada orang yang lembur di luar cakupan,
        beserta jumlahnya.
        """
        type(self)._counter += 1

        stranger = self.make_employee_in(
            self.division_b, basic_salary="12000000",
        )

        PayrollAssignment.objects.filter(employee=stranger).update(
            overtime_eligible=True,
            overtime_group=self.overtime_group,
        )

        mine = self.make_employee_in(self.division_a, basic_salary="9000000")

        period = self.make_period(code=f"SUM-OT-{type(self)._counter}")
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)

        PayrollRunEmployee.objects.filter(run=run).exclude(
            employee_id__in=[stranger.pk, mine.pk],
        ).delete()

        self.add_overtime(stranger, period=period, day=5, minutes=600)

        PayrollRunService.calculate(run=run)

        full = self.summary_for(self.full_user, run)
        partial = self.summary_for(self.partial_user, run)

        full_codes = {row["code"] for row in full["earnings"]}
        partial_codes = {row["code"] for row in partial["earnings"]}

        self.assertIn("OT", full_codes)
        self.assertNotIn("OT", partial_codes)

    def add_overtime(self, employee, *, period, day, minutes):
        from apps.hr.models import EmployeeOvertime
        from apps.hr.models.overtime import OvertimeStatus

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
