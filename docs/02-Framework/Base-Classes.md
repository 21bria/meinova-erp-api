# Base Classes

Referensi `BaseModel`, `BaseReference`, `BaseService` beserta turunannya, dan `BaseMasterViewSet`.

---

## `BaseModel` — `apps/core/models/base.py`

Semua model bisnis mewarisinya.

| Kolom | Isi |
|---|---|
| `created_at`, `created_by` | audit pembuatan |
| `updated_at`, `updated_by` | audit perubahan |
| `is_deleted`, `deleted_at`, `deleted_by` | soft delete |

**Soft delete, bukan hard delete.** Query selalu `.filter(is_deleted=False)` — `BaseMasterService.get_queryset()` sudah menanganinya.

`created_by` / `updated_by` terisi otomatis **hanya** lewat `BaseMasterService.before_create/before_update`, yaitu hanya untuk viewset yang memasang `ServiceWriteMixin`. Pemanggil non-HTTP (management command, task Celery, test) harus mengoper `user=` eksplisit.

### Field unik wajib dikondisikan ke `is_deleted`

Kalau tidak, nilainya **terkunci selamanya** oleh record yang sudah dihapus.

```python
class Meta:
    constraints = [
        models.UniqueConstraint(
            fields=["company", "code"],
            condition=Q(is_deleted=False),
            name="uniq_active_hr_vehicle_company_code",
        ),
    ]
```

**Jangan `unique=True` polos** di model turunan `BaseModel`.

Yang sengaja **tidak** dikonversi, dan alasannya:

| Kolom | Alasan |
|---|---|
| `public_id` (UUID) | tidak pernah dipakai ulang |
| `ApiKey.hashed_key` | harus unik global **termasuk** yang sudah dicabut |
| `OrganizationAssignment.employee` dan OneToOne lain | mengubahnya berarti mengganti `OneToOneField` jadi FK + constraint, dan itu mengubah accessor seperti `employee.organization` |

---

## `BaseReference`

`BaseModel` + `code` (unik) + `name` + `description` + `sort_order`. Untuk master referensi.

Ia sudah menangani constraint `code` lewat `Meta.constraints` dengan nama ber-placeholder `%(app_label)s_%(class)s`.

!!! danger "Turunannya wajib `class Meta(BaseReference.Meta)`"
    ```python
    class LeaveType(BaseReference):
        class Meta(BaseReference.Meta):   # ✅
            db_table = "hr_leave_type"

        class Meta:                        # ❌ constraint & ordering hilang
            db_table = "hr_leave_type"
    ```

Kode unik di luar `BaseReference` (payroll, `Bank`, `Currency`, `Country`, `Menu`, `Role`, `Dashboard*`, `AttendanceImportProfile`) sudah dikonversi satu per satu.

---

## `BaseService` — `apps/core/services/base.py`

Classmethod-only. Setiap mutasi `@transaction.atomic` + `full_clean()`.

```python
class BaseService:
    model = None
    audit_enabled = True

    @classmethod def get_queryset(cls): ...
    @classmethod def get_by_id(cls, pk): ...

    @classmethod def before_create(cls, data, user=None): ...
    @classmethod def create(cls, *, data, user=None): ...
    @classmethod def after_create(cls, instance, data, user=None): ...

    @classmethod def before_update(cls, instance, data, user=None): ...
    @classmethod def update(cls, *, instance, data, user=None): ...
    @classmethod def after_update(cls, instance, data, user=None): ...

    @classmethod def before_delete(cls, instance, user=None): ...
    @classmethod def delete(cls, *, instance, user=None): ...
```

### Turunan

| Class | Tambahan |
|---|---|
| `BaseMasterService` | `list()`, filter soft-delete, `save_children()`, `soft_delete()` + `restore()` beserta hooknya, pengisian `created_by`/`updated_by` |
| `BaseReferenceService` | untuk master ber-`code`/`name` |
| `BaseTransactionService` | untuk dokumen transaksional |

### Aturan pembagi `Model.clean()` vs Service

> **Kalau aturannya perlu melihat baris lain, tempatnya di service.**

| Aturan | Tempatnya |
|---|---|
| `OrganizationAssignment.location` harus milik `branch` terpilih | `Model.clean()` — konsistensi satu record |
| Kuota `TrainingProgram` | service — menyangkut jumlah baris lain |
| Cuti tidak boleh tumpang tindih | service — menyangkut record cuti lain |
| Contract End tidak boleh menempel di pegawai Permanent | `Model.clean()` |

### Audit

Dicatat di `BaseService` (`_audit` / `_snapshot` / `_diff`), satu tempat. Dimatikan per service lewat `audit_enabled = False`.

