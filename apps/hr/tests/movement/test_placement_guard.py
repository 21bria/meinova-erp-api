"""
Mengunci penjagaan penempatan: mutasi harus lewat Employee Action.

Sebelum penjagaan ini ada, `OrganizationService` sama sekali tidak punya
padanan `PROTECTED_FIELDS` milik `EmploymentService` di sebelahnya. Satu
PATCH ke form Employee memindahkan orang antarperusahaan tanpa dokumen,
tanpa persetujuan, dan **tanpa jejak apa pun** — `OrganizationAssignment`
cuma menyimpan keadaan sekarang, dan `EmployeeService` bukan turunan
`BaseService` jadi `_audit()` pun tidak pernah menulis untuk jalur ini.

Akibatnya bukan cuma soal kontrol: Manpower Movement tidak bisa
menjawab Transfer In/Out sama sekali kalau mutasi boleh terjadi tanpa
meninggalkan peristiwa. Test di bawah menjaga tiga hal yang gagalnya
tidak berbunyi:

1. Perpindahan lewat form **ditolak**, bukan diterima diam-diam.
2. Yang **bukan** perpindahan tetap boleh disimpan — kalau tidak,
   penjagaannya akan dimatikan orang pertama yang mau membetulkan
   Organization Notes.
3. Penempatan **awal** tetap bebas, dan `EmployeeAction` tetap bisa
   menuliskannya.

`TenantTestCase` django-tenants tidak memanggil `super().setUpClass()`,
jadi tidak ada rollback per-test: tiap test membuat pegawainya sendiri.
"""

from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase

from apps.administration.models import Company, Department, Location, Position
from apps.hr.api.employee.services.organization_service import (
    PROTECTED_FIELDS,
    PROTECTED_FIELD_ACTIONS,
    OrganizationService,
)
from apps.hr.models import (
    Employee,
    EmployeeActionType,
    OrganizationAssignment,
)


class PlacementGuardTestCase(TenantTestCase):
    _counter = 0

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company_a = Company.objects.create(code="PGA", name="Company A")
        cls.company_b = Company.objects.create(code="PGB", name="Company B")

        cls.loc_a = Location.objects.create(
            code="PGLA", name="Location A", company=cls.company_a,
        )
        cls.loc_b = Location.objects.create(
            code="PGLB", name="Location B", company=cls.company_a,
        )

        cls.dept_a = Department.objects.create(
            code="PGDA", name="Dept A", company=cls.company_a,
        )
        cls.dept_b = Department.objects.create(
            code="PGDB", name="Dept B", company=cls.company_a,
        )

        cls.pos_a = Position.objects.create(
            code="PGPA", name="Position A", company=cls.company_a,
        )
        cls.pos_b = Position.objects.create(
            code="PGPB", name="Position B", company=cls.company_a,
        )

        # Perangkat milik Company B sendiri. `OrganizationAssignment.clean()`
        # menolak penempatan yang lokasi/department/jabatannya bukan milik
        # company-nya, jadi pindah antarperusahaan berarti seluruh
        # perangkatnya ikut pindah — bukan cuma satu kolom.
        cls.loc_c = Location.objects.create(
            code="PGLC", name="Location C", company=cls.company_b,
        )
        cls.dept_c = Department.objects.create(
            code="PGDC", name="Dept C", company=cls.company_b,
        )
        cls.pos_c = Position.objects.create(
            code="PGPC", name="Position C", company=cls.company_b,
        )

    @classmethod
    def make_employee(cls, **placement):
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"PG{cls._counter:04d}",
            first_name="Guard",
            last_name=f"Subject {cls._counter}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company_a,
            location=cls.loc_a,
            department=cls.dept_a,
            position=cls.pos_a,
            organization_effective_date=date(2026, 1, 1),
            **placement,
        )

        return Employee.objects.get(pk=employee.pk)


# ----------------------------------------------------------------------
# Yang ditolak
# ----------------------------------------------------------------------


