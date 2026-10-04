# HR — Dashboard

`framework_module = "hr/dashboard"`, `schema_type = "dashboard"`. Contoh terlengkap di sistem ini: **12 widget** dalam satu schema.

Mekanisme umumnya di [UI/UX → Dashboard](../../04-ui-ux/Dashboard.md).

---

## Bentuk

```
GET /api/hr/dashboard/?mode=&start=&end=
→ {period, widgets: {<key>: ...}}
```

**Satu request mengembalikan semua widget.** Satu endpoint per widget bikin halaman ini menembak **12 request** hanya untuk render pertama.

`apps/hr/api/dashboard/` — schema 12 widget + `HRDashboardService`.

**Tiap widget wajib punya `resolve_<key>`.** Widget tanpa resolver melempar `NotImplementedError` — sengaja berisik daripada tampil kosong.

---

## Widget yang tidak dibuat, dan kenapa

Mockup awal memuat kartu **"Kinerja Tercapai"** dan **"Total Payroll"**. Keduanya **tidak dibuat**:

| Kartu | Kenapa |
|---|---|
| Kinerja Tercapai | `apps/hr/models/performance.py` **file kosong** |
| Total Payroll | belum ada model payroll run |

Tempatnya diisi **Jam Lembur** dan **Lowongan Terbuka** yang datanya nyata.

Turnover dihitung dari `EmploymentAssignment.termination_date` — `separation.py` juga file kosong, tapi angkanya bisa diturunkan dari kolom yang sudah ada.

> **Widget yang datanya belum ada modelnya tidak dibuat, bukan diisi angka contoh.**

---

## Cakupan data: wajib dipasang manual

!!! danger "Dashboard tidak melewati `filter_queryset()`"
    `BaseMasterViewSet` menyaring `RoleDataPermission` di sana. `BaseDashboardAPIView` adalah **`APIView` biasa** yang merakit querysetnya sendiri, jadi jalur itu tidak pernah dilewati.

Tiap queryset **wajib** memanggil:

```python
DataScopeService.filter(qs, EMPLOYEE_SCOPE, context["user"])
```

Empat peta di `apps/hr/api/dashboard/services.py`:

| Peta | Catatan |
|---|---|
| `EMPLOYEE_SCOPE` | |
| `TRANSACTION_SCOPE` | |
| `TRAINING_SCOPE` | dipanggil dengan **`allow_null=True`** |
| `VACANCY_SCOPE` | **tanpa `own`** — lowongan bukan "data milik seseorang" |

!!! warning "Petanya disamakan PERSIS dengan `data_scope` di viewset masing-masing"
    Kalau salah satu diubah, yang satunya harus ikut — kalau tidak, **angka dashboard tidak cocok dengan isi tabelnya**.

    Dan selisih itu sendiri bermasalah: admin Gebe yang membaca 10 di dashboard dan 6 di tabel jadi tahu ada 4 baris yang disembunyikan darinya.

`TRAINING_SCOPE` memakai `allow_null=True` karena di `TrainingProgram`, company kosong berarti **"berlaku untuk semua"** — program induksi K3 se-grup tidak boleh hilang dari layar admin site. **Jangan** dipakai sebagai jalan pintas untuk model yang kosongnya cuma karena datanya belum lengkap.

---

## Periode

`HRDashboardService.bounds()` / `previous_bounds()` / `compare_label()` adalah **pola rujukan** untuk dashboard modul lain.

- Periode = **rentang tanggal**, bukan bulan/tahun. Satu widget melayani mode harian sampai rentang bebas tanpa cabang khusus
- Pembanding memakai **periode kalender sebelumnya** (Februari vs Januari penuh), bukan "mundur sekian hari"
- `trend_buckets()` memberi 12 titik dengan satuan mengikuti mode — tanpa ini, memilih "hari ini" menghasilkan chart **satu titik**
- **Awal minggu = Senin**, dan frontend menghitung ulang rentang yang sama untuk label tombol
- Tren **`None` kalau pembandingnya nol** — "naik 100%" untuk data yang baru terisi lebih menyesatkan daripada tidak menampilkan apa-apa
- Query param yang tidak masuk akal **diabaikan** (jatuh ke default), bukan dibalas error

Beberapa widget sengaja **di luar filter periode** — Pengingat Kepegawaian, misalnya. Kontrak yang akan habis bulan depan tidak boleh hilang hanya karena periodenya disetel ke bulan lalu.

---

## Dashboard `EMPLOYEE`

Role `EMPLOYEE` punya akses ke `hr/dashboard`, dan angkanya sudah tersaring `RoleDataPermission` ke datanya sendiri — "Total Pegawai 1" memang dirinya.

Jadi **bukan kebocoran**, tapi juga belum dashboard yang berguna.

!!! note "Dashboard pribadi belum ada"
    Yang dibutuhkan pegawai biasa berbeda: sisa saldo cutinya, jadwal rosternya, dokumen yang sedang ia ajukan. Bukan agregasi seluruh tenant yang kebetulan menyempit jadi satu baris.

---

## Membuat dashboard modul baru

- [ ] Schema dengan `dashboard.schema(...)`, `span` grid 12 kolom
- [ ] View turunan `BaseDashboardAPIView`
- [ ] **`resolve_<key>` untuk setiap widget**
- [ ] **`DataScopeService.filter` di setiap queryset**, petanya disamakan dengan viewset
- [ ] `Cls.as_schema_view()` didaftarkan — subclass-nya sengaja mengosongkan `framework_module`
- [ ] Widget yang datanya belum ada **tidak dibuat**
- [ ] Agregasi lewat join memakai `Count(..., distinct=True)`
- [ ] `pnpm meinova generate hr/dashboard`
