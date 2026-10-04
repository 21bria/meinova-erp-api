# Permission

Tiga lapis penjagaan, dan **jangan tertukar** — ketiganya menjawab pertanyaan yang berbeda.

| Lapis | Pertanyaan | Kelas | Menjaga sungguhan? |
|---|---|---|---|
| Izin model | "boleh **mengubah** tabel ini?" | `ModelPermission` | ya |
| Akses menu | "menu ini disodorkan atau tidak?" | `MenuAccessService` | **tidak** |
| Cakupan data | "**baris yang mana** yang boleh dilihat?" | `DataScopeService` | ya |

**Menu tersembunyi dan izin tulis tidak menyembunyikan satu baris pun.**

Plus dua lapis khusus di HR: [`EmployeeActionPolicy`](../09-business-flows/Employee-Action.md#siapa-boleh-mengusulkan-employeeactionpolicy) (siapa boleh mengusulkan) dan [`EmployeeDataPolicy`](../09-business-flows/Employee-Action.md#kerahasiaan-employeedatapolicy) (bagian mana dari satu baris yang boleh dilihat).

---

## Tidak ada konsep "group"

Yang ada `Role` kustom, dan ia sudah berfungsi sebagai grup:

| Model | Isi |
|---|---|
| `Role.permissions` | M2M ke `auth.Permission` — 708 baris |
| `RoleMenuPermission` | menu apa yang terlihat |
| `RoleDataPermission` | data siapa yang terlihat |
| `User.roles` | penugasan |

!!! danger "`User.groups` bawaan Django diwarisi tapi TIDAK dibaca satu baris kode pun"
    Dua sistem paralel, dan yang bawaan itu jebakan. Karena itu `groups` **tidak lagi dikirim** di `/api/accounts/auth/me/` maupun jadi kolom di layar Users.

---

## Izin model — `ModelPermission`

708 baris `auth.Permission` sudah lama tersimpan di `Role.permissions` dan bisa dicentang di layar Roles, tapi **tidak ada satu baris kode pun yang membacanya** — `user.has_perm()` bawaan Django cuma melihat `user_permissions` dan `groups`.

Yang menutup jaraknya `RolePermissionBackend` (`apps/accounts/backends.py`), terdaftar di `AUTHENTICATION_BACKENDS` **di samping** `ModelBackend` (yang tetap dibutuhkan untuk `authenticate()` saat login; Django meng-OR hasil semua backend).

### Tiga batas yang disengaja

| Batas | Alasan |
|---|---|
| **Hanya aksi CRUD baku** (`create`/`update`/`partial_update`/`destroy`/`bulk_delete`) | Endpoint `@action` seperti `submit/`, `approve/`, `sync/` punya aturan jauh lebih spesifik. Pegawai berhak mengajukan cutinya sendiri tanpa izin mengubah tabel cuti seisi perusahaan |
| **Membaca dibiarkan terbuka** | Dropdown dipakai lintas modul oleh orang yang tidak berkepentingan mengubahnya. Penyaringan baris itu urusan `RoleDataPermission` |
| **`ENFORCE_MODEL_PERMISSIONS`** bisa dimatikan | Menyalakannya di tenant yang role-nya kosong membuat seluruh sistem read-only kecuali superuser |

### Dipasang di `get_permissions()`, bukan cuma `permission_classes`

Puluhan viewset menulis ulang `permission_classes` — kebanyakan sekadar mengulang `[IsAuthenticated]` — dan itu **mengganti** daftarnya, bukan menambah. `CurrencyViewSet` sudah terbukti lolos begitu: 403 di mana-mana, 400 di currency, tanpa satu pesan pun.

Viewset yang memang tidak boleh dijaga izin model menyatakannya lewat `enforce_model_permissions = False` — dipakai `WorkflowDelegationViewSet`, karena menyerahkan hak tanda tangan sendiri tidak boleh perlu menunggu IT.

### Urutan menyalakannya bukan selera

```bash
python manage.py tenant_command seed_security_roles --schema=demo
```

**Dulu itu, baru penjagaannya berlaku.** Seed mengisi matriks awal:

| Role | Izin |
|---|---|
| `SYSTEM-ADMIN` | semua |
| `HR-ADMIN`, `HR-MANAGER` | `hr` + `administration` |
| `HRGA` | `hr` |
| `SECURITY-ADMIN` | `accounts` |
| `WORKFLOW-ADMIN` | `workflow` |
| `EMPLOYEE` | 4 model cuti/perjalanan |
| `ADMIN-SECTION`, `ADMIN-DEPARTMENT` | 7 model (roster setup + baris, attendance, leave, travel request + purpose + arrangement) |

Ia juga memberi `SYSTEM-ADMIN` ke semua superuser, dan role dasar `EMPLOYEE` ke akun yang belum punya role sama sekali — tanpa yang terakhir, pegawai biasa kehilangan kemampuan mengajukan cutinya sendiri begitu penjagaan menyala.

Aman diulang: izin **ditambahkan**, tidak pernah dicabut.

!!! note "Matriks itu titik awal, bukan kebijakan"
    Sesudah seed, seluruh pengaturannya pindah ke layar Roles — centang per model, per tenant, tanpa rilis kode. Matriksnya cuma supaya sistem tidak lumpuh di menit pertama.

`ADMIN-SECTION` sengaja **tanpa** `hr.employee` dan `hr.siterotation`: jadwal terbit dari dokumen Setup dan berubah lewat Adjustment; membukanya untuk disunting langsung membatalkan seluruh gunanya versi dan baseline.

---

## Cakupan data — `DataScopeService`

Lapisan **satu-satunya yang benar-benar mencegah data bocor**.

`RoleDataPermission` sudah lama ada dan bisa dicentang di tab Data Permissions, tapi — pola yang sama untuk keempat kalinya — tidak ada yang membacanya.

### Semantik

| | Operator |
|---|---|
| Antar-jenis dalam satu role | **AND** (company Karya Wijaya *dan* location Gebe) |
| Sesama jenis | **OR** (Gebe *atau* Jakarta HO) |
| Antar role | **OR** — menambah role selalu menambah akses |

!!! danger "Role tanpa satu pun baris = TANPA BATASAN"
    Bukan tanpa akses. Konsekuensinya **cakupan wajib menempel pada role yang memberi aksesnya.**

    Memisah jadi `HR-ADMIN` (fungsi, tak bercakupan) + `SCOPE-GEBE` (cakupan) **tidak bekerja** — role fungsi yang tak bercakupan membuka semuanya kembali.

    Karena itu polanya `HR-ADMIN-GEBE` / `HR-ADMIN-JKT`, dan yang mencakup keduanya diberi dua role. Titik pindahnya: kalau lebih dari ~5 site, cakupan sebaiknya dipindah ke user, bukan menumpuk role.

Jebakan yang sama mengenai role dasar `EMPLOYEE`: tanpa satu baris pun ia justru berarti *tanpa batasan*, dan pegawai biasa tetap bisa membaca daftar seluruh pegawai lewat API walau menunya tersembunyi. Karena itu ia dibatasi ke `own`.

### Peta per viewset

```python
data_scope = {
    "company": "organization__company",
    "location": "organization__location",
    "section": "organization__section",
    "own": "user_id",
}
```

- `None` = tidak disaring — benar untuk master data (jenis cuti bukan rahasia per lokasi).
- **Jenis yang tidak ada di peta dilewati**, bukan menolak semua. Model yang tidak menyimpan section tidak bisa dipersempit ke section, dan menolak seluruh barisnya mengosongkan layar tanpa sebab yang bisa dibaca.

### Dipasang di `filter_queryset()`

Dua alasan, dan yang kedua menentukan — dijelaskan di [Siklus Request](Request-Lifecycle.md#cakupan-data-datascopeservice).

### `DATA_SCOPE_INCLUDE_NULL`

Bawaan `False`: baris yang kolom cakupannya kosong **tidak ikut terlihat**.

Trade-off-nya nyata di dua arah. Hanya Company yang wajib di struktur ini, jadi membiarkan NULL lolos membuat data siapa pun yang lupa mengisi lokasi jadi terbuka — tapi sebaliknya, data itu jadi **tak terlihat siapa pun kecuali superuser**.

Beberapa pemanggil menimpanya per-panggilan dengan `allow_null=True`, dan alasannya harus jelas:

| Model | Kenapa `allow_null=True` |
|---|---|
| `AuditTrail` | `company`-nya sering kosong **bukan** karena datanya belum diisi — perubahan pada Role, Currency, dan seluruh master referensi memang tidak menempel ke perusahaan mana pun |
| `TrainingProgram` | company kosong berarti "berlaku untuk semua". Program induksi K3 se-grup tidak boleh hilang dari layar admin site |
| Division/Department/Section/Position | department tanpa `location` berarti **berlaku lintas site** |

**Jangan** dipakai sebagai jalan pintas untuk model yang kosongnya cuma karena datanya belum lengkap.

!!! warning "`RoleDataPermission` tidak punya kolom `can_view`"
    Itu milik `RoleMenuPermission`. Dua model bersaudara dengan bentuk berbeda, dan sudah **dua kali** menjatuhkan kode yang menyalinnya.

### Yang belum disaring

- Lookup di luar Employee
- Delapan dari sembilan viewset organisasi (`data_scope` belum dipasang) — dashboard Administration sekarang justru **lebih ketat** daripada tabelnya
- Jalur workflow, **sengaja** — memasang cakupan lokasi di situ membuat approver lintas lokasi tidak bisa menyetujui dokumen yang mendarat di mejanya

---

## Akses menu — `MenuAccessService`

Pola ketiga yang sama: `Menu` + `RoleMenuPermission` + layarnya semuanya sudah ada, tapi tabelnya **tidak pernah diisi** (0 baris) dan tidak ada yang membaca centangnya.

```bash
python manage.py tenant_command seed_menus --schema=demo   # 17 grup + 57 item
```

- **Sumber kebenarannya tetap sisi Nuxt** (`app/constants/menus.ts`). Menambah item di sana berarti menambahnya di sini juga, kalau tidak item itu **tidak akan pernah bisa dibatasi**.
- **Kunci pencocokannya `route`, bukan judul** — judul berubah jauh lebih sering, dan centang yang sudah disimpan orang tidak boleh hilang gara-gara "Leave" diganti jadi "Cuti".
- **Kode grup berprefiks `group:`.** Tanpa itu grup "Masters" dan menu "Masters" menghasilkan kode yang sama, dan `update_or_create` menimpa baris grupnya diam-diam.
- **Role tanpa satu pun baris menu = tanpa batasan.** Seed membatasi **tiga** role lewat `RESTRICTED_ROLES`; sisanya sengaja dibiarkan supaya menambah menu baru tidak mengharuskan seseorang mencentanginya ulang di tujuh role.

### `visibility_rule` — syarat pola kerja per menu

`always` / `roster_only` / `non_roster_only`.

Ada menu yang benar untuk sebuah role tapi **tidak untuk semua pemegangnya**: Travel Request adalah dokumen **kepulangan dari site**, jadi pegawai kantor pusat tidak punya kepulangan untuk diajukan.

- **Disimpan di baris `RoleMenuPermission`, bukan di settings.** Sempat ditulis sebagai `MENU_ROSTER_ONLY_ROUTES` di `base.py` dan itu salah tempat — seluruh pengaturan menu di sistem ini sudah per tenant dan bisa disunting dari layar.
- **Satu baris tanpa syarat sudah cukup membuka menunya.** Menambah role harus menambah akses, tidak pernah menguranginya.
- Penandanya **dua**: `roster_crew` (jalur lama) **atau** `roster_policy` (jalur Roster Setup). Memeriksa salah satunya saja membuat separuh pegawai site kehilangan menunya.

!!! note "Jangan memecah `EMPLOYEE` jadi dua role hanya demi menu"
    Tiga lapisan harus diduplikasi dan dijaga tetap sama — menu, izin model, dan cakupan data — untuk satu perbedaan. Dan pemberian rolenya jadi langkah manual yang **gagal diam-diam** saat orangnya pindah HO↔site: rolenya tertinggal, menunya salah, tanpa satu pun pesan.

    `visibility_rule` membacanya dari penempatan, jadi ikut sendiri.

### Bukan penjagaan

Rutenya tetap bisa diketik dan API-nya tetap melayani. FE menyaring **dua kali** — `isGranted` (wewenang) dan `isVisible` (centang per role) — dan **route yang tidak dikenal dianggap boleh**.

Menu access disimpan di `useState` yang bertahan lintas navigasi, jadi `authStore.clear()` **wajib** me-`reset()`-nya. Tanpa itu pengguna berikutnya yang login di tab yang sama mewarisi pembatasan milik pengguna sebelumnya.

---

## Wewenang — `apps/accounts/capabilities.py`

Satu-satunya sumber wewenang, dipakai **dua arah**:

1. `permissions.py` tiap modul memakainya menolak request
2. `/auth/me` mengirimkannya sebagai `capabilities` supaya frontend menyembunyikan menu

Dua-duanya, bukan salah satu — menu tersembunyi tidak menghalangi orang menembak API, dan API yang menolak tanpa menu tersembunyi membuat orang mengetuk pintu yang tak akan dibuka.

| Kelas | Baca | Tulis |
|---|---|---|
| `CanManageSecurity` | terbuka | superuser + `SECURITY_ADMIN_ROLES` |
| `IsSecurityAdmin` | **terkunci** | idem — isinya sendiri sudah sensitif |
| `CanConfigureWorkflow` | terbuka | superuser + `WORKFLOW_CONFIG_ROLES` |
| `CanManageDelegation` | terbuka | orang boleh mengurus kuasanya **sendiri** |

**Nama wewenang yang tidak dikenal dianggap boleh** (`isGranted`). Menu yang hilang gara-gara salah ketik jauh lebih sulit dilacak daripada menu yang tampil lalu ditolak API-nya dengan pesan jelas.

---

## Peta izin untuk frontend

```
GET /api/framework/permissions/
```

Satu request untuk seluruh resource, dikunci pada **endpoint** (bukan `framework_module`, yang boleh berbeda dari path URL-nya).

**Dihitung di backend, bukan disimpulkan frontend dari `/auth/me`** — viewset ber-`enforce_model_permissions = False` dan saklar `ENFORCE_MODEL_PERMISSIONS` tidak terlihat dari sana, dan salah menyimpulkannya justru **menghilangkan tombol yang seharusnya ada**.

Dipasang di `useCrud` (di `framework/`, bukan di berkas hasil generate): seluruh tabel membaca `crud.ui`, jadi satu gerbang di sana menutup semua modul **tanpa regenerate**.

- **Resource yang tidak dikenal tidak disaring.** 22 viewset belum menuliskan `endpoint` di schema-nya sehingga tidak terdaftar; menganggapnya terlarang akan mengosongkan tombol di layar yang izinnya sebenarnya ada.
- `import`/`export` **tidak** ikut disaring — keduanya membaca.
- `authStore.clear()` wajib me-`reset()`-nya.

!!! bug "Dua jebakan saat membangunnya"
    1. `ModelPermission._model` menerima *instance* dan jatuh ke `get_queryset()`. Memanggilnya pada **kelas** membuat `get_queryset()` jalan tanpa `self` → `TypeError` → tertangkap `except` → `None` untuk **semua** viewset, dan hasilnya daftar izin kosong yang terbaca persis seperti "semua tombol boleh". `_model_of()` karena itu membaca `queryset` → `service_class.model` → `serializer_class.Meta.model`, tanpa menyentuh database.
    2. `_all_subclasses` hanya menemukan kelas yang **sudah diimpor**, jadi view-nya menyentuh `get_resolver().url_patterns` lebih dulu.

---

## Mengaturnya dari layar

Penjagaan izin tidak ada gunanya kalau tidak ada kenopnya, dan layar Security hasil generate **tidak punya satu pun**. Dua tab ditambahkan, keduanya **ditulis tangan** (aman dari regenerate):

| Tab | Endpoint |
|---|---|
| **User Roles** — pilih pengguna → centang role | `/api/accounts/user-roles/{tree,save}/` |
| **Role Permissions** — pohon app → model → View/Create/Edit/Delete | `/api/accounts/role-permissions/{tree,save}/` |

- Urutan kata kerjanya **View → Create → Edit → Delete**, bukan abjad `add/change/delete/view` — itu urutan orang berpikir, dan daftar abjad menaruh "hapus" di tengah.
- **Dikelompokkan, bukan didaftar rata.** 708 kotak centang dalam satu daftar tidak bisa dipakai siapa pun. App infrastruktur Django disembunyikan lewat `HIDDEN_APPS`.
- Simpul app/model **bukan** izin; id-nya string (`app:hr`, `model:hr.employee`) supaya tidak pernah tertukar dengan pk `Permission`. Sisi service **membuang** yang bukan angka, bukan menolaknya — menolak berarti seluruh penyimpanan gagal gara-gara satu simpul grup.
- Pencarian mencocokkan simpul **atau keturunannya**; mencocokkan simpulnya saja membuat mengetik "employee" menyembunyikan grup HR yang justru memuatnya.

!!! bug "Tombol Save di layar Menu Permissions selalu dibalas 400 sejak layarnya dibuat"
    `MTreeBuilder` komponen generik dan selalu mengirim `resources`; `MenuPermissionSaveSerializer` cuma mengenal `menus`. Tidak pernah ketahuan karena penolakannya juga tidak pernah tampil.

!!! bug "`MTreeBuilder` menulis \"No resources found.\" untuk dua keadaan berbeda"
    Baik saat filternya belum dipilih maupun saat datanya memang kosong — jadi tab Data Permissions terbaca seperti master yang kosong padahal role-nya belum dipilih. Sekarang dipisah lewat `missingQuery`.

---

## Penolakan 403 dulu tidak terlihat sama sekali di layar

Menyalakan penjagaan izin memunculkan bug yang jauh lebih luas: **request yang ditolak gagal tanpa satu kalimat pun**. Tombol Save ditekan, tidak terjadi apa-apa.

Lima sebab bertumpuk. Semuanya sudah diperbaiki **di `framework/`**, bukan di berkas hasil generate — jadi regenerate module tidak menghidupkannya lagi.

| # | Sebab |
|---|---|
| 1 | `notify` tidak pernah dioper. Dari **196** pemakaian composable CRUD, hanya **4** yang mengopernya. Sekarang composable-nya sendiri jatuh ke `useNotify()` |
| 2 | Kunci pesannya salah — envelope menaruh kalimatnya di **`message`**, hampir semua penanganan error membaca `detail` lalu jatuh ke `error.message` milik `$fetch` (`[POST] "http://…": 403 Forbidden`). Sekarang lewat `apiErrorMessage()` |
| 3 | Grid inline diam total — error tanpa nama field tidak menempel ke kolom mana pun |
| 4 | `<X>Form.vue` menyaring error ke kunci yang cocok dengan kolom tab itu, jadi `detail` dibuang sebelum dirender |
| 5 | `page.vue` menangkap kegagalan simpan dan menelannya diam-diam — benar untuk 400 berisi error per field, tapi 403 tidak punya field mana pun untuk ditempeli |

Laporannya dipasang di **`normalizeApiErrors`**: satu-satunya titik di `framework/` yang dilewati **setiap** jalur simpan di seluruh modul hasil generate. Memasangnya di template generator berarti seratus modul harus diregenerate dulu, dan yang lupa tetap gagal diam-diam.

Dedupe lewat penanda pada objek error-nya (`reportApiError` / `wasReported`), bukan dengan mencabut toast milik pemanggil — tanpa penanda itu satu 403 menghasilkan dua toast yang sama persis.

Plus **banner yang menempel di bawah form** (`MFormBuilder`). Bukan pengganti toast: form Employee panjangnya empat puluh kolom, jadi banner di kepala sudah keluar layar sebelum orangnya menekan Save, sementara toast hilang dalam empat detik — dan pesan penolakan hak akses justru yang perlu tetap terbaca sambil disalin.

---

## Seed uji

```bash
python manage.py tenant_command seed_data_scopes --schema=demo
```

Membuat `HR-ADMIN-GEBE`, `HR-ADMIN-JKT`, `HR-ADMIN-ALL` + membatasi `EMPLOYEE` ke data sendiri.
