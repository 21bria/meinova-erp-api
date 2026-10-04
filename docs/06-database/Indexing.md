# Indexing

214 `models.Index` terdaftar di 168 model. Halaman ini soal **kapan menambah** dan **apa yang sudah otomatis**.

---

## Yang sudah ada tanpa ditulis

| Otomatis dari Django | Index |
|---|---|
| Primary key | unik |
| `ForeignKey` | index pada `<field>_id` |
| `OneToOneField` | unik |
| `unique=True` / `UniqueConstraint` | unik |

**Jangan menambah `db_index=True` pada FK** — sudah ada, dan duplikatnya memperlambat tulis tanpa mempercepat baca.

---

## Yang layak diberi index di sistem ini

### 1 · Kolom yang selalu ikut di `WHERE`

```python
class Meta:
    indexes = [
        models.Index(fields=["is_deleted"]),
        models.Index(fields=["company", "is_deleted"]),
    ]
```

**`is_deleted` ada di hampir setiap query** — `BaseMasterService.get_queryset()` selalu `.filter(is_deleted=False)`. Untuk tabel besar, index gabungan `(kolom_penyaring, is_deleted)` lebih berguna daripada `is_deleted` sendirian.

### 2 · Jalur cakupan data

`DataScopeService` menyaring lewat jalur yang didaftarkan `data_scope`:

```python
data_scope = {
    "company": "organization__company",
    "location": "organization__location",
    "own": "user_id",
}
```

Kolom di ujung jalur itu **selalu** ikut di `WHERE` untuk setiap pengguna bercakupan. Untuk `OrganizationAssignment`, index gabungan `(company, location)` menutup sebagian besar kasus.

### 3 · Kolom yang jadi kunci pencarian dokumen

| Model | Kolom |
|---|---|
| `WorkflowInstance` | `(module, document_type, object_id)` — kunci pencarian dokumen |
| `WorkflowApproval` | `(approver, status)` — kotak masuk |
| `EmployeeAttendance` | `(employee, work_date)` — dedup import |
| `RotationPeriod` | `(rotation, start_date)` — urutan tampilan |
| `AuditTrail` | `(created_at)` — selalu diurutkan menurun |

### 4 · Kolom rentang tanggal

Dokumen effective-dated selalu dicari lewat rentang:

```python
models.Index(fields=["employee", "effective_from"])   # PayrollAssignment
models.Index(fields=["version_from", "version_to"])   # RotationPeriod
```

---

## Yang **tidak** perlu diindex

- Kolom dengan sedikit nilai berbeda (`status` dengan 5 nilai) **sendirian** — PostgreSQL akan memilih seq scan. Berguna hanya sebagai bagian index gabungan atau **partial index**
- Kolom yang tidak pernah difilter atau disortir
- Tabel referensi kecil (`Gender`, `BloodType`) — puluhan baris, index-nya tidak pernah dipakai

---

## Partial index untuk soft delete

Karena hampir semua query menyaring `is_deleted=False`, partial index sering lebih kecil dan lebih cepat:

```python
models.Index(
    fields=["company", "code"],
    condition=Q(is_deleted=False),
    name="idx_active_location_company_code",
)
```

`UniqueConstraint` terkondisi yang sudah dipakai di mana-mana **sudah** menghasilkan partial unique index — jadi sebagian kebutuhan ini terpenuhi tanpa index tambahan.

---

## Kesalahan yang lebih sering daripada kurang index

!!! danger "N+1 query, bukan index yang kurang"
    Endpoint list yang lambat di sistem ini **hampir selalu** karena relasi yang belum di-prefetch, bukan karena index.

    Satu tabel 20 baris dengan 5 kolom FK yang lupa `select_related` menjalankan **101 query**. Menambah index tidak menolong sama sekali.

Yang sudah terbukti butuh prefetch:

| Kasus | Yang dibutuhkan |
|---|---|
| Kolom `<relasi>_name` di tabel | `select_related` |
| Kepala Travel Request (department, section, position, POH) | `select_related` |
| `build_schedule_warnings` | `prefetch_related("periods__travels")` — tanpa itu satu query **per periode** |
| `SiteRotationSerializer.leave_balances` | prefetch lalu saring **di Python** |

**Periksa jumlah query dulu, baru pikirkan index.**

---

## Agregasi yang perlu perhatian khusus

```python
Count("id", distinct=True)
```

Donut Approval Status memakai `distinct=True` karena `visible_instances` menyaring lewat **join ke `approvals`** — dokumen bertiga kotak tanda tangan terhitung tiga kali.

!!! warning "`.distinct()` pada queryset tidak menolong setelah `values().annotate()`"
    Yang benar `distinct=True` di dalam agregatnya.

---

## Mengukur

```python
from django.db import connection
print(len(connection.queries))
```

```sql
EXPLAIN ANALYZE SELECT ...;
```

**Belum ada pemantauan query lambat** — lihat [Monitoring](../07-deployment/Monitoring.md). Sampai ada, penambahan index adalah tebakan.

---

## Catatan multi-tenant

Index dibuat **per schema**. Menambah satu index berarti `CREATE INDEX` di setiap schema tenant, dan durasinya sebanding jumlah tenant × ukuran tabel.

Untuk tabel besar di produksi, pertimbangkan `AddIndexConcurrently` (`django.contrib.postgres.operations`) supaya tidak mengunci tabel — tapi ia **tidak bisa** di dalam transaksi, jadi migrasinya perlu `atomic = False`.

---

## Checklist sebelum menambah index

- [ ] Sudah diukur bahwa querynya memang lambat
- [ ] Sudah dipastikan bukan N+1
- [ ] Kolomnya benar-benar ikut di `WHERE`/`ORDER BY`
- [ ] Bukan FK (sudah otomatis)
- [ ] Pertimbangkan gabungan dengan `is_deleted`
- [ ] Durasi pembuatan × jumlah tenant masih masuk akal
