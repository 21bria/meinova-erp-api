# Filtering & Search

Tiga backend terpasang di `BaseMasterViewSet`, urutannya berarti:

```python
filter_backends = [
    DjangoFilterBackend,   # ?company=3&is_active=true
    SafeSearchFilter,      # ?search=budi
    filters.OrderingFilter # ?ordering=-created_at
]
```

---

## Filter per field — `DjangoFilterBackend`

```python
class VehicleViewSet(BaseMasterViewSet):
    filterset_fields = ["company", "location", "is_active"]
```

atau `filterset_class` untuk yang butuh lookup di relasi:

```python
class EmployeeFilterSet(django_filters.FilterSet):
    company = django_filters.NumberFilter(field_name="organization__company")
    location = django_filters.NumberFilter(field_name="organization__location")
```

`EmployeeFilterSet` (`apps/hr/api/employee/filters.py`) ada persis karena datanya di relasi `organization`, bukan di kolom `Employee`.

!!! danger "`filter=True` di schema hanya menampilkan filter di UI"
    Tanpa pemetaan di `filterset_class` / `filterset_fields`, parameternya **diterima lalu diabaikan diam-diam**. Tabelnya menampilkan seluruh data seolah filternya tidak berpengaruh — dan tidak ada satu pun error.

    Ini pasangan yang **selalu** harus ditulis bersamaan.

### Filter yang menembus relasi

`foreign_key="period__rotation"` pada tabel inline mengirim parameter `period__rotation`. Jalur itu **wajib** ada di `filterset_fields`:

```python
class RotationTravelViewSet(BaseMasterViewSet):
    filterset_fields = ["period", "period__rotation", "direction"]
```

Tanpa itu parameternya diabaikan dan **grid menampilkan travel seluruh tenant** di dalam dokumen satu orang.

---

## Pencarian — `SafeSearchFilter`

```
GET /api/hr/employees/?search=budi
```

```python
search_fields = ["employee_number", "full_name", "organization__department__name"]
```

Untuk kolom FK pakai `relasi__field` (`city__name`), bukan nama relasinya saja.

!!! danger "`search_fields` wajib diperiksa terhadap model"
    Base memberi default `["code", "name"]`. Model tanpa kolom itu yang lupa menimpanya dulu membalas **HTTP 500 setiap kali user mengetik di kotak pencarian** — 12 viewset kena.

    `SafeSearchFilter` (`apps/framework/filters.py`) sekarang **melewati field tak dikenal** dan mencatatnya di log. Itu **jaring, bukan izin**: perbaiki konfigurasinya, karena field yang dilewati berarti pencarian yang diam-diam tidak mencari apa yang diharapkan.

---

## Cakupan data ikut menyaring, dan itu bukan filter

`filter_queryset()` memanggil `super().filter_queryset()` **lalu** `DataScopeService.filter()`. Jadi hasil akhir = filter user **AND** cakupan rolenya.

Konsekuensi yang perlu disadari saat debugging: **dua orang menjalankan URL yang sama persis bisa mendapat jumlah baris berbeda**, dan itu benar. Kalau "kok datanya kurang", periksa `RoleDataPermission` sebelum mencurigai filternya.

Detail: [Permission](../02-Framework/Permission.md#cakupan-data--datascopeservice).

---

## Filter berantai di toolbar

Filter Location harus menyempit begitu Company dipilih. Mekanismenya sama persis dengan form:

```python
field.lookup(
    lookup_endpoint=".../locations/",
    lookup_params={"company_id": "$company"},
    depends_on="company",
    filter={"group": "quick", "order": 20},
)
```

Empat bug pernah bertumpuk di jalur ini dan semuanya gagal tanpa suara — [Lookup](../02-Framework/Lookup.md#filter-berantai-di-toolbar-tabel).

!!! warning "`filter` punya dua bentuk"
    `filter=True` **dan** `filter={"group": "quick", "order": 20}`. Generator dulu memeriksa `=== true` sehingga bentuk kedua jatuh seluruhnya — layar Departments tidak punya filter Company, Location, maupun Division **sama sekali**, padahal ketiganya dideklarasikan.

---

## Filter di lookup

Endpoint lookup menyaring lewat `filter_fields`:

```python
class LocationLookup(OrganizationScopedLookup):
    filter_fields = ["company_id", "branch_id"]
```

**Parameter yang tidak terdaftar diabaikan diam-diam** — penyebab klasik dropdown yang "tidak mau tersaring".

Lookup organisasi mewarisi `OrganizationScopedLookup` yang memakai pola **"cocok dengan induk ATAU induknya null"**, karena level organisasi boleh dilompati.

---

## Export mengikuti filter aktif

`GET .../export/` menjalankan `filter_queryset(get_queryset())` yang sama dengan `list`. Jadi CSV-nya **persis** apa yang sedang dilihat user, termasuk cakupan datanya.

---

## Checklist

- [ ] Setiap field ber-`filter` di schema punya padanan di `filterset_fields`/`filterset_class`
- [ ] Filter lookup punya `lookup_endpoint`
- [ ] `depends_on` menyebut setiap field yang dipakai di `lookup_params`
- [ ] `search_fields` cocok dengan model, FK pakai `relasi__field`
- [ ] Field relasi yang difilter ikut di `select_related`
