# Forms

Form **tidak ditulis tangan**. `MFormBuilder` merender dari `form.ts` hasil generate, yang berasal dari `fields` di schema backend.

Referensi DSL-nya: [Schema](../02-Framework/Schema.md).

---

## Komponen field

30 komponen di `framework/components/forms/`:

| Kelompok | Komponen |
|---|---|
| Teks | `MInputField`, `MTextareaField`, `MEmailField`, `MPasswordField`, `MPhoneField`, `MRichEditor` |
| Angka | `MNumberField`, `MCurrencyField`, `MPercentField` |
| Tanggal | `MDateField`, `MDateTimeField`, `MTimeField` |
| Pilihan | `MSelectField`, `MMultiSelectField`, `MRadioField`, `MCheckboxField`, `MCheckboxGroupField`, `MSwitchField` |
| Relasi | **`MLookupField`**, **`MMultiLookupField`** |
| File | `MFileField`, `MImageField` |
| Rangka | `MFormBuilder`, `MForm`, `MFormGrid`, `MFormSection`, `MFieldLabel`, `MFieldHint`, `MFieldError` |

---

## `MFormBuilder` — yang dikerjakannya

1. Merender field sesuai `type` dan urutan `order`
2. Menilai `visible_when` / `readonly_when` terhadap nilai form
3. Mengisi `default` — **hanya di mode create**, dan **hanya untuk kunci yang belum ada di model**
4. Me-resolve `lookup_params` (`$field` → nilai form, `$me.*` → profil pengguna)
5. Menerapkan `autofill` saat lookup dipilih
6. Menampilkan **banner** untuk error non-field (`detail` / `non_field_errors` / `__all__`)

!!! note "Root `MFormBuilder` adalah pembungkus, bukan grid"
    Karena banner harus duduk di luar grid. `gridClass()` turun satu tingkat.

---

## Lima jebakan form

### 1 · Field read-only hilang dari form

Generator membuang semua field ber-`read_only` dari `form.ts`. Benar untuk kolom audit, tapi field turunan yang sengaja ditaruh di sebuah tab **hilang tanpa error**.

**Perbaikannya `display=True`.** Jangan pakai `form=True` — `form` diisi otomatis introspeksi untuk hampir semua kolom model, jadi memakainya sebagai penanda paksa menyeret masuk kolom read-only modul lain (`hr/attendance` sempat kebawa `approved_at`/`approved_by`).

### 2 · `is_false` vs `not is_true`

`is_false` menuntut nilainya benar-benar `false`. **Penanda write-only tidak pernah dikirim balik API**, jadi di layar edit nilainya `undefined` dan syaratnya gagal — field yang bergantung padanya **hilang tanpa satu pun pesan**.

Untuk "selama belum dinyalakan": `{"not": {..., "op": "is_true"}}`.

### 3 · `autofill` yang menyebut kunci tak diserialisasi

Dulu menulis `selected?.[sourceKey] ?? null` — kunci yang tidak ada = **tulis null**.

Akibatnya di Roster Setup: pilih Company → pilih Site → **Company kosong lagi**, dan Section ikut mati karena `depends_on`-nya.

Sekarang kunci yang **tidak ada** dilewati (+ `console.warn` di dev); kunci yang **ada tapi null** tetap mengosongkan — pegawai yang memang tidak punya branch harus mengosongkan Branch.

**Tetap periksa `serialize()` lookup-nya.** Jaring itu bukan izin menebak nama kunci.

### 4 · `depends_on` bukan cuma enable/disable

Ia juga yang **mengosongkan** field saat induknya berubah. Field yang dipakai di `lookup_params` tapi tidak disebut di `depends_on` akan **tetap menempel** setelah induknya diganti, dan penolakannya baru muncul saat Simpan.

### 5 · Syarat harus bisa dinilai dari nilai form

Model form memegang **pk** lookup, bukan kodenya. "Employment type = kontrak" butuh tiga bagian:

