"""
Mengunci urutan go-live cuti dari ujung ke ujung.

Yang diuji di sini bukan satu fungsi, melainkan **urutannya**: tetapkan
tanggal → import/isi saldo awal → review → post → saldo pegawai. Tiap
langkah punya satu invarian yang gagalnya diam kalau rusak — angkanya
tetap keluar, cuma bukan angka yang dimaksud siapa pun:

1. Baris baru berstatus draft, dan draft **tidak** menyentuh kartu.
   Rusak, dan sebuah file yang belum diperiksa siapa pun sudah mengubah
   saldo seluruh perusahaan.
2. Post membuat kartunya, dan angkanya persis angka yang diserahkan HR
   — bukan angka itu **ditambah** jatah setahun penuh.
3. Jatah tahun go-live tidak diterbitkan untuk pegawai yang sudah
   bekerja sebelum tanggal itu, walau `generate_leave_balances`
   dijalankan berkali-kali.
4. Pegawai yang masuk **sesudah** go-live tetap dapat jatahnya. Ini
   yang paling gampang ikut termatikan.
5. Tahun berikutnya kembali normal — kalau tidak, satu tanggal migrasi
   mematikan jatah cuti seseorang selamanya.

Angkanya sengaja diambil dari contoh yang dipakai saat merancang alur
ini: go-live 1 September 2026, cut-off 31 Agustus 2026, Sarah 7 hari.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.core.testing.tenant import ReusableTenantTestCase

from apps.administration.models import Company, LeavePolicy, LeaveType
from apps.hr.api.leave.eligibility import OpeningValidation
from apps.hr.api.leave.entitlement import LeaveBalanceGenerator
from apps.hr.api.leave_opening.serializers import (
    LeaveOpeningBalanceSerializer,
)
from apps.hr.api.leave_opening.services import LeaveOpeningBalanceService
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    LeaveBalance,
    LeaveGoLive,
    LeaveOpeningStatus,
    OrganizationAssignment,
)


YEAR = 2026

GO_LIVE_DATE = date(2026, 9, 1)
CUTOFF_DATE = date(2026, 8, 31)


class LeaveGoLiveFlowTestCase(ReusableTenantTestCase):
    reusable_schema_name = "fast_leave_golive"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "leave-go-live-test"
        tenant.name = "Leave Go-Live Test"

    @classmethod
    def build_baseline(cls):

        cls.company, _ = Company.objects.get_or_create(
            code='GLV',
            is_deleted=False,
            defaults={
                "name": 'Go Live Co',
            },
        )

        cls.annual, _ = LeaveType.objects.get_or_create(
            code='ANNUAL-GLV',
            is_deleted=False,
            defaults={
                "name": 'Cuti Tahunan',
            },
        )

        cls.policy, _ = LeavePolicy.objects.get_or_create(
            code='ANNUAL-GLV-STD',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "leave_type": cls.annual,
                "name": 'Cuti Tahunan 12 Hari',
                "entitlement_days": Decimal('12'),
                "eligible_after_months": 12,
            },
        )

        cls.go_live = LeaveGoLive.objects.create(
            company=cls.company,
            go_live_date=GO_LIVE_DATE,
        )

    _counter = 0

    @classmethod
    def make_employee(
        cls,
        *,
        join_date=date(2020, 3, 10),
        company=None,
    ) -> Employee:
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"GLV{cls._counter:04d}",
            first_name="Sarah",
            last_name=f"Wibowo {cls._counter}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=company or cls.company,
            organization_effective_date=join_date,
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=join_date,
        )

        return Employee.objects.get(pk=employee.pk)

    def open_balance(self, employee, *, days="7.0", **extra):
        return LeaveOpeningBalanceService.create(
            data={
                "employee": employee,
                "leave_type": self.annual,
                "days": Decimal(days),
                "remark": f"Saldo per {CUTOFF_DATE} dari sistem lama",
                **extra,
            },
        )

    @classmethod
    def company_without_go_live(cls):
        """
        Perusahaan yang **tidak** punya baris `LeaveGoLive`.

        Dibuat sekali dan dipakai bersama beberapa test — bikin
        perusahaan baru per test akan menumpuk master yang tidak
        dibersihkan siapa pun, karena `TenantTestCase` tidak
        me-rollback antar test.
        """
        company = Company.objects.filter(code="NGL").first()

        if company is None:
            company = Company.objects.create(
                code="NGL",
                name="No Go-Live Co",
            )

            LeavePolicy.objects.create(
                company=company,
                leave_type=cls.annual,
                code="ANNUAL-NGL-STD",
                name="Cuti Tahunan 12 Hari",
                entitlement_days=Decimal("12"),
                eligible_after_months=12,
            )

        return company

    def bucket(self, employee, year: int = YEAR) -> LeaveBalance | None:
        return (
            LeaveBalance.objects
            .filter(
                employee=employee,
                leave_type=self.annual,
                year=year,
                is_deleted=False,
            )
            .first()
        )

    # ------------------------------------------------------------------
    # 1 — tanggal go-live
    # ------------------------------------------------------------------

    def test_cutoff_diturunkan_dari_go_live(self):
        self.assertEqual(self.go_live.cutoff_date, CUTOFF_DATE)

    def test_opening_date_ikut_go_live_kalau_dikosongkan(self):
        # Inilah buah dari langkah pertama: tanggalnya ditetapkan sekali,
        # dan tidak perlu diketik ulang di tiap baris — satu baris yang
        # meleset ke tahun lain akan mendarat di kartu saldo tahun yang
        # salah, dan yang membacanya cuma melihat saldonya nol.
        employee = self.make_employee()

        document = self.open_balance(employee)

        self.assertEqual(document.opening_date, GO_LIVE_DATE)
        self.assertEqual(document.year, YEAR)

    # ------------------------------------------------------------------
    # 2 — review: draft belum berlaku
    # ------------------------------------------------------------------

    def test_baris_baru_masuk_sebagai_draft(self):
        employee = self.make_employee()

        document = self.open_balance(employee)

        self.assertEqual(document.status, LeaveOpeningStatus.DRAFT)

    def test_draft_tidak_menyentuh_kartu_saldo(self):
        employee = self.make_employee()

        self.open_balance(employee)

        # Kartunya belum ada sama sekali. Bukan kartu berisi nol —
        # keduanya berbeda arti, dan yang kedua terbaca seperti saldo
        # yang memang habis.
        self.assertIsNone(self.bucket(employee))

    # ------------------------------------------------------------------
    # 3 — post: saldo awal jadi saldo pegawai
    # ------------------------------------------------------------------

    def test_post_membuat_saldo_awal_pegawai(self):
        employee = self.make_employee()

        document = self.open_balance(employee)

        LeaveOpeningBalanceService.post(instance=document)

        balance = self.bucket(employee)

        self.assertIsNotNone(balance)
        self.assertEqual(balance.opening_balance, Decimal("7.0"))

        # Angka yang menentukan, dan inti seluruh perubahan ini: 7,
        # bukan 19. Jatah 2026 tidak diterbitkan karena tahun itu
        # dipegang sistem lama.
        self.assertEqual(balance.entitlement, Decimal("0.0"))
        self.assertEqual(balance.remaining, Decimal("7.0"))

    def test_post_mengisi_jejaknya(self):
        employee = self.make_employee()

        document = LeaveOpeningBalanceService.post(
            instance=self.open_balance(employee),
        )

        self.assertEqual(document.status, LeaveOpeningStatus.POSTED)
        self.assertIsNotNone(document.posted_at)

    def test_unpost_menarik_angkanya_kembali(self):
        employee = self.make_employee()

        document = LeaveOpeningBalanceService.post(
            instance=self.open_balance(employee),
        )

        LeaveOpeningBalanceService.unpost(instance=document)

        self.assertEqual(
            self.bucket(employee).opening_balance,
            Decimal("0.0"),
        )

    def test_baris_yang_sudah_di_post_tidak_bisa_disunting(self):
        from django.core.exceptions import ValidationError

        employee = self.make_employee()

        document = LeaveOpeningBalanceService.post(
            instance=self.open_balance(employee),
        )

        with self.assertRaises(ValidationError):
            LeaveOpeningBalanceService.update(
                instance=document,
                data={"days": Decimal("9.0")},
            )

    def test_post_massal(self):
        employees = [self.make_employee() for _ in range(3)]

        for index, employee in enumerate(employees):
            self.open_balance(employee, days=str(7 + index))

        from apps.hr.models import LeaveOpeningBalance

        result = LeaveOpeningBalanceService.post_many(
            queryset=LeaveOpeningBalance.objects.filter(
                employee__in=employees,
                status=LeaveOpeningStatus.DRAFT,
                is_deleted=False,
            ),
        )

        self.assertEqual(result["posted"], 3)
        self.assertEqual(result["failed"], 0)

        for index, employee in enumerate(employees):
            self.assertEqual(
                self.bucket(employee).opening_balance,
                Decimal(f"{7 + index}.0"),
            )

    # ------------------------------------------------------------------
    # 4 — generator tidak boleh menimpanya
    # ------------------------------------------------------------------

    def test_generator_tidak_menerbitkan_jatah_tahun_go_live(self):
        employee = self.make_employee()

        LeaveOpeningBalanceService.post(
            instance=self.open_balance(employee),
        )

        # Dijalankan dua kali: yang paling berbahaya bukan jalan
        # pertamanya, melainkan perintah yang dijalankan ulang berbulan
        # -bulan kemudian oleh orang yang tidak tahu tenant ini pernah
        # bermigrasi.
        LeaveBalanceGenerator.run(year=YEAR, employees=[employee])
        LeaveBalanceGenerator.run(year=YEAR, employees=[employee])

        balance = self.bucket(employee)

        self.assertEqual(balance.entitlement, Decimal("0.0"))
        self.assertEqual(balance.opening_balance, Decimal("7.0"))
        self.assertEqual(balance.remaining, Decimal("7.0"))

    def test_generator_melaporkan_yang_dipegang_sistem_lama(self):
        employee = self.make_employee()

        result = LeaveBalanceGenerator.run(
            year=YEAR,
            employees=[employee],
            leave_types=[self.annual],
            dry_run=True,
        )

        self.assertEqual(result["from_opening"], 1)

    def test_pegawai_yang_masuk_setelah_go_live_tetap_dapat_jatah(self):
        # Cabang yang paling gampang ikut termatikan. Sistem ini
        # memegangnya sejak hari pertama, jadi tidak ada saldo lama yang
        # bisa menjelaskan jatah nol.
        employee = self.make_employee(join_date=date(2020, 10, 1))

        LeaveBalanceGenerator.run(
            year=2027,
            employees=[employee],
            leave_types=[self.annual],
        )

        self.assertEqual(
            self.bucket(employee, year=2027).entitlement,
            Decimal("12"),
        )

    def test_tahun_berikutnya_kembali_normal(self):
        employee = self.make_employee()

        LeaveOpeningBalanceService.post(
            instance=self.open_balance(employee),
        )

        LeaveBalanceGenerator.run(
            year=YEAR + 1,
            employees=[employee],
            leave_types=[self.annual],
        )

        # Satu tanggal migrasi tidak boleh mematikan jatah cuti
        # seseorang selamanya.
        self.assertEqual(
            self.bucket(employee, year=YEAR + 1).entitlement,
            Decimal("12"),
        )

    def test_go_live_nonaktif_mengembalikan_perhitungan_biasa(self):
        employee = self.make_employee()

        self.go_live.is_active = False
        self.go_live.save(update_fields=["is_active"])

        try:
            LeaveBalanceGenerator.run(
                year=YEAR,
                employees=[employee],
                leave_types=[self.annual],
            )

            self.assertEqual(
                self.bucket(employee).entitlement,
                Decimal("12"),
            )
        finally:
            self.go_live.is_active = True
            self.go_live.save(update_fields=["is_active"])

    # ------------------------------------------------------------------
    # 6 — saldo awal memegang tahunnya, tanpa perlu baris go-live
    # ------------------------------------------------------------------
    #
    # Lapis kedua di samping gerbang `LeaveGoLive`, dan yang menutup
    # jebakan paling mahal di alur ini: tenant yang mengimpor saldo awal
    # **tanpa** pernah menyetel Leave Go-Live. Jatahnya sudah terbit —
    # `EmploymentService.sync_leave_balances` menjalankan generator tiap
    # kali kartu pegawai disunting, tanpa syarat — jadi tanpa lapis ini
    # kartunya berbunyi 19 untuk orang yang sisanya 7, dan tidak ada
    # satu pun baris di layar yang menyebutkannya.
    #
    # Dulu ini bergantung penanda `replaces_entitlement` per baris.
    # Penanda itu dibuang: saldo awal cuma punya satu arti — saldo aktual
    # pegawai pada tanggal go-live — jadi tidak ada yang perlu
    # ditanyakan per baris, dan bawaan penanda itu (mati) justru tafsir
    # yang lebih jarang benar.

    def test_post_mematikan_jatah_tahun_itu_walau_tanpa_baris_go_live(self):
        company = self.company_without_go_live()

        employee = self.make_employee(
            join_date=date(2019, 1, 7),
            company=company,
        )

        LeaveBalanceGenerator.run(
            year=YEAR,
            employees=[employee],
            leave_types=[self.annual],
        )

        # Keadaan awal yang berbahaya itu: jatah setahun penuh sudah
        # menempel di kartunya.
        self.assertEqual(self.bucket(employee).entitlement, Decimal("12"))

        row = self.open_balance(employee, opening_date=date(2026, 8, 19))

        # Draft belum mengubah apa pun — termasuk belum berhak
        # mematikan jatah tahun berjalan.
        self.assertEqual(self.bucket(employee).entitlement, Decimal("12"))

        LeaveOpeningBalanceService.post(instance=row)

        balance = self.bucket(employee)

        self.assertEqual(balance.entitlement, Decimal("0.0"))
        self.assertEqual(balance.opening_balance, Decimal("7.0"))

        # Inti seluruh alur ini: saldo pegawainya persis angka yang
        # diserahkan HR, bukan angka itu ditambah jatah setahun penuh.
        self.assertEqual(balance.remaining, Decimal("7.0"))

    def test_unpost_mengembalikan_jatahnya(self):
        company = self.company_without_go_live()

        employee = self.make_employee(
            join_date=date(2019, 1, 7),
            company=company,
        )

        row = self.open_balance(employee, opening_date=date(2026, 8, 19))

        LeaveOpeningBalanceService.post(instance=row)
        LeaveOpeningBalanceService.unpost(instance=row)

        balance = self.bucket(employee)

        # Simetris: yang ditarik pemberiannya, dan tahun itu kembali
        # dipegang policy. Kalau tidak, satu kesalahan ketik yang
        # di-unpost meninggalkan kartu bersaldo nol tanpa jalan keluar.
        self.assertEqual(balance.entitlement, Decimal("12"))
        self.assertEqual(balance.opening_balance, Decimal("0.0"))

    def test_saldo_nol_juga_memegang_tahunnya(self):
        """
        "Jatahnya habis terpakai di sistem lama" adalah pernyataan
        tentang tahun itu, sama tegasnya dengan tujuh hari. Kalau nol
        dilewatkan, orang yang cutinya sudah habis justru mendapat dua
        belas hari lagi di sini.
        """
        company = self.company_without_go_live()

        employee = self.make_employee(
            join_date=date(2019, 1, 7),
            company=company,
        )

        LeaveBalanceGenerator.run(
            year=YEAR,
            employees=[employee],
            leave_types=[self.annual],
        )

        LeaveOpeningBalanceService.post(
            instance=self.open_balance(
                employee,
                days="0.0",
                opening_date=date(2026, 8, 19),
            ),
        )

        balance = self.bucket(employee)

        self.assertEqual(balance.entitlement, Decimal("0.0"))
        self.assertEqual(balance.remaining, Decimal("0.0"))

    # ------------------------------------------------------------------
    # 7 — bahan Review ikut di baris yang tombol Post-nya ada
    # ------------------------------------------------------------------

    def test_serializer_membawa_kelayakan_untuk_layar_review(self):
        """
        Preview yang sudah ditinggalkan tidak bisa dibuka lagi, jadi
        Join Date, Eligible Date, dan statusnya harus ikut di daftar
        tempat tombol Post berada. Tanpa itu langkah Review berarti
        menekan Post atas dasar satu angka tanpa pembanding.
        """
        employee = self.make_employee(join_date=date(2025, 11, 10))

        row = self.open_balance(
            employee,
            days="2.0",
            opening_date=date(2026, 8, 19),
        )

        data = LeaveOpeningBalanceSerializer(row).data

        # `SerializerMethodField` mengembalikan objek `date` apa adanya —
        # yang mengubahnya jadi "2025-11-10" adalah renderer JSON, jadi
        # respons HTTP-nya tetap string ISO seperti kolom tanggal lain.
        self.assertEqual(data["join_date"], date(2025, 11, 10))
        self.assertEqual(data["eligible_date"], date(2026, 11, 10))
        self.assertEqual(data["validation"], OpeningValidation.REVIEW)
        self.assertEqual(data["validation_label"], "REVIEW")
        self.assertIn("2026-11-10", data["validation_reason"])

        # REVIEW **tidak** menghalangi Post: yang ditandai perlu dibaca
        # orang, bukan ditolak sistem. Menolaknya berarti migrasi
        # berhenti pada baris yang bisa jadi memang benar.
        LeaveOpeningBalanceService.post(instance=row)

        self.assertEqual(
            self.bucket(employee).opening_balance,
            Decimal("2.0"),
        )

    def test_baris_valid_tidak_membawa_alasan(self):
        employee = self.make_employee(join_date=date(2019, 1, 7))

        data = LeaveOpeningBalanceSerializer(
            self.open_balance(employee, opening_date=date(2026, 8, 19)),
        ).data

        self.assertEqual(data["validation_label"], "VALID")
        self.assertEqual(data["validation_reason"], "")