class ProtectedPlacementTests(PlacementGuardTestCase):
    def test_pindah_company_lewat_form_ditolak(self):
        employee = self.make_employee()

        with self.assertRaises(ValidationError) as ctx:
            OrganizationService.save(
                employee=employee,
                data={"company": self.company_b},
            )

        self.assertIn("company", ctx.exception.message_dict)

    def test_pesan_penolakan_menyebut_employee_action_mana(self):
        """
        "Harus lewat Employee Action" tanpa menyebut yang mana cuma
        memindahkan kebingungan satu layar lebih dalam — alasan yang
        sama sudah ditulis `EmploymentService`.
        """
        employee = self.make_employee()

        with self.assertRaises(ValidationError) as ctx:
            OrganizationService.save(
                employee=employee,
                data={"location": self.loc_b},
            )

        message = " ".join(ctx.exception.message_dict["location"])

        self.assertIn("Employee Action", message)
        self.assertIn(PROTECTED_FIELD_ACTIONS["location"], message)

    def test_penempatan_tidak_berubah_saat_ditolak(self):
        """
        Penolakan yang terjadi setelah `setattr` akan tetap menyimpan
        kalau ada `save()` di jalur lain. Dibuktikan dari database.
        """
        employee = self.make_employee()

        with self.assertRaises(ValidationError):
            OrganizationService.save(
                employee=employee,
                data={"company": self.company_b, "location": self.loc_b},
            )

        assignment = OrganizationAssignment.objects.get(employee=employee)

        self.assertEqual(assignment.company_id, self.company_a.pk)
        self.assertEqual(assignment.location_id, self.loc_a.pk)

    def test_semua_kolom_terlindungi_ditolak(self):
        values = {
            "company": self.company_b,
            "branch": None,
            "location": self.loc_b,
            "division": None,
            "department": self.dept_b,
            "section": None,
            "position": self.pos_b,
            "job_level": None,
            "job_grade": None,
        }

        self.assertEqual(
            set(values),
            set(PROTECTED_FIELDS),
            "Kolom terlindungi bertambah tanpa test — tambahkan nilainya "
            "di sini, jangan longgarkan daftarnya.",
        )

        for field_name, changed_to in values.items():
            with self.subTest(field=field_name):
                employee = self.make_employee()

                assignment = OrganizationAssignment.objects.get(
                    employee=employee,
                )

                current = getattr(assignment, f"{field_name}_id", None)

                # Kolom yang memang kosong di data awal dibalik arahnya:
                # yang diuji "berubah", bukan "diisi nilai tertentu".
                if changed_to is None and current is None:
                    continue

                with self.assertRaises(ValidationError) as ctx:
                    OrganizationService.save(
                        employee=employee,
                        data={field_name: changed_to},
                    )

                self.assertIn(field_name, ctx.exception.message_dict)

    def test_setiap_kolom_terlindungi_punya_nama_action(self):
        """
        Kolom yang masuk `PROTECTED_FIELDS` tanpa barisnya di
        `PROTECTED_FIELD_ACTIONS` melempar `KeyError` saat menyusun
        pesan — penolakannya berubah jadi 500 persis di jalur yang
        seharusnya menjelaskan.
        """
        self.assertEqual(
            set(PROTECTED_FIELDS) - set(PROTECTED_FIELD_ACTIONS),
            set(),
        )

    def test_nama_action_menyebut_jenis_yang_benar_benar_ada(self):
        known = {
            label
            for _, label in EmployeeActionType.choices
        }

        for field_name, text in PROTECTED_FIELD_ACTIONS.items():
            with self.subTest(field=field_name):
                for name in text.split(" / "):
                    self.assertIn(
                        name,
                        known,
                        f"'{name}' bukan jenis Employee Action yang ada",
                    )


# ----------------------------------------------------------------------
# Yang tetap boleh
# ----------------------------------------------------------------------


class AllowedWritesTests(PlacementGuardTestCase):
    def test_kolom_tidak_terlindungi_tetap_bisa_disimpan(self):
        """
        Penjagaan yang menolak seluruh kiriman akan dimatikan orang
        pertama yang mau membetulkan catatan.
        """
        employee = self.make_employee()

        OrganizationService.save(
            employee=employee,
            data={"organization_notes": "dibetulkan"},
        )

        assignment = OrganizationAssignment.objects.get(employee=employee)

        self.assertEqual(assignment.organization_notes, "dibetulkan")

    def test_mengirim_nilai_yang_sama_tidak_ditolak(self):
        """
        Form mengirim seluruh isi tab apa adanya, termasuk nilai yang
        barusan dibacanya dari API. Menolak berdasarkan kunci yang
        dikirim — bukan berdasarkan perubahannya — akan membuat
        menyimpan catatan pun ditolak dengan alasan mutasi.
        """
        employee = self.make_employee()

        OrganizationService.save(
            employee=employee,
            data={
                "company": self.company_a,
                "location": self.loc_a,
                "department": self.dept_a,
                "position": self.pos_a,
                "organization_notes": "tidak ada yang pindah",
            },
        )

        assignment = OrganizationAssignment.objects.get(employee=employee)

        self.assertEqual(assignment.organization_notes, "tidak ada yang pindah")

    def test_reports_to_tetap_bisa_dibetulkan(self):
        """
        Garis pelaporan sengaja **tidak** dikunci: itu koreksi data,
        dan satu atasan yang resign berarti seluruh bawahannya harus
        dialihkan. Memaksanya lewat dokumen persetujuan bukan
        penjagaan, itu kemacetan.
        """
        employee = self.make_employee()
        supervisor = self.make_employee()

        OrganizationService.save(
            employee=employee,
            data={"reports_to": supervisor},
        )

        assignment = OrganizationAssignment.objects.get(employee=employee)

        self.assertEqual(assignment.reports_to_id, supervisor.pk)

    def test_penempatan_awal_bebas(self):
        """
        Pegawai baru boleh langsung membawa penempatannya — belum ada
        sejarah yang bisa hilang. Yang dikunci hanya perubahan
        sesudahnya.
        """
        Employee.objects.filter(employee_number="PGNEW").delete()

        employee = Employee.objects.create(
            employee_number="PGNEW",
            first_name="Baru",
            last_name="Masuk",
        )

        OrganizationService.save(
            employee=employee,
            data={
                "company": self.company_b,
                "location": self.loc_c,
                "position": self.pos_c,
                "organization_effective_date": date(2026, 3, 1),
            },
        )

        assignment = OrganizationAssignment.objects.get(employee=employee)

        self.assertEqual(assignment.company_id, self.company_b.pk)
        self.assertEqual(assignment.position_id, self.pos_c.pk)

    def test_via_action_melewati_penjagaan(self):
        employee = self.make_employee()

        OrganizationService.save(
            employee=employee,
            data={
                "company": self.company_b,
                "location": self.loc_c,
                "department": self.dept_c,
                "position": self.pos_c,
                "organization_effective_date": date(2026, 4, 1),
            },
            via_action=True,
        )

        assignment = OrganizationAssignment.objects.get(employee=employee)

        self.assertEqual(assignment.company_id, self.company_b.pk)
        self.assertEqual(assignment.location_id, self.loc_c.pk)
