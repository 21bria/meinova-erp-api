# Tables

Kolom, filter, dan toolbar digenerate dari `fields` di schema backend. Yang ditulis orang adalah schema, bukan `columns.ts`.

---

## Komponen

| Komponen | Isi |
|---|---|
| `MCrudTable` | tabel + toolbar + pagination, dipakai seluruh modul CRUD |
| `MTable` | tabel murni |
| `MTableToolbar`, `MCrudToolbar` | pencarian, filter, tombol |
| `MCrudFilters` | dropdown filter, termasuk yang berantai |
| `MColumnHeader` | sortir |
| `MRowActions`, `MCrudActions` | Edit/Delete/action per baris |
| `MCrudPagination`, `MPagination` | |
| `MCrudEmpty`, `MCrudLoading` | |
| `MCrudDelete` | konfirmasi hapus |

---

## Kolom = field ber-`table=True`

```python
"plate_number": field.text(label="Plate Number", table=True, sortable=True, order=30),
```

Field lain tetap ada di schema tapi tidak muncul di grid. **Itu satu-satunya kenop pengatur lebar tabel.**

### Jebakan #1: kolom "-" di semua baris

Penyebab tunggal terbanyak masalah UI di repo ini.

Kolom dibuat dari **field model** lewat introspeksi; datanya datang dari **serializer**. Generator memetakan kolom lookup ke `<field>_name`.

```python
class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        fields = "__all__"      # ← kolom Company "-" di SEMUA baris
```

!!! danger "Kadang lebih buruk daripada kolom kosong"
    `Holiday` wajib menyebut company, jadi satu hari libur nasional tersimpan **dua belas kali** di tenant berisi dua belas perusahaan. Kolom Company yang tidak terisi membuat datanya terbaca **seperti duplikat yang perlu dibersihkan**.

    Kena juga: Audit Trail (kolom User kosong — satu-satunya alasan orang membuka layar itu), tabel Permission (708 baris semuanya "-"), dan tabel User yang punya kolom berjudul **"Password"**.

**Cara memeriksa:** cocokkan `column.*("key")` di `columns.ts` hasil generate dengan kunci payload API sungguhan.

### Jebakan #2: `display_key`

Dibaca untuk **semua tipe field**, bukan cuma lookup.

Tanpa itu: kolom Action Type menampilkan `employment_type_change` dan Status menampilkan `applied`, padahal versi siap-tampilnya (`action_type_label`, `status_label`) ada di serializer.

`subject_employee` pernah tidak menyebutnya → kolomnya mencari `subject_employee_name` yang tidak pernah ada, padahal datanya di `subject_name`.

### Jebakan #3: kolom dobel

Field hasil introspeksi datang dengan `table=True`, jadi tiap relasi muncul **dua kali** — `definition` ("Definition") plus `definition_name` ("Workflow") yang isinya sama persis.

Tabel instance workflow sempat **17 kolom** dan harus digulir ke samping hanya untuk melihat status. Matikan lewat konstanta `HIDDEN_COLUMNS` per schema.

---

## Filter

```python
filter=True
filter={"group": "quick", "order": 20}
```

**Keduanya sah**, dan generator dulu cuma mengenali yang pertama (`=== true`) — sehingga seluruh schema organisasi jatuh: layar Departments **tidak punya filter Company, Location, maupun Division sama sekali**, padahal ketiganya dideklarasikan.

!!! danger "`filter=True` sendirian hanya menampilkan filter di UI"
    Tanpa `filterset_fields` / `filterset_class` di backend, parameternya **diterima lalu diabaikan diam-diam**.

Filter lookup **tanpa `lookup_endpoint` dilewati**, bukan dirender — dropdown yang bisa dibuka tapi selalu kosong lebih buruk daripada tidak ada. Yang dilewati dicatat sebagai komentar di `filters.ts`.

### Filter berantai

`depends_on` + `lookup_params` bekerja di toolbar, sama seperti di form. Empat bug pernah bertumpuk di jalur ini dan semuanya gagal tanpa suara:

1. Generator membuang `depends_on` dan `lookup_params` dari `filters.ts`
2. `filter` bentuk dict diperiksa `=== true`
3. `MCrudFilters` mengoper tiga prop yang **tidak ada** di `MLookupField` — Vue tidak mengeluhkan prop tak dikenal, ketiganya jatuh jadi atribut mati
4. Prop hantu keempat: `placeholder` pada `MLookupSelect` — tiga dropdown berjejer semuanya berbunyi **"Select"**

