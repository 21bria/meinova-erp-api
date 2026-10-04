# Charts

Chart hanya muncul di dashboard, dan **bentuknya ditentukan schema backend** — bukan ditulis di komponen.

---

## Deklarasi

```python
dashboard.line(key="attendance_trend", label="Attendance Trend", span=8)
dashboard.bar(key="overtime_by_dept", span=6)
dashboard.donut(key="leave_by_type", span=4)
```

`span` memakai grid 12 kolom. Renderernya `MDashboardChart`.

**Tiap chart wajib punya `resolve_<key>`** di view-nya — widget tanpa resolver melempar `NotImplementedError`, sengaja berisik daripada tampil kosong.

---

## Memilih bentuk

| Bentuk | Untuk | Bukan untuk |
|---|---|---|
| `line` | tren sepanjang waktu | perbandingan kategori |
| `bar` | perbandingan antar kategori | tren halus |
| `donut` | komposisi, **sedikit** kategori | banyak kategori, atau angka yang perlu dibaca persis |

Kalau angkanya perlu dibaca persis, `listing` atau `stat` lebih baik daripada chart.

---

## Chart yang tidak dibuat, dan kenapa

Aturan yang sama dengan seluruh dashboard: **yang datanya belum ada modelnya tidak dibuat, bukan diisi angka contoh.**

| Chart | Kenapa dihapus |
|---|---|
| "Revenue vs Expense" | `finance` masih kerangka kosong |
| "Monthly Payroll" | belum ada model payroll run |
| "Master Records Growth" | tidak ada model yang mencatat pertumbuhan master per bulan |

Yang terakhir layak diperhatikan: menurunkannya dari `created_at` master yang **diseed sekaligus** cuma menghasilkan **satu batang raksasa** di bulan tenant dibuat — chart yang secara teknis benar tapi tidak memberi informasi apa pun.

Penggantinya **Struktur Organisasi** (jumlah baris per level), yang justru menjawab pertanyaan sebenarnya: level mana yang sudah terisi.

---

## Tren butuh deret titik, bukan satu nilai

`trend_buckets()` memberi deret dengan satuan mengikuti mode periode:

| Mode | Satuan |
|---|---|
| harian | 12 hari |
| mingguan | 12 minggu |
| bulanan | 12 bulan |
| rentang bebas | ≤31 hari → harian, ≤180 → mingguan, selebihnya bulanan |

!!! warning "Tanpa ini, memilih 'hari ini' menghasilkan chart satu titik"
    Satu titik bukan tren, dan chart-nya terlihat rusak.

**Awal minggu = Senin.** Frontend menghitung ulang rentang yang sama untuk label tombol, jadi aturan ini harus tetap sama di dua repo.

---

## Tren `None` kalau pembandingnya nol

"Naik 100%" untuk data yang baru mulai terisi lebih menyesatkan daripada tidak menampilkan apa-apa. FE menyembunyikan bagian tren saat nilainya null.

Pembandingnya memakai **periode kalender sebelumnya** (Februari vs Januari penuh), bukan "mundur sekian hari". Kalimatnya ikut menyesuaikan lewat `compare_label` ("dari minggu lalu", "dari periode sebelumnya").

---

## Jebakan agregasi

```python
Count("id", distinct=True)
```

Donut Approval Status menyaring lewat **join ke `approvals`**, jadi dokumen bertiga kotak tanda tangan terhitung **tiga kali**.

!!! danger "`.distinct()` pada queryset tidak menolong setelah `values().annotate()`"
    Yang benar `distinct=True` di dalam agregatnya.

Ini kelas bug yang menghasilkan angka **yang terlihat masuk akal** — jadi tidak ada yang curiga sampai ada yang membandingkannya dengan tabel.

---

## Cakupan data

Chart merakit querysetnya sendiri lewat `APIView`, jadi **`filter_queryset()` tidak pernah dilewati**.

`DataScopeService.filter` wajib dipanggil di setiap queryset, dan petanya disamakan persis dengan viewset modul itu — kalau tidak, **angka chart tidak cocok dengan isi tabelnya**, dan selisih itu sendiri membocorkan berapa baris yang disembunyikan.

---

## Sumber data yang baru mungkin belakangan

Chart aktivitas di dashboard Administration datanya dari `AuditTrail` — dan itu **baru mungkin setelah jejak audit punya penulis**. Sebelum itu tabelnya nol baris, dan widget yang selalu kosong memang tidak layak dibuat.

Pola yang layak ditiru: **buat chartnya setelah sumber datanya benar-benar terisi**, bukan sebelumnya.

---

## Checklist

- [ ] Ada `resolve_<key>` untuk setiap chart
- [ ] `DataScopeService.filter` di setiap queryset
- [ ] Agregasi lewat join memakai `distinct=True`
- [ ] Tren memakai `trend_buckets()`, bukan satu nilai
- [ ] Tren `None` kalau pembanding nol
- [ ] Datanya benar-benar ada — kalau belum, jangan dibuat
