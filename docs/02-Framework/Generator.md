# Generator Frontend

CLI di repo Nuxt (`~/Project/nuxt/meinova-erp`) yang mengubah schema backend jadi berkas Vue/TypeScript.

Baca [Pipeline BE → FE](BE-to-FE-Pipeline.md) dulu untuk gambaran besarnya. Halaman ini referensi teknisnya.

---

## Perintah

```bash
pnpm meinova generate <module>          # dari schema API — yang biasa dipakai
pnpm meinova generate:import <module>   # hanya berkas import
pnpm meinova make:crud <module>         # scaffold kosong, tanpa memanggil API
```

Contoh:

```bash
pnpm meinova generate hr/employees
pnpm meinova generate administration/organization/company
pnpm meinova generate:import hr/employees
```

### Sumber schema

```
${MEINOVA_API_BASE_URL}/api/framework/schema/<module>/
```

`MEINOVA_API_BASE_URL` default `http://demo.localhost:8000`.

Override sekali jalan:

```bash
pnpm meinova generate hr/leave \
  --schema-url=http://tenant.localhost:8000/api/framework/schema/hr/leave/
```

Keluaran yang benar:

```
✔ Schema   : http://demo.localhost:8000/api/framework/schema/hr/leave/
✔ Endpoint : /api/hr/leaves/
✔ Import   : hr.leave        ← hanya kalau schema punya key "import"
```

!!! warning "Baris `Endpoint` adalah pemeriksaan pertamamu"
    Kalau isinya bukan URL API yang kamu harapkan, `endpoint` belum dideklarasikan di schema dan generator menurunkannya dari `framework_module`. Tabelnya akan menampilkan **"No results."** tanpa error apa pun.

---

## Pemilihan template

`schema.type` yang menentukan:

| `type` | Generator | Template |
|---|---|---|
| `crud` | `crud.mjs` | `crud-dialog/` · `crud-page/` · `crud-workspace/` (dipilih dari `ui.editor`) |
| `tree` | `tree.mjs` | |
| `setting` | `setting.mjs` | |
| `dashboard` | `dashboard.mjs` | `dashboard/` |

Untuk `dashboard`, `schema.endpoint` dipakai **apa adanya** — endpoint datanya bukan URL schema, melainkan endpoint tersendiri yang mengembalikan seluruh widget sekaligus. Tiga tipe lainnya memakai pathname dari URL schema.

---

## Generator per bagian

`scripts/meinova/generators/`:

| Berkas | Menghasilkan | Membaca dari schema |
|---|---|---|
| `columns.mjs` | `columns.ts` | field ber-`table` |
| `filters.mjs` | `filters.ts` | field ber-`filter`, `depends_on`, `lookup_params` |
| `form.mjs` | `form.ts` | field ber-`form`, `visible_when`, `hidden`, `default` |
| `table.mjs` | `table.ts` | `ui` |
| `actions.mjs` | `actions.ts` | `schema.actions` yang punya `endpoint` |
| `workspace.mjs` | `workspace.ts` | `tabs` |
| `overview.mjs` | komponen Overview | field ber-`overview` |
| `types.mjs` | `types.ts` | seluruh field |
| `import.mjs` | berkas import | `schema.import` |
| `page.mjs` | `page.vue` | |

---

## Keluaran satu module CRUD workspace

```
app/modules/hr/leave/
├── columns.ts  filters.ts  form.ts  table.ts  actions.ts  workspace.ts
├── types.ts  index.ts  page.vue
├── components/
│   ├── LeaveTable.vue      LeaveForm.vue    LeaveTabs.vue
│   ├── LeaveHeader.vue     LeaveOverview.vue LeaveWorkspace.vue
│   └── forms/LeaveForm.vue
├── composables/
│   └── useLeaveList.ts  useLeaveDetail.ts  useLeaveWorkspace.ts
└── shared/workspace-resource/
    └── InlineResource.vue  ResourceDialog.vue  ResourceTable.vue
        WorkspaceResource.vue  useResource.ts
```

