# Components

Katalog komponen `framework/` di repo Nuxt. Semuanya berprefiks `M`.

Halaman ini indeks; detail per kelompok ada di halaman masing-masing.

---

## Di mana komponen tinggal

| Lokasi | Isi | Boleh disunting? |
|---|---|---|
| `app/components/ui/` | shadcn-vue | hanya lewat CLI shadcn |
| `framework/components/` | komponen Meinova | **ya** |
| `app/modules/**/components/` | hasil generate | **tidak** |
| `app/pages/**` | halaman | ya |

!!! warning "Auto-import Nuxt tidak mencakup `app/modules/**`"
    Hanya `app/components/` dan direktori framework yang didaftarkan di `nuxt.config`.

    `MenuTreeNode.vue` pernah kena: datanya termuat ("Selected: 11") tapi **pohonnya tidak dirender sama sekali**, karena komponennya di bawah `app/modules/` dan tidak diimpor.

---

## Katalog

### `crud/`

| Komponen | Isi |
|---|---|
| `MCrudTable` | tabel + toolbar + pagination |
| `MCrudToolbar` | pencarian, tombol |
| `MCrudFilters` | dropdown filter, termasuk berantai |
| `MCrudActions` | Add/Export/Import |
| `MRecordActions` | tombol action per record (Submit/Approve/Generate) + dialognya |
| `MCrudDelete` | konfirmasi hapus |
| `MCrudEmpty`, `MCrudLoading`, `MCrudPagination` | |

→ [Tables](Tables.md)

### `forms/` — 30 komponen

`MFormBuilder` + field per tipe + rangka (`MFormGrid`, `MFormSection`, `MFieldLabel`, `MFieldHint`, `MFieldError`).

→ [Forms](Forms.md)

### `table/`

`MTable`, `MTableToolbar`, `MColumnHeader`, `MRowActions`, `MPagination`.

### `lookup/`

| Komponen | Untuk |
|---|---|
| `MLookupSelect` | dropdown |
| `MLookupDialog` | pilih dari dialog berpencarian |
| `MLookupTable` | pilih dari tabel |
| `MLookupTree` | pilih dari pohon |

→ [Lookup](../02-Framework/Lookup.md)

### `workspace/`

`MWorkspaceHistory` + `resource/` (`WorkspaceResource`, `ResourceTable`, `ResourceDialog`, `InlineResource`, `useResource`).

→ [Workspace](Workspace.md)

### `dashboard/`

`MDashboard`, `MDashboardStat`, `MDashboardChart`, `MDashboardList`, `MDashboardPeriodPicker`, `MDashboardFilters`.

→ [Dashboard](Dashboard.md)

### `tree/`

`MTreeBuilder`, `MTreeNode`, `MTreeSearch`, `MTreeToolbar` — dipakai Menu Permission & Data Permission.

### `import/` — 8 komponen

`MImportWorkspace`, `MImportForm`, `MImportColumnMapping`, `MImportPreviewTable`, `MImportReview`, `MImportResult`, `MImportSummary`, `MImportPagination`.

### `setting/`, `dialogs/`, `feedback/`

---

## Empat prop hantu yang pernah bertumpuk

!!! danger "Vue tidak mengeluhkan prop yang tidak dikenal"
    Prop yang tidak ada di komponen tujuan **jatuh jadi atribut mati**, tanpa satu pun error.

    `MCrudFilters` mengoper `:depends-on`, `:lookup-params`, `:form-values` ke `MLookupField` — **ketiganya tidak ada di sana**. Ditambah `placeholder` pada `MLookupSelect` yang dioper sejak lama padahal propnya tidak pernah ada.

    Hasilnya: filter tidak berantai walau Company sudah dipilih, dan tiga dropdown berjejer semuanya berbunyi **"Select"** tanpa ada yang memberi tahu mana Branch dan mana Location Type.

**`MLookupField` hanya menerima `depends`** — pasangan siap kirim yang sudah ter-resolve.

Urutan label tombol: `nullLabel` → `placeholder` → turunan label, diperiksa **truthy bukan nullish** (bawaan keduanya string kosong, dan `""` bukan nullish — ia menang lalu tombolnya kosong melompong), dan turunannya di-`trim()`.

---

## Komponen yang ditulis tangan, bukan digenerate

| Layar | Kenapa |
|---|---|
| `/workflow/inbox`, `/workflow/submissions`, `/workflow/instances/[id]` | bentuknya bukan CRUD |
| `WorkflowApprovalTrail.vue` | dipakai ulang ketiga halaman di atas |
| Tab User Roles & Role Permissions | tidak ada padanan CRUD-nya |
| `app/pages/index.vue` (beranda) | dirakit dari registry widget |
| `UsersTable.vue` dan saudaranya | ⚠️ **hasil generate yang disunting tangan** |

!!! danger "Tiga tabel Security membawa kode yang tidak dihasilkan generator"
    Role gating, `notify`, dan label hapus yang menyebut nama barisnya. Meregenerate module-nya **menghapus ketiganya tanpa error** — tabelnya tetap jalan, cuma tombolnya muncul untuk peran yang seharusnya read-only.

    Ada komentar pengingat di kepala tiap berkas.

Komponen versi tunggal sisa dari sebelum sebuah modul diregenerate (`UserTable.vue` vs `UsersTable.vue`) **wajib dihapus** — berkas pendampingnya berganti nama, jadi komponen lamanya mengimpor ekspor yang tidak ada lagi dan itu menggagalkan build **seluruh aplikasi**, bukan cuma halamannya.

---

## Composable

| Composable | Isi |
|---|---|
| `useCrud` | daftar, filter, pagination, **gerbang izin tombol** |
| `useCrudDialog`, `useCrudDelete`, `useCrudBulkDelete` | |
| `useAccess` | `can()`, `canWrite()`, `isGranted()` |
| `useMenuAccess` | centang menu per role |
| `useNotify` | toast |
| `useApi` | `cleanQuery` membuang parameter kosong |

!!! warning "State yang bertahan lintas navigasi wajib di-reset saat logout"
    `useMenuAccess`, `useNotifications`, dan gerbang izin `useCrud` disimpan di `useState`. `authStore.clear()` **wajib** me-`reset()` ketiganya — tanpa itu pengguna berikutnya yang login di tab yang sama mewarisi pembatasan (atau keleluasaan) milik pengguna sebelumnya.

!!! bug "`notify` tidak pernah dioper generator"
    Dari **196** pemakaian composable CRUD di seluruh modul, hanya **4** yang mengopernya — tiga tabel Security yang pernah ditambal tangan.

    `options.notify?.error(...)` pada `undefined` **tidak melakukan apa-apa**, jadi seluruh penolakan gagal tanpa suara. Sekarang composable-nya sendiri jatuh ke `useNotify()`.

Sisa yang belum rapi: `entity` juga tidak pernah dioper, jadi toast berbunyi `Data "X" created` alih-alih `Gender "X" created`. `useCrud` belum mengekspos nama resource-nya.

---

## Menambah komponen framework

- [ ] Prefix `M`, taruh di `framework/components/<kelompok>/`
- [ ] Ekspor di `index.ts` kelompoknya
- [ ] Prop dideklarasikan eksplisit — **prop tak dikenal gagal diam**
- [ ] Kalau menggantikan pola yang tersebar di banyak modul, pasang di `framework/` **bukan** di template generator — perbaikan di template tidak menyentuh modul yang sudah ada
- [ ] Kalau membedakan "kosong" dan "belum dipilih", pisahkan keadaannya secara eksplisit
