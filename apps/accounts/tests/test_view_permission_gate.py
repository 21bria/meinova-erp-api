"""
Membaca resource sensitif menuntut **izin dan cakupan**, bukan salah satu.

Sampai sebelum ini `ModelPermission` mengembalikan `True` untuk seluruh
SAFE_METHOD, jadi satu-satunya yang menjaga baca adalah cakupan data.
Itu membuat kontrak "izin + cakupan" hanya benar setengahnya: cakupan
menjawab **baris siapa**, dan tidak ada yang menjawab **jenis data apa**.
Akibatnya bisa dinyatakan dalam satu kalimat — kebetulan berada di satu
lokasi cukup untuk membuka slip gaji orang di lokasi itu.

Yang diuji di sini gerbang barunya, dan diuji dari **dua arah**. Test
yang hanya membuktikan "yang berhak bisa masuk" akan tetap hijau pada
gerbang yang tidak pernah menolak siapa pun; karena itu tiap skenario
punya pasangan negatifnya.

Empat sudut yang harus tetap benar bersamaan:

1. tanpa izin, **di dalam** cakupan  -> ditolak
2. punya izin, **di luar** cakupan   -> ditolak
3. punya izin, di dalam cakupan      -> boleh
4. superuser                         -> tetap seperti kontrak lama

Ditambah dua yang menjaga gerbangnya sendiri: resource yang tidak
menyatakan diri sensitif **tidak** boleh ikut tertutup (kalau ikut,
seluruh dropdown mati), dan tiap resource yang menyatakan diri sensitif
wajib punya `data_scope` (kalau tidak, izinnya membuka seluruh tenant).
"""

from __future__ import annotations

from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings

from django_tenants.test.cases import TenantTestCase
from rest_framework.test import APIClient

from apps.accounts.services.role_assignment import grant_role
from apps.accounts.models import AuthorityMode, Role
from apps.administration.models import Company, Department, Location, Position
from apps.framework.views.master import BaseMasterViewSet
from apps.hr.models import Employee, OrganizationAssignment


JOIN = date(2020, 1, 6)

# Resource sensitif yang dipakai sebagai contoh sepanjang berkas ini.
# Employee dipilih karena ia satu-satunya yang **pasti** punya baris di
# tiap tenant — slip gaji dan rekening bank bisa saja kosong, dan
# gerbang yang diuji pada tabel kosong tidak membuktikan apa pun soal
# baris yang tersaring.
GATED_URL = "/api/hr/employees/"

# Pembanding: resource yang bacanya memang dibiarkan terbuka. Ada di
# sini supaya kegagalan "gerbangnya bocor ke mana-mana" terlihat sebagai
# test merah, bukan sebagai laporan pengguna bahwa dropdown kosong.
OPEN_URL = "/api/administration/organization/company/"


