"""
Mengunci perilaku saldo awal migrasi.

Empat invarian di berkas ini, dan tiga di antaranya adalah hal yang
gagal **tanpa suara** kalau rusak — angkanya tetap keluar, cuma bukan
angka yang dimaksud siapa pun:

0. Berkas ini menguji **mekanika kantongnya**, di tenant yang belum
   menyatakan tanggal go-live. Alurnya sendiri — tanggal go-live,
   draft, post, dan cakupannya untuk pegawai tanpa dokumen — ada di
   `test_go_live_flow.py`.
1. Saldo awal masuk ke kartu dan **menggantikan** jatah tahun itu,
   bukan menumpuk di atasnya.
2. `LeaveBalanceGenerator` **tidak** menghapusnya. Ini yang paling
   penting: generator dipanggil otomatis dari `EmploymentService.save()`
   tiap kali Join Date disunting, jadi kalau kantongnya ikut ditulis
   ulang, saldo migrasi seseorang hilang saat ada yang membetulkan satu
   huruf di kartu pegawainya.
3. Menghapus dokumen mengosongkan kantongnya — kalau tidak, angka yang
   sudah ditarik tetap terbaca di kartu.
4. Tanggal hangus dibekukan: mengubah policy sesudahnya tidak boleh
   menggeser tanggal yang sudah terbit.

Tiap test memakai pegawainya sendiri, jadi hasilnya tidak bergantung
pada apakah data antar-test ikut dibersihkan — `TenantTestCase`
django-tenants tidak memanggil `super().setUpClass()` sehingga tidak ada
rollback per-test.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from apps.core.testing.tenant import ReusableTenantTestCase

from apps.administration.models import Company, LeavePolicy, LeaveType
from apps.hr.api.leave.entitlement import LeaveBalanceGenerator
from apps.hr.api.leave_opening.services import LeaveOpeningBalanceService
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    LeaveBalance,
    LeaveOpeningBalance,
    OrganizationAssignment,
)


YEAR = 2026
OPENING = date(YEAR, 8, 16)


class LeaveOpeningBalanceTestCase(ReusableTenantTestCase):
    # Pilot TEST-ISO-HR-0B. Schema dipakai ulang, jadi pondasinya
    # dibangun lewat `build_baseline()` yang idempoten — `setUpClass`
    # tidak ikut di-rollback, dan `create()` tanpa syarat akan menabrak
    # unique constraint pada kelas kedua yang memakai schema ini.
    reusable_schema_name = "fast_leave"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "leave-opening-test"
        tenant.name = "Leave Opening Test"

    @classmethod
    def build_baseline(cls):
        cls.company, _ = Company.objects.get_or_create(
            code="LOB",
            is_deleted=False,
            defaults={"name": "Leave Opening Co"},
        )

        cls.annual, _ = LeaveType.objects.get_or_create(
            code="ANNUAL-LOB",
            is_deleted=False,
            defaults={"name": "Cuti Tahunan"},
        )

        cls.policy, _ = LeavePolicy.objects.get_or_create(
            code="ANNUAL-LOB-STD",
            is_deleted=False,
            defaults={
                "company": cls.company,
                "leave_type": cls.annual,
                "name": "Cuti Tahunan 12 Hari",
                "entitlement_days": Decimal("12"),
                "eligible_after_months": 12,
            },
        )

    _counter = 0

    @classmethod
    def make_employee(cls, *, join_date=date(2024, 3, 10)) -> Employee:
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"LOB{cls._counter:04d}",
            first_name="Andi",
            last_name=f"Migrasi {cls._counter}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            organization_effective_date=date(2024, 3, 10),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=join_date,
        )

        # Relasi dibaca lewat `employee.employment` / `.organization`,
        # dan instance yang sudah di tangan tidak memuatnya sendiri.
        return Employee.objects.get(pk=employee.pk)

    def open_balance(self, employee, *, days="7.0", post=True, **extra):
        """
        Membuat dokumen saldo awal, lalu **mem-post**-nya.

        Post-nya bukan detail: sejak alur go-live punya langkah Review,
        baris yang baru dibuat berstatus draft dan sengaja belum
        menyumbang satu angka pun ke kartu. Test di berkas ini menguji
        apa yang terjadi **sesudah** angkanya dinyatakan berlaku, jadi
        keduanya dijalankan bersama di sini. Yang menguji draft-nya
        sendiri ada di `test_go_live_flow.py`.
        """
        instance = LeaveOpeningBalanceService.create(
            data={
                "employee": employee,
                "leave_type": self.annual,
                "opening_date": OPENING,
                "days": Decimal(days),
                "remark": "Saldo dari sistem HR lama",
                **extra,
            },
        )

        if post:
            instance = LeaveOpeningBalanceService.post(instance=instance)

        return instance

    def bucket(self, employee, year: int = YEAR) -> LeaveBalance:
        return LeaveBalance.objects.get(
            employee=employee,
            leave_type=self.annual,
            year=year,
            is_deleted=False,
        )

    # ------------------------------------------------------------------

    def test_opening_balance_masuk_ke_kartu(self):
        employee = self.make_employee()

        document = self.open_balance(employee)

        # Tahun kartu diturunkan dari tanggal berlaku, bukan diketik.
        self.assertEqual(document.year, YEAR)

        balance = self.bucket(employee)

        self.assertEqual(balance.opening_balance, Decimal("7.0"))

        # 7, bukan 19 — dan inilah invarian yang paling menentukan di
        # seluruh fitur ini. Saldo awal **menggantikan** jatah tahun
        # itu, tidak menumpuk di atasnya: sebagiannya sudah dipakai di
        # sistem lama, dan yang tersisa persis angka yang diserahkan HR.
        #
        # Berlaku tanpa syarat apa pun begitu barisnya di-post — tidak
        # butuh penanda per baris (sudah dibuang) dan tidak butuh baris
        # `LeaveGoLive` (fixture ini sengaja tidak punya). Yang
        # ditentukan Go-Live Date adalah cakupannya untuk pegawai yang
        # **belum** punya dokumen sama sekali; diuji di
        # `test_go_live_flow.py`.
        self.assertEqual(balance.entitlement, Decimal("0.0"))
        self.assertEqual(balance.remaining, Decimal("7.0"))

    def test_kartu_dibuat_kalau_belum_ada(self):
        """
        Saldo migrasi lazim menyangkut jenis cuti yang kartunya belum
        pernah diterbitkan. Kalau kartunya tidak dibuat di sini, angka
        yang sudah diimpor tidak muncul di layar mana pun.
        """
        employee = self.make_employee()

        self.assertFalse(
            LeaveBalance.objects
            .filter(employee=employee, leave_type=self.annual)
            .exists(),
        )

        self.open_balance(employee, days="4.5")

        self.assertEqual(
            self.bucket(employee).opening_balance,
            Decimal("4.5"),
        )

    def test_generator_tidak_menghapus_saldo_awal(self):
        """
        Invarian paling rapuh di fitur ini.

        `LeaveBalanceGenerator` menulis ulang `entitlement`, dan ia
        dipanggil otomatis tiap kali data kepegawaian disunting. Kantong
        saldo awal harus lolos dari sana — kalau tidak, angka migrasi
        hilang tanpa satu pun pesan.
        """
        employee = self.make_employee()

        self.open_balance(employee)

        LeaveBalanceGenerator.run(
            year=YEAR,
            employees=[employee],
            leave_types=[self.annual],
        )

        balance = self.bucket(employee)

        # Kantong saldo awalnya utuh — itu yang diuji di sini.
        self.assertEqual(balance.opening_balance, Decimal("7.0"))

        # Dan jatahnya tetap nol walau generator baru saja dijalankan:
        # baris saldo awal yang sudah di-post memegang tahun itu, jadi
        # menjalankan generate berapa kali pun tidak menumpuk 12 hari
        # di atasnya.
        self.assertEqual(balance.entitlement, Decimal("0.0"))
        self.assertEqual(balance.remaining, Decimal("7.0"))

    def test_tidak_menerbitkan_kartu_tahun_lampau(self):
        """
        Pegawai yang masuk 2024 tidak boleh mendapat kartu 2024 dan 2025
        hanya karena masa kerjanya panjang — histori pemakaiannya tidak
        diketahui, dan menerbitkannya berarti mengarang jatah.
        """
        employee = self.make_employee(join_date=date(2022, 1, 10))

        self.open_balance(employee)

        LeaveBalanceGenerator.sync_employee(employee=employee)

        years = set(
            LeaveBalance.objects
            .filter(employee=employee, leave_type=self.annual)
            .values_list("year", flat=True)
        )

        self.assertFalse(
            {year for year in years if year < YEAR},
            "Kartu tahun lampau tidak boleh diterbitkan otomatis.",
        )

    def test_hapus_dokumen_mengosongkan_kantongnya(self):
        employee = self.make_employee()

        document = self.open_balance(employee)

        LeaveOpeningBalanceService.soft_delete(instance=document)

        balance = self.bucket(employee)

        self.assertEqual(balance.opening_balance, Decimal("0.0"))
        self.assertIsNone(balance.opening_expires_at)

    def test_pindah_jenis_cuti_mengosongkan_kartu_lama(self):
        other = LeaveType.objects.create(
            code=f"OTHER-{self._counter}",
            name="Cuti Lain",
        )

        employee = self.make_employee()

        document = self.open_balance(employee)

        # Baris yang sudah di-post ditarik dulu. Itu jalur resminya:
        # angkanya sudah menempel di kartu cuti orang, dan menggesernya
        # tanpa peristiwa yang bisa ditunjuk membuat saldo seseorang
        # berubah tanpa sebab yang terbaca di layar mana pun.
        LeaveOpeningBalanceService.unpost(instance=document)

        document = LeaveOpeningBalanceService.update(
            instance=document,
            data={"leave_type": other},
        )

        LeaveOpeningBalanceService.post(instance=document)

        self.assertEqual(
            self.bucket(employee).opening_balance,
            Decimal("0.0"),
        )

        moved = LeaveBalance.objects.get(
            employee=employee,
            leave_type=other,
            year=YEAR,
            is_deleted=False,
        )

        self.assertEqual(moved.opening_balance, Decimal("7.0"))

    def test_tanggal_hangus_dibekukan(self):
        """
        Diturunkan sekali dari policy, lalu tidak pernah dihitung ulang.
        Policy yang berubah besok tidak boleh memundurkan tanggal yang
        sudah dikabarkan ke pegawai.
        """
        self.policy.allow_carry_over = True
        self.policy.carry_over_expiry_months = 6
        self.policy.save(
            update_fields=["allow_carry_over", "carry_over_expiry_months"],
        )

        try:
            employee = self.make_employee()

            document = self.open_balance(employee)

            # Anchor-nya tanggal berlaku, bukan 1 Januari: tenant yang
            # go-live bulan Agustus tidak boleh mendapat tanggal hangus
            # yang sudah lewat pada hari pertama sistemnya dipakai.
            self.assertEqual(document.expires_at, date(2027, 2, 16))
            self.assertEqual(
                self.bucket(employee).opening_expires_at,
                date(2027, 2, 16),
            )

            self.policy.carry_over_expiry_months = 3
            self.policy.save(update_fields=["carry_over_expiry_months"])

            LeaveOpeningBalanceService.unpost(instance=document)

            document = LeaveOpeningBalanceService.update(
                instance=document,
                data={"days": Decimal("8.0")},
            )

            document = LeaveOpeningBalanceService.post(instance=document)

            self.assertEqual(document.expires_at, date(2027, 2, 16))
            self.assertEqual(
                self.bucket(employee).opening_balance,
                Decimal("8.0"),
            )
        finally:
            self.policy.allow_carry_over = False
            self.policy.carry_over_expiry_months = None
            self.policy.save(
                update_fields=[
                    "allow_carry_over",
                    "carry_over_expiry_months",
                ],
            )

    def test_tanpa_masa_berlaku_di_policy_tidak_hangus(self):
        employee = self.make_employee()

        document = self.open_balance(employee)

        self.assertIsNone(document.expires_at)

    def test_saldo_negatif_ditolak(self):
        from django.core.exceptions import ValidationError

        employee = self.make_employee()

        with self.assertRaises(ValidationError):
            self.open_balance(employee, days="-3.0")

    def test_tanggal_sebelum_join_date_ditolak(self):
        from django.core.exceptions import ValidationError

        employee = self.make_employee(join_date=date(2026, 12, 1))

        with self.assertRaises(ValidationError):
            self.open_balance(employee)

    def test_duplikat_ditolak(self):
        from django.core.exceptions import ValidationError

        employee = self.make_employee()

        self.open_balance(employee)

        with self.assertRaises(ValidationError):
            self.open_balance(employee, days="3.0")

        self.assertEqual(
            LeaveOpeningBalance.objects
            .filter(employee=employee, is_deleted=False)
            .count(),
            1,
        )
