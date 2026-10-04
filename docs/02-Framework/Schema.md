# Schema DSL

Referensi builder di `apps/framework/builders/`. Ini yang menentukan bentuk layar di frontend.

---

## Bentuk sebuah schema

```python
from apps.framework.builders import field, ui, tabs, action

LEAVE_SCHEMA = {
    "module": "hr/leave",
    "name": "Leave",
    "label": "Leave Request",
    "endpoint": "/api/hr/leaves/",     # eksplisit kalau beda dari module
    "schema_type": "crud",

    "ui": {**ui.workspace(title="Leave Request", columns=2, export=True)},
    "tabs": LEAVE_TABS,
    "actions": LEAVE_ACTIONS,
    "fields": {**GENERAL_FIELDS, **DISPLAY_FIELDS},
    "import": importer.config(module="hr.leave"),   # opsional
}
```

Hasil akhir yang dikirim ke frontend adalah **gabungan introspeksi model/serializer + schema deklaratif ini**, digabung lewat `deep_merge` — yang deklaratif menang.

Konstanta schema ditulis `SCREAMING_SNAKE` (`EMPLOYEE_SCHEMA`, `GENERAL_FIELDS`).

---

## `ui` — bentuk editor

| Builder | Editor | Butuh rute FE |
|---|---|---|
| `ui.dialog(size="lg", columns=1)` | dialog | tidak |
| `ui.page(size="full", columns=2)` | halaman | ya |
| `ui.workspace(size="full", columns=2)` | workspace bertab | ya — `create`, `[id]`, `[id]/edit` |
| `ui.drawer(side="right")` | drawer | tidak |
| `ui.wizard(linear=True)` | wizard | ya |

Flag tambahan (kwargs bebas, ikut apa adanya): `title`, `description`, `create`, `edit`, `delete`, `bulk_delete`, `export`, `import`.

!!! danger "`ui.workspace()` tanpa key `tabs` menghasilkan layar kosong"
    `workspaceTabs = []` dan halaman create/edit-nya menampilkan **"No workspace tabs available."** — bukan error, cuma kosong, jadi terbaca seperti modul yang belum jadi.

!!! warning "Editor `dialog` tidak butuh rute create/edit"
    Membuatkan rute untuk modul dialog justru error — `page.vue`-nya tidak menerima prop `mode`.

---

## `field` — tipe field

```python
field.text() field.email() field.password() field.url() field.phone()
field.textarea(rows=4) field.richtext() field.json() field.color() field.icon()
field.integer() field.number(min=, max=) field.decimal(decimal_places=, max_digits=)
field.percentage() field.currency(currency_field="currency")
field.date() field.datetime() field.time()
field.boolean() field.switch() field.checkbox()
field.select(options=[...]) field.multiselect(options=[...])
field.lookup(lookup_endpoint=...) 
field.file(...) field.image(...)
field.hidden()
field.custom("multilookup", ...)          # tipe baru
field.merge(config, **overrides)          # salin config field lalu ubah sebagian
```

### Metadata tampilan (berlaku untuk semua tipe)

| Kunci | Isi |
|---|---|
| `label` | teks di layar — **Bahasa Inggris** |
| `help_text` | keterangan di bawah field — **Bahasa Indonesia** |
| `tab` | tab workspace tempatnya duduk |
| `order` | urutan dalam tab |
| `required` | wajib diisi |
| `table` | tampil sebagai kolom tabel |
| `filter` | tampil sebagai filter toolbar |
| `search` | ikut dicari kotak pencarian |
| `sortable` | kolom bisa disortir |
| `overview` | tampil di kartu Overview workspace |
| `display` | paksa field read-only tetap tampil di form |
| `modes` | batasi ke `["create"]` atau `["edit"]` |
| `default` | nilai awal (**hanya di mode create**) |
| `visible_when` | syarat tampil |
| `readonly_when` | syarat terkunci |
| `hidden` | sembunyikan |
| `compute` | hitung ulang di grid inline |

