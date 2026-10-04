# Dashboard

**Dua hal berbeda yang sering tertukar.**

| | Dashboard **home** | Dashboard **modul** |
|---|---|---|
| Di mana | `/` (beranda) | `/hr/dashboard`, `/administration/dashboard` |
| Susunan | **per pengguna**, disimpan di DB | ditentukan kode, sama untuk semua |
| Backend | `apps/administration/api/dashboard/` | `schema_type: "dashboard"` per modul |
| Isi | widget lintas modul + pintasan | agregasi transaksi modul itu |

---

## Dashboard modul — `schema_type: "dashboard"`

Schema ditulis dengan `apps/framework/builders/dashboard.py`:

```python
dashboard.schema(
    widgets=[
        dashboard.stat(key="active_employees", label="Active Employees", span=3),
        dashboard.line(key="attendance_trend", span=8),
        dashboard.donut(key="leave_by_type", span=4),
        dashboard.listing(key="upcoming_holidays", columns=[...], span=6),
    ],
    filters=[dashboard.period_filter(modes=[...]), dashboard.lookup_filter(...)],
)
```

`span` memakai grid 12 kolom.

View mewarisi `BaseDashboardAPIView`. **Tiap widget wajib punya method `resolve_<key>`** — itu satu-satunya penghubung schema ↔ perhitungan.

!!! note "Widget tanpa resolver melempar `NotImplementedError`"
    Sengaja berisik daripada tampil kosong.

**Satu request mengembalikan semua widget** (`{period, widgets: {<key>: ...}}`). Satu endpoint per widget bikin halaman seperti HR menembak **12 request** hanya untuk render pertama.

Pasangan `ui-schema/` didaftarkan lewat `Cls.as_schema_view()` (`AllowAny`). Subclass yang dihasilkannya sengaja **mengosongkan `framework_module`** supaya `framework_schema_view` tidak menemukan dua kandidat untuk module yang sama.

Nilai query param yang tidak masuk akal **diabaikan** (jatuh ke default), bukan dibalas error — dashboard tidak boleh mati gara-gara satu query param salah ketik.

### Cakupan data tidak ikut sendiri

!!! danger "`BaseDashboardAPIView` adalah `APIView` biasa"
    `BaseMasterViewSet` menyaring `RoleDataPermission` lewat `filter_queryset()`. Dashboard merakit querysetnya sendiri, jadi jalur itu **tidak pernah dilewati**.

    Tiap service dashboard **wajib** memanggil `DataScopeService.filter(qs, <peta>, context["user"])` di **setiap** queryset yang dibangunnya.

Petanya sengaja disamakan persis dengan `data_scope` di viewset masing-masing — kalau salah satu diubah, yang satunya harus ikut, kalau tidak **angka dashboard tidak cocok dengan isi tabelnya**.

Tiga peta yang butuh `allow_null=True`, dan alasannya harus jelas:

| Model | Kenapa |
|---|---|
| `TrainingProgram` | company kosong berarti "berlaku untuk semua" — program induksi K3 se-grup tidak boleh hilang dari layar admin site |
| `AuditTrail` | `company` sering kosong bukan karena belum diisi — perubahan Role/Currency memang tidak menempel ke perusahaan mana pun |
| Division/Department/Section/Position | department tanpa `location` berarti berlaku lintas site |

`JobVacancy` tidak punya `own` — lowongan bukan "data milik seseorang".

---

## Periode: rentang tanggal, bukan bulan/tahun

`?mode=&start=&end=` diubah `resolve_period()` jadi satu dict. Resolver widget cukup membaca `period["start"]` / `period["end"]` — **satu widget melayani mode harian sampai rentang bebas tanpa cabang khusus**.

- Mode yang boleh dipakai ditentukan `modes` pada `period_filter(...)`; di luar itu ditolak backend
- `?year=&month=` masih diterima sebagai jalur lama
- Pembanding tren memakai **periode kalender sebelumnya** (Februari vs Januari penuh), bukan "mundur sekian hari"
- `trend_buckets()` memberi deret titik dengan satuan mengikuti mode — tanpa ini, memilih "hari ini" menghasilkan chart **satu titik**
- **Awal minggu = Senin.** Frontend menghitung ulang rentang yang sama untuk label tombol, jadi aturan ini harus tetap sama di dua repo

