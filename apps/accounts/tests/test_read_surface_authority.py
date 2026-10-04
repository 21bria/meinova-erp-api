"""
Permukaan baca yang tersisa: pelamar, riwayat import, dan dropdown.

Stage 3B menutup dashboard, laporan, dan export. Stage 3B.1 menutup
lampiran. Yang tertinggal dua induk yang **sendirinya** terbuka —
`hr.Candidate` dan `imports.ImportJob` — dan karena lampiran mewarisi
otoritas induknya, keduanya adalah sebab terakhir berkas masih terbaca
luas. Menutup induknya menutup keduanya sekaligus, dan itu yang diuji
di sini: bukan "berkasnya tersembunyi", melainkan **berkasnya menyempit
karena induknya menyempit**.

Panggungnya dua perusahaan dengan satu lowongan di masing-masing,
seorang pelamar di tiap lowongan, dan berkas lamaran yang menempel di
keduanya.

Tiap skenario punya assertion negatif. Test otoritas yang cuma
memeriksa "yang boleh memang bisa" akan tetap hijau pada mesin yang
tidak menutup apa pun.
"""

from __future__ import annotations

import tempfile

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.services.role_assignment import grant_role
from apps.accounts.models import (
    AuthorityResourceType,
    AuthorityMode,
    Role,
)
from apps.administration.models import Company, Department, Location, Position
from apps.hr.models import Candidate, JobVacancy
from apps.imports.models import ImportJob
from apps.uploads.models import UploadedFile
from apps.uploads.services import UploadService


JOIN = date(2020, 1, 6)

CANDIDATES_URL = "/api/hr/candidates/"
CANDIDATE_LOOKUP_URL = "/api/hr/lookup/candidates/"
VACANCY_LOOKUP_URL = "/api/hr/lookup/job-vacancies/"
JOBS_URL = "/api/imports/jobs/"
UPLOADS_URL = "/api/uploads/"

# Modul yang sasarannya **dijaga izin** (`PayslipViewSet`), jadi riwayat
# importnya ikut dijaga. Modul yang sasarannya terbuka tetap terbuka —
# itu memang aturannya, dan diuji terpisah di bawah.
GUARDED_MODULE = "payroll/payslips"


