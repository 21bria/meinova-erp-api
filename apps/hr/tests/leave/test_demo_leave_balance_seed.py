"""
Mengunci seed saldo cuti tenant peragaan.

Yang diuji di sini adalah **pembangunan ulangnya**, bukan mekanika
kantong saldo (`test_opening_balance.py`) dan bukan kapan saldo boleh
bergerak (`test_ho_leave_workflow.py`). Tiga hal yang gagal tanpa suara
kalau seed ini rusak, dan ketiganya sudah pernah terjadi di tenant
peragaan:

1. **Angka lama menempel.** Dokumen saldo awal yang sudah di-post tidak
   bisa disunting di tempat, jadi seed yang cuma `get_or_create` akan
   melapor "sudah ada" lalu membiarkan angka kemarin berlaku selamanya.
   Yang benar: unpost → update → post.

2. **Kartu ganda.** Dijalankan dua kali harus menghasilkan tepat satu
   dokumen dan satu kartu per pasangan (pegawai, jenis cuti, tahun).

3. **Pemakaian hilang.** `recalculate_used` diam saja kalau kartunya
   belum ada, jadi cuti yang disetujui sebelum kartunya terbit
   meninggalkan `used` nol. Membangun ulang harus mengembalikannya —
   dan tidak boleh menghitungnya dua kali.

Nomor pegawainya sengaja nomor data uji yang sungguhan (`HO003`,
`HO001`, `SGA004`): daftar `OPENING_DAYS` dikunci pada nomor itu, dan
test yang memakai nomor karangan akan tetap hijau setelah daftarnya
berubah.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest import mock

from apps.core.testing.tenant import ReusableTenantTestCase

from apps.administration.models import (
    Company,
    LeavePolicy,
    LeaveType,
    Location,
    WorkCalendar,
)
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.models import (
    Employee,
    EmployeeLeave,
    EmploymentAssignment,
    LeaveBalance,
    LeaveGoLive,
    LeaveOpeningBalance,
    LeaveOpeningStatus,
    LeaveStatus,
    OrganizationAssignment,
)
from apps.hr.seeds import demo_leave_balance as seed
from apps.workflow.models import InstanceStatus


YEAR = 2026

# Senin, supaya jumlah hari kerjanya tidak bergantung pada hari apa
# test dijalankan.
MONDAY = date(YEAR, 8, 3)


class DemoLeaveBalanceSeedTestBase(ReusableTenantTestCase):
    reusable_schema_name = "fast_leave_demo_seed"

    """
    Panggung sekecil mungkin yang masih membuat seed ini punya kerja.

    Kode jenis cutinya harus **persis** `ANNUAL`: itu satu-satunya yang
    dicari `demo_leave_balance._leave_type()`, dan jenis cuti bernama
    lain membuat seluruh berkas ini menguji jalur "master belum ada".
    """

    @classmethod
    def build_baseline(cls):

        cls.company, _ = Company.objects.get_or_create(
            code='MMR',
            is_deleted=False,
            defaults={
                "name": 'Demo Mining',
            },
        )

        cls.location, _ = Location.objects.get_or_create(
            code='JKT-HO',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": 'Jakarta Head Office',
            },
        )

        cls.calendar, _ = WorkCalendar.objects.get_or_create(
            code='DEMO-OFFICE',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": 'Office Mon-Fri',
                "monday": True,
                "tuesday": True,
                "wednesday": True,
                "thursday": True,
                "friday": True,
                "saturday": False,
                "sunday": False,
                "is_default": True,
            },
        )

        cls.annual, _ = LeaveType.objects.get_or_create(
            code='ANNUAL',
            is_deleted=False,
            defaults={
                "name": 'Cuti Tahunan',
            },
        )

        cls.policy, _ = LeavePolicy.objects.get_or_create(
            code='ANNUAL-STD',
            is_deleted=False,
            defaults={
                "company": cls.company,
                "leave_type": cls.annual,
                "name": 'Cuti Tahunan 12 Hari',
                "uses_balance": True,
                "entitlement_days": Decimal('12'),
                "eligible_after_months": 12,
            },
        )

        # Bimo — pengaju di skenario UAT. Masuk sebelum go-live, jadi
        # jatah 2026-nya dipegang sistem lama dan seluruh saldonya
        # datang dari dokumen saldo awal.
        cls.bimo = cls._make_employee(
            number="HO003",
            first_name="Bimo",
            last_name="Nugroho",
            join_date=date(2025, 8, 15),
        )

        cls.sarah = cls._make_employee(
            number="HO001",
            first_name="Sarah",
            last_name="Wibowo",
            join_date=date(2019, 1, 7),
        )

        # Pegawai lama yang jatahnya habis terpakai di sistem lama —
        # baris bernilai nol di `OPENING_DAYS`.
        cls.citra = cls._make_employee(
            number="SGA004",
            first_name="Citra",
            last_name="Halimah",
            join_date=date(2021, 11, 1),
        )

        # Tidak ada di daftar saldo awal. Harus dilaporkan, bukan
        # dikarang angkanya.
        cls.tanpa_daftar = cls._make_employee(
            number="HO900",
            first_name="Tanpa",
            last_name="Daftar",
            join_date=date(2019, 5, 1),
        )

    @classmethod
    def _make_employee(
        cls,
        *,
        number: str,
        first_name: str,
        last_name: str,
        join_date: date,
    ) -> Employee:
        employee = Employee.objects.create(
            employee_number=number,
            first_name=first_name,
            last_name=last_name,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=cls.location,
            organization_effective_date=join_date,
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=join_date,
            working_calendar=cls.calendar,
        )

        # Relasi dibaca lewat `employee.employment` / `.organization`,
        # dan instance yang sudah di tangan tidak memuatnya sendiri.
        return Employee.objects.get(pk=employee.pk)

    # ------------------------------------------------------------------

    @staticmethod
    def rebuild(**kwargs):
        return seed.run(year=YEAR, log=lambda *_: None, **kwargs)

    def card(self, employee, *, year: int = YEAR) -> LeaveBalance:
        return LeaveBalance.objects.get(
            employee=employee,
            leave_type=self.annual,
            year=year,
            is_deleted=False,
        )

    @staticmethod
    def documents(employee):
        return LeaveOpeningBalance.objects.filter(
            employee=employee,
            is_deleted=False,
        )


# ----------------------------------------------------------------------
# 1 — pembangunan ulang
# ----------------------------------------------------------------------


class DemoLeaveBalanceRebuildTestCase(DemoLeaveBalanceSeedTestBase):
    """
    Seed dijalankan berkali-kali, dan tiap test membiarkan tenantnya
    dalam keadaan yang sama seperti saat ia mulai — `TenantTestCase`
    django-tenants tidak mengembalikan data antar-test.
    """

    def setUp(self):
        super().setUp()

        self.rebuild()

    def test_go_live_dinyalakan_untuk_company_pegawai_uji(self):
        row = LeaveGoLive.objects.get(company=self.company, is_deleted=False)

        self.assertEqual(row.go_live_date, date(YEAR, 9, 1))
        self.assertTrue(row.is_active)

    def test_saldo_awal_bimo_lima_hari(self):
        """5 hari, dan **bukan** 5 + 12 dari policy."""
        card = self.card(self.bimo)

        self.assertEqual(card.opening_balance, Decimal("5.0"))

        # Nol, karena tahun 2026 dipegang sistem lama. Inilah yang
        # membuat 5 tetap 5: jatah policy tidak ikut diterbitkan.
        self.assertEqual(card.entitlement, Decimal("0.0"))

        self.assertEqual(card.used, Decimal("0.0"))
        self.assertEqual(card.remaining, Decimal("5.0"))

    def test_dokumen_saldo_awal_langsung_berlaku(self):
        document = self.documents(self.bimo).get()

        self.assertEqual(document.status, LeaveOpeningStatus.POSTED)
        self.assertEqual(document.days, Decimal("5.0"))
        self.assertEqual(document.year, YEAR)
        self.assertEqual(document.opening_date, date(YEAR, 9, 1))

    def test_saldo_nol_tetap_punya_kartu_dan_dokumen(self):
        """
        "Habis terpakai di sistem lama" harus bisa dibedakan dari
        "datanya belum masuk", dan satu-satunya pembedanya adalah
        adanya dokumen bertanggal.

        Kartunya sendiri tidak dibuat `sync_balance` — nol tanpa masa
        berlaku sengaja tidak menerbitkan baris — jadi baris ini
        membuktikan langkah generator di dalam `run()` memang jalan.
        """
        document = self.documents(self.citra).get()

        self.assertEqual(document.days, Decimal("0.0"))
        self.assertEqual(document.status, LeaveOpeningStatus.POSTED)

        card = self.card(self.citra)

        self.assertEqual(card.opening_balance, Decimal("0.0"))
        self.assertEqual(card.remaining, Decimal("0.0"))

    def test_pegawai_di_luar_daftar_dilaporkan_bukan_dikarang(self):
        result = self.rebuild()

        self.assertIn("HO900", result["unlisted"])

        self.assertFalse(self.documents(self.tanpa_daftar).exists())

    def test_tahun_berikutnya_kembali_dihitung_dari_policy(self):
        """
        Go-live cuma memegang tahunnya sendiri. Kalau ia memegang
        selamanya, satu dokumen migrasi akan mematikan jatah cuti
        seseorang untuk seterusnya.
        """
        card = self.card(self.sarah, year=YEAR + 1)

        self.assertEqual(card.entitlement, Decimal("12.0"))
        self.assertEqual(card.opening_balance, Decimal("0.0"))

    def test_dijalankan_dua_kali_tidak_menggandakan_apa_pun(self):
        self.rebuild()
        self.rebuild()

        for employee in (self.bimo, self.sarah, self.citra):
            self.assertEqual(
                self.documents(employee).count(),
                1,
                f"{employee.employee_number} punya dokumen saldo awal "
                f"lebih dari satu.",
            )

            self.assertEqual(
                LeaveBalance.objects
                .filter(
                    employee=employee,
                    leave_type=self.annual,
                    year=YEAR,
                    is_deleted=False,
                )
                .count(),
                1,
                f"{employee.employee_number} punya kartu saldo ganda.",
            )

        self.assertEqual(self.card(self.bimo).opening_balance, Decimal("5.0"))

    def test_putaran_kedua_melaporkan_tidak_ada_yang_berubah(self):
        result = self.rebuild()

        self.assertEqual(result["opening"]["created"], 0)
        self.assertEqual(result["opening"]["updated"], 0)
        self.assertEqual(result["opening"]["unchanged"], 3)

    def test_saldo_yang_sudah_berlaku_bisa_disamakan_ulang(self):
        """
        Inti keluhan yang membuat berkas ini ditulis: dokumen yang sudah
        di-post menolak disunting di tempat, jadi seed yang tidak
        melewati unpost akan membiarkan angka lama menempel.
        """
        patched = dict(seed.OPENING_DAYS)
        patched["HO003"] = Decimal("9.0")

        with mock.patch.object(seed, "OPENING_DAYS", patched):
            result = self.rebuild()

        self.assertEqual(result["opening"]["updated"], 1)

        card = self.card(self.bimo)

        self.assertEqual(card.opening_balance, Decimal("9.0"))
        self.assertEqual(self.documents(self.bimo).count(), 1)

        # Dikembalikan supaya test lain di kelas ini tidak bergantung
        # pada urutan jalannya.
        self.rebuild()

        self.assertEqual(self.card(self.bimo).opening_balance, Decimal("5.0"))

    def test_reset_membersihkan_lalu_membentuk_ulang(self):
        self.rebuild(do_reset=True)

        self.assertEqual(self.documents(self.bimo).count(), 1)
        self.assertEqual(self.card(self.bimo).opening_balance, Decimal("5.0"))

        self.assertEqual(
            LeaveOpeningBalance.objects.filter(employee=self.bimo).count(),
            1,
            "Reset meninggalkan bangkai dokumen — kunci uniknya "
            "dikondisikan ke is_deleted=False, jadi baris bertanda "
            "terhapus tetap menempatinya.",
        )


# ----------------------------------------------------------------------
# 2 — saldo bertemu cuti
# ----------------------------------------------------------------------


class DemoLeaveBalanceDeductionTestCase(DemoLeaveBalanceSeedTestBase):
    """
    Skenario UAT Bimo, dari awal sampai akhir, dalam satu test.

    Satu test dan bukan lima, karena tahapannya berurutan dan
    `TenantTestCase` tidak mengembalikan data antar-test — memecahnya
    membuat hasilnya bergantung pada urutan jalannya.

    Yang dikunci di sini adalah **saldo hasil seed** yang dipotong, jadi
    angka 5-nya datang dari dokumen saldo awal, bukan dari
    `entitlement` yang diketik test. Potongan lewat alur persetujuan
    yang sungguhan ada di `test_ho_leave_workflow.py`; yang dipanggil di
    sini adalah seam yang sama persis dipakai engine saat instance-nya
    ditutup — `apply_workflow_status`.
    """

    def test_lima_lalu_dua_hari_disetujui_menyisakan_tiga(self):
        self.rebuild()

        self.assertEqual(self.card(self.bimo).remaining, Decimal("5.0"))

        leave = EmployeeLeaveService.create(
            data={
                "employee": self.bimo,
                "leave_type": self.annual,
                "start_date": MONDAY,
                "end_date": date(YEAR, 8, 4),
                "total_days": Decimal("2.0"),
                "status": LeaveStatus.DRAFT,
            },
        )

        # DRAFT tidak memotong apa pun.
        card = self.card(self.bimo)

        self.assertEqual(card.used, Decimal("0.0"))
        self.assertEqual(card.remaining, Decimal("5.0"))

        EmployeeLeaveService.set_status(
            instance=leave,
            status=LeaveStatus.SUBMITTED,
        )

        # SUBMITTED juga tidak: cuti yang belum disetujui tidak boleh
        # sudah mengurangi jatah orang.
        card = self.card(self.bimo)

        self.assertEqual(card.used, Decimal("0.0"))
        self.assertEqual(card.remaining, Decimal("5.0"))

        EmployeeLeaveService.apply_workflow_status(
            instance=leave,
            status=InstanceStatus.APPROVED,
        )

        leave.refresh_from_db()

        self.assertEqual(leave.status, LeaveStatus.APPROVED)

        card = self.card(self.bimo)

        self.assertEqual(card.used, Decimal("2.0"))
        self.assertEqual(card.remaining, Decimal("3.0"))

        # Seluruh potongannya menggerus kantong saldo awal, bukan
        # mendarat di `advance_used` — kartu bersaldo cukup tidak boleh
        # terbaca sebagai cuti dibayar di muka.
        self.assertEqual(card.opening_used, Decimal("2.0"))
        self.assertEqual(card.advance_used, Decimal("0.0"))

        # Dan membangun ulang **sesudah** cutinya disetujui tidak
        # menghitungnya dua kali, tidak pula mengembalikannya ke nol.
        self.rebuild()

        card = self.card(self.bimo)

        self.assertEqual(card.used, Decimal("2.0"))
        self.assertEqual(card.remaining, Decimal("3.0"))

        # Catatan cutinya tidak ikut dibuang oleh pembangunan ulang.
        self.assertEqual(
            EmployeeLeave.objects.filter(
                employee=self.bimo,
                is_deleted=False,
            ).count(),
            1,
        )

    def test_reset_penuh_mengembalikan_pemakaian_dari_catatan_cuti(self):
        """
        Kartunya dibuang, catatan cutinya tidak — dan `used` harus
        pulih dari sana. Kalau tidak, satu kali reset menghapus seluruh
        jejak pemakaian cuti tanpa ada yang berkurang di layar mana pun.
        """
        self.rebuild()

        leave = EmployeeLeaveService.create(
            data={
                "employee": self.sarah,
                "leave_type": self.annual,
                "start_date": MONDAY,
                "end_date": date(YEAR, 8, 4),
                "total_days": Decimal("2.0"),
                "status": LeaveStatus.DRAFT,
            },
        )

        EmployeeLeaveService.apply_workflow_status(
            instance=leave,
            status=InstanceStatus.APPROVED,
        )

        self.assertEqual(self.card(self.sarah).used, Decimal("2.0"))

        self.rebuild(do_reset=True)

        card = self.card(self.sarah)

        self.assertEqual(card.opening_balance, Decimal("7.0"))
        self.assertEqual(card.used, Decimal("2.0"))
        self.assertEqual(card.remaining, Decimal("5.0"))
