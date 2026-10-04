# Lookup

Semua dropdown dan relasi di frontend dilayani lookup registry (`apps/framework/lookup/`), bukan endpoint CRUD resource-nya.

Alasannya: endpoint CRUD membalas envelope `{success, data: [...]}` lengkap dengan seluruh kolom, sementara dropdown cuma butuh `{value, label}` dan harus bisa disaring/dicari dengan cepat.

---

## Mendaftarkan lookup

```python
from apps.framework.lookup.decorators import register_lookup
from apps.framework.lookup.base import BaseLookup


@register_lookup
class RosterCrewLookup(BaseLookup):
    name = "roster-crews"                    # unik LINTAS DOMAIN
    model = RosterCrew
    search_fields = ["code", "name"]
    filter_fields = ["company_id", "location_id"]

    @classmethod
    def serialize(cls, obj):
        return {
            "value": obj.pk,
            "label": obj.name,
            # Hanya kunci di sini yang boleh dipakai `autofill`.
            "work_schedule": obj.work_schedule_id,
        }
```

Tiga syarat, dan melanggar salah satunya gagal tanpa suara:

1. **`name` unik lintas domain** — registry-nya global.
2. **Modulnya di-import dari `AppConfig.ready()`.** Kalau lupa, endpoint-nya **404**. `apps/hr/api/lookup/registry.py` di-import dari `HrConfig.ready()` persis karena ini.
3. **Parameter yang tidak terdaftar di `filter_fields` diabaikan diam-diam** — penyebab klasik dropdown yang "tidak mau tersaring".

---

## Path endpoint

Bentuknya `/<prefix domain>/lookup/<nama>/`, **bukan** `/<resource>/lookup/`.

| Kelompok | Path |
|---|---|
| Organisasi | `/api/administration/organization/lookup/{companies,branches,locations,divisions,departments,sections,positions,cost-centers}/` |
| Referensi HR | `/api/administration/references/hr/lookup/<nama>/` |
| Currency | `/api/administration/currency/lookup/currencies/` |
| Transaksional HR | `/api/hr/lookup/{training-programs,job-vacancies,candidates,roster-plans,rotation-segments}/` |
| Workflow | `/api/workflow/lookup/workflow-definitions/` |
| Roles | `/api/accounts/lookup/roles/` |

!!! bug "Path yang salah tulis gagal diam"
    Schema attendance sempat memakai `/api/administration/companies/lookup/` yang tidak pernah ada — dropdown-nya **404 tanpa pesan error**.

!!! bug "Dropdown role selalu kosong"
    Panel Menu Permissions menunjuk `/api/accounts/roles/` — endpoint **CRUD** yang membalas envelope `{success, data: [...]}`, sementara `LookupSelect` membaca `results` di tingkat teratas. Pakai `/api/accounts/lookup/roles/`.

---

## Penyaringan berantai

Dua kunci yang bekerja berpasangan, dan **keduanya wajib**:

```python
field.lookup(
    lookup_endpoint="/api/administration/organization/lookup/sections/",
    lookup_params={
        "company_id": "$company",
        "location_id": "$location",
        "department_id": "$department",
    },
    depends_on=["company", "location"],
)
```

| Kunci | Fungsinya |
|---|---|
| `lookup_params` | menyaring isi dropdown; `$field` di-resolve dari nilai form |
| `depends_on` | menonaktifkan field sampai induknya terisi, **dan mengosongkannya saat induknya berubah** |

!!! danger "`depends_on` bukan cuma pengatur enable/disable"
    Ia juga yang **mengosongkan** field saat induknya berubah. Field yang dipakai di `lookup_params` tapi tidak disebut di `depends_on` akan **tetap menempel** setelah induknya diganti, dan penolakannya baru muncul saat Simpan.

    Boleh diisi list. FE menonaktifkan field kalau **salah satu** induknya kosong, jadi hanya sebutkan induk yang memang wajib di form itu.

### Kirim seluruh induk, bukan cuma yang terdekat

Karena level organisasi boleh dilompati, penyaringan satu level akan gugur dan dropdown menampilkan data seluruh perusahaan.

Di sisi backend, lookup organisasi mewarisi `OrganizationScopedLookup` yang mendaftarkan seluruh induk di `filter_fields` dan memakai pola **"cocok dengan induk ATAU induknya null"**.

### Contoh konkret: Section di Roster Setup

`depends_on` tetap `["company", "location"]`, **tanpa** `department` — menyebutnya membuat Section mati selama Department kosong, padahal Department memang boleh tidak dipakai. Penyaringannya tetap jalan lewat `lookup_params={"department_id": "$department"}` yang diabaikan kalau nilainya kosong.

---

## `autofill`

Mengisi field lain dari baris lookup yang dipilih.

```python
field.lookup(
    lookup_endpoint=".../roster-crews/",
    autofill={"work_schedule": "work_schedule"},   # {field tujuan: kunci lookup}
)
```

