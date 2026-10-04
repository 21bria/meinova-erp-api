# Coding Standards

Konvensi yang **sudah berlaku di codebase ini**. Ikuti yang ada, jangan bawa gaya baru — kode yang terlihat asing di tengah modul lain lebih mahal daripada kode yang gayanya kurang kamu sukai.

!!! warning "Belum ada linter/formatter yang menegakkan ini"
    Tidak ada `ruff`, `black`, atau `flake8` di `requirements.txt`, dan tidak ada `.github/`. Seluruh aturan di halaman ini ditegakkan lewat review, bukan tooling. Kalau nanti tooling dipasang, konfigurasinya harus **mengikuti** gaya yang sudah ada — bukan sebaliknya.

---

## Bahasa: label Inggris, komentar Indonesia

Ini konvensi paling terlihat dan paling sering dilanggar orang baru.

```python
work_date = models.DateField(
    verbose_name="Work Date",                                    # Inggris
    help_text="Kosongkan untuk ikut tanggal mulai siklus crew.", # Indonesia
)

# Nomor hanya dialokasikan saat create dan tidak pernah dihitung
# ulang saat update — yang tercetak di TR harus tetap menunjuk
# dokumen yang sama.
```

| Bagian | Bahasa |
|---|---|
| `label`, `verbose_name`, `TextChoices` display, `options` dropdown, heading menu, kategori Master Hub | **Inggris** |
| `help_text`, komentar, docstring, pesan error ke pengguna | **Indonesia** |

Modul Travel Request, Leave Policy, dan Roster Policy sempat menyimpang dengan label Indonesia dan sudah dikembalikan. **Campur bahasa di satu tabel adalah hal pertama yang dikeluhkan pengguna.**

---

## Penamaan

| Jenis | Pola | Contoh |
|---|---|---|
| Model | `PascalCase` **singular** | `EmployeeBankAccount` |
| Serializer | `<Model>Serializer` | `EmployeeSerializer` |
| Service | `<Model>Service` | `EmployeeLeaveService` |
| ViewSet | `<Model>ViewSet` | `TravelRequestViewSet` |
| Lookup | `<Model>Lookup` | `RosterCrewLookup` |
| Schema dict | `SCREAMING_SNAKE` | `EMPLOYEE_SCHEMA`, `GENERAL_FIELDS` |
| `db_table` | `<app>_<model_snake>` | `hr_travel_request` |
| Constraint | `uniq_active_<app>_<model>_<kolom>` | `uniq_active_hr_vehicle_company_code` |
| URL | plural kebab-case | `/api/hr/travel-requests/` |
| `framework_module` | `<domain>/<resource>` kebab-case | `hr/travel-requests` |

---

## Struktur app

```
apps/<domain>/
  models/                     # satu file per agregat, reexport lewat __init__.py
  api/<resource>/             # serializers.py, services.py, views.py, urls.py
  api/<resource>/schema/      # schema UI deklaratif (resource kompleks)
  seeds/ · management/commands/ · imports/ · tasks.py
```

Resource kompleks memecah file jadi package — lihat `apps/hr/api/employee/` (`serializers/mixins/`, `services/` per aspek, `views/` per action, `schema/fields/` per tab).

**App baru wajib masuk `TENANT_APPS`**, bukan `SHARED_APPS`.

---

## Layering — tidak ada pengecualian

```
View → Service → Model
```

| Lapis | Boleh | Tidak boleh |
|---|---|---|
| ViewSet | routing, permission, filter, serialisasi | aturan bisnis |
| Serializer | bentuk data, validasi format, pesan ramah | perhitungan, efek samping |
| Service | aturan bisnis, transaksi, efek samping | tahu soal HTTP |
| Model | invarian satu record | aturan yang melihat baris lain |

Detail: [Siklus Request](../02-Framework/Request-Lifecycle.md).

---

## Komentar: tulis *kenapa*, bukan *apa*

Ini yang membedakan codebase ini dari kebanyakan. Komentar di sini panjang, dan itu disengaja — sebagian besar menjelaskan **keputusan** dan **apa yang gagal kalau diubah**.

```python
# Penyaringan baris dipasang di sini, BUKAN di get_queryset().
#
# Dua alasan, dan yang kedua yang menentukan:
# 1. get_object() DRF memanggil filter_queryset(get_queryset()), jadi
#    satu tempat ini menutup daftar, detail by id, export, hapus, dan
#    update sekaligus.
# 2. 41 viewset menimpa get_queryset() sendiri. Kalau penyaringannya
#    dipasang di sana, semuanya lolos diam-diam.
```