Halamannya **tidak** digenerate — buat sendiri di `app/pages/<framework_module>/`.

---

## Apa yang boleh disunting tangan

| | Aman disunting? |
|---|---|
| `app/modules/**` hasil generate | **Tidak** — tertimpa saat regenerate |
| `framework/**` | Ya — berlaku di semua modul tanpa regenerate |
| `scripts/meinova/generators/**` | Ya — berlaku untuk modul yang **diregenerate sesudahnya** |
| `scripts/meinova/templates/**` | Ya — berlaku untuk modul **baru** |
| `app/pages/**` | Ya |
| Halaman workflow inbox/submissions/detail | Ya — memang ditulis tangan |

!!! danger "Tiga tabel Security adalah pengecualian yang harus diingat"
    `UsersTable.vue` dan saudaranya membawa **role gating**, **`notify`**, dan **label hapus yang menyebut nama barisnya** — ketiganya tidak dihasilkan generator.

    Meregenerate module-nya menghapus ketiganya **tanpa error**: tabelnya tetap jalan, cuma tombolnya muncul untuk peran yang seharusnya read-only. Ada komentar pengingat di kepala tiap berkas; pasang ulang setelah regenerate.

### Aturan memilih tempat perbaikan

> **Perbaikan yang menyentuh lebih dari satu modul hampir selalu masuk `framework/`, bukan generator.**

Perbaikan di generator tidak menyentuh modul yang sudah ada sampai diregenerate — dan yang lupa meregenerate tetap membawa bug lamanya, tanpa tanda apa pun.

Contoh nyata: penanganan error 403 dipasang di `normalizeApiErrors` (`framework/`) supaya seratus modul tidak perlu diregenerate satu per satu.

---

## Bug generator yang pernah terjadi

Berguna dibaca karena polanya berulang — semuanya **gagal tanpa error**.

| Bug | Akibatnya |
|---|---|
| `filter` bentuk dict diperiksa `=== true` | Layar Departments tidak punya filter Company/Location/Division **sama sekali**, padahal ketiganya dideklarasikan |
| `depends_on` + `lookup_params` dibuang dari `filters.ts` | Filter berantai jalan di form, mati di toolbar tabel |
| `schema.actions` tidak dibaca sama sekali | "Generate Periods" dan "Regenerate" tidak pernah muncul walau endpoint-nya jalan |
| `visible_when` dan `hidden` dibuang | Kolom kontrak ikut tampil untuk pegawai tetap |
| `default` dibuang | Switch "Auto Generate Employee Number" tampil **mati** padahal schema menyalakannya |
| Field ber-`read_only` dibuang dari `form.ts` | Field turunan yang sengaja ditaruh di sebuah tab **hilang** — perbaikannya `display=True` |
| `display_key` cuma dibaca untuk lookup | Kolom Action Type menampilkan `employment_type_change`, Status menampilkan `applied` |

---

## Sisa yang belum rapi

- **`entity` pada composable CRUD tidak pernah dioper generator**, jadi toast berbunyi `Data "X" created` alih-alih `Gender "X" created`. `useCrud` belum mengekspos nama resource-nya.
- Komponen versi tunggal sisa dari sebelum sebuah modul diregenerate (`UserTable.vue` vs `UsersTable.vue`) **wajib dihapus** — berkas pendampingnya berganti nama, jadi komponen lamanya mengimpor ekspor yang tidak ada lagi dan itu menggagalkan build **seluruh aplikasi**, bukan cuma halamannya.

---

## Verifikasi setelah generate

1. Buka halamannya **di browser sungguhan.** `nuxi build` lolos dan `curl` membalas 200 walau halamannya rusak — `<SelectItem value="">` melempar saat **hidrasi**, bukan saat SSR.
2. Rute baru butuh **restart dev server**.
3. Cocokkan `column.*("key")` di `columns.ts` dengan kunci payload API sungguhan. Kolom yang keynya tidak ada akan tampil `-` tanpa error.