---

## `filter` punya dua bentuk

```python
filter=True
filter={"group": "quick", "order": 20}
```

Keduanya sah. `group` di dalam dict jadi `placement`, `order`-nya menang atas `order` field.

!!! bug "Generator dulu cuma mengenali bentuk pertama"
    Diperiksa `=== true`, jadi seluruh schema organisasi (yang memakai bentuk kedua) jatuh: layar Departments tidak punya filter Company, Location, maupun Division **sama sekali**, padahal ketiganya dideklarasikan.

    Gagalnya diam, dan ke arah yang paling sulit dilacak — filter yang tidak pernah muncul tidak bisa dibedakan dari filter yang memang tidak ditulis.

!!! danger "`filter=True` sendirian hanya menampilkan filter di UI"
    Tanpa pemetaan di `filterset_class` / `filterset_fields`, parameternya **diterima lalu diabaikan diam-diam**.

Filter lookup tanpa `lookup_endpoint` sekarang **dilewati**, bukan dirender — dropdown "Select" yang bisa dibuka tapi selalu kosong lebih buruk daripada tidak ada. Yang dilewati dicatat sebagai komentar di `filters.ts` hasil generate.

---

## `visible_when` / `readonly_when`

Bentuknya **sengaja sama dengan `WorkflowStep.condition`** — satu dialek untuk dua keperluan.

```python
visible_when={"field": "action_type", "op": "in",
              "value": ["salary_change", "promotion"]}

visible_when={"all": [
    {"field": "employment_type_requires_contract", "op": "is_true"},
    {"not": {"field": "is_permanent", "op": "is_true"}},
]}
```

Op: `eq` (bawaan), `ne`, `in`, `not_in`, `is_true`, `is_false`, `is_null`, `is_not_null`. Digabung `all` / `any` / `not`.

**Syarat yang tidak bisa dinilai dianggap terpenuhi.** Field yang hilang gara-gara salah ketik nama kolom membuat orang mencari kesalahan di backend; field yang telanjur tampil kelihatan sendiri.

!!! danger "Jebakan `is_false` vs `not is_true`"
    `is_false` menuntut nilainya benar-benar `false`. **Penanda write-only tidak pernah dikirim balik API**, jadi di layar edit nilainya `undefined` dan syaratnya gagal — field yang bergantung padanya **hilang tanpa satu pun pesan**.

    Untuk "selama belum dinyalakan", tulis `{"not": {..., "op": "is_true"}}`.

!!! warning "Syaratnya harus bisa dinilai dari nilai form"
    Model form memegang **pk** lookup, bukan kodenya. Jadi "employment type = kontrak" tidak bisa dibaca langsung.

    Jalannya tiga bagian, dan mencabut salah satunya membuat kolomnya benar di satu keadaan dan salah di keadaan lain:

    1. `EmploymentTypeLookup.serialize()` mengirim `requires_contract`
    2. field Employment Type membawa `autofill={"employment_type_requires_contract": "requires_contract"}`
    3. serializer Employee ikut mengirim field yang sama, supaya nilainya sudah benar saat form **dimuat** — bukan cuma setelah diganti

### `$me.*` — nilai dari profil pengguna

Dibaca `MFormBuilder` dari `/auth/me`, bukan dari nilai form. Berlaku di `default`, `visible_when`, dan `readonly_when` sekaligus.

```python
default="$me.placement.company",
readonly_when={"field": "$me.data_scope.values.company", "op": "is_not_null"},
```

Dua sumbernya **jangan dicampur**:

| | Isi | Untuk |
|---|---|---|
| `$me.placement.*` | penempatan organisasi orangnya | **mengisi** form |
| `$me.data_scope.values.*` | nilai yang disiratkan cakupannya | **mengunci** form |

HR pusat menunjukkan kenapa harus terpisah: ditempatkan di Jakarta, cakupannya seluruh tenant — form-nya boleh terisi Jakarta tapi tidak boleh terkunci ke sana.

