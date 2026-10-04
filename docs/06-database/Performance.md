# Performance Database

Diurutkan dari yang paling sering jadi penyebab di sistem ini, bukan dari yang paling teoretis.

---

## 1 · N+1 query — penyebab nomor satu

Satu tabel 20 baris dengan 5 kolom FK yang lupa `select_related` menjalankan **101 query**.

```python
class VehicleService(BaseMasterService):
    @classmethod
    def get_queryset(cls):
        return super().get_queryset().select_related("company", "location")
```

| Kebutuhan | Cara |
|---|---|
| ForeignKey / OneToOne | `select_related` (JOIN) |
| Reverse FK / M2M | `prefetch_related` (query kedua) |
| Relasi bersarang | `prefetch_related("periods__travels")` |

### Yang sudah terbukti butuh dan gampang terlewat

| Kasus | Tanpa itu |
|---|---|
| Kepala Travel Request — `department_name`, `section_name`, `position_name`, `point_of_hire_name` | daftar dokumen menambah **beberapa query per baris** |
| `build_schedule_warnings` | **satu query per periode** |
| `SiteRotationSerializer.leave_balances` | prefetch lalu saring **di Python** — jangan diubah jadi query per baris |
| Setiap kolom `<relasi>_name` di tabel | satu query per baris |

!!! tip "Cara menemukannya"
    ```python
    from django.db import connection
    print(len(connection.queries))    # DEBUG=True
    ```

    Kalau jumlahnya **tumbuh sebanding jumlah baris**, ada relasi yang belum di-prefetch.

**Periksa ini sebelum memikirkan index.** Menambah index tidak menolong N+1 sama sekali.

---

## 2 · Agregasi yang menghitung ganda

```python
Count("id", distinct=True)
```

Donut Approval Status menyaring lewat **join ke `approvals`**, jadi dokumen bertiga kotak tanda tangan terhitung tiga kali.

!!! warning "`.distinct()` pada queryset tidak menolong setelah `values().annotate()`"
    Yang benar `distinct=True` **di dalam** agregatnya.

---

## 3 · Perhitungan ulang yang disengaja

Beberapa nilai **sengaja** dihitung ulang penuh, bukan diperbarui inkremental:

| Nilai | Dihitung ulang saat |
|---|---|
| `LeaveBalance.used` | setiap record cuti dibuat/diubah/dihapus |
| `RotationCreditBalance` | setiap transaksi ledger |

Itu memang lebih mahal. Tapi penjumlahan ulang **tidak bisa hanyut**, sementara penambahan inkremental yang meleset sekali akan salah selamanya tanpa ada yang tahu.

**Jangan optimasi ini jadi inkremental.** Kalau jadi masalah, yang benar adalah membatasi cakupan perhitungan ulangnya (per pegawai per tahun, seperti sekarang), bukan mengubah caranya.

---

## 4 · Pagination `COUNT(*)`

`StandardPagination` menjalankan `COUNT(*)` penuh tiap halaman. Untuk tabel jutaan baris itu jadi bagian termahal dari request.

Belum mendesak. Kalau nanti perlu: kelas pagination terpisah untuk layar yang tidak butuh total — **jangan** ubah `StandardPagination` yang dipakai semua orang.

---

## 5 · Export CSV

`export/` mengalirkan hasil lewat `queryset.iterator(chunk_size=500)` supaya tidak memuat seluruh tabel ke memori. Itu sudah benar.

Yang perlu diperhatikan: **`resolve_export_value` membaca instance**, jadi setiap kolom relasi yang tidak di-`select_related` menghasilkan satu query per baris — dan di export, "per baris" berarti seluruh tabel.

---

## 6 · Batas yang mencegah request tak terbatas

Bukan optimasi, tapi pagar yang mencegah satu request meminta pekerjaan tak berhingga:

| Batas | Nilai |
|---|---|
| `MAX_PAGE_SIZE` | 100 |
| `MAX_HORIZON_MONTHS` | 24 |
| `MAX_SEGMENTS_PER_PLAN` | 400 |
| `MAX_SETUP_LINES` | 200 |
| `UPLOAD_MAX_MULTIPLE_FILES` | 20 |

Batas roster ada **di dalam kalkulator**, bukan di viewset — supaya query param yang salah ketik tidak bisa memintanya membuat roster tak hingga.

---

## 7 · Kalkulator tanpa query

`RosterCalculationService` dan `RotationPeriodGenerator` **tidak menjalankan satu query pun**. Itu properti yang sengaja dijaga, dan dua berkas `SimpleTestCase` yang menjaganya akan gagal begitu ada yang menambahkan query.

Manfaat performanya nyata: preview roster untuk 30 pegawai menghitung 30 jadwal tanpa satu round-trip tambahan ke database.

---

## 8 · Multi-tenant

| | Catatan |
|---|---|
| Connection pooling | belum ada. Tiap request membuka koneksi baru — `CONN_MAX_AGE` belum diset |
| `search_path` per request | overhead kecil tapi ada; sifat django-tenants |
| Satu tenant besar | bisa mendominasi CPU database dan memperlambat yang lain |

Baris terakhir dijawab di level model bisnis, bukan optimasi: **klien enterprise dijalankan dedicated/on-premise** dari codebase yang sama. Pertanyaannya bukan "bagaimana mengisolasi", melainkan **kapan sebuah klien dipindahkan**.

---

## Yang belum diukur

Semuanya:

- Query per request di endpoint yang paling sering dibuka
- Query lambat
- Ukuran per schema
- Durasi `migrate_schemas`

**Sampai ini diukur, optimasi apa pun adalah tebakan.** Lihat [Monitoring](../07-deployment/Monitoring.md).

---

## Urutan yang benar

1. **Ukur** — hitung query, `EXPLAIN ANALYZE`
2. **Periksa N+1** — hampir selalu ini
3. **Baru pikirkan index** — lihat [Indexing](Indexing.md)
4. **Terakhir** pertimbangkan denormalisasi, dan hanya kalau ada satu tempat yang menghitungnya ulang penuh