Yang layak dikomentari:

- Kenapa pendekatan yang **lebih jelas** tidak dipakai
- Apa yang **gagal tanpa suara** kalau baris ini dihapus
- Bug yang pernah terjadi di titik itu
- Batas yang disengaja ("sengaja tidak menolak, cuma memperingatkan")

Yang tidak: `# increment counter` di atas `counter += 1`.

---

## Gaya Python

Mengikuti apa yang sudah ada:

```python
# Argumen service selalu keyword-only
@classmethod
def create(cls, *, data, user=None): ...

# Multi-line untuk pemanggilan panjang, trailing comma
return DataScopeService.filter(
    queryset,
    getattr(self, "data_scope", None),
    getattr(request, "user", None),
)

# from __future__ import annotations di file yang pakai type hint modern
```

- Indentasi 4 spasi, tanda kutip ganda
- `classmethod` untuk seluruh service (tidak ada instance service)
- Import dikelompokkan: stdlib → Django → DRF → pihak ketiga → `apps.*`

---

## Aturan yang gagalnya diam — hafalkan

Delapan hal yang **tidak menghasilkan error** kalau dilanggar:

1. **`unique=True` polos** di turunan `BaseModel` → nilai terkunci selamanya oleh record terhapus
2. **`class Meta:` polos** di turunan `BaseReference` → constraint & ordering hilang
3. **`fields = "__all__"`** pada model berelasi → kolom "-" di semua baris
4. **`search_fields` bawaan** pada model tanpa `code`/`name` → HTTP 500 saat mengetik di kotak cari
5. **`filter=True` tanpa `filterset_fields`** → filter tampil, parameternya diabaikan
6. **Lupa `ServiceWriteMixin`** → logika service tidak jalan, audit tidak tercatat
7. **Lupa `AppConfig.ready()`** untuk registry lookup/importer/workflow → 404, atau status dokumen tidak berpindah
8. **Lupa regenerate frontend** → perubahan schema tidak terlihat di layar

Checklist lengkapnya: [Checklist](Checklist.md).

---

## Migrasi

```bash
python manage.py makemigrations <app>
python manage.py migrate_schemas --shared
python manage.py migrate_schemas
```

!!! danger "Migrasi yang menyentuh model hasil rename wajib `run_before`"
    Empat migrasi pernah menambah FK ke `administration.Site` (direname jadi `Location`) tanpa menyatakan urutannya. Django bebas menjadwalkan rename lebih dulu, dan **penyediaan tenant baru gagal** dengan `Related model 'administration.site' cannot be resolved`.

    Tiga di antaranya cuma *kebetulan* terjadwal benar — menambah migrasi baru bisa mengubah urutannya kapan saja.

---

## Seed

- **Aman diulang** (`update_or_create`), selalu.
- **Jangan pernah menghapus lalu membuat ulang** data yang mungkin dirujuk dokumen berjalan.
- Kode yang ditarik dari daftar dibuang lewat `OBSOLETE_CODES` — **soft delete** kalau modelnya dilindungi `PROTECT`.
- **Jangan seed angka karangan.** `SICK-STD` 30 hari pernah diseed dan angka itu tidak punya dasar hukum; angka karangan di master lebih berbahaya daripada tidak ada angka, karena orang menganggapnya sudah divalidasi.

---

## Sisi frontend

| | Aturan |
|---|---|
| `app/modules/**` | **jangan disunting** — hasil generate |
| `framework/**` | tempat perbaikan lintas modul |
| `scripts/meinova/**` | generator & template |
| `app/pages/**` | ditulis tangan |

Perbaikan yang menyentuh lebih dari satu modul hampir selalu masuk `framework/`. Detail: [Generator](../02-Framework/Generator.md#aturan-memilih-tempat-perbaikan).

---

## Kalau nanti memasang tooling

Urutan yang paling sedikit menimbulkan diff besar:

1. `ruff check` dengan aturan minimal (unused import, undefined name) — **tanpa** auto-format dulu
2. `ruff format` di satu commit terpisah yang tidak mengubah apa pun selain format
3. Baru tambahkan aturan lain satu per satu

Menyalakan semuanya sekaligus menghasilkan diff ribuan baris yang tidak bisa direview.