class ViewPermissionGateTestCase(TenantTestCase):
    """
    Dua company, dan tiap peran diuji terhadap keduanya.

    Dua, bukan satu: "apakah cakupannya benar-benar menyaring" tidak
    bisa dijawab panggung yang seluruh barisnya boleh dilihat.
    """

    _n = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "view-gate"
        tenant.name = "View Gate"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company_a = Company.objects.create(code="VGA", name="Company A")
        cls.company_b = Company.objects.create(code="VGB", name="Company B")

        cls.site_a = Location.objects.create(
            company=cls.company_a, code="VGA-1", name="Site A1")
        cls.site_b = Location.objects.create(
            company=cls.company_b, code="VGB-1", name="Site B1")

        cls.dept_a = Department.objects.create(
            company=cls.company_a, code="VGA-OPS", name="Operations A")
        cls.dept_b = Department.objects.create(
            company=cls.company_b, code="VGB-OPS", name="Operations B")

        # Sasaran yang dibaca. Keduanya ada supaya "di luar cakupan"
        # punya baris sungguhan untuk ditolak — bukan sekadar id yang
        # kebetulan tidak ada.
        cls.target_a = cls.make_employee(
            cls.company_a, cls.site_a, cls.dept_a, with_user=False)
        cls.target_b = cls.make_employee(
            cls.company_b, cls.site_b, cls.dept_b, with_user=False)

        cls.view_employee = Permission.objects.get(
            content_type__app_label="hr",
            codename="view_employee",
        )

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
                username=f"vg.user{cls._n}",
                email=f"vg.user{cls._n}@example.test",
                password="Test-Only#Pw1",
            )

        position = Position.objects.create(
            company=company,
            department=department,
            code=f"VG-POS{cls._n}",
            name=f"Position {cls._n}",
        )

        employee = Employee.objects.create(
            employee_number=f"VG-{cls._n:03d}",
            first_name="Gate",
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
    def make_role(cls, code, *, mode=EXPLICIT, level=""):
        role = Role.objects.create(code=code, name=code.title())

        cls._declared[role.pk] = {"mode": mode, "level": level, "rows": []}

        return role

    @classmethod
    def scope_row(cls, role, resource_type, resource=None):
        """Satu nilai cakupan untuk `role`, dicatat sebagai deklarasi."""
        cls._declared[role.pk]["rows"].append(
            (resource_type, getattr(resource, "pk", None)))

    def api_client(self, user) -> APIClient:
        """
        Klien yang **menyebut domain tenant**.

        Tanpa `HTTP_HOST`, `APIClient` mengirim `Host: testserver`,
        `TenantMainMiddleware` tidak mengenalinya, dan requestnya
        dilayani dari schema `public` — yang gejalanya bukan 404
        melainkan `relation "..." does not exist`, jauh dari sebabnya.
        """
        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

        client.force_authenticate(user=user)

        return client

    def setUp(self):
        super().setUp()

        # `RolePermissionBackend` dan `DataScopeService` sama-sama
        # menyimpan hasilnya di instance user. Test yang mengubah role
        # sesudah cache terisi akan membaca keadaan lama.
        for user in get_user_model().objects.all():
            for attribute in ("_role_perm_cache", "_data_scope_cache"):
                if hasattr(user, attribute):
                    delattr(user, attribute)

    # ------------------------------------------------------------------
    # Empat sudut
    # ------------------------------------------------------------------

    def test_without_view_permission_read_is_denied_even_inside_scope(self):
        """
        **Sudut pertama, dan yang paling banyak berubah.**

        Cakupannya seluas mungkin — role bermode `all`, jadi tidak ada
        satu baris pun yang tersaring — dan tetap ditolak. Yang menolak
        izinnya, bukan cakupannya, dan itu justru intinya: sebelum ini
        kombinasi ini menghasilkan 200 berisi seluruh tenant.
        """
        employee = self.make_employee(self.company_a, self.site_a, self.dept_a)

        role = self.make_role("VG-ALL-NOPERM", mode=ViewPermissionGateTestCase.ALL)

        self.grant(employee.user, role)

        response = self.api_client(employee.user).get(GATED_URL)

        self.assertEqual(response.status_code, 403, response.content[:300])

    def test_with_view_permission_rows_outside_scope_stay_hidden(self):
        """
        **Sudut kedua.** Izin menjawab jenis datanya, bukan baris siapa.

        Diperiksa dua kali dengan sengaja: daftarnya tidak memuat
        Company B, **dan** menembak id-nya langsung tetap 404. Yang
        pertama saja tidak cukup — nomor urut gampang ditebak, dan
        penyaringan yang hanya terjadi di `list()` meninggalkan pintu
        detail terbuka lebar.
        """
        employee = self.make_employee(self.company_a, self.site_a, self.dept_a)

        role = self.make_role("VG-SCOPED-A")

        role.permissions.add(self.view_employee)

        self.scope_row(role, "company", self.company_a)

        self.grant(employee.user, role)

        client = self.api_client(employee.user)

        response = client.get(GATED_URL, {"page_size": 100})

        self.assertEqual(response.status_code, 200, response.content[:300])

        numbers = {
            row["employee_number"]
            for row in response.json()["data"]
        }

        self.assertIn(self.target_a.employee_number, numbers)

        self.assertNotIn(
            self.target_b.employee_number,
            numbers,
            msg="Company B bocor ke daftar milik pemegang cakupan Company A.",
        )

        detail = client.get(f"{GATED_URL}{self.target_b.pk}/")

        self.assertEqual(
            detail.status_code,
            404,
            msg=(
                "Baris di luar cakupan tetap terbuka lewat id langsung — "
                f"{detail.status_code}."
            ),
        )

    def test_with_view_permission_inside_scope_is_allowed(self):
        """
        **Sudut ketiga.** Keduanya terpenuhi, jadi barisnya terbuka —
        termasuk lewat detail, bukan cuma daftar.
        """
        employee = self.make_employee(self.company_a, self.site_a, self.dept_a)

        role = self.make_role("VG-OK-A")

        role.permissions.add(self.view_employee)

        self.scope_row(role, "company", self.company_a)

        self.grant(employee.user, role)

        client = self.api_client(employee.user)

        self.assertEqual(client.get(GATED_URL).status_code, 200)

        detail = client.get(f"{GATED_URL}{self.target_a.pk}/")

        self.assertEqual(detail.status_code, 200, detail.content[:300])

    def test_superuser_contract_is_unchanged(self):
        """
        **Sudut keempat.** Superuser tidak memegang role apa pun dan
        tetap membuka semuanya.

        Bukan pengecualian yang ditambahkan di gerbang ini: `has_perm`
        milik Django sudah selalu `True` untuk superuser, dan
        `DataScopeService` sudah selalu melepasnya. Yang diuji di sini
        bahwa keduanya **tetap** begitu — kalau gerbang barunya sampai
        memblokir superuser, seluruh dugaan "tinggal matikan lewat
        superuser" ikut hilang bersamanya.
        """
        User = get_user_model()

        root = User.objects.create_superuser(
            username="vg.root",
            email="vg.root@example.test",
            password="Test-Only#Pw1",
        )

        client = self.api_client(root)

        response = client.get(GATED_URL, {"page_size": 100})

        self.assertEqual(response.status_code, 200, response.content[:300])

        numbers = {row["employee_number"] for row in response.json()["data"]}

        self.assertIn(self.target_a.employee_number, numbers)
        self.assertIn(self.target_b.employee_number, numbers)

    # ------------------------------------------------------------------
    # Gerbangnya sendiri
    # ------------------------------------------------------------------

    def test_resources_that_are_not_sensitive_stay_open(self):
        """
        Batas gerbangnya, dan alasan gerbang ini opt-in.

        `EMPLOYEE` hari ini hanya punya `view_*` untuk 7 dari 152 model
        yang ada di balik endpoint. Kalau penjagaan baca berlaku untuk
        semuanya, hampir setiap layar mati — dan matinya bukan karena
        keputusan siapa pun.
        """
        employee = self.make_employee(self.company_a, self.site_a, self.dept_a)

        role = self.make_role("VG-OPEN", mode=ViewPermissionGateTestCase.ALL)

        self.grant(employee.user, role)

        response = self.api_client(employee.user).get(OPEN_URL)

        self.assertEqual(
            response.status_code,
            200,
            msg=(
                "Resource tanpa `require_view_permission` ikut tertutup — "
                "gerbangnya bocor ke resource yang bacanya memang terbuka."
            ),
        )

    @override_settings(ENFORCE_VIEW_PERMISSIONS=False)
    def test_kill_switch_reopens_reads(self):
        """
        Saklar daruratnya benar-benar bekerja.

        Ada supaya tenant yang seed-nya belum diperbarui bisa
        mematikan penjagaan baca **tanpa** ikut membuka izin tulis —
        dan supaya urutan "seed dulu, baru nyalakan" punya jalan
        mundur kalau ternyata masih ada role yang terlewat.
        """
        employee = self.make_employee(self.company_a, self.site_a, self.dept_a)

        role = self.make_role("VG-KILLSWITCH", mode=ViewPermissionGateTestCase.ALL)

        self.grant(employee.user, role)

        response = self.api_client(employee.user).get(GATED_URL)

        self.assertEqual(response.status_code, 200, response.content[:300])

    def test_every_gated_viewset_also_declares_a_data_scope(self):
        """
        Pasangan izin+cakupan dijaga di sini, bukan oleh kesepakatan.

        Viewset ber-`require_view_permission` tanpa `data_scope` adalah
        setengah kontrak yang terbaca seperti kontrak penuh: pemegang
        izinnya membaca **seluruh tenant**, dan di layar Roles satu
        centang itu terlihat sama tak berbahayanya dengan centang lain.

        Dijalankan atas seluruh subclass yang termuat, jadi viewset
        sensitif yang ditambahkan besok ikut terperiksa tanpa ada yang
        perlu ingat menambahkannya ke daftar mana pun.
        """
        from django.urls import get_resolver

        # `__subclasses__` hanya menemukan yang sudah diimpor. Lewat
        # HTTP itu selalu terpenuhi; dari test belum tentu, dan daftar
        # kosong di sini berarti test hijau yang tidak memeriksa apa pun.
        get_resolver().url_patterns

        def subclasses(cls):
            found = []

            for subclass in cls.__subclasses__():
                found.append(subclass)
                found.extend(subclasses(subclass))

            return found

        classes = subclasses(BaseMasterViewSet)

        self.assertGreater(len(classes), 50, "Viewset-nya belum termuat.")

        gated = [
            view_class
            for view_class in classes
            if getattr(view_class, "require_view_permission", False)
        ]

        self.assertGreater(
            len(gated),
            0,
            "Tidak ada satu pun resource sensitif — gerbangnya menganggur.",
        )

        unscoped = sorted(
            f"{view_class.__module__}.{view_class.__name__}"
            for view_class in gated
            if not getattr(view_class, "data_scope", None)
        )

        self.assertEqual(
            unscoped,
            [],
            msg=(
                "Sensitif tapi tanpa cakupan — pemegang izinnya membaca "
                f"seluruh tenant: {unscoped}"
            ),
        )