1. `EmploymentTypeLookup.serialize()` mengirim `requires_contract`
2. field membawa `autofill={"employment_type_requires_contract": "requires_contract"}`
3. serializer Employee ikut mengirim field yang sama — supaya nilainya benar saat form **dimuat**, bukan cuma setelah diganti

Cabut salah satunya, dan kolomnya benar di satu keadaan lalu salah di keadaan lain.

---

## `$me.*` — mengisi vs mengunci

```python
default="$me.placement.company",
readonly_when={"field": "$me.data_scope.values.company", "op": "is_not_null"},
```

| Sumber | Untuk |
|---|---|
| `$me.placement.*` | **mengisi** |
| `$me.data_scope.values.*` | **mengunci** |

HR pusat menunjukkan kenapa terpisah: ditempatkan di Jakarta, cakupannya seluruh tenant — form-nya boleh terisi Jakarta tapi **tidak boleh terkunci** ke sana.

Dikunci **per jenis**, bukan satu penanda untuk seluruh form: admin bercakupan company boleh memilih site mana pun di dalam company-nya.

`applyDefaults` ikut mengamati `auth.user` — `/auth/me` lazim datang **setelah** form dirender, dan tanpa itu yang membuka layarnya langsung setelah login mendapat form kosong tanpa sebab yang terlihat.

!!! danger "Mengunci dropdown bukan penjagaan"
    Backend tetap harus mengisi default dari cakupan pembuatnya lalu menolak yang di luar cakupan.

---

## Error di form

| Bentuk error | Dirender sebagai |
|---|---|
| `{"employee": ["..."]}` | pesan di bawah field |
| `{"detail": "..."}` / `non_field_errors` / `__all__` | **banner** di bawah form |

Keduanya + toast. Detail kenapa berlapis: [Design System](Design-System.md#2--penolakan-harus-terlihat).

`normalizeApiErrors` mengembalikan `{detail}` untuk envelope tanpa `errors` — sebelumnya seluruh isi envelope terbaca sebagai nama field, dan form mencari kolom bernama **"success"**.

---

## `multilookup`

Memilih banyak baris dari sebuah endpoint, dengan pencarian, "Select all shown", dan baris terpakai ditandai lewat `disabled_key`.

`MMultiSelectField` cuma menerima opsi statis dari schema — daftar pegawai satu site tidak bisa ditulis di schema.

- `endpoint` menerima placeholder `{id}`
- Dirender di `MRecordActions` (dialog action); **belum** di `MFormBuilder`
- **Nilai awalnya array, bukan string kosong** — `MRecordActions` mengisi seluruh field action dengan `""`, dan untuk multilookup itu membuat `v-model` menimpa isian pertama

---

## Form workspace vs dialog

| | Dialog | Workspace |
|---|---|---|
| Builder | `ui.dialog()` | `ui.workspace()` + `tabs` |
| Rute FE | tidak perlu | `create`, `[id]`, `[id]/edit` |
| Error non-field | banner | **pernah dibuang** oleh `tabErrors` di `<X>Form.vue` — sudah diperbaiki di template |

!!! warning "`ui.workspace()` tanpa key `tabs` = layar kosong"
    `workspaceTabs = []` → "No workspace tabs available." Bukan error, cuma kosong, jadi terbaca seperti modul yang belum jadi.

Tab yang **pernah dibuka** tetap terpasang (`keptTabs` + `force-mount` + `data-[state=inactive]:hidden`) — tanpa itu baris yang baru diketik di grid inline lenyap begitu penggunanya menengok tab sebelah.

---

## Checklist

- [ ] Field read-only yang harus tampil diberi `display=True`
- [ ] "Selama belum dinyalakan" pakai `not is_true`, bukan `is_false`
- [ ] `autofill` menyebut kunci yang benar-benar diserialisasi lookup
- [ ] `depends_on` menyebut setiap field yang dipakai di `lookup_params`
- [ ] `ui.workspace()` punya `tabs`
- [ ] Dicoba di browser dengan akun non-superuser