!!! note "Pelajarannya"
    Resolusi `lookup_params` sekarang lewat **satu helper bersama** (`resolveLookupParams`) yang dipakai `MFormBuilder` **dan** `MCrudFilters`.

    Dua salinan resolver yang harus tetap sama adalah persis cara bug ini lahir: berantai di form, diam-diam mati di tabel.

Urutan label tombol: `nullLabel` → `placeholder` → turunan label, diperiksa **truthy bukan nullish** (bawaan keduanya string kosong, dan `""` bukan nullish — ia akan menang lalu tombolnya kosong melompong).

---

## Sortir

```
?ordering=-created_at
```

`ordering` di viewset **menang** atas `Meta.ordering` model — mengubah salah satunya saja tidak cukup. Detail: [Sorting](../05-api/Sorting.md).

Kolom turunan yang dirakit di serializer tidak ada di database; beri `sortable=False` atau denormalisasi.

---

## Pagination

Server-side, selalu. `?page=&page_size=`, total dari `meta.count`.

`page_size` dibatasi **100** dan nilai di atasnya **dipotong diam-diam** — FE tidak boleh menawarkan pilihan lebih besar.

---

## Aksi

| Jenis | Pembeda | Dirender oleh |
|---|---|---|
| Form action (`save`, `delete`, `export`, `import`) | **tanpa** `endpoint` | jalur CRUD |
| Record action (Submit, Approve, Generate) | **punya** `endpoint` | `MRecordActions` |

Menyertakan `save` di `schema.actions` menghasilkan **dua tombol Save** yang salah satunya menembak URL tak ada.

`visible_when` dinilai terhadap record yang dibuka — **bukan penjagaan**, yang menolak tetap service di backend.

### Tombol yang pasti ditolak disembunyikan

`useCrud` membaca `GET /api/framework/permissions/`.

Dipasang di `framework/`, bukan di berkas hasil generate: seluruh tabel membaca `crud.ui`, jadi satu gerbang menutup semua modul **tanpa regenerate**.

- **Resource tak dikenal tidak disaring** — 22 viewset belum menuliskan `endpoint` di schema-nya
- `import`/`export` tidak ikut disaring — keduanya membaca
- `authStore.clear()` **wajib** me-`reset()`-nya, kalau tidak pegawai yang login setelah HR manager di tab yang sama mendapat tombol yang API-nya pasti menolaknya

---

## Export

`GET .../export/` — kolomnya = kolom tabel, **ikut filter aktif**, jadi CSV-nya persis apa yang dilihat user.

!!! warning "Export membaca instance, bukan serializer"
    Masking apa pun di serializer **tidak menyentuh export**. Untuk data yang dibatasi `EmployeeDataPolicy`, kolomnya harus dibuang lewat `get_export_fields` — dan **dibuang seluruhnya**, bukan dikosongkan per baris: CSV yang sebagian selnya terisi justru membocorkan polanya.

---

## Tabel resource inline

`tabs.resource(..., inline=True)` — baris disunting langsung di grid, tanpa dialog per baris.

Dipakai untuk jadwal: menambah lima baris tanggal lewat lima modal membuat baris yang justru harus dibandingkan tidak pernah terlihat bersamaan.

- **Kolom = field `table=True`**
- Dua tabel yang membaca endpoint sama **wajib bawa salinan config field sendiri**
- `foreign_key` yang menembus relasi **wajib** ada di `filterset_fields`
- Kolom turunan dihitung ulang lewat `compute` — tanpa itu, mengubah tanggal menyimpan jumlah hari yang lama tanpa pesan apa pun
- Error tanpa nama field dirender sebagai baris pesan di bawah barisnya

---

## Checklist

- [ ] Setiap FK ber-`table=True` punya `<field>_name` di serializer
- [ ] `display_key` untuk kolom yang punya versi siap-tampil
- [ ] Kolom dobel dimatikan lewat `HIDDEN_COLUMNS`
- [ ] Setiap `filter` punya padanan `filterset_fields`
- [ ] Filter lookup punya `lookup_endpoint`
- [ ] FK yang jadi kolom ikut `select_related`
- [ ] Dibuka di browser — hitung kolom "-"
