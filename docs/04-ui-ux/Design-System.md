# Design System

Frontend Nuxt 3 + Tailwind CSS v4 + **shadcn-vue** (di atas `reka-ui`).

Yang membedakannya dari kebanyakan design system: **komponennya hampir tidak pernah dipakai langsung.** Layar CRUD digenerate dari schema backend, dan yang ditulis orang adalah *schema*, bukan template.

---

## Tiga lapis

```
app/components/ui/     ← shadcn-vue, jangan disunting manual
framework/components/  ← komponen Meinova (prefix M*), lintas modul
app/modules/**         ← hasil generate, JANGAN disunting
```

| Lapis | Boleh disunting? |
|---|---|
| `app/components/ui/` | hanya lewat CLI shadcn |
| `framework/**` | **ya** — perbaikan lintas modul tempatnya di sini |
| `app/modules/**` | **tidak** — tertimpa saat regenerate |
| `app/pages/**` | ya |

Aturan memilih tempat perbaikan: [Generator](../02-Framework/Generator.md#aturan-memilih-tempat-perbaikan).

---

## Komponen framework

Semuanya berprefiks `M`.

| Kelompok | Isi |
|---|---|
| `crud/` | `MCrudTable`, `MCrudToolbar`, `MCrudFilters`, `MCrudActions`, `MCrudDelete`, `MCrudEmpty`, `MCrudLoading`, `MCrudPagination`, `MRecordActions` |
| `forms/` | 30 komponen field + `MFormBuilder`, `MFormGrid`, `MFormSection` |
| `table/` | `MTable`, `MTableToolbar`, `MColumnHeader`, `MRowActions`, `MPagination` |
| `lookup/` | `MLookupSelect`, `MLookupDialog`, `MLookupTable`, `MLookupTree` |
| `workspace/` | `MWorkspaceHistory`, `resource/` (inline & dialog) |
| `dashboard/` | `MDashboard`, `MDashboardStat`, `MDashboardChart`, `MDashboardList`, `MDashboardPeriodPicker`, `MDashboardFilters` |
| `tree/` | `MTreeBuilder`, `MTreeNode`, `MTreeSearch`, `MTreeToolbar` |
| `import/` | 8 komponen alur import |
| `setting/`, `dialogs/`, `feedback/` | |

Detail per kelompok: [Components](Components.md) · [Forms](Forms.md) · [Tables](Tables.md) · [Workspace](Workspace.md) · [Dashboard](Dashboard.md)

---

## Registry — nama string yang dipetakan ke aset

Backend mengirim **nama**, bukan komponen. Pemetaannya di `app/registry/`:

| Berkas | Memetakan |
|---|---|
| `app.ts` | nama ikon aplikasi/modul |
| `color.ts` | nama warna → kelas gradien + teks |
| `badge.ts`, `status.ts` | status → varian badge |
| `widget.ts` | nama widget → komponen Vue |
| `menu.ts`, `permission.ts` | |
| `master-hub/` | kartu Master Hub per modul |

!!! danger "Nama yang tidak dikenal jatuh ke bawaan, tanpa error"
    Salah ketik `icon`/`color` di backend **gagal tanpa suara** — kartunya tetap tampil, cuma dengan ikon polos.

    Konsekuensi praktisnya: menu baru yang ikonnya belum didaftarkan di `app/registry/app.ts` akan terlihat "kurang jadi" tanpa ada yang tahu kenapa. 26 ikon pernah ditambahkan sekaligus untuk menutup seluruh isi `MENU_TREE`.

**Menambah widget beranda = dua baris:** satu di `HOME_WIDGETS` (backend) + satu di registry FE. Nama komponen yang tidak dikenal **dilewati, bukan menjatuhkan halaman** — backend boleh di-deploy lebih dulu daripada frontend.

---

## Dua kosakata ikon yang harus dijembatani

| Tempat | Gaya |
|---|---|
| `Menu.icon` (sidebar) | Nuxt UI — `i-lucide-clock-3` |
| Beranda | kunci `appRegistry` — `clock-3` |

`menu_catalog._icon()` di backend yang membuang awalannya. Kalau menambah menu, periksa **keduanya**.

---

## Warna

`app/registry/color.ts` memetakan nama → pasangan kelas:

```ts
blue: { bg: 'from-blue-500/15 to-cyan-500/5', text: 'text-blue-600' }
```

Backend menyebut `"blue"`, bukan kelas Tailwind. Alasannya dua: kelas Tailwind harus ada di build FE (purge), dan warna adalah keputusan tampilan yang tidak boleh diketik ulang di setiap katalog.

Detail: [Colors](Colors.md).

---

## Prinsip yang berulang di UI ini

Lima hal yang muncul lagi dan lagi dalam keputusan komponen:

### 1 · Yang kosong harus bisa dibedakan dari yang gagal

`MTreeBuilder` pernah menulis "No resources found." baik saat filternya **belum dipilih** maupun saat datanya memang kosong — jadi tab Data Permissions terbaca seperti master kosong padahal role-nya belum dipilih. Sekarang dipisah lewat `missingQuery`.

Pola yang sama: kartu Notifications menampilkan "No notifications." (bukan kotak putih), dan filter lookup **tanpa `lookup_endpoint` dilewati** alih-alih dirender sebagai dropdown yang selalu kosong.

### 2 · Penolakan harus terlihat

Request yang ditolak pernah gagal **tanpa satu kalimat pun** — lima sebab bertumpuk. Sekarang: toast (lewat `normalizeApiErrors`) + banner yang menempel di bawah form.

Banner **bukan** pengganti toast: form Employee panjangnya empat puluh kolom, jadi banner di kepala sudah keluar layar sebelum orangnya menekan Save, sementara toast hilang dalam empat detik.

### 3 · Tombol yang pasti ditolak sebaiknya tidak ada

`useCrud` membaca `GET /api/framework/permissions/` dan menyembunyikan Add/Edit/Delete yang izinnya tidak ada.

Tapi **resource yang tidak dikenal tidak disaring** — menganggapnya terlarang akan mengosongkan tombol di layar yang izinnya sebenarnya ada.

### 4 · Bawaan yang tidak pernah ditulis ke DB

Susunan beranda, katalog aplikasi, pintasan menu: **pembeda "belum pernah menyusun" adalah tidak adanya baris.** Menulis bawaan saat seed membuat pengguna berhenti mengikuti bawaan yang berubah besok.

### 5 · Naik/turun, bukan drag

Di ponsel, drag bertabrakan dengan gulir halaman dan selalu terasa rusak. Tombol bekerja sama di kedua ukuran layar.

Pengecualian: `vuedraggable` di mode Customize — dan di sana drag **dimatikan selama daftarnya tersaring**, karena ia mengembalikan urutan daftar yang **dirender**, dan menyimpannya saat tersaring akan membuang seluruh baris yang sedang tidak cocok.

---

## Verifikasi

!!! danger "Build lolos bukan bukti halamannya jalan"
    `<SelectItem value="">` melempar dan menjatuhkan seluruh halaman — errornya muncul saat **hidrasi di browser**, bukan SSR. `curl` membalas 200 dan `nuxi build` lolos.

    Opsi "Semua …" memakai sentinel (`const ALL = 'all'`) yang diterjemahkan jadi string kosong tepat sebelum dikirim ke API.

!!! danger "Vue tidak mengeluhkan prop yang tidak dikenal"
    Prop hantu jatuh jadi atribut mati tanpa satu pun error. **Empat pernah bertumpuk sekaligus** di toolbar filter (`depends-on`, `lookup-params`, `form-values`, `placeholder`) — filternya tidak berantai dan dropdown-nya semua berbunyi "Select", tanpa petunjuk apa pun.

Satu-satunya verifikasi yang sah: **buka halamannya di browser sungguhan**, dan coba dengan akun non-superuser.
