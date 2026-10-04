"""
Berkas tidak memiliki otoritasnya sendiri.

Sampai Stage 3B.1, `/api/uploads/` cuma `IsAuthenticated` dengan
queryset `UploadedFile.objects.active()` tanpa penyaringan apa pun: di
tenant peragaan **22 berkas terbaca seluruh 30 akun**, lengkap dengan
`public_id`-nya, dan `download/` melayani siapa pun yang memegangnya.

Yang dikunci berkas ini bukan "berkasnya tersembunyi", melainkan
**dari mana izinnya datang**: dari record bisnis yang menunjuk berkas
itu. Karena itu hampir seluruh test di bawah memeriksa dua hal
sekaligus — bahwa yang berhak tetap bisa membuka, dan bahwa
mengetahui `public_id` tidak menggantikan hak itu.

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
from apps.hr.models import (
    Employee,
    EmployeeDocument,
    OrganizationAssignment,
)
from apps.uploads.models import UploadedFile
from apps.uploads.services import UploadService


JOIN = date(2020, 1, 6)

UPLOADS_URL = "/api/uploads/"


# Berkas uji ditulis ke direktori sementara, bukan ke `media/` repo:
# test yang meninggalkan berkas di pohon kerja membuat `git status`
# berisik dan, lebih buruk, membuat run berikutnya membaca sisa run
# sebelumnya.
@override_settings(MEDIA_ROOT=tempfile.mkdtemp(prefix="uploads-test-"))
class FileAuthorityTests(TenantTestCase):
    """
    Dua lokasi di satu company, satu dokumen pegawai berkas di
    masing-masing, dan satu berkas yang belum tertaut ke apa pun.
    """

    _n = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "file-auth"
        tenant.name = "File Authority"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(code="FAC", name="Company")

        cls.site_a = Location.objects.create(
            company=cls.company, code="FAC-A", name="Site A")
        cls.site_b = Location.objects.create(
            company=cls.company, code="FAC-B", name="Site B")

        cls.department = Department.objects.create(
            company=cls.company, code="FAC-OPS", name="Operations")

        cls.document_type = DocumentType.objects.create(
            code="FA-KTP", name="KTP")

        cls.view_document = Permission.objects.get(
            content_type__app_label="hr",
            codename="view_employeedocument",
        )

        # Pemilik dokumen: satu di tiap site, tanpa akun sendiri.
        cls.target_a = cls.make_employee(cls.site_a, with_user=False)
        cls.target_b = cls.make_employee(cls.site_b, with_user=False)

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(cls, location, *, with_user=True):
        User = get_user_model()

        cls._n += 1

        user = None

        if with_user:
            user = User.objects.create_user(
                username=f"fa.user{cls._n}",
                email=f"fa.user{cls._n}@example.test",
                password="Test-Only#Pw1",
            )

        position = Position.objects.create(
            company=cls.company,
            department=cls.department,
            code=f"FA-POS{cls._n}",
            name=f"Position {cls._n}",
        )

        employee = Employee.objects.create(
            employee_number=f"FA-{cls._n:03d}",
            first_name="File",
            last_name=f"User {cls._n}",
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=location,
            department=cls.department,
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
    def make_role(cls, code, *, mode=EXPLICIT, permissions=()):
        cls._n += 1

        role = Role.objects.create(code=f"{code}-{cls._n}", name=code.title())

        cls._declared[role.pk] = {"mode": mode, "level": "", "rows": []}

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

    @classmethod
    def make_file(cls, user, *, name="ktp.pdf"):
        """Berkas sungguhan lewat service produksinya."""
        cls._n += 1

        payload = SimpleUploadedFile(
            f"{cls._n}-{name}",
            b"%PDF-1.4 berkas uji",
            content_type="application/pdf",
        )

        return UploadService.create(
            uploaded_file=payload,
            metadata={"category": UploadedFile.Category.ATTACHMENT},
            user=user,
        )

    @classmethod
    def attach(cls, employee, uploaded_file):
        cls._n += 1

        return EmployeeDocument.objects.create(
            employee=employee,
            document_type=cls.document_type,
            document_name=f"KTP {cls._n}",
            uploaded_file=uploaded_file,
        )

    # ------------------------------------------------------------------
    # Pembacaan
    # ------------------------------------------------------------------

    def setUp(self):
        super().setUp()

        EmployeeDataPolicy.objects.all().delete()

        for user in get_user_model().objects.all():
            for attribute in ("_role_perm_cache", "_data_scope_cache"):
                if hasattr(user, attribute):
                    delattr(user, attribute)

    def api_client(self, user) -> APIClient:
        for attribute in ("_role_perm_cache", "_data_scope_cache"):
            if hasattr(user, attribute):
                delattr(user, attribute)

        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

        client.force_authenticate(user=user)

        return client

    def listed(self, user) -> set[str]:
        """`public_id` yang bisa **ditemukan** akun ini."""
        response = self.api_client(user).get(UPLOADS_URL)

        self.assertEqual(
            response.status_code,
            200,
            msg=f"Daftar berkas menjawab {response.status_code}.",
        )

        rows = response.data

        if isinstance(rows, dict):
            rows = rows.get("data", rows.get("results", []))

        return {str(row["public_id"]) for row in rows}

    def fetch(self, user, uploaded_file, suffix=""):
        """Status HTTP untuk detail / unduh / pratinjau satu berkas."""
        url = f"{UPLOADS_URL}{uploaded_file.public_id}/{suffix}"

        return self.api_client(user).get(url).status_code

    # ==================================================================
    # 1–2 — berkas yang belum tertaut
    # ==================================================================

    def test_an_unrelated_user_cannot_list_someone_elses_draft(self):
        """**1.** Unggahan yang belum tertaut milik pengunggahnya."""
        owner = self.make_employee(self.site_a)
        stranger = self.make_employee(self.site_a)

        draft = self.make_file(owner.user)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertNotIn(
                str(draft.public_id),
                self.listed(stranger.user),
                msg="Unggahan orang lain ikut terdaftar.",
            )

    def test_the_uploader_can_reach_their_own_draft(self):
        """
        **2.** Dan penyempitannya tidak boleh mengunci pengunggahnya
        sendiri — ia sedang menyusun dokumennya.
        """
        owner = self.make_employee(self.site_a)

        draft = self.make_file(owner.user)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertIn(str(draft.public_id), self.listed(owner.user))

            self.assertEqual(self.fetch(owner.user, draft), 200)

            self.assertEqual(
                self.fetch(owner.user, draft, "download/"),
                200,
            )

    def test_the_uploader_loses_the_draft_rule_once_it_is_attached(self):
        """
        **Aturan sementara berhenti sendiri.**

        Begitu berkasnya menempel ke dokumen pegawai, yang berlaku
        otoritas dokumen itu — bukan lagi "saya yang mengunggahnya".
        Tanpa ini, pengunggah memegang pintu belakang permanen ke
        berkas yang sudah jadi milik record orang lain.
        """
        uploader = self.make_employee(self.site_a)

        uploaded = self.make_file(uploader.user)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertIn(str(uploaded.public_id), self.listed(uploader.user))

        self.attach(self.target_b, uploaded)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertNotIn(
                str(uploaded.public_id),
                self.listed(uploader.user),
                msg=(
                    "Pengunggah tetap memegang berkas yang sudah jadi "
                    "milik dokumen orang lain."
                ),
            )

    # ==================================================================
    # 3–4, 10–11 — otoritas induk
    # ==================================================================

    def test_parent_read_authority_grants_the_attachment(self):
        """**3 & 10.** HR Admin bercakupan Site A membuka berkas Site A."""
        admin_role = self.make_role(
            "FA-HR-ADMIN",
            permissions=[self.view_document],
        )

        self.scope_row(
            admin_role,
            AuthorityResourceType.LOCATION,
            self.site_a,
        )

        admin = self.make_employee(self.site_a)

        self.grant(admin.user, admin_role)

        uploaded = self.make_file(admin.user)

        self.attach(self.target_a, uploaded)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertIn(str(uploaded.public_id), self.listed(admin.user))

            self.assertEqual(self.fetch(admin.user, uploaded), 200)

            self.assertEqual(
                self.fetch(admin.user, uploaded, "download/"),
                200,
            )

    def test_no_parent_read_authority_means_no_attachment(self):
        """**4 & 11.** Dokumen yang sama, dari Site B — tertutup."""
        admin_role = self.make_role(
            "FA-HR-ADMIN-A",
            permissions=[self.view_document],
        )

        self.scope_row(
            admin_role,
            AuthorityResourceType.LOCATION,
            self.site_a,
        )

        admin = self.make_employee(self.site_a)

        self.grant(admin.user, admin_role)

        other = self.make_employee(self.site_b)

        uploaded = self.make_file(other.user)

        self.attach(self.target_b, uploaded)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertNotIn(
                str(uploaded.public_id),
                self.listed(admin.user),
                msg="Berkas di luar cakupan ikut terdaftar.",
            )

            self.assertEqual(
                self.fetch(admin.user, uploaded),
                404,
                msg="Detail berkas di luar cakupan tetap terbuka.",
            )

    def test_knowing_the_public_id_does_not_bypass_authority(self):
        """
        **5–8.** `public_id` diketahui — dan tetap tidak cukup, di
        keempat pintunya.
        """
        outsider = self.make_role("FA-OUTSIDER", mode=FileAuthorityTests.ALL)

        stranger = self.make_employee(self.site_a)

        self.grant(stranger.user, outsider)

        owner = self.make_employee(self.site_b)

        uploaded = self.make_file(owner.user)

        self.attach(self.target_b, uploaded)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            for suffix in ("", "download/", "preview/"):
                self.assertEqual(
                    self.fetch(stranger.user, uploaded, suffix),
                    404,
                    msg=(
                        f"`{suffix or 'detail'}` melayani berkas hanya "
                        f"karena `public_id`-nya diketahui."
                    ),
                )

    def test_a_broad_unrelated_role_does_not_grant_file_access(self):
        """
        **9.** Cakupan seluas tenant, tanpa `hr.view_employeedocument`
        — nol berkas.
        """
        broad = self.make_role("FA-BROAD", mode=FileAuthorityTests.ALL)

        executive = self.make_employee(self.site_a)

        self.grant(executive.user, broad)

        owner = self.make_employee(self.site_a)

        uploaded = self.make_file(owner.user)

        self.attach(self.target_a, uploaded)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertNotIn(
                str(uploaded.public_id),
                self.listed(executive.user),
                msg=(
                    "Cakupan luas membuka lampiran tanpa izin membaca "
                    "dokumennya."
                ),
            )

    # ==================================================================
    # 12–13 — kelompok data pegawai
    # ==================================================================

    def test_the_subject_policy_still_applies_to_attachments(self):
        """
        **12 & 13.** Lapis ketiga ikut: aturan `field_document` yang
        menyebut satu role menutup berkasnya untuk yang lain, meski
        izin dan cakupannya cukup.
        """
        # **Cakupannya harus benar-benar cukup**, dan itu perlu
        # dinyatakan. Sebelum Stage 4G `make_role()` bawaannya
        # `explicit` tanpa satu pun baris, dan arti lamanya *tanpa
        # batasan* — jadi test ini lulus karena kebocoran, bukan karena
        # cakupannya memang diberikan. Begitu kebocorannya ditutup,
        # kedua role tidak melihat apa pun dan yang gagal justru
        # baris pertamanya, bukan lapis yang sedang diuji.
        #
        # `ALL` menyatakan maksudnya: yang membedakan kedua role di
        # sini **hanya** aturan kelompok data, bukan cakupan.
        hr_role = self.make_role(
            "FA-POLICY-HR",
            mode=FileAuthorityTests.ALL,
            permissions=[self.view_document],
        )

        other_role = self.make_role(
            "FA-POLICY-OTHER",
            mode=FileAuthorityTests.ALL,
            permissions=[self.view_document],
        )

        insider = self.make_employee(self.site_a)
        outsider = self.make_employee(self.site_a)

        self.grant(insider.user, hr_role)
        self.grant(outsider.user, other_role)

        uploaded = self.make_file(insider.user)

        self.attach(self.target_a, uploaded)

        EmployeeDataPolicy.objects.create(
            code="FA-EDP-DOC",
            name="Documents",
            subject=EmployeeDataSubject.FIELD_DOCUMENT,
            role=hr_role,
            allow_self=False,
            allow_manager=False,
            allow_department_head=False,
            is_active=True,
        )

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertIn(
                str(uploaded.public_id),
                self.listed(insider.user),
                msg="Role yang disebut aturan kehilangan berkasnya.",
            )

            self.assertNotIn(
                str(uploaded.public_id),
                self.listed(outsider.user),
                msg=(
                    "Kelompok data pegawai tidak ikut menutup "
                    "lampirannya — lapisan ketiga terlewat."
                ),
            )

    # ==================================================================
    # 14 — baca bukan tulis
    # ==================================================================

    def test_read_access_does_not_allow_deleting_an_attachment(self):
        """
        **14.** Boleh membaca dokumennya tidak berarti boleh mengganti
        atau menghapus berkasnya. `uploaded_file` ber-`PROTECT` di
        tujuh model; menghapusnya mengubah isi dokumen orang lain
        tanpa menyentuh dokumennya.
        """
        # Cakupannya dinyatakan, bukan diwarisi dari arti lama
        # `explicit` tanpa baris — lihat catatan di
        # `test_the_subject_policy_still_applies_to_attachments`. Yang
        # diuji di sini baca-bukan-tulis, jadi bacanya memang harus
        # benar-benar boleh.
        admin_role = self.make_role(
            "FA-DELETE-HR",
            mode=FileAuthorityTests.ALL,
            permissions=[self.view_document],
        )

        admin = self.make_employee(self.site_a)

        self.grant(admin.user, admin_role)

        uploaded = self.make_file(admin.user)

        self.attach(self.target_a, uploaded)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            # Ia memang boleh membacanya…
            self.assertIn(str(uploaded.public_id), self.listed(admin.user))

            # …dan tetap tidak boleh menghapusnya.
            response = self.api_client(admin.user).delete(
                f"{UPLOADS_URL}{uploaded.public_id}/",
            )

            self.assertEqual(
                response.status_code,
                403,
                msg=(
                    "Pemegang akses baca menghapus lampiran bersama. "
                    f"Jawabannya {response.status_code}."
                ),
            )

        self.assertTrue(
            UploadedFile.objects.active().filter(pk=uploaded.pk).exists(),
            msg="Berkasnya benar-benar terhapus.",
        )

    def test_the_uploader_may_still_delete_an_unattached_draft(self):
        """
        Sisi sebaliknya: penyempitan yang mengunci pengunggah dari
        draftnya sendiri bukan perbaikan.
        """
        owner = self.make_employee(self.site_a)

        draft = self.make_file(owner.user)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            response = self.api_client(owner.user).delete(
                f"{UPLOADS_URL}{draft.public_id}/",
            )

        self.assertEqual(response.status_code, 200)

    # ==================================================================
    # 15–17 — mode, dan daur hidup
    # ==================================================================

    def test_role_aware_prevents_cross_role_borrowing_on_files(self):
        """
        **15 & 16.** Izin dokumen dari role bercakupan Site A, cakupan
        seluruh company dari role yang tidak memberi izin apa pun.

        Diuji di kedua mode: jalur lama memang meminjam, dan itu yang
        membuat saklarnya masih ada.
        """
        narrow = self.make_role(
            "FA-NARROW",
            permissions=[self.view_document],
        )

        self.scope_row(
            narrow,
            AuthorityResourceType.LOCATION,
            self.site_a,
        )

        wide = self.make_role("FA-WIDE")

        self.scope_row(
            wide,
            AuthorityResourceType.COMPANY,
            self.company,
        )

        holder = self.make_employee(self.site_a)

        self.grant(holder.user, narrow, wide)

        owner = self.make_employee(self.site_b)

        uploaded = self.make_file(owner.user)

        self.attach(self.target_b, uploaded)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertNotIn(
                str(uploaded.public_id),
                self.listed(holder.user),
                msg=(
                    "Izin dokumen memakai cakupan role yang tidak "
                    "memberikannya — peminjaman lintas-role kembali."
                ),
            )

        with override_settings(ROLE_AWARE_DATA_SCOPE=False):
            self.assertIn(
                str(uploaded.public_id),
                self.listed(holder.user),
                msg=(
                    "Jalur lama berhenti meminjam. Kalau ini yang "
                    "berubah, saklarnya sudah tidak diperlukan — "
                    "cabut, jangan longgarkan testnya."
                ),
            )

    def test_a_deleted_file_disappears_for_everyone(self):
        """
        **17.** Daur hidup lama tidak berubah: yang dihapus keluar dari
        daftar dan dari unduhan, juga bagi pengunggahnya.
        """
        owner = self.make_employee(self.site_a)

        draft = self.make_file(owner.user)

        draft.soft_delete(user=owner.user)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertNotIn(str(draft.public_id), self.listed(owner.user))

            self.assertEqual(self.fetch(owner.user, draft), 404)

            self.assertEqual(
                self.fetch(owner.user, draft, "download/"),
                404,
            )

    def test_a_superuser_is_unaffected(self):
        """
        Superuser dilewati, sama seperti di seluruh lapisan otoritas
        lain. Tanpa ini satu aturan yang salah isi mengunci berkasnya
        tanpa jalan keluar selain lewat shell.
        """
        User = get_user_model()

        type(self)._n += 1

        root = User.objects.create_user(
            username=f"fa.root{type(self)._n}",
            email=f"fa.root{type(self)._n}@example.test",
            password="Test-Only#Pw1",
            is_superuser=True,
            is_staff=True,
        )

        owner = self.make_employee(self.site_b)

        uploaded = self.make_file(owner.user)

        self.attach(self.target_b, uploaded)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertIn(str(uploaded.public_id), self.listed(root))

    # ==================================================================
    # Foto pegawai — `Employee.avatar_file`
    # ==================================================================
    #
    # Daftar pegawai, kepala halaman pegawai, dan pratinjau di form Edit
    # semuanya memasang `avatar_display.url` — alamat `preview/`. Yang
    # dijaga di sini: alamat itu **tidak** jadi jalan pintas. Hak
    # bacanya tetap diturunkan dari baris Employee pemilik foto, persis
    # seperti lampiran lain.

    AVATAR_PNG = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
        b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
        b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    def attach_avatar(self, employee, uploader):
        type(self)._n += 1

        uploaded = UploadService.create(
            uploaded_file=SimpleUploadedFile(
                f"{type(self)._n}-foto.png",
                self.AVATAR_PNG,
                content_type="image/png",
            ),
            metadata={"category": UploadedFile.Category.AVATAR},
            user=uploader,
        )

        employee.avatar_file = uploaded
        employee.save(update_fields=["avatar_file"])

        return uploaded

    def employee_viewer(self, site):
        role = self.make_role(
            "FA-HR-VIEW",
            permissions=[
                Permission.objects.get(
                    content_type__app_label="hr",
                    codename="view_employee",
                ),
            ],
        )

        self.scope_row(role, AuthorityResourceType.LOCATION, site)

        viewer = self.make_employee(site)

        self.grant(viewer.user, role)

        return viewer.user

    def test_employee_avatar_preview_follows_employee_read_authority(self):
        """Foto pegawai Site A terbuka bagi pembaca pegawai Site A."""
        viewer = self.employee_viewer(self.site_a)

        uploaded = self.attach_avatar(self.target_a, viewer)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertEqual(self.fetch(viewer, uploaded, "preview/"), 200)

    def test_employee_avatar_preview_is_closed_outside_scope(self):
        """
        Foto pegawai Site B tertutup bagi pembaca Site A — sekalipun
        `public_id`-nya ikut terkirim di payload yang ia pegang.
        """
        viewer = self.employee_viewer(self.site_a)

        other = self.make_employee(self.site_b)

        uploaded = self.attach_avatar(self.target_b, other.user)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertEqual(self.fetch(viewer, uploaded, "preview/"), 404)
            self.assertEqual(self.fetch(viewer, uploaded, "download/"), 404)

    def test_employee_avatar_preview_needs_employee_permission(self):
        """Akun tanpa `hr.view_employee` tidak membuka foto siapa pun."""
        stranger = self.make_employee(self.site_a)

        owner = self.make_employee(self.site_a)

        uploaded = self.attach_avatar(self.target_a, owner.user)

        with override_settings(ROLE_AWARE_DATA_SCOPE=True):
            self.assertEqual(
                self.fetch(stranger.user, uploaded, "preview/"),
                404,
            )