@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="rsa-test-"))
class ReadSurfaceAuthorityTests(TenantTestCase):
    _n = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "read-surface"
        tenant.name = "Read Surface"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company_a = Company.objects.create(code="RSA", name="Company A")
        cls.company_b = Company.objects.create(code="RSB", name="Company B")

        cls.site_a = Location.objects.create(
            company=cls.company_a, code="RSA-1", name="Site A")
        cls.site_b = Location.objects.create(
            company=cls.company_b, code="RSB-1", name="Site B")

        cls.dept_a = Department.objects.create(
            company=cls.company_a, code="RSA-OPS", name="Ops A")
        cls.dept_b = Department.objects.create(
            company=cls.company_b, code="RSB-OPS", name="Ops B")

        cls.vacancy_a = JobVacancy.objects.create(
            code="VAC-A", title="Operator A",
            company=cls.company_a, location=cls.site_a,
            open_date=JOIN,
        )
        cls.vacancy_b = JobVacancy.objects.create(
            code="VAC-B", title="Operator B",
            company=cls.company_b, location=cls.site_b,
            open_date=JOIN,
        )

        cls.view_candidate = Permission.objects.get(
            content_type__app_label="hr", codename="view_candidate")
        cls.view_payslip = Permission.objects.get(
            content_type__app_label="payroll", codename="view_payslip")

        cls.candidate_a = cls.make_candidate(cls.vacancy_a)
        cls.candidate_b = cls.make_candidate(cls.vacancy_b)

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    @classmethod
    def make_candidate(cls, vacancy):
        cls._n += 1

        return Candidate.objects.create(
            candidate_number=f"CAND-{cls._n:03d}",
            full_name=f"Pelamar {cls._n}",
            email=f"pelamar{cls._n}@example.test",
            vacancy=vacancy,
            applied_date=JOIN,
        )

    @classmethod
    def make_user(cls, roles=()):
        User = get_user_model()

        cls._n += 1

        user = User.objects.create_user(
            username=f"rsa.user{cls._n}",
            email=f"rsa.user{cls._n}@example.test",
            password="Test-Only#Pw1",
        )

        if roles:
            # Lewat `grant()`: kewenangan penugasan harus ikut
            # diterjemahkan dari deklarasi `Role`-nya, kalau tidak
            # pemegangnya tidak melihat apa pun.
            cls.grant(user, *roles)

        return user

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
    def grant(cls, user, *roles):
        """Memberi role berikut kewenangan yang dideklarasikan test ini."""
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
    def make_role(cls, code, *, mode=EXPLICIT, permissions=()):
        cls._n += 1

        role = Role.objects.create(code=f"{code}-{cls._n}", name=code.title())

        cls._declared[role.pk] = {"mode": mode, "level": "", "rows": []}

        if permissions:
            role.permissions.add(*permissions)

        return role

    @classmethod
    def scope_row(cls, role, resource_type, resource=None):
        """Satu nilai cakupan untuk `role`, dicatat sebagai deklarasi."""
        cls._declared[role.pk]["rows"].append(
            (resource_type, getattr(resource, "pk", None)))

    @classmethod
    def make_file(cls, user):
        cls._n += 1

        payload = SimpleUploadedFile(
            f"{cls._n}-cv.pdf",
            b"%PDF-1.4 lamaran",
            content_type="application/pdf",
        )

        return UploadService.create(
            uploaded_file=payload,
            metadata={"category": UploadedFile.Category.ATTACHMENT},
            user=user,
        )

    # ------------------------------------------------------------------
    # Pembacaan
    # ------------------------------------------------------------------

    def setUp(self):
        super().setUp()

        for user in get_user_model().objects.all():
            for attribute in ("_role_perm_cache", "_data_scope_cache"):
                if hasattr(user, attribute):
                    delattr(user, attribute)

    def client_for(self, user) -> APIClient:
        for attribute in ("_role_perm_cache", "_data_scope_cache"):
            if hasattr(user, attribute):
                delattr(user, attribute)

        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

        client.force_authenticate(user=user)

        return client

    @staticmethod
    def rows(response):
        payload = response.data

        if isinstance(payload, dict):
            payload = payload.get("data", payload.get("results", []))

        return payload

    def listed_candidates(self, user, **params) -> set[str]:
        response = self.client_for(user).get(CANDIDATES_URL, params)

        self.assertEqual(
            response.status_code,
            200,
            msg=f"Daftar pelamar menjawab {response.status_code}.",
        )

        return {row["candidate_number"] for row in self.rows(response)}

    def listed_jobs(self, user) -> set[str]:
        response = self.client_for(user).get(JOBS_URL)

        self.assertEqual(response.status_code, 200)

        return {str(row["public_id"]) for row in self.rows(response)}

    def listed_files(self, user) -> set[str]:
        response = self.client_for(user).get(UPLOADS_URL)

        self.assertEqual(response.status_code, 200)

        return {str(row["public_id"]) for row in self.rows(response)}

    # ==================================================================
    # Pelamar
    # ==================================================================

    def test_without_the_permission_the_candidate_list_is_refused(self):
        """**1.** Tanpa `hr.view_candidate`, daftarnya 403 — bukan kosong."""
        outsider = self.make_user([self.make_role("RSA-NOPERM")])

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            response = self.client_for(outsider).get(CANDIDATES_URL)

        self.assertEqual(
            response.status_code,
            403,
            msg=(
                "Data pelamar masih terbaca akun tanpa izin apa pun — "
                f"jawabannya {response.status_code}."
            ),
        )

    def test_candidate_authority_follows_the_vacancy_company(self):
        """
        **2, 4 & 10.** Pelamar tidak punya kolom organisasi; yang
        menentukan lowongan yang dilamarnya.

        Sekaligus menguji pencarian: `?search=` tidak boleh
        memunculkan baris yang tidak muncul di daftar biasa.
        """
        role = self.make_role(
            "RSA-HR-A", permissions=[self.view_candidate])

        self.scope_row(
            role, AuthorityResourceType.COMPANY, self.company_a)

        recruiter = self.make_user([role])

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            visible = self.listed_candidates(recruiter)

            searched = self.listed_candidates(
                recruiter,
                search=self.candidate_b.full_name,
            )

        self.assertIn(self.candidate_a.candidate_number, visible)

        self.assertNotIn(
            self.candidate_b.candidate_number,
            visible,
            msg="Pelamar company lain ikut terbaca.",
        )

        self.assertNotIn(
            self.candidate_b.candidate_number,
            searched,
            msg=(
                "Pencarian memunculkan pelamar di luar otoritas — "
                "`?search=` melewati penyaring cakupan."
            ),
        )

    def test_candidate_direct_id_cannot_bypass_authority(self):
        """**3.** Id-nya diketahui, dan tetap tidak cukup."""
        role = self.make_role(
            "RSA-HR-A2", permissions=[self.view_candidate])

        self.scope_row(
            role, AuthorityResourceType.COMPANY, self.company_a)

        recruiter = self.make_user([role])

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            response = self.client_for(recruiter).get(
                f"{CANDIDATES_URL}{self.candidate_b.pk}/",
            )

        self.assertEqual(
            response.status_code,
            404,
            msg="Detail pelamar di luar otoritas tetap terbuka lewat id.",
        )

    def test_a_broad_role_without_the_permission_reads_no_candidate(self):
        """
        **10 & 17.** Cakupan seluas tenant, nol izin pelamar — nol
        baris, dan bukan karena kebetulan kosong.
        """
        broad = self.make_role("RSA-ALL", mode=ReadSurfaceAuthorityTests.ALL)

        executive = self.make_user([broad])

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            response = self.client_for(executive).get(CANDIDATES_URL)

        self.assertEqual(response.status_code, 403)

    def test_two_qualifying_roles_union_their_scopes(self):
        """**16.** Dua role yang sama-sama memberi izin: gabungannya."""
        role_a = self.make_role(
            "RSA-UNION-A", permissions=[self.view_candidate])
        role_b = self.make_role(
            "RSA-UNION-B", permissions=[self.view_candidate])

        self.scope_row(
            role_a, AuthorityResourceType.COMPANY, self.company_a)
        self.scope_row(
            role_b, AuthorityResourceType.COMPANY, self.company_b)

        both = self.make_user([role_a, role_b])

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            visible = self.listed_candidates(both)

        self.assertIn(self.candidate_a.candidate_number, visible)
        self.assertIn(self.candidate_b.candidate_number, visible)

    def test_cross_role_borrowing_is_blocked_for_candidates(self):
        """
        **Kontrak inti, di permukaan baru.** Izin dari role bercakupan
        Company A, cakupan luas dari role yang tidak memberi izin.
        """
        narrow = self.make_role(
            "RSA-NARROW", permissions=[self.view_candidate])

        self.scope_row(
            narrow, AuthorityResourceType.COMPANY, self.company_a)

        wide = self.make_role("RSA-WIDE", mode=ReadSurfaceAuthorityTests.ALL)

        holder = self.make_user([narrow, wide])

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            aware = self.listed_candidates(holder)

        self.assertIn(self.candidate_a.candidate_number, aware)

        self.assertNotIn(
            self.candidate_b.candidate_number,
            aware,
            msg=(
                "Izin pelamar memakai cakupan role yang tidak "
                "memberikannya — peminjaman lintas-role kembali."
            ),
        )

        with override_settings(ROLE_AWARE_DATA_SCOPE=False):
            legacy = self.listed_candidates(holder)

        self.assertIn(
            self.candidate_b.candidate_number,
            legacy,
            msg=(
                "Jalur lama berhenti meminjam. Kalau ini yang berubah, "
                "saklarnya sudah tidak diperlukan — cabut, jangan "
                "longgarkan testnya."
            ),
        )

    # ==================================================================
    # Berkas lamaran — mewarisi, tanpa aturan sendiri
    # ==================================================================

    def test_the_resume_follows_candidate_authority(self):
        """
        **5 & 6.** Berkas lamaran tidak dijaga terpisah: ia menyempit
        karena induknya menyempit. `public_id`-nya diketahui, dan tetap
        tidak cukup.
        """
        role = self.make_role(
            "RSA-RESUME", permissions=[self.view_candidate])

        self.scope_row(
            role, AuthorityResourceType.COMPANY, self.company_a)

        recruiter = self.make_user([role])

        resume_a = self.make_file(recruiter)
        resume_b = self.make_file(recruiter)

        Candidate.objects.filter(pk=self.candidate_a.pk).update(
            resume_file=resume_a)
        Candidate.objects.filter(pk=self.candidate_b.pk).update(
            resume_file=resume_b)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            files = self.listed_files(recruiter)

            denied = self.client_for(recruiter).get(
                f"{UPLOADS_URL}{resume_b.public_id}/download/",
            )

        self.assertIn(
            str(resume_a.public_id),
            files,
            msg="Perekrut kehilangan berkas lamaran di company-nya.",
        )

        self.assertNotIn(
            str(resume_b.public_id),
            files,
            msg="Berkas lamaran company lain ikut terdaftar.",
        )

        self.assertEqual(
            denied.status_code,
            404,
            msg=(
                "Unduhan berkas lamaran di luar otoritas berhasil hanya "
                "karena `public_id`-nya diketahui."
            ),
        )

    # ==================================================================
    # Riwayat import
    # ==================================================================

    def test_import_history_follows_the_target_resource(self):
        """
        **7, 8 & 9.** Riwayat import sebuah resource terbaca oleh yang
        boleh membaca resource itu — dan berkas sumbernya ikut.

        Sasarannya `payroll/payslips`, yang **dijaga izin**; itu yang
        membuat riwayatnya ikut dijaga.
        """
        operator_role = self.make_role(
            "RSA-IMPORT", permissions=[self.view_payslip])

        operator = self.make_user([operator_role])

        outsider = self.make_user([self.make_role("RSA-IMPORT-NO")])

        source = self.make_file(operator)

        job = ImportJob.objects.create(
            module=GUARDED_MODULE,
            filename="payslip.csv",
            source_file=source,
            imported_by=operator,
        )

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertIn(
                str(job.public_id),
                self.listed_jobs(operator),
                msg="Operator kehilangan riwayat importnya sendiri.",
            )

            self.assertNotIn(
                str(job.public_id),
                self.listed_jobs(outsider),
                msg=(
                    "Riwayat import resource terjaga terbaca akun yang "
                    "tidak boleh membaca resource itu."
                ),
            )

            self.assertIn(
                str(source.public_id),
                self.listed_files(operator),
            )

            self.assertNotIn(
                str(source.public_id),
                self.listed_files(outsider),
                msg=(
                    "Berkas sumber import tidak ikut menyempit bersama "
                    "job-nya — pewarisan lampiran putus."
                ),
            )

            denied = self.client_for(outsider).get(
                f"{UPLOADS_URL}{source.public_id}/download/",
            )

        self.assertEqual(denied.status_code, 404)

    def test_a_broad_role_does_not_widen_import_history(self):
        """**11.** Cakupan seluas tenant tidak memberi izin apa pun."""
        operator = self.make_user([
            self.make_role("RSA-IMP-OP", permissions=[self.view_payslip]),
        ])

        broad = self.make_user([
            self.make_role("RSA-IMP-ALL", mode=ReadSurfaceAuthorityTests.ALL),
        ])

        job = ImportJob.objects.create(
            module=GUARDED_MODULE,
            filename="payslip2.csv",
            imported_by=operator,
        )

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertNotIn(
                str(job.public_id),
                self.listed_jobs(broad),
                msg=(
                    "Role bercakupan ALL membaca riwayat import payroll "
                    "tanpa satu pun izin payroll."
                ),
            )

    def test_import_history_of_an_open_resource_stays_open(self):
        """
        **Sisi sebaliknya, dan disengaja.** Modul yang resource-nya
        memang terbuka bacanya tetap terbuka riwayatnya: catatan
        tentang sebuah tabel tidak boleh lebih rahasia daripada isi
        tabelnya.
        """
        stranger = self.make_user([self.make_role("RSA-OPEN")])

        job = ImportJob.objects.create(
            module="administration/calendar/work-calendar",
            filename="kalender.csv",
        )

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertIn(
                str(job.public_id),
                self.listed_jobs(stranger),
                msg=(
                    "Riwayat import resource terbuka jadi lebih tertutup "
                    "daripada resource-nya sendiri."
                ),
            )

    def test_an_unknown_module_is_refused(self):
        """
        Fail-closed: modul yang tidak dikenali tidak jatuh ke
        "boleh semua". Yang tetap melihatnya cuma pengunggahnya.
        """
        owner = self.make_user([self.make_role("RSA-UNK-OWN")])
        stranger = self.make_user([self.make_role("RSA-UNK-OTHER")])

        job = ImportJob.objects.create(
            module="modul/yang/tidak/pernah/ada",
            filename="entah.csv",
            imported_by=owner,
        )

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertIn(str(job.public_id), self.listed_jobs(owner))

            self.assertNotIn(
                str(job.public_id),
                self.listed_jobs(stranger),
                msg=(
                    "Modul tak dikenal terbaca siapa pun — tidak adanya "
                    "otoritas yang bisa dihitung berarti terbuka."
                ),
            )

    # ==================================================================
    # Dropdown
    # ==================================================================

    def test_a_transactional_lookup_matches_its_main_resource(self):
        """
        **12.** Dropdown lowongan dan tabel lowongan menjawab semesta
        yang sama. Dropdown yang lebih luas berarti yang tidak muncul
        di tabel tetap bisa dipilih.
        """
        role = self.make_role(
            "RSA-VAC", permissions=[self.view_candidate])

        self.scope_row(
            role, AuthorityResourceType.COMPANY, self.company_a)

        user = self.make_user([role])

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            response = self.client_for(user).get(VACANCY_LOOKUP_URL)

        self.assertEqual(response.status_code, 200)

        labels = {row["value"] for row in self.rows(response)}

        self.assertIn(self.vacancy_a.pk, labels)

        self.assertNotIn(
            self.vacancy_b.pk,
            labels,
            msg="Dropdown lowongan mengirim company lain.",
        )

    def test_a_sensitive_lookup_search_cannot_reveal_unauthorized_rows(self):
        """
        **13.** Pencarian di dropdown pelamar tidak boleh jadi jalan
        pintas ke baris yang tidak boleh dibaca.
        """
        role = self.make_role(
            "RSA-LOOKUP", permissions=[self.view_candidate])

        self.scope_row(
            role, AuthorityResourceType.COMPANY, self.company_a)

        user = self.make_user([role])

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            response = self.client_for(user).get(
                CANDIDATE_LOOKUP_URL,
                {"search": self.candidate_b.full_name},
            )

        self.assertEqual(response.status_code, 200)

        values = {row["value"] for row in self.rows(response)}

        self.assertNotIn(
            self.candidate_b.pk,
            values,
            msg="Pencarian dropdown memunculkan pelamar di luar otoritas.",
        )

    def test_the_candidate_lookup_returns_only_selection_fields(self):
        """
        **Minimisasi data.** Dropdown perlu id, label, dan nomor —
        tidak perlu surel, telepon, atau gaji yang diharapkan.
        """
        role = self.make_role(
            "RSA-MIN", permissions=[self.view_candidate])

        self.scope_row(
            role, AuthorityResourceType.COMPANY, self.company_a)

        user = self.make_user([role])

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            response = self.client_for(user).get(CANDIDATE_LOOKUP_URL)

        rows = self.rows(response)

        self.assertTrue(rows, msg="Panggungnya kosong — tidak menguji apa pun.")

        for row in rows:
            self.assertEqual(
                set(row),
                {"value", "label", "code"},
                msg=f"Payload dropdown pelamar membawa {sorted(row)}.",
            )
