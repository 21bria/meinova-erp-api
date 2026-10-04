# Code Review

Sistem ini punya banyak aturan yang **gagal tanpa error**. Review di sini bukan soal gaya kode — gaya bisa diserahkan ke linter nanti. Yang tidak bisa diserahkan ke tooling adalah delapan hal di bawah.

---

## Delapan hal yang wajib diperiksa

Semuanya pernah lolos ke `main` dan baru ketahuan dari layar yang salah.

### 1. `fields = "__all__"` pada model berelasi

```python
class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        fields = "__all__"      # ← kolom Company "-" di semua baris
```

Generator memetakan kolom lookup ke `<field>_name`. Kalau serializer tidak mengirimnya, kolomnya "-" **tanpa error**.

Di Holiday akibatnya lebih buruk daripada kolom kosong biasa: satu hari libur nasional menghasilkan dua belas baris identik kecuali kolom Company — dan kolom itulah yang tidak terisi, sehingga datanya terbaca **seperti duplikat yang perlu dibersihkan**.

**Periksa:** setiap FK yang `table=True` punya padanan `<field>_name` di serializer.

### 2. `search_fields` tidak cocok dengan model

Bawaan `["code", "name"]`. Model tanpa kolom itu membalas **HTTP 500 setiap kali user mengetik di kotak cari**. Dua belas viewset pernah kena.

`SafeSearchFilter` sekarang menjaringnya, tapi itu berarti **pencariannya diam-diam tidak mencari** apa yang diharapkan.

### 3. `filter=True` tanpa `filterset_fields`

Filternya tampil di UI, parameternya diterima lalu **diabaikan diam-diam**. Tabelnya menampilkan seluruh data seolah filternya tidak berpengaruh.

### 4. `ServiceWriteMixin` tidak dipasang

```python
class XViewSet(BaseMasterViewSet):     # ← service.create() tidak pernah jalan
    service_class = XService
```

`service_class` sendirian hanya dipakai untuk `get_queryset()` dan `soft_delete()`. Tanpa mixin: logika service tidak jalan, `full_clean()` tidak jalan, **dan perubahannya tidak masuk jejak audit**.

### 5. `unique=True` polos di turunan `BaseModel`

Nilainya terkunci selamanya oleh record yang sudah di-soft-delete. Harus `UniqueConstraint` + `condition=Q(is_deleted=False)`.

Dan turunan `BaseReference` wajib `class Meta(BaseReference.Meta)` — `class Meta:` polos membuang constraint dan `ordering`-nya.

### 6. Registry tidak di-import dari `AppConfig.ready()`

| Registry | Gagalnya |
|---|---|
| Lookup | endpoint **404** tanpa petunjuk |
| Importer | job gagal `No importer registered` |
| `register_completion` | Approve jalan, **status dokumen tidak berpindah** |

### 7. `data_scope` kosong

Role bercakupan sempit membaca **seluruh tenant**. Dan yang paling mudah terlewat: **lookup yang merakit querysetnya sendiri tidak melewati `filter_queryset()`** — `EmployeeViewSet.lookup` butuh `DataScopeService.filter` eksplisit.

### 8. Frontend belum diregenerate

Perubahan schema tanpa `pnpm meinova generate` = tidak ada yang berubah di layar. Tidak ada error, tidak ada indikator versi.

---

## Yang khusus untuk dokumen berapproval

- [ ] Validasi berat dipanggil saat **Submit** (`assert_submittable`), bukan di `on_complete` — kalau di akhir, kegagalannya membatalkan persetujuan yang sah dan muncul di layar orang yang tidak bisa memperbaikinya
- [ ] `on_complete` **tidak melempar** — kegagalannya ditempel ke `apply_error`, diulang lewat `POST .../apply/`
- [ ] Idempotensi dijaga kolom yang **dibaca ulang di bawah `select_for_update`** (`applied_at`), bukan `status` yang sudah di tangan
- [ ] Efek samping berjalan saat disetujui, bukan saat diketik
- [ ] Nomor dokumen dialokasikan saat create dan **tidak pernah dihitung ulang**

---

## Yang khusus untuk perubahan lintas modul

Pertanyaan tunggalnya: **tempatnya sudah benar?**

| Perubahannya berlaku untuk | Tempatnya |
|---|---|
| satu modul | schema backend |
| semua modul | `framework/` di repo Nuxt |
| semua modul baru saja | template generator |

Perbaikan di generator **tidak menyentuh modul yang sudah ada** sampai diregenerate — dan yang lupa tetap membawa bug lamanya. Kalau sebuah PR memperbaiki bug di satu berkas hasil generate, tanyakan apakah 99 modul lain punya bug yang sama.

Dan **dua salinan logika yang harus tetap sama** adalah tanda bahaya. Bug filter berantai lahir persis begitu: resolver `lookup_params` disalin di `MFormBuilder` dan `MCrudFilters`, lalu yang satu diperbaiki dan yang lain tidak.

---

## Yang layak dikomentari, dan yang tidak

**Layak diangkat di review:**

- Aturan bisnis yang ditaruh di serializer/view alih-alih service
- Aturan yang melihat baris lain tapi ditaruh di `Model.clean()`
- Pesan error yang tidak menyebut nomor dokumen / nama pemakai
- Angka yang dikarang di seed
- Komentar yang menjelaskan *apa*, padahal yang tidak jelas adalah *kenapa*
- Label UI berbahasa Indonesia
- Widget/kolom yang diisi data contoh karena modelnya belum ada

**Tidak layak jadi blocker:**

- Panjang baris, urutan import, spasi — serahkan ke linter kalau nanti dipasang
- Preferensi penamaan variabel lokal
- "Aku akan menulisnya begini"

---

## Yang harus dijalankan reviewer, bukan cuma dibaca

Beberapa hal di sistem ini **hanya** terlihat di browser sungguhan:

- [ ] Buka halamannya — build lolos bukan bukti (`<SelectItem value="">` melempar saat **hidrasi**, bukan SSR)
- [ ] Coba dengan akun **non-superuser** — penjagaan izin baru terlihat di sana
- [ ] Periksa tidak ada kolom "-"
- [ ] Coba filternya benar-benar menyaring
- [ ] Coba dropdown berantai menyempit saat induknya dipilih

Vue tidak mengeluhkan prop yang tidak dikenal — prop hantu jatuh jadi atribut mati **tanpa satu pun error**. Empat pernah bertumpuk di toolbar filter sekaligus.

---

## Ukuran PR

PR yang menyentuh 40 file di 6 modul tidak akan direview dengan sungguh-sungguh — dan review yang tidak sungguh-sungguh lebih buruk daripada tidak ada, karena ia memberi rasa aman palsu.

Pisahkan hasil generate FE ke commit tersendiri supaya reviewer bisa melewatinya.

---

## Keadaan hari ini

Belum ada proses review formal (2 commit, 1 branch, tanpa CI). Halaman ini menetapkan apa yang diperiksa begitu ada orang kedua — dan sementara itu berguna sebagai **checklist self-review**.