!!! note "Tren `None` kalau pembandingnya nol"
    "Naik 100%" untuk data yang baru mulai terisi lebih menyesatkan daripada tidak menampilkan apa-apa. FE menyembunyikan bagian tren saat nilainya null.

---

## Aturan isi: yang belum ada modelnya tidak dibuat

Seluruh isi beranda dulu `dashboardDummy`: "Total Companies 4", "Active Employees 248" di tenant berisi 10 orang, "Monthly Payroll Rp 1.2B" untuk modul yang belum punya model payroll run. **Angka yang sama persis untuk setiap orang yang login, termasuk saat didemokan ke klien.**

Karena itu "Monthly Payroll" dan "Revenue vs Expense" **hilang, bukan diganti nol**.

Contoh lain: "Master Records Growth" dihapus karena tidak ada model yang mencatat pertumbuhan master per bulan — menurunkannya dari `created_at` master yang diseed sekaligus cuma menghasilkan **satu batang raksasa** di bulan tenant dibuat. Penggantinya **Struktur Organisasi**, yang justru menjawab pertanyaan sebenarnya: level mana yang sudah terisi.

---

## Dua sumber angka yang jangan tertukar

| Widget | Disaring |
|---|---|
| Kotak masuk / pengajuan / dokumen berjalan | **keterlibatan** (`selectors.visible_instances`) |
| Active Employees | `RoleDataPermission` |

Yang pertama bukan cakupan organisasi — **approver lintas lokasi memang harus melihat dokumen yang mendarat di mejanya**.

Yang kedua harus sama persis dengan tabel Employee: kalau tidak, admin Gebe membaca 10 di beranda dan 6 di tabelnya, dan **selisih itu justru memberi tahu ada 4 baris yang disembunyikan darinya**.

!!! warning "Donut yang menghitung ganda"
    Approval Status memakai `Count("id", distinct=True)` — `visible_instances` menyaring lewat join ke `approvals`, jadi dokumen bertiga kotak tanda tangan terhitung tiga kali.

    `.distinct()` pada queryset **tidak** menolong setelah `values().annotate()`.

---

## Dashboard home

Beranda dulu merender **delapan komponen tetap dalam urutan tetap**, dan tidak pernah menyentuh `UserDashboardLayout` walau tabelnya sudah berisi dua belas baris.

Sekarang: katalog di kode (`HOME_WIDGETS`), susunan per pengguna di DB.

**Menambah widget = dua baris:** `HOME_WIDGETS` (backend) + `app/modules/dashboard/registry.ts` (peta nama → komponen). `index.vue` tidak perlu disentuh. Nama komponen tak dikenal **dilewati, bukan menjatuhkan halaman** — backend boleh di-deploy lebih dulu.

### Yang disimpan cuma urutan, tampil/tidak, terlipat/tidak

Bukan koordinat, bukan ukuran. `span` tetap milik katalog: ukuran bebas berarti tiap widget harus terlihat benar di berapa pun lebar, dan biaya perawatannya jauh lebih besar daripada nilainya.

`PUT` menyimpan **seluruh** susunan sekaligus — menggeser satu kartu mengubah posisi semua yang di bawahnya, jadi menyimpan per widget berarti puluhan request untuk satu tarikan.

### Bawaan tidak pernah ditulis ke DB

**Pembeda "belum pernah menyusun" adalah tidak adanya baris.** `seed_default_layout` (yang menulis satu baris untuk setiap pengguna × setiap widget) sudah dihapus: pengguna yang dibuat setelah seed tidak dapat susunan apa pun, dan yang dapat baris bawaan **berhenti mengikuti bawaan yang berubah besok**.

Pelajaran yang sama persis dengan `FavoriteApp.DEFAULT_CODES` dan pintasan menu.

### Keputusan tampilan yang punya alasan