**Menguncinya per jenis, bukan satu penanda "terkunci" untuk seluruh form.** Admin bercakupan company boleh memilih site mana pun **di dalam** company-nya.

Jalur yang tidak ketemu = "tidak ada nilai", **bukan** null — menulis null ke Company sama saja dengan mengosongkannya.

!!! danger "Mengunci dropdown bukan penjagaan"
    Sisi backend tetap harus mengisi default dari cakupan pembuatnya lalu menolak yang di luar cakupan. Lihat `RosterSetupService.apply_scope_defaults` / `assert_within_scope`.

---

## `default` — hanya di mode create

Diisi `MFormBuilder` **hanya di mode create** dan **hanya untuk kunci yang belum ada di model**. Mengisinya di mode edit berarti menulis nilai ke kolom yang tidak dibuka siapa pun.

!!! bug "Sebelumnya dibuang generator dan tidak dibaca siapa pun"
    `default=True` di schema tidak berpengaruh di mana-mana — switch "Auto Generate Employee Number" tampil **mati** padahal schema-nya menyalakannya, dan field yang syarat tampilnya membaca switch itu ikut salah.

---

## `tabs`

```python
tabs.form(key="general", label="General", fields=[...])
tabs.resource(key="periods", label="Travel Purpose",
              endpoint="/api/hr/rotation-periods/",
              foreign_key="rotation", inline=True, create=True, fields={...})
tabs.history(key="history", label="History",
             endpoint="/api/hr/employees/{employee_id}/employment-history/")
tabs.custom(key="...", ...)
```

| Jenis | Render |
|---|---|
| `form` | field biasa |
| `resource` | tabel sub-resource; `inline=True` → sunting langsung di grid, tanpa dialog |
| `history` | timeline generik (`MWorkspaceHistory`) |
| `custom` | **hati-hati** — diteruskan ke slot yang tidak diisi `page.vue`, hasilnya kotak "belum tersambung" |

### Tabel resource inline

`inline=True` dipakai untuk jadwal: menambah lima baris tanggal lewat lima modal membuat baris yang justru harus dibandingkan tidak pernah terlihat bersamaan.

Aturan yang menyertainya:

- **Kolom inline = field yang `table=True`.** Itu satu-satunya kenop pengatur lebar tabel; field lain tetap ada di schema tapi tidak muncul di grid.
- Dua tabel yang membaca endpoint sama **wajib membawa salinan config field sendiri** — mengubah flag `table` di tempat akan ikut mengubah tabel yang satunya.
- `foreign_key="period__rotation"` boleh menembus satu relasi, tapi jalur itu **wajib** ada di `filterset_fields` viewsetnya. Tanpa itu parameternya diabaikan dan grid menampilkan data seluruh tenant.
- Lookup di dalam baris menyaring lewat `$<foreign_key>` — komponen inline menanam id dokumen di setiap baris.
- `create=False` menyembunyikan tombol Add Row.

**Kolom turunan dihitung ulang di grid lewat `compute`:**

```python
compute={"kind": "date_diff", "from": "start_date", "to": "end_date", "inclusive": True}
```

Wajib ada kalau service **menghormati nilai kiriman** sebagai isian manual — tanpa perhitungan ulang di klien, mengubah tanggal menyimpan jumlah hari yang lama tanpa pesan apa pun.

!!! bug "Tab yang tidak aktif dilepas dan membuang state lokalnya"
    `TabsContent` bawaan melepas isi tab yang tidak aktif — baris yang baru diketik tapi belum ditekan "Save Rows" lenyap begitu penggunanya menengok tab sebelah.

    Penambalnya `keptTabs`: tab yang **pernah** aktif diberi `force-mount` + `data-[state=inactive]:hidden`. **`force-mount` sendirian tidak cukup** — reka-ui memasang `hidden` dari `!present`, dan begitu `force-mount` menyala `present` selalu true sehingga tab yang tidak aktif justru ikut tampil.

    Sengaja hanya tab yang **pernah dibuka**, bukan semuanya: tiap tab resource menembak satu request daftar saat dipasang.

