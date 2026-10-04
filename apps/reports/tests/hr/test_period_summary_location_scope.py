"""
Filter Location pada HR Period Summary, dan tombol pintas "Lokasi Saya".

Dua aturan yang diuji di sini, dan keduanya pernah terbaca seperti bug
yang sebenarnya bukan bug:

1. **`Result = Authorized Organization Scope ∩ Selected Location`.**
   Filter hanya mempersempit; menyebut id lokasi di luar cakupan tidak
   pernah membuka satu baris pun. Yang menentukan siapa yang terlihat
   **bukan** garis pelaporan, department, section, atau jabatan
   pemilihnya — hanya kolom Location pegawainya.

2. **Satu nama lokasi bisa berarti dua baris.** Location unik per
   company, jadi satu gedung yang ditempati dua badan usaha berdiri
   sebagai dua baris dengan nama yang sama persis. Memilih salah
   satunya benar-benar mengembalikan sebagian — dan itu yang membuat
   labelnya harus menyebut company.

Ditambah perilaku tombol "Lokasi Saya" untuk direksi: satu tekan =
tempat ia duduk **di seluruh badan usaha yang boleh ia lihat**, bukan
satu baris dan bukan seluruh cakupannya. Itu kenyamanan, bukan
wewenang — isinya tetap lewat `DataScopeService`.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import override_settings

from apps.accounts import board
from apps.accounts.api.auth.serializers import MeSerializer
from apps.hr.tests.access_helpers import grant_employee_read
from apps.accounts.models import (
    AuthorityMode,
    DataScopeLevel,
    Role,
)
from apps.accounts.services.role_assignment import grant_role
from apps.administration.api.organization.lookup.registry import LocationLookup
from apps.administration.models import Company, Location
from apps.administration.models.references.hr import EmployeeGroup
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    OrganizationAssignment,
)
from apps.reports.api.hr.period_summary.services import HRPeriodSummaryService

from .base import PERIOD_END, PERIOD_START, PeriodSummaryTestCase


User = get_user_model()


BOARD_GROUPS = ["BOARD"]


class LocationScopeTests(PeriodSummaryTestCase):
    """
    Panggung: dua company, dan **dua lokasi bernama sama persis**.

    `cls.company` + `cls.ho` ("Jakarta HO") datang dari base. Yang
    ditambahkan di sini company kedua dengan lokasi bernama "Jakarta
    HO" juga — bentuk yang sama dengan tenant peragaan, tempat MNI dan
    MMR sama-sama punya "Jakarta Head Office".
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.other_company = Company.objects.create(
            code="RPT2",
            name="Report Test Dua",
        )

        # Nama **dan kode**-nya sengaja sama persis dengan `cls.ho`.
        # Kode hanya unik per company (`uniq_core_location_company_code`),
        # jadi satu gedung yang ditempati dua badan usaha memang berdiri
        # sebagai dua baris ber-kode sama — bentuk yang sama dengan
        # `JKT-HO` milik MNI dan MMR di tenant peragaan.
        cls.other_ho = Location.objects.create(
            company=cls.other_company,
            code=cls.ho.code,
            name="Jakarta HO",
        )

        cls.board_group = EmployeeGroup.objects.create(
            code="BOARD",
            name="Board of Directors",
        )

    # ------------------------------------------------------------------
    # Pabrik
    # ------------------------------------------------------------------

    @classmethod
    def make_employee_at(cls, *, company, location, group=None) -> Employee:
        index = cls._next()

        employee = Employee.objects.create(
            employee_number=f"LOC{index:04d}",
            first_name="Uji",
            last_name=f"Lokasi {index}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=company,
            location=location,
            organization_effective_date=date(2025, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=date(2025, 1, 1),
            working_calendar=cls.calendar,
            employee_group=group,
        )

        return Employee.objects.get(pk=employee.pk)

    def make_user(self, *, username, employee=None, companies=(), location=None):
        """
        Akun bercakupan, **dinyatakan pada penugasannya**.

        Ada `companies` berarti `EXPLICIT` berisi company itu; tanpa
        `companies` berarti cakupan ikut penempatan pemegangnya sedalam
        Location.
        """
        user = User.objects.create_user(
            username=username,
            password="Uji#12345",
        )

        # `Role` menjawab WHAT saja; WHERE-nya pada penugasan di bawah.
        role = Role.objects.create(
            code=f"ROLE-{username.upper()}",
            name=f"Role {username}",
        )

        # Laporan menuntut `hr.view_employee`, sama dengan tabel
        # Employee. Di produksi setiap role yang diseed memegangnya
        # (`READ_GRANTS`), jadi fixture yang tidak memberikannya
        # menguji keadaan yang tidak pernah ada — dan gagal karena
        # sebab yang bukan sedang diujinya.
        grant_employee_read(role)

        if companies:
            grant_role(
                user, role,
                mode=AuthorityMode.EXPLICIT,
                authorities=[("company", company.id) for company in companies],
            )
        else:
            grant_role(
                user, role,
                mode=AuthorityMode.PLACEMENT,
                level=DataScopeLevel.LOCATION,
            )

        if employee is not None:
            employee.user = user
            employee.save(update_fields=["user"])

        return user

    def counted(self, user, locations=None) -> int:
        """
        Angka yang **benar-benar dilihat orang di layar**.

        Pilihannya dilewatkan `expand_location_selection` lebih dulu —
        penerjemahan yang sama persis dengan yang dipasang
        `BaseDashboardAPIView.expand_filter_values`. Menghitung tanpa
        itu berarti test membuktikan sesuatu yang tidak pernah terjadi
        di layar mana pun.
        """
        context = {
            "user": user,
            "period": {"start": PERIOD_START, "end": PERIOD_END},
        }

        if locations is not None:
            context["location"] = board.expand_location_selection(
                user,
                [str(item) for item in locations],
            )

        return HRPeriodSummaryService.employee_queryset(
            context,
            PERIOD_START,
            PERIOD_END,
        ).count()

    def counted_raw(self, user, locations) -> int:
        """
        Tanpa penerjemahan — kontrak `employee_queryset` sendiri:
        cakupan ∩ id yang disebut, apa adanya.
        """
        return HRPeriodSummaryService.employee_queryset(
            {
                "user": user,
                "period": {"start": PERIOD_START, "end": PERIOD_END},
                "location": [str(item) for item in locations],
            },
            PERIOD_START,
            PERIOD_END,
        ).count()

    def setUp(self):
        super().setUp()

        # Dua orang di "Jakarta HO" milik company pertama, satu orang di
        # "Jakarta HO" milik company kedua, satu di site. Angkanya
        # sengaja berbeda-beda supaya assertion tidak bisa lolos karena
        # kebetulan sama.
        self.ho_a1 = self.make_employee_at(
            company=self.company, location=self.ho,
        )
        self.ho_a2 = self.make_employee_at(
            company=self.company, location=self.ho,
        )
        self.ho_b1 = self.make_employee_at(
            company=self.other_company, location=self.other_ho,
        )
        self.site_1 = self.make_employee_at(
            company=self.company, location=self.site,
        )

    # ------------------------------------------------------------------
    # Cakupan ∩ Location
    # ------------------------------------------------------------------

    def test_tanpa_filter_location_mengembalikan_seluruh_cakupan(self):
        director = self.make_employee_at(
            company=self.other_company,
            location=self.other_ho,
            group=self.board_group,
        )

        user = self.make_user(
            username="uji.bod",
            employee=director,
            companies=[self.company, self.other_company],
        )

        # 4 dari setUp + direksinya sendiri.
        self.assertEqual(self.counted(user), 5)

    def test_memilih_satu_baris_location_mengembalikan_baris_itu_saja(self):
        user = self.make_user(
            username="uji.bod2",
            companies=[self.company, self.other_company],
        )

        # Dua lokasi bernama sama persis, isinya berbeda — inilah yang
        # membuat "pilih Jakarta HO" terbaca seperti cakupan yang bocor
        # kalau labelnya tidak menyebut company.
        self.assertEqual(self.counted(user, [self.ho.id]), 2)
        self.assertEqual(self.counted(user, [self.other_ho.id]), 1)

    def test_memilih_kedua_baris_menggabungkan_keduanya(self):
        user = self.make_user(
            username="uji.bod3",
            companies=[self.company, self.other_company],
        )

        self.assertEqual(
            self.counted(user, [self.ho.id, self.other_ho.id]),
            3,
        )

    def test_multi_location_tidak_pernah_melewati_cakupan_company(self):
        """Company kedua di luar cakupan → barisnya tidak ikut."""
        user = self.make_user(
            username="uji.satu.company",
            companies=[self.company],
        )

        total = self.counted(user)

        # Menyebut lokasi milik company yang tidak dicakupnya tidak
        # menambah satu baris pun.
        self.assertEqual(
            self.counted(user, [self.ho.id, self.other_ho.id, self.site.id]),
            total,
        )

    def test_location_di_luar_cakupan_tidak_membuka_data(self):
        user = self.make_user(
            username="uji.terbatas",
            companies=[self.company],
        )

        self.assertEqual(self.counted(user, [self.other_ho.id]), 0)

    def test_filter_location_tidak_memakai_garis_pelaporan(self):
        """
        Pegawai di lokasi yang sama tetap muncul walau tidak punya
        hubungan atasan-bawahan, department, atau group yang sama
        dengan pemilihnya.
        """
        director = self.make_employee_at(
            company=self.company,
            location=self.ho,
            group=self.board_group,
        )

        user = self.make_user(
            username="uji.tanpa.bawahan",
            employee=director,
            companies=[self.company, self.other_company],
        )

        # Tidak ada satu pun `reports_to` yang menunjuk direkturnya, dan
        # `ho_a1`/`ho_a2` tidak sekelompok dengannya — semuanya tetap
        # terhitung karena lokasinya sama.
        #
        # Empat, bukan tiga: pemilihnya direksi (`BOARD` ada di
        # `BOARD_EMPLOYEE_GROUPS` bawaan), jadi "Jakarta HO" berarti
        # kedua baris ber-kode sama — `ho_b1` di company kedua ikut.
        # Yang dibuktikan test ini tetap yang sama: **lokasi** yang
        # menentukan siapa terlihat, bukan garis pelaporan.
        self.assertEqual(self.counted(user, [self.ho.id]), 4)

    # ------------------------------------------------------------------
    # Tombol "Lokasi Saya"
    # ------------------------------------------------------------------

    @override_settings(BOARD_EMPLOYEE_GROUPS=BOARD_GROUPS)
    def test_lokasi_saya_direksi_mencakup_seluruh_baris_penempatannya(self):
        director = self.make_employee_at(
            company=self.other_company,
            location=self.other_ho,
            group=self.board_group,
        )

        user = self.make_user(
            username="uji.direksi",
            employee=director,
            companies=[self.company, self.other_company],
        )

        values = MeSerializer().get_self_filter_values(user)

        self.assertIsInstance(values["location"], list)

        # Tempatnya tetap tempat ia duduk. Yang ditambahkan cuma baris
        # kembarannya di company pertama — bukan lokasi lain dalam
        # cakupannya.
        self.assertEqual(
            sorted(values["location"]),
            sorted([self.ho.id, self.other_ho.id]),
        )
        self.assertNotIn(self.site.id, values["location"])

        # Empat orang di "Jakarta HO": `ho_a1`, `ho_a2`, `ho_b1`, plus
        # direkturnya sendiri.
        self.assertEqual(self.counted(user, values["location"]), 4)

        # Dan tombolnya benar-benar **mempersempit**: `site_1` tidak
        # ikut, jadi angkanya berbeda dari tanpa filter sama sekali.
        # Tombol yang menghasilkan angka yang sama tidak memberi tahu
        # apa-apa.
        self.assertNotEqual(
            self.counted(user, values["location"]),
            self.counted(user),
        )

        # Menekan tombol sama dengan memilih "Jakarta HO" di dropdown
        # yang sudah dikelompokkan — satu jalan, satu angka.
        self.assertEqual(self.counted(user, [self.other_ho.id]), 4)

        # Kontrak service-nya sendiri tidak ikut berubah: kalau yang
        # dioper memang satu id, yang terhitung tetap baris itu saja.
        self.assertEqual(self.counted_raw(user, [self.other_ho.id]), 2)

    @override_settings(BOARD_EMPLOYEE_GROUPS=BOARD_GROUPS)
    def test_lokasi_saya_non_direksi_tetap_satu_lokasi_penempatan(self):
        staff = self.make_employee_at(
            company=self.company,
            location=self.ho,
        )

        user = self.make_user(
            username="uji.staf",
            employee=staff,
            companies=[self.company, self.other_company],
        )

        values = MeSerializer().get_self_filter_values(user)

        # Satu angka, bukan daftar — perilaku lama, tidak berubah.
        self.assertEqual(values["location"], self.ho.id)

    @override_settings(BOARD_EMPLOYEE_GROUPS=BOARD_GROUPS)
    def test_lokasi_saya_direksi_tidak_menambah_akses(self):
        """
        Tombolnya kenyamanan, bukan wewenang: daftar yang diisinya tidak
        pernah memuat lokasi di luar cakupan pemegangnya.
        """
        director = self.make_employee_at(
            company=self.company,
            location=self.ho,
            group=self.board_group,
        )

        user = self.make_user(
            username="uji.direksi.sempit",
            employee=director,
            companies=[self.company],
        )

        values = MeSerializer().get_self_filter_values(user)

        self.assertNotIn(self.other_ho.id, values["location"])
        self.assertEqual(values["location"], [self.ho.id])

        # Sama dengan memilih lokasi itu sendiri: `ho_a1`, `ho_a2`, plus
        # direkturnya. `site_1` di luar, walau ada di cakupannya.
        self.assertEqual(self.counted(user, values["location"]), 3)
        self.assertEqual(
            self.counted(user, values["location"]),
            self.counted(user, [self.ho.id]),
        )

    @override_settings(BOARD_EMPLOYEE_GROUPS=[])
    def test_tanpa_konfigurasi_group_direksi_perilakunya_kembali_lama(self):
        director = self.make_employee_at(
            company=self.company,
            location=self.ho,
            group=self.board_group,
        )

        user = self.make_user(
            username="uji.direksi.mati",
            employee=director,
            companies=[self.company, self.other_company],
        )

        values = MeSerializer().get_self_filter_values(user)

        self.assertEqual(values["location"], self.ho.id)

    # ------------------------------------------------------------------
    # Label dropdown
    # ------------------------------------------------------------------

    def test_label_location_menyebut_company_hanya_saat_namanya_ambigu(self):
        user = self.make_user(
            username="uji.label",
            companies=[self.company, self.other_company],
        )

        queryset = LocationLookup.apply_scope(
            LocationLookup.get_queryset(),
            SimpleNamespace(user=user),
        )

        labels = {
            item.id: LocationLookup.serialize(item)["label"]
            for item in queryset
        }

        # Dua baris bernama "Jakarta HO" → keduanya diberi pembeda.
        self.assertEqual(labels[self.ho.id], f"Jakarta HO — {self.company.code}")
        self.assertEqual(
            labels[self.other_ho.id],
            f"Jakarta HO — {self.other_company.code}",
        )

        # Yang namanya memang cuma satu **tidak** ikut diberi ekor.
        self.assertEqual(labels[self.site.id], self.site.name)

    def test_dropdown_location_mengikuti_cakupan(self):
        user = self.make_user(
            username="uji.dropdown",
            companies=[self.company],
        )

        queryset = LocationLookup.apply_scope(
            LocationLookup.get_queryset(),
            SimpleNamespace(user=user),
        )

        self.assertNotIn(
            self.other_ho.id,
            set(queryset.values_list("id", flat=True)),
        )

    # ------------------------------------------------------------------
    # Pengelompokan Location per kode — khusus direksi
    # ------------------------------------------------------------------

    @override_settings(BOARD_EMPLOYEE_GROUPS=BOARD_GROUPS)
    def test_dropdown_direksi_satu_baris_per_kode(self):
        director = self.make_employee_at(
            company=self.company,
            location=self.ho,
            group=self.board_group,
        )

        user = self.make_user(
            username="uji.group.dropdown",
            employee=director,
            companies=[self.company, self.other_company],
        )

        queryset = LocationLookup.apply_scope(
            LocationLookup.get_queryset(),
            SimpleNamespace(user=user),
        )

        rows = [LocationLookup.serialize(item) for item in queryset]
        labels = [row["label"] for row in rows]

        # "Jakarta HO" muncul **sekali**, bukan dua kali, dan tanpa ekor
        # company — barisnya memang mewakili keduanya.
        self.assertEqual(labels.count("Jakarta HO"), 1)
        self.assertNotIn(f"Jakarta HO — {self.company.code}", labels)
        self.assertIn(self.site.name, labels)

        # Satu baris per kode, bukan per company.
        codes = list(queryset.values_list("code", flat=True))
        self.assertEqual(len(codes), len(set(codes)))

    @override_settings(BOARD_EMPLOYEE_GROUPS=BOARD_GROUPS)
    def test_direksi_pilih_satu_tempat_menjaring_seluruh_company_dalam_cakupan(self):
        director = self.make_employee_at(
            company=self.company,
            location=self.ho,
            group=self.board_group,
        )

        user = self.make_user(
            username="uji.group.pilih",
            employee=director,
            companies=[self.company, self.other_company],
        )

        # `ho_a1`, `ho_a2`, `ho_b1`, plus direkturnya — satu pilihan,
        # dua baris master, empat orang. Tidak perlu mencentang
        # keduanya satu per satu.
        self.assertEqual(self.counted(user, [self.ho.id]), 4)

        # Wakil mana pun yang terpilih di dropdown memberi hasil yang
        # sama — itu yang membuat "id terkecil sebagai wakil" tidak
        # menentukan apa-apa.
        self.assertEqual(self.counted(user, [self.other_ho.id]), 4)

    @override_settings(BOARD_EMPLOYEE_GROUPS=BOARD_GROUPS)
    def test_kode_yang_sama_di_luar_cakupan_tidak_ikut_terjaring(self):
        """
        Inilah batas yang harus dipegang pengelompokan: kode yang sama
        di perusahaan yang **tidak** dicakupnya tidak punya jalan masuk.
        """
        director = self.make_employee_at(
            company=self.company,
            location=self.ho,
            group=self.board_group,
        )

        user = self.make_user(
            username="uji.group.sempit",
            employee=director,
            companies=[self.company],
        )

        expanded = board.expand_location_selection(user, [str(self.ho.id)])

        self.assertNotIn(str(self.other_ho.id), expanded)

        # `ho_a1`, `ho_a2`, plus direkturnya. `ho_b1` di company kedua
        # tidak ikut walau kode lokasinya sama persis.
        self.assertEqual(self.counted(user, [self.ho.id]), 3)

    @override_settings(BOARD_EMPLOYEE_GROUPS=BOARD_GROUPS)
    def test_dua_tempat_yang_dipilih_digabungkan(self):
        director = self.make_employee_at(
            company=self.company,
            location=self.ho,
            group=self.board_group,
        )

        user = self.make_user(
            username="uji.group.dua",
            employee=director,
            companies=[self.company, self.other_company],
        )

        # Seluruh Jakarta HO (4) + site (1).
        self.assertEqual(
            self.counted(user, [self.ho.id, self.site.id]),
            5,
        )

    @override_settings(BOARD_EMPLOYEE_GROUPS=BOARD_GROUPS)
    def test_pengelompokan_tidak_berlaku_untuk_non_direksi(self):
        staff = self.make_employee_at(
            company=self.company,
            location=self.ho,
        )

        user = self.make_user(
            username="uji.group.staf",
            employee=staff,
            companies=[self.company, self.other_company],
        )

        # Dropdown-nya tetap memuat kedua baris, lengkap dengan pembeda
        # company.
        queryset = LocationLookup.apply_scope(
            LocationLookup.get_queryset(),
            SimpleNamespace(user=user),
        )

        labels = [LocationLookup.serialize(item)["label"] for item in queryset]

        self.assertIn(f"Jakarta HO — {self.company.code}", labels)
        self.assertIn(f"Jakarta HO — {self.other_company.code}", labels)

        # Dan pilihannya tidak diperluas: `ho_a1`, `ho_a2`, plus dirinya.
        self.assertEqual(
            board.expand_location_selection(user, [str(self.ho.id)]),
            [str(self.ho.id)],
        )
        self.assertEqual(self.counted(user, [self.ho.id]), 3)

    @override_settings(BOARD_EMPLOYEE_GROUPS=BOARD_GROUPS)
    def test_id_di_luar_cakupan_tidak_diperluas_jadi_tanpa_filter(self):
        """
        Id yang tidak dikenal dibiarkan apa adanya, bukan dibuang.

        Membuangnya membuat daftar pilihannya kosong, dan filter kosong
        berarti **tanpa penyaringan** di sistem ini — persis kebalikan
        dari yang dimaksud.
        """
        director = self.make_employee_at(
            company=self.company,
            location=self.ho,
            group=self.board_group,
        )

        user = self.make_user(
            username="uji.group.asing",
            employee=director,
            companies=[self.company],
        )

        self.assertEqual(
            board.expand_location_selection(user, [str(self.other_ho.id)]),
            [str(self.other_ho.id)],
        )
        self.assertEqual(self.counted(user, [self.other_ho.id]), 0)

    @override_settings(BOARD_EMPLOYEE_GROUPS=BOARD_GROUPS)
    def test_lokasi_saya_tidak_terpotong_pengelompokan_dropdown(self):
        """
        Dropdown-nya menampilkan satu wakil per kode; tombolnya tidak
        boleh ikut terpotong begitu. Isinya tetap **seluruh** id
        ber-kode sama, karena id itulah yang dikirim sebagai filter.
        """
        director = self.make_employee_at(
            company=self.other_company,
            location=self.other_ho,
            group=self.board_group,
        )

        user = self.make_user(
            username="uji.group.lokasisaya",
            employee=director,
            companies=[self.company, self.other_company],
        )

        values = MeSerializer().get_self_filter_values(user)

        self.assertIn(self.ho.id, values["location"])
        self.assertIn(self.other_ho.id, values["location"])

        # Berhenti di kodenya sendiri: lokasi lain dalam cakupannya
        # tidak ikut terbawa.
        self.assertNotIn(self.site.id, values["location"])