| Keputusan | Alasan |
|---|---|
| Widget baru ditempel **di belakang** susunan tersimpan | kalau hanya baris tersimpan yang dirender, modul yang menambah widget besok tidak akan pernah terlihat oleh siapa pun yang sudah menekan Save |
| Yang disembunyikan **tetap dirender** saat Customize (pudar + tombol mata) | kalau dibuang, tidak ada cara memunculkannya lagi |
| **Naik/turun, bukan drag** | di ponsel drag bertabrakan dengan gulir halaman |
| `fixed_height` di katalog, bukan kelas CSS di komponen | tanpa itu tiga kartu berjejer jadi tiga tinggi berbeda — Notifications yang kosong tinggal seperempat tinggi tetangganya, dan barisnya terbaca seperti ada yang gagal dimuat |
| `fixed_height` **dilepas saat dilipat** | kalau tetap menempel, widget terlipat menyisakan sel setinggi 26rem — melipat ketiganya justru menghasilkan lubang kosong sebesar layar |
| Berlaku **hanya di `lg` ke atas** | kotak bergulir di dalam halaman yang juga bergulir adalah hal paling menjengkelkan di ponsel |

!!! note "`DashboardWidgetFrame` wajib `flex h-full flex-col` + `min-h-0 flex-1` pada slotnya"
    Anak sebuah flex punya `min-height: auto` bawaan, jadi tanpa `min-h-0` kartunya **menolak menyusut** dan `overflow-y-auto` di dalamnya tidak pernah menyala — kartunya memanjang sepanjang daftarnya.

### Kepala beranda

Sorotan hari ini: ulang tahun, ulang tahun kerja, hari libur. Ikut cakupan data.

- **Di hari biasa daftarnya kosong dan seluruh bagian itu hilang.** Baris yang 360 hari setahun berbunyi "tidak ada apa-apa hari ini" hanya melatih orang berhenti membacanya
- **Umur tidak disebut** — yang berulang tahun belum tentu ingin usianya diumumkan ke seluruh kantor
- Hari libur dikelompokkan jadi **satu baris**, bukan dua belas
- Sapaan (pagi/siang/sore/malam) dihitung di **frontend** dari jam perangkat — tenant ini dipakai lintas zona waktu, dan "Selamat pagi" jam sembilan malam adalah kesalahan yang langsung terlihat
- **Orang di kiri, hari libur di kanan** — menumpuknya dalam satu deret membuat "17 Agustus" terbaca seperti nama orang berikutnya
- Ulang tahun lebih dari satu ditampilkan **bergantian** (5 detik); berjejer semuanya membuat kepala halaman menabrak tombol Customize di hari yang ramai
- Gradien **di kepala saja** — latar berwarna di belakang angka adalah cara tercepat membuat kartu data tidak terbaca. Lingkaran aksennya wajib `pointer-events-none`, tanpa itu tombol Customize tidak bisa ditekan tanpa satu pun petunjuk kenapa

---

## Komponen

`MDashboard`, `MDashboardStat`, `MDashboardChart`, `MDashboardList`, `MDashboardPeriodPicker`, `MDashboardFilters`.

Dipakai HR **dan** Administration, jadi carousel kartu KPI di layar sempit ikut tanpa kode tambahan.

!!! warning "Urutan kolom `listing` menentukan tata letaknya"
    `MDashboardList` memakai kolom **pertama** sebagai judul baris, kolom **kedua** sebagai keterangan (**hanya kalau formatnya `text`**), sisanya jadi nilai kanan berlabel.

    Menaruh `time` di depan membuat daftar aktivitas dimulai dari jam, dan `hint` panjang di posisi terakhir akan terjepit di kolom kanan.

Dua format kolom yang ditambahkan ke framework: `datetime` (jejak audit yang tiga barisnya jatuh di hari yang sama tidak berarti apa-apa tanpa jam) dan `status` (badge, warnanya dari `state` pada barisnya — **bukan** dari teksnya, karena status yang sama berbunyi "Siap" di satu baris dan "Terisi 2026" di baris lain).

---

## Membuat dashboard modul baru

- [ ] Schema dengan `dashboard.schema(...)`
- [ ] View turunan `BaseDashboardAPIView`
- [ ] **`resolve_<key>` untuk setiap widget**
- [ ] **`DataScopeService.filter` di setiap queryset**, petanya disamakan dengan viewset
- [ ] `Cls.as_schema_view()` didaftarkan
- [ ] Widget yang datanya belum ada modelnya **tidak dibuat**
- [ ] `pnpm meinova generate <module>`