!!! danger "`autofill` yang menyebut kunci tak diserialisasi akan MENGOSONGKAN field tujuannya"
    `MFormBuilder.applyAutofill` dulu menulis `selected?.[sourceKey] ?? null`, jadi kunci yang tidak ada = tulis `null`.

    Akibatnya di form Roster Setup: pilih Company → pilih Site → **Company kosong lagi**, dan Section ikut mati karena `depends_on`-nya. `LocationLookup` memang cuma mengirim `{value, label}`; yang mengirim `company`/`branch`/`location` adalah `EmployeeLookup`.

    Sekarang kunci yang **tidak ada** dilewati (+ `console.warn` di dev), sementara kunci yang **ada tapi bernilai null** tetap mengosongkan — pegawai yang memang tidak punya branch harus mengosongkan Branch.

    **Tetap periksa `serialize()` lookup-nya sebelum menulis `autofill`.** Jaring itu bukan izin untuk menebak nama kunci.

Contoh pemakaian yang benar: field Company di form Employee membawa `autofill={"employee_number": "next_employee_number"}`, dan `CompanyLookup.serialize()` mengirim `EmployeeNumberService.preview()` — memilih Company langsung memperlihatkan nomor yang akan terbit.

---

## Filter berantai di toolbar tabel

`depends_on` + `lookup_params` sudah lama ditulis di schema dan sudah lama dipakai `MFormBuilder`, tapi generator filter **membuang keduanya** — jadi hanya form-nya yang tersaring.

Di tabel Locations, memilih Company "Karya Wijaya" tetap menyisakan dropdown Branch berisi seluruh tenant: dua belas baris bernama persis "Default Location" dari dua belas perusahaan berbeda, tanpa satu pun keterangan yang membedakannya.

Sudah diperbaiki. **Setelah ini, schema apa pun yang punya `depends_on`/`lookup_params` otomatis dapat filter berantai begitu module-nya diregenerate.**

Empat bug yang bertumpuk di jalur ini, layak diketahui karena polanya berulang:

1. Generator membuang `depends_on` dan `lookup_params` dari `filters.ts`
2. `filter` bentuk dict diperiksa `=== true` sehingga jatuh — lihat [Schema DSL](Schema.md#filter-punya-dua-bentuk)
3. **`MCrudFilters` mengoper tiga prop yang tidak ada di `MLookupField`** (`:depends-on`, `:lookup-params`, `:form-values`). Vue tidak mengeluhkan prop tak dikenal — ketiganya jatuh jadi atribut mati, dan tidak ada satu pun error yang menyertainya
4. **Prop hantu keempat: `placeholder` pada `MLookupSelect`** — dioper sejak lama padahal propnya tidak pernah ada, jadi tiga dropdown berjejer semuanya berbunyi **"Select"** tanpa ada yang memberi tahu mana Branch dan mana Location Type

!!! note "Pelajarannya"
    Resolusi `lookup_params` sekarang lewat **satu helper bersama** `resolveLookupParams` yang dipakai `MFormBuilder` **dan** `MCrudFilters`.

    Dua salinan resolver yang harus tetap sama adalah persis cara bug ini lahir: berantai di form, diam-diam mati di tabel.

---

## Cakupan data di lookup

!!! danger "Dropdown adalah jalur bocor yang paling gampang terlewat"
    `EmployeeViewSet.lookup` merakit querysetnya sendiri dari `Employee.objects`, jadi **tidak melewati `filter_queryset()`**. Tanpa `DataScopeService.filter` eksplisit di sana, admin site yang hanya boleh melihat 6 pegawai tetap mendapat daftar nama seluruh tenant.

**Belum disaring: lookup di luar Employee.**

---

## `multilookup` — memilih banyak baris

Tipe field baru untuk tombol bulk seperti **Add Employees** di Roster Setup: memilih banyak baris dari sebuah endpoint, dengan pencarian, "Select all shown", dan baris yang sudah dipakai ditandai lewat `disabled_key`.

`MMultiSelectField` yang sudah ada cuma menerima opsi statis dari schema, dan daftar pegawai satu site tidak bisa ditulis di schema.

- `endpoint` pada field menerima placeholder `{id}` seperti `action.endpoint` — daftar kandidatnya memang milik dokumen yang sedang dibuka.
- Dirender **dua tempat**: `MRecordActions.vue` (dialog action) dan nantinya `MFormBuilder`. Yang dipakai sekarang yang pertama.
- **Nilai awalnya array, bukan string kosong.** `MRecordActions` mengisi seluruh field action dengan `""`; untuk multilookup itu membuat `v-model` menimpa isian pertama dan `missingRequired` membacanya sebagai sudah terisi.

!!! bug "Endpoint tanpa tombol tidak bisa dibedakan dari fitur yang tidak ada"
    `POST .../add-employees/` sudah jalan sejak awal, tapi tidak pernah dideklarasikan di `schema.actions` — jadi satu-satunya jalan menambah pegawai adalah mengetik baris satu per satu di grid, persis pekerjaan yang mau dihindari fitur bulk.
