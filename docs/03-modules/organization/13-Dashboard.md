# Administration — Dashboard Modul

`framework_module = "administration/dashboard"`, endpoint `/api/administration/overview/`.

!!! warning "Nama paketnya `overview`, bukan `dashboard`"
    `apps/administration/api/overview/` — sengaja berbeda supaya tidak tertukar dengan `apps/administration/api/dashboard/` yang adalah dashboard **home** (favorit aplikasi, pintasan, tata letak widget per pengguna).

    Yang menentukan letak berkas hasil generate adalah **nama module** (`administration/dashboard` → `app/modules/administration/dashboard/`), dan `app/pages/administration/index.vue` sudah mengimpor dari sana sejak versi statisnya.

---

## Apa yang digantikannya

Isinya dulu `data.ts` di repo Nuxt: "Companies 5", "Users 286", "Master Records 1,245", grafik berjudul **"Dummy monthly growth"**, dan "Today · 08 Jul 2026" yang ditulis mati di template.

Angka yang sama persis untuk setiap orang yang login, di tenant mana pun, **termasuk saat didemokan ke klien**.

---

## Widget

### "Master Records Growth" dihapus, bukan dihitung ulang

Tidak ada model yang mencatat pertumbuhan master per bulan, dan menurunkannya dari `created_at` master yang **diseed sekaligus** cuma menghasilkan **satu batang raksasa** di bulan tenant dibuat — chart yang secara teknis benar tapi tidak memberi informasi apa pun.

Penggantinya **Struktur Organisasi** — jumlah baris per level, yang justru menjawab pertanyaan sebenarnya: **level mana yang sudah terisi.**

### Kartu struktur `trend=False`

Jumlah perusahaan tidak berubah tiap bulan. "Naik 0% dari bulan lalu" di bawah setiap kartu cuma derau.

Yang bertren cuma **aktivitas**.

### Chart aktivitas dari `AuditTrail`

Baru mungkin **setelah jejak audit punya penulis**. Sebelum itu tabelnya nol baris — dan widget yang selalu kosong memang tidak layak dibuat.

Pola yang layak ditiru: buat chartnya **setelah** sumber datanya benar-benar terisi.

### Hari Libur Mendatang: dikelompokkan per (tanggal, nama)

Bukan per baris.

`Holiday` wajib menyebut company, jadi satu libur nasional tersimpan **dua belas kali** di tenant berisi dua belas perusahaan — daftar enam baris itu seluruhnya terisi "Hari Kemerdekaan" yang sama dan **libur berikutnya tidak pernah kelihatan**.

Sengaja **di luar filter periode**, sama seperti Pengingat Kepegawaian di dashboard HR.

---

## Kesehatan Konfigurasi — delapan pemeriksaan sungguhan

Menggantikan enam baris yang dulu **selalu berbunyi sama**, termasuk "Email Notification: Not configured" di sistem yang tidak punya modul notifikasi email sama sekali.

- Tiap baris membawa **`link`** ke layar tempat memperbaikinya — temuan tanpa jalan keluar cuma memindahkan kebingungan
- `critical` memisahkan "sistem tidak bisa dipakai" (**danger**) dari "sebaiknya diisi" (**warning**)

!!! bug "Pemeriksaan ini menemukan bug lama di menit pertama"
    `apps/administration/seeds/currency.py` menulis kunci `is_base`, sementara kolomnya `is_base_currency`.

    `seed_reference` **membuang kunci yang bukan field model — tanpa error**. Jadi **tidak ada satu tenant pun yang punya mata uang dasar** sejak seed pertama.

    Gagalnya jauh dari sumbernya: import payroll menjatuhkan currency kosong ke `Currency.is_base_currency`, tidak ketemu, dan baris penempatan gajinya **ditolak**.

    Sudah dibetulkan; tenant lama wajib `seed_administration --only=currency`.

---

## Cakupan data

Dipasang di tiap queryset, seperti dashboard modul lain. Dua catatan yang tidak boleh hilang:

| Model | Perlakuan | Kenapa |
|---|---|---|
| `AuditTrail` | **`allow_null=True`** | `company`-nya sering kosong **bukan** karena belum diisi — perubahan Role, Currency, dan seluruh master referensi memang tidak menempel ke perusahaan mana pun. Menyaringnya dengan aturan biasa membuat baris-baris itu tak terlihat siapa pun kecuali superuser |
| Division/Department/Section/Position | **`allow_null=True`** | hanya Company yang wajib; department tanpa `location` berarti **berlaku lintas site**. Tanpa itu, admin yang dicakup ke satu lokasi membaca "Department 0" padahal departmentnya sendiri ada |

!!! danger "Dashboard ini lebih ketat daripada tabelnya"
    **Delapan dari sembilan viewset organisasi tidak punya `data_scope` sama sekali**, jadi tabel Company/Branch/Location/Department masih terbaca utuh oleh admin bercakupan sempit.

    Selisihnya disengaja — layar baru sebaiknya menutup lebih dulu — tapi itu berarti invarian **"angka dashboard cocok dengan isi tabel" belum berlaku di sini.**

---

## Frontend

`MDashboard` yang sama dengan HR, jadi carousel kartu KPI di layar sempit ikut tanpa kode tambahan.

Dua format kolom ditambahkan ke framework untuk dashboard ini:

| Format | Kenapa |
|---|---|
| `datetime` | jejak audit yang tiga barisnya jatuh di hari yang sama tidak berarti apa-apa tanpa jam |
| `status` | badge berwarna, warnanya dari **`state`** pada barisnya — **bukan** dari teksnya, karena status yang sama berbunyi "Siap" di satu baris dan "Terisi 2026" di baris lain |

!!! warning "Urutan kolom `listing` menentukan tata letaknya"
    `MDashboardList` memakai kolom **pertama** sebagai judul baris, kolom **kedua** sebagai keterangan (**hanya kalau formatnya `text`**), sisanya jadi nilai kanan berlabel.

    Menaruh `time` di depan membuat daftar aktivitas dimulai dari jam, dan `hint` panjang di posisi terakhir akan terjepit di kolom kanan.

---

## Rujukan

Mekanisme dashboard modul: [UI/UX → Dashboard](../../04-ui-ux/Dashboard.md) · Contoh terlengkap: [HR Dashboard](../hr/Dashboard.md)