---

## `action` — tombol record

Pembeda **record action** dari **form action** (`save`/`delete`/`export`/`import`) adalah **adanya `endpoint`**. Menyertakan `save` di situ menghasilkan dua tombol Save yang salah satunya menembak URL tak ada.

```python
action.record(key="generate", label="Generate Periods",
              endpoint="/api/hr/site-rotations/{id}/generate-periods/",
              method="post", confirm=True,
              visible_when={"status": ["draft"]},
              permission="hr.change_siterotation")

action.submit(endpoint="/api/hr/leaves/{id}/submit/")
action.approve(endpoint="/api/hr/leaves/{id}/approve/")
action.reject(endpoint="/api/hr/leaves/{id}/reject/")
action.withdraw(endpoint="/api/hr/leaves/{id}/withdraw/")
```

`endpoint` sengaja **URL penuh** dengan placeholder `{id}` — `url_path` sebuah `@action` boleh berbeda dari nama methodnya, dan menebaknya membuat tombolnya mendarat di 404.

`visible_when` menerima **dua dialek** (`{"status": ["draft"]}` dan `{field, op, value}`) karena keduanya sudah dipakai di schema yang ada. Ini **bukan** penjagaan — yang menolak tetap service di backend.

!!! danger "`permission` menerima dua kosakata yang sama-sama berbentuk `a.b`"
    | Bentuk | Contoh | Pemeriksa FE |
    |---|---|---|
    | wewenang | `security.manage` | `isGranted` |
    | izin per model | `hr.add_employeeaction` | `can` |

    Pembedanya **garis bawah di ruas kedua**. Memakai pemeriksa yang salah gagal ke arah berbeda dan **tanpa suara**: `can("workflow.configure")` selalu false untuk yang bukan superuser, `isGranted("hr.add_x")` selalu true.

### `action.create_resource()`

Membuat **dokumen lain** untuk record yang sedang dibuka, bukan menembak `@action` miliknya.

- `endpoint` = koleksi resource tujuan
- `form.fields` berisi dict schema resource itu **apa adanya** — jadi `visible_when`, lookup berantai, dan kolom pembanding read-only ikut tanpa ditulis ulang
- `parent_field` diisi id record yang sedang dibuka lalu **dibuang dari form** — yang membuka kartu Budi tidak boleh tanpa sadar membuat dokumen untuk Ani

Dipakai tombol **Actions** di kartu Employee.

---

## `display_key`

Dibaca untuk **semua tipe field**, bukan cuma lookup — di kolom tabel maupun kartu Overview.

Generator memetakan kolom lookup ke `<nama_field>_name` kalau `display_key` kosong.

!!! bug "Contoh nyata"
    - `subject_employee` tidak menyebutnya → kolom mencari `subject_employee_name` yang tidak pernah ada di serializer, dan **tampil "-" untuk semua baris** — padahal datanya ada di `subject_name`.
    - Kolom Action Type menampilkan `employment_type_change` dan Status menampilkan `applied`, karena versi siap-tampilnya (`action_type_label`, `status_label`) ada di serializer tapi tidak pernah dirujuk.
    - Kartu Overview bahkan menampilkan **pk mentah** untuk field lookup.

---

## `HIDDEN_COLUMNS`

Field hasil introspeksi model datang dengan `table=True`, jadi tiap relasi muncul **dua kali** — `definition` (kolom "Definition") plus `definition_name` (kolom "Workflow") yang isinya sama persis. Tabel instance workflow sempat 17 kolom dan harus digulir ke samping hanya untuk melihat status.

Konstanta `HIDDEN_COLUMNS` per schema mematikan yang tidak dipakai. Dipakai juga untuk kolom cakupan (`company`/`branch`/`location`) yang cuma salinan untuk `RoleDataPermission` dan tampil "-" di semua baris.
