"""
Dua baris untuk satu kelompok data, dan keduanya bekerja.

Stage 3A berhenti di sini: `EmployeeDataPolicy` hanya bisa membolehkan
satu role per kelompok, karena `visible_employees_q()` berhenti sesudah
aturan global pertama. Stage 3A.1 mengelompokkan aturan menurut
**sasarannya** (company/location/employee group) dan menggabungkan
aturan di sasaran yang sama dengan OR. `role` tetap FK tunggal; yang
menyusun gabungannya barisnya, bukan kolomnya — jadi tidak ada
migration.

Berkas ini menguji tiga hal yang harus benar sekaligus, dan yang
ketiganya adalah alasan perubahan sekecil ini perlu dikunci:

1. **baris kedua berlaku** — HR Manager dan Finance Manager sama-sama
   membaca kelompok payroll, HR Admin dan HR Manager sama-sama membaca
   dokumen;
2. **penutupan antar-sasaran tidak ikut jadi izin** — baris yang lebih
   khusus tetap mencabut jangkauan baris global di sasarannya. Itu
   satu-satunya bentuk "tidak boleh" yang dipunyai master ini, dan
   menyatukan semua baris dengan OR akan menghapusnya diam-diam;
3. **lapisan cakupan tidak tergeser** — kelompok data menjawab "jenis
   data apa", bukan "baris siapa". Role yang tidak memberi izin dokumen
   tidak boleh meminjamkan cakupannya untuk dokumen, dan itu tetap
   dijawab `ROLE_AWARE_DATA_SCOPE` (Stage 3A), bukan oleh policy.

Tiap skenario punya assertion negatif. Test kerahasiaan yang cuma
memeriksa "yang boleh melihat memang melihat" akan tetap hijau di mesin
yang tidak menutup apa pun.
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings

from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.services.role_assignment import grant_role
from apps.accounts.models import (
    AuthorityMode,
    AuthorityResourceType,
    Role,
)
from apps.administration.models import (
    Company,
    Department,
    DocumentType,
    EmployeeDataPolicy,
    EmployeeDataSubject,
    Location,
    Position,
)
from apps.hr.api.employee.visibility import EmployeeDataVisibility
from apps.hr.models import (
    Employee,
    EmployeeDocument,
    OrganizationAssignment,
)


JOIN = date(2020, 1, 6)

DOCUMENT = str(EmployeeDataSubject.FIELD_DOCUMENT)
PAYROLL = str(EmployeeDataSubject.FIELD_PAYROLL)

DOCUMENTS_URL = "/api/hr/employee-documents/"
PAYROLL_URL = "/api/hr/payroll-assignments/"


class EmployeeDataPolicyCompositionTests(TenantTestCase):
    """
    Dua company, dua lokasi di salah satunya, dan satu dokumen di tiap
    sudut.

    Dokumen pegawai dipakai sebagai resource utama karena ia justru
    kelompok yang **belum punya baris sama sekali** sebelum 3A.1 — jadi
    panggungnya sekaligus memperlihatkan bedanya "tanpa aturan =
    terlihat" dan "diatur dua baris".
    """

    _n = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "edp-compose"
        tenant.name = "EDP Composition"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company_a = Company.objects.create(code="ECA", name="Company A")
        cls.company_b = Company.objects.create(code="ECB", name="Company B")

        cls.site_a1 = Location.objects.create(
            company=cls.company_a, code="ECA-1", name="Site A1")
        cls.site_a2 = Location.objects.create(
            company=cls.company_a, code="ECA-2", name="Site A2")
        cls.site_b1 = Location.objects.create(
            company=cls.company_b, code="ECB-1", name="Site B1")

        cls.dept_a = Department.objects.create(
            company=cls.company_a, code="ECA-OPS", name="Operations A")
        cls.dept_b = Department.objects.create(
            company=cls.company_b, code="ECB-OPS", name="Operations B")

        cls.document_type = DocumentType.objects.create(
            code="EC-KTP", name="KTP")

        cls.target_a1 = cls.make_employee(
            cls.company_a, cls.site_a1, cls.dept_a, with_user=False)
        cls.target_a2 = cls.make_employee(
            cls.company_a, cls.site_a2, cls.dept_a, with_user=False)
        cls.target_b1 = cls.make_employee(
            cls.company_b, cls.site_b1, cls.dept_b, with_user=False)

        for employee in (cls.target_a1, cls.target_a2, cls.target_b1):
            EmployeeDocument.objects.create(
                employee=employee,
                document_type=cls.document_type,
                document_name=f"KTP {employee.employee_number}",
            )

        cls.view_document = Permission.objects.get(
            content_type__app_label="hr", codename="view_employeedocument")
        cls.view_payroll_assignment = Permission.objects.get(
            content_type__app_label="hr",
            codename="view_payrollassignment")

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(cls, company, location, department, *, with_user=True):
        User = get_user_model()

        cls._n += 1

        user = None

        if with_user:
            user = User.objects.create_user(
                username=f"ec.user{cls._n}",
                email=f"ec.user{cls._n}@example.test",
                password="Test-Only#Pw1",
            )

        position = Position.objects.create(
            company=company,
            department=department,
            code=f"EC-POS{cls._n}",
            name=f"Position {cls._n}",
        )

        employee = Employee.objects.create(
            employee_number=f"EC-{cls._n:03d}",
            first_name="Compose",
            last_name=f"User {cls._n}",
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=company,
            location=location,
            department=department,
            position=position,
            organization_effective_date=JOIN,
        )

        return Employee.objects.get(pk=employee.pk)

    # ------------------------------------------------------------------
    # Deklarasi maksud — milik test ini, bukan skema
    # ------------------------------------------------------------------
    #
    # Bentuk panggilannya tidak berubah, jadi tiap skenario di bawah
    # tetap terbaca seperti sebelumnya. Yang berubah **ke mana**
    # deklarasinya disimpan: dulu ke kolom `Role` dan baris
    # `RoleDataPermission`, sekarang ke dict Python milik kelas ini.
    #
    # Sampai Wave C penerjemahnya `backfill_authority()` — perkakas
    # migrasi yang membaca model lama. Model itu sudah dihapus, jadi
    # pemetaannya ada di `grant()`, dengan aturan yang sama persis:
    #
    #   ALL      -> UNRESTRICTED
    #   OWN      -> PLACEMENT pada level yang disebut
    #   EXPLICIT -> EXPLICIT berisi baris yang dideklarasikan
    #
    # Termasuk kasus yang paling mudah salah: `EXPLICIT` **tanpa** baris
    # tetap berarti tanpa kewenangan, bukan tanpa batasan.

    ALL = "all"
    OWN = "own"
    EXPLICIT = "explicit"

    _declared: dict = {}

    @classmethod
    def make_role(cls, code, *, mode=EXPLICIT, level="", permissions=()):
        cls._n += 1

        role = Role.objects.create(code=f"{code}-{cls._n}", name=code.title())

        cls._declared[role.pk] = {"mode": mode, "level": level, "rows": []}

        if permissions:
            role.permissions.add(*permissions)

        return role

    @classmethod
    def grant(cls, user, *roles):
        """
        Memberi role **berikut** kewenangan yang dideklarasikan test ini.

        Sejak Stage 4H `Role` menjawab WHAT saja: penugasan tidak lagi
        mewarisi `data_scope_mode`/`RoleDataPermission`, jadi
        `roles.add()` telanjang menghasilkan pemegang yang tidak melihat
        apa pun — dan seluruh pernyataan **positif** di berkas ini
        jatuh, sementara pernyataan penolakannya tetap hijau karena
        sebab yang salah.

        Test di sini menyatakan cakupannya lewat `make_role(mode=...)`
        dan `scope_row(...)`. Bentuk itu dipertahankan: yang diuji
        berkas ini penyaringan berkas/kebijakan, bukan kontrak
        pembuatan penugasan — dan menuliskan kewenangan penugasan satu
        per satu di dua puluh tempat cuma mengaburkan apa yang
        sebenarnya diuji.

        Penerjemahnya `grant()` di bawah, dengan aturan yang sama
        persis seperti `backfill_authority()` dulu. Kontrak pembuatan
        penugasan yang sebenarnya diuji di
        `apps.accounts.tests.test_assignment_creation_contract`.
        """
        for role in roles:
            declared = cls._declared.get(
                role.pk, {"mode": cls.EXPLICIT, "level": "", "rows": []})

            if declared["mode"] == cls.ALL:
                grant_role(user, role, mode=AuthorityMode.UNRESTRICTED)
            elif declared["mode"] == cls.OWN:
                grant_role(
                    user, role,
                    mode=AuthorityMode.PLACEMENT,
                    level=declared["level"],
                )
            else:
                grant_role(
                    user, role,
                    mode=AuthorityMode.EXPLICIT,
                    authorities=declared["rows"],
                )

    @classmethod
    def scope_row(cls, role, resource_type, resource=None):
        """Satu nilai cakupan untuk `role`, dicatat sebagai deklarasi."""
        cls._declared[role.pk]["rows"].append(
            (resource_type, getattr(resource, "pk", None)))

    def policy(self, code, *, subject, role=None, order=10,
               company=None, location=None, allow_self=False):
        return EmployeeDataPolicy.objects.create(
            code=code,
            name=code,
            subject=subject,
            role=role,
            company=company,
            location=location,
            allow_self=allow_self,
            allow_manager=False,
            allow_department_head=False,
            sort_order=order,
            is_active=True,
        )

    def setUp(self):
        super().setUp()

        EmployeeDataPolicy.objects.all().delete()

        # `RolePermissionBackend` dan `DataScopeService` sama-sama
        # menyimpan hasilnya di instance user; test yang mengubah role
        # sesudah cache terisi akan membaca keadaan lama.
        for user in get_user_model().objects.all():
            for attribute in ("_role_perm_cache", "_data_scope_cache"):
                if hasattr(user, attribute):
                    delattr(user, attribute)

    # ------------------------------------------------------------------
    # Pembacaan
    # ------------------------------------------------------------------

    def visible_to(self, user, *, subject) -> set[str]:
        """Nomor pegawai yang kelompok `subject`-nya boleh dibaca."""
        allowed = EmployeeDataVisibility.visible_employees_q(
            subject=subject,
            user=user,
        )

        queryset = Employee.objects.filter(is_deleted=False)

        if allowed is not None:
            queryset = queryset.filter(allowed)

        return set(queryset.values_list("employee_number", flat=True))

    def api_client(self, user) -> APIClient:
        """
        Klien yang **menyebut domain tenant**. Tanpa `HTTP_HOST`
        requestnya dilayani dari schema `public`, dan gejalanya bukan
        404 melainkan `relation "..." does not exist`.

        Cache dibuang tiap kali klien dibuat. `force_authenticate()`
        memakai **objek user yang sama**, dan cache cakupan hidup di
        instance itu — jadi tanpa ini jawaban mode sebelumnya terbaca
        lagi di mode berikutnya, dan test dua-mode lulus karena alasan
        yang salah.
        """
        for attribute in ("_role_perm_cache", "_data_scope_cache"):
            if hasattr(user, attribute):
                delattr(user, attribute)

        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

        client.force_authenticate(user=user)

        return client

    def documents_seen(self, user) -> set[int]:
        """
        Id pegawai yang dokumennya terbaca lewat endpoint asli.

        Dibaca dari `employee`, bukan `employee_number`:
        `EmployeeDocumentSerializer` memulangkan relasinya sebagai pk,
        dan menebak nama field yang tidak ada akan gagal sebagai
        `KeyError` — jauh dari pertanyaan yang sedang diuji.
        """
        response = self.api_client(user).get(DOCUMENTS_URL)

        self.assertEqual(
            response.status_code,
            200,
            msg=f"Daftar dokumen menjawab {response.status_code}.",
        )

        return {row["employee"] for row in response.data["data"]}

    # ==================================================================
    # 1–3 — komposisi baris
    # ==================================================================

    def test_two_global_rows_both_take_effect(self):
        """
        **1.** Inti 3A.1. Dua baris global untuk kelompok dokumen; role
        di baris pertama dan role di baris kedua sama-sama membaca.
        Sebelum ini baris kedua tidak pernah dinilai.
        """
        admin_role = self.make_role("EC-DOC-ADMIN")
        manager_role = self.make_role("EC-DOC-MANAGER")

        admin = self.make_employee(self.company_a, self.site_a1, self.dept_a)
        manager = self.make_employee(self.company_a, self.site_a1, self.dept_a)
        outsider = self.make_employee(
            self.company_a, self.site_a1, self.dept_a)

        self.grant(admin.user, admin_role)
        self.grant(manager.user, manager_role)

        self.policy(
            "EC-DOC-1", subject=DOCUMENT, role=admin_role, order=10)
        self.policy(
            "EC-DOC-2", subject=DOCUMENT, role=manager_role, order=20)

        number = self.target_a1.employee_number

        self.assertIn(number, self.visible_to(admin.user, subject=DOCUMENT))

        self.assertIn(
            number,
            self.visible_to(manager.user, subject=DOCUMENT),
            msg=(
                "Baris global kedua tidak berlaku — penilaian kembali "
                "berhenti sesudah baris pertama."
            ),
        )

        self.assertNotIn(
            number,
            self.visible_to(outsider.user, subject=DOCUMENT),
            msg="Menggabungkan dua baris membuka untuk semua orang.",
        )

    def test_hr_manager_and_finance_manager_both_read_the_payroll_subject(
        self,
    ):
        """
        **2, dan 3A.1-3.** Dua meja yang memang berbeda pekerjaannya —
        yang menghitung dan yang menyetujui — sama-sama perlu membaca
        angkanya per orang. Sampai 3A.1 hanya satu dari keduanya bisa
        dinyatakan, dan menambahkan yang kedua justru mencabut yang
        pertama.
        """
        hr_manager_role = self.make_role("EC-HR-MANAGER")
        finance_role = self.make_role("EC-FINANCE-MANAGER")

        hr_manager = self.make_employee(
            self.company_a, self.site_a1, self.dept_a)
        finance = self.make_employee(
            self.company_a, self.site_a1, self.dept_a)
        unrelated = self.make_employee(
            self.company_a, self.site_a1, self.dept_a)

        self.grant(hr_manager.user, hr_manager_role)
        self.grant(finance.user, finance_role)

        self.policy(
            "EC-PAY-HR", subject=PAYROLL, role=hr_manager_role, order=10)
        self.policy(
            "EC-PAY-FIN", subject=PAYROLL, role=finance_role, order=20)

        number = self.target_a1.employee_number

        self.assertIn(
            number,
            self.visible_to(hr_manager.user, subject=PAYROLL),
            msg="HR Manager kehilangan kelompok payroll-nya.",
        )

        self.assertIn(
            number,
            self.visible_to(finance.user, subject=PAYROLL),
            msg="Finance Manager tidak mendapat kelompok payroll.",
        )

        self.assertNotIn(
            number,
            self.visible_to(unrelated.user, subject=PAYROLL),
            msg="Kelompok payroll terbuka untuk yang tidak disebut.",
        )

    def test_deleting_one_rule_leaves_the_other_working(self):
        """
        **3.** Baris saling menambah, bukan saling menopang. Menghapus
        baris Finance tidak boleh ikut mematikan baris HR — dan yang
        dihapus memang berhenti berlaku.
        """
        hr_role = self.make_role("EC-DEL-HR")
        finance_role = self.make_role("EC-DEL-FIN")

        hr_user = self.make_employee(self.company_a, self.site_a1, self.dept_a)
        finance = self.make_employee(
            self.company_a, self.site_a1, self.dept_a)

        self.grant(hr_user.user, hr_role)
        self.grant(finance.user, finance_role)

        self.policy("EC-DEL-1", subject=PAYROLL, role=hr_role, order=10)

        removed = self.policy(
            "EC-DEL-2", subject=PAYROLL, role=finance_role, order=20)

        number = self.target_a1.employee_number

        self.assertIn(number, self.visible_to(finance.user, subject=PAYROLL))

        removed.delete()

        self.assertIn(
            number,
            self.visible_to(hr_user.user, subject=PAYROLL),
            msg=(
                "Menghapus satu baris ikut mematikan baris lain di "
                "kelompok yang sama."
            ),
        )

        self.assertNotIn(
            number,
            self.visible_to(finance.user, subject=PAYROLL),
            msg="Baris yang sudah dihapus masih membolehkan.",
        )

    def test_a_narrower_rule_still_shadows_the_global_one(self):
        """
        **Sisi sebaliknya, dan yang paling mudah hilang.**

        Penutupan antar-sasaran adalah satu-satunya "tidak boleh" yang
        dipunyai master ini: baris `company=A` memang dimaksudkan
        mencabut jangkauan baris global di Company A. Kalau seluruh
        baris digabung dengan OR tanpa memandang sasaran, pencabutan
        itu berubah jadi izin — dan tidak ada yang berbunyi.
        """
        global_role = self.make_role("EC-SHADOW-GLOBAL")
        company_role = self.make_role("EC-SHADOW-A")

        holder = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        self.grant(holder.user, global_role)

        self.policy(
            "EC-SHADOW-1", subject=DOCUMENT, role=global_role, order=10)

        self.policy(
            "EC-SHADOW-2",
            subject=DOCUMENT,
            role=company_role,
            company=self.company_a,
            order=20,
        )

        visible = self.visible_to(holder.user, subject=DOCUMENT)

        self.assertIn(
            self.target_b1.employee_number,
            visible,
            msg="Baris global berhenti berlaku di luar sasaran khusus.",
        )

        self.assertNotIn(
            self.target_a1.employee_number,
            visible,
            msg=(
                "Baris `company=A` tidak lagi menutupi baris global — "
                "pencabutan berubah jadi izin."
            ),
        )

    # ==================================================================
    # 4–8 — dokumen pegawai, lewat endpoint aslinya
    # ==================================================================

    def test_employee_reads_own_document(self):
        """
        **4.** Swalayan. Barisnya menyebut HR Admin, dan `allow_self`
        di baris yang sama-lah yang membuat pegawainya sendiri tetap
        bisa membuka berkasnya.
        """
        admin_role = self.make_role("EC-SELF-ADMIN")

        employee = self.make_employee(
            self.company_a,
            self.site_a1,
            self.dept_a,
        )

        own_role = self.make_role(
            "EC-SELF-EMPLOYEE",
            mode=EmployeeDataPolicyCompositionTests.EXPLICIT,
            permissions=[self.view_document],
        )

        self.scope_row(own_role, AuthorityResourceType.OWN)

        self.grant(employee.user, own_role)

        EmployeeDocument.objects.create(
            employee=employee,
            document_type=self.document_type,
            document_name="KTP sendiri",
        )

        self.policy(
            "EC-SELF-1",
            subject=DOCUMENT,
            role=admin_role,
            allow_self=True,
            order=10,
        )

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            seen = self.documents_seen(employee.user)

        self.assertIn(
            employee.pk,
            seen,
            msg="Pegawai kehilangan berkasnya sendiri.",
        )

    def test_employee_cannot_read_another_employee_document(self):
        """
        **5.** Batas swalayan. `allow_self` berhenti di dirinya
        sendiri, dan cakupan `own` menutup sisanya.
        """
        admin_role = self.make_role("EC-OTHER-ADMIN")

        employee = self.make_employee(
            self.company_a,
            self.site_a1,
            self.dept_a,
        )

        own_role = self.make_role(
            "EC-OTHER-EMPLOYEE",
            permissions=[self.view_document],
        )

        self.scope_row(own_role, AuthorityResourceType.OWN)

        self.grant(employee.user, own_role)

        EmployeeDocument.objects.create(
            employee=employee,
            document_type=self.document_type,
            document_name="KTP sendiri",
        )

        self.policy(
            "EC-OTHER-1",
            subject=DOCUMENT,
            role=admin_role,
            allow_self=True,
            order=10,
        )

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            seen = self.documents_seen(employee.user)

        self.assertNotIn(
            self.target_a1.pk,
            seen,
            msg="Pegawai membaca berkas rekannya.",
        )

        self.assertNotIn(
            self.target_b1.pk,
            seen,
            msg="Pegawai membaca berkas company lain.",
        )

    def test_hr_admin_document_access_stays_inside_its_own_scope(self):
        """
        **6.** HR Admin bercakupan Site A1: berkas Site A1 terbaca,
        berkas Site A2 — company yang sama — tidak.
        """
        admin_role = self.make_role(
            "EC-ADMIN-SITE",
            permissions=[self.view_document],
        )

        self.scope_row(
            admin_role,
            AuthorityResourceType.LOCATION,
            self.site_a1,
        )

        admin = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        self.grant(admin.user, admin_role)

        self.policy(
            "EC-ADMIN-1", subject=DOCUMENT, role=admin_role, order=10)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            seen = self.documents_seen(admin.user)

        self.assertIn(self.target_a1.pk, seen)

        self.assertNotIn(
            self.target_a2.pk,
            seen,
            msg="Cakupan lokasi tidak menahan berkas lokasi lain.",
        )

        self.assertNotIn(self.target_b1.pk, seen)

    def test_hr_manager_document_access_stays_inside_its_own_scope(self):
        """
        **7.** HR Manager bercakupan Company A, lewat baris policy
        **kedua** — jadi test ini sekaligus membuktikan baris kedua
        bekerja sampai ke endpoint, bukan hanya di `Q`-nya.
        """
        admin_role = self.make_role("EC-MGR-ADMIN")

        manager_role = self.make_role(
            "EC-MGR-COMPANY",
            permissions=[self.view_document],
        )

        self.scope_row(
            manager_role,
            AuthorityResourceType.COMPANY,
            self.company_a,
        )

        manager = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        self.grant(manager.user, manager_role)

        # Baris HR Admin lebih dulu; baris HR Manager kedua.
        self.policy(
            "EC-MGR-1", subject=DOCUMENT, role=admin_role, order=10)
        self.policy(
            "EC-MGR-2", subject=DOCUMENT, role=manager_role, order=20)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            seen = self.documents_seen(manager.user)

        self.assertIn(self.target_a1.pk, seen)
        self.assertIn(self.target_a2.pk, seen)

        self.assertNotIn(
            self.target_b1.pk,
            seen,
            msg="Cakupan company tidak menahan berkas company lain.",
        )

    def test_an_unrelated_broad_role_cannot_widen_document_access(self):
        """
        **8.** Role berjangkauan luas yang **tidak disebut** baris
        dokumen mana pun tetap tidak membacanya — meski cakupannya
        seluas tenant dan izin modelnya ada.

        Ini lapisan policy yang menolak, bukan cakupan: justru karena
        cakupannya sengaja dibuat `all`.
        """
        admin_role = self.make_role("EC-WIDE-ADMIN")

        broad_role = self.make_role(
            "EC-WIDE-EXEC",
            mode=EmployeeDataPolicyCompositionTests.ALL,
            permissions=[self.view_document],
        )

        executive = self.make_employee(
            self.company_a, self.site_a1, self.dept_a)

        self.grant(executive.user, broad_role)

        self.policy(
            "EC-WIDE-1", subject=DOCUMENT, role=admin_role, order=10)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            seen = self.documents_seen(executive.user)

        self.assertNotIn(
            self.target_a1.pk,
            seen,
            msg=(
                "Role berjangkauan luas membaca dokumen tanpa disebut "
                "satu baris policy pun."
            ),
        )

        self.assertNotIn(self.target_b1.pk, seen)

    # ==================================================================
    # 9–10 — lapisan cakupan tidak tergeser
    # ==================================================================

    def test_a_broad_role_without_the_payroll_permission_is_denied(self):
        """
        **9.** Direksi dan Executive: cakupan seluas tenant, tanpa izin
        payroll. Ditolak di gerbang izin — 403, sebelum satu baris pun
        disaring. Keputusan Stage 3A #2, dikunci di sini supaya 3A.1
        tidak diam-diam membukanya lewat baris policy baru.
        """
        finance_role = self.make_role("EC-BOD-FINANCE")

        board = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        board_role = self.make_role("EC-BOD", mode=EmployeeDataPolicyCompositionTests.ALL)

        self.grant(board.user, board_role)

        # Dua baris payroll, dan tak satu pun menyebut BOD.
        self.policy(
            "EC-BOD-1", subject=PAYROLL, role=finance_role, order=10)
        self.policy(
            "EC-BOD-2", subject=PAYROLL, role=board_role, order=20)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            response = self.api_client(board.user).get(PAYROLL_URL)

        self.assertEqual(
            response.status_code,
            403,
            msg=(
                "Cakupan seluas tenant tanpa `hr.view_payrollassignment` "
                "tidak lagi ditolak — baris policy tidak boleh menjadi "
                "jalan masuk kedua."
            ),
        )

    def test_document_permission_does_not_borrow_a_broader_roles_scope(self):
        """
        **10, dan 3A.1-5.** Izin dokumen datang dari role bercakupan
        Site A1; role kedua memberi cakupan seluruh Company A tanpa
        izin dokumen. Yang berlaku cakupan role **pemberi izinnya**.

        Diuji di kedua mode: jalur lama memang meminjam, dan itu yang
        membuat saklarnya masih ada.
        """
        admin_role = self.make_role("EC-BORROW-ADMIN")

        narrow_role = self.make_role(
            "EC-BORROW-NARROW",
            permissions=[self.view_document],
        )

        self.scope_row(
            narrow_role,
            AuthorityResourceType.LOCATION,
            self.site_a1,
        )

        wide_role = self.make_role("EC-BORROW-WIDE")

        self.scope_row(
            wide_role,
            AuthorityResourceType.COMPANY,
            self.company_a,
        )

        holder = self.make_employee(self.company_a, self.site_a1, self.dept_a)

        self.grant(holder.user, narrow_role, wide_role)

        # Baris kedua menyebut role sempit itu — komposisi 3A.1 dan
        # cakupan 3A dinilai bersama, bukan bergantian.
        self.policy(
            "EC-BORROW-1", subject=DOCUMENT, role=admin_role, order=10)
        self.policy(
            "EC-BORROW-2", subject=DOCUMENT, role=narrow_role, order=20)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            aware = self.documents_seen(holder.user)

        self.assertIn(self.target_a1.pk, aware)

        self.assertNotIn(
            self.target_a2.pk,
            aware,
            msg=(
                "Izin dokumen memakai cakupan role yang tidak "
                "memberikannya — peminjaman lintas-role kembali."
            ),
        )

        with override_settings(ROLE_AWARE_DATA_SCOPE=False):
            legacy = self.documents_seen(holder.user)

        self.assertIn(
            self.target_a2.pk,
            legacy,
            msg=(
                "Jalur lama berhenti meminjam. Kalau ini yang berubah, "
                "saklarnya sudah tidak diperlukan — cabut, jangan "
                "longgarkan testnya."
            ),
        )