Empat aturannya dijelaskan di [Siklus Request](Request-Lifecycle.md#hook-baseservice).

!!! bug "Tipe kolom yang tidak bisa di-JSON-kan mematikan pencatatan seluruh model, tanpa suara"
    `PrintSetting.logo` bertipe `ImageFieldFile`; `record()` melempar, ditelan `except`, dan tabelnya tetap nol baris. `_jsonable()` sekarang memakai `DjangoJSONEncoder` + `default=str`.

---

## `BaseMasterViewSet` — `apps/framework/views/master.py`

Bawaan yang perlu diketahui:

```python
schema_type = "crud"
permission_classes = [IsAuthenticated, ModelPermission]
pagination_class = StandardPagination
enforce_model_permissions = True
data_scope = None

filter_backends = [DjangoFilterBackend, SafeSearchFilter, filters.OrderingFilter]
search_fields = ["code", "name"]      # ← periksa terhadap model!
ordering_fields = "__all__"
ordering = ["name"]

service_class = None
framework_module = None
schema = {}
```

### `get_queryset()` — dari `service_class.list()`

Kalau `service_class` punya `list()`, queryset diambil dari sana. Kalau tidak, dari atribut `queryset`.

!!! warning "Menimpa `get_queryset()` yang salah membalas 500 dengan pesan menyesatkan"
    Errornya berbunyi *"must define `queryset`"* — dan bunyinya menuntun ke tempat yang salah. `BaseMasterViewSet` merakit querysetnya lewat `service_class.list()`, bukan `get_queryset()`.

### `filter_queryset()` — tempat cakupan data dipasang

Bukan `get_queryset()`. Alasannya di [Siklus Request](Request-Lifecycle.md#cakupan-data-datascopeservice).

### `get_permissions()` — tempat `ModelPermission` dipasang

Bukan cuma atribut `permission_classes`, karena puluhan viewset menulis ulang atribut itu dan **mengganti** daftarnya.

### `perform_soft_delete()`

Satu-satunya jalur penghapusan, dipakai `destroy()` maupun `bulk_delete()` supaya perilakunya tidak berbeda:

1. `service_class.soft_delete()` kalau ada
2. tandai `is_deleted` / `deleted_at` / `deleted_by` langsung
3. hard delete **hanya** kalau model tidak punya kolom `is_deleted`

### Export

`get_export_fields()` memakai schema hasil `build_ui_schema` dan mempertahankan urutan aslinya, supaya file export **sama persis** dengan yang dilihat user di tabel.

`EXPORT_EXCLUDED_FIELDS` membuang kolom audit. `export=False` datang dari introspeksi untuk field yang memang tidak bisa diekspor (file, image, m2m).

!!! warning "Export membaca instance, bukan serializer"
    `resolve_export_value` mengambil dari model langsung. Jadi masking apa pun yang dipasang di serializer **tidak menyentuh export** — itu harus ditutup terpisah lewat `get_export_fields`. Lihat `EmployeeViewSet` dan `EmployeeDataPolicy`.

---

## `ServiceWriteMixin` — `apps/framework/views/mixins.py`

Mengarahkan `perform_create` / `perform_update` ke `service_class`. **Dipasang di depan base-nya:**

```python
class XViewSet(ServiceWriteMixin, BaseMasterViewSet):
    service_class = XService
```

Tanpa mixin ini, `Service.create()` / `Service.update()` **tidak pernah jalan lewat API**, dan perubahannya **tidak masuk jejak audit**. Detailnya di [Siklus Request](Request-Lifecycle.md#service_class-sendirian-tidak-cukup).

---

## Base view lain

| Class | Untuk | Catatan |
|---|---|---|
| `BaseReferenceViewSet` | master referensi | turunan `BaseMasterViewSet` dengan default yang cocok untuk `BaseReference` |
| `BaseTreeAPIView` | pohon centang | dipakai Menu Permission & Data Permission |
| `BaseSettingAPIView` | satu form, satu record | **hanya bisa menyunting satu record** — salah untuk model yang punya satu baris per company |
| `BaseDashboardAPIView` | grid widget | tiap widget wajib punya `resolve_<key>`; widget tanpa resolver melempar `NotImplementedError`, sengaja berisik daripada tampil kosong |

`BaseDashboardAPIView` mengembalikan **semua widget dalam satu request** (`{period, widgets: {<key>: ...}}`). Satu endpoint per widget bikin halaman seperti HR menembak 12 request hanya untuk render pertama.

Pasangan `ui-schema/`-nya didaftarkan lewat `Cls.as_schema_view()` (`AllowAny`).

!!! danger "Dashboard tidak melewati `filter_queryset()`"
    `BaseDashboardAPIView` adalah `APIView` biasa. Tiap service dashboard **wajib** memanggil `DataScopeService.filter(qs, <peta>, context["user"])` di **setiap** queryset yang dibangunnya, dan petanya harus disamakan persis dengan `data_scope` di viewset masing-masing — kalau salah satu diubah, yang satunya harus ikut, kalau tidak angka dashboard tidak cocok dengan isi tabelnya.

---

## `SafeSearchFilter` — `apps/framework/filters.py`

Melewati field yang tidak dikenal alih-alih melempar, dan mencatatnya di log. Ini **jaring, bukan izin** — 12 viewset pernah membalas HTTP 500 setiap kali user mengetik di kotak pencarian karena `search_fields` bawaan (`["code", "name"]`) menyebut kolom yang tidak ada di modelnya.

Tetap perbaiki konfigurasinya. Untuk kolom FK pakai `relasi__field` (`city__name`), bukan nama relasinya saja.
