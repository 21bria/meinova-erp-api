# Membuat Modul Baru — End to End

Tutorial lengkap dari model kosong sampai halaman yang bisa dipakai. Contohnya sengaja sederhana: master **Vehicle** di modul HR, supaya yang terlihat adalah *pipeline*-nya, bukan aturan bisnisnya.

Estimasi: ~30 menit untuk CRUD sederhana kalau semua langkah diikuti berurutan.

---

## Sebelum mulai: pilih bentuk layarnya

| Bentuk | Kapan dipakai | Builder |
|---|---|---|
| **Dialog** | master sederhana, < 10 field | `ui.dialog(...)` |
| **Page** | form sedang, tidak bertab | `ui.page(...)` |
| **Workspace** | dokumen bertab, punya sub-tabel | `ui.workspace(...)` + key `tabs` |
| **Drawer / Wizard** | jarang | `ui.drawer(...)` / `ui.wizard(...)` |

Editor `dialog` **tidak butuh** rute create/edit. Editor `workspace` butuh tiga: `create`, `[id]`, `[id]/edit`. Membuatkan rute untuk modul dialog justru error — `page.vue`-nya tidak menerima prop `mode`.

---

## Langkah 1 — Model

`apps/hr/models/vehicle.py`

```python
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel


class Vehicle(BaseModel):
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="vehicles",
        verbose_name="Company",
    )
    code = models.CharField(max_length=32, verbose_name="Code")
    plate_number = models.CharField(max_length=32, verbose_name="Plate Number")
    # Kosongkan untuk kendaraan yang tidak menempel ke lokasi tertentu.
    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="vehicles",
        verbose_name="Location",
    )
    is_active = models.BooleanField(default=True, verbose_name="Active")

    class Meta:
        db_table = "hr_vehicle"
        ordering = ["code"]
        verbose_name = "Vehicle"
        constraints = [
            # Wajib dikondisikan ke is_deleted — tanpa ini kodenya
            # terkunci selamanya oleh record yang sudah dihapus.
            models.UniqueConstraint(
                fields=["company", "code"],
                condition=Q(is_deleted=False),
                name="uniq_active_hr_vehicle_company_code",
            ),
        ]

    def __str__(self):
        return f"{self.code} — {self.plate_number}"
```

Reexport di `apps/hr/models/__init__.py`:

```python
from .vehicle import Vehicle
```

Lalu:

```bash
python manage.py makemigrations hr
python manage.py migrate_schemas
```

!!! warning "Migrasi yang menyentuh model yang pernah direname wajib `run_before`"
    Empat migrasi lama pernah menambah FK ke `administration.Site` (model yang direname jadi `Location`) tanpa menyatakan urutannya, dan penyediaan tenant baru gagal dengan `Related model 'administration.site' cannot be resolved`. Django bebas menjadwalkan rename lebih dulu.

**Checklist model:**

- [ ] Turunan `BaseModel` (atau `BaseReference` untuk master ber-`code`/`name`)
- [ ] Tidak ada `unique=True` polos — pakai `UniqueConstraint` + `condition=Q(is_deleted=False)`
- [ ] Kalau turunan `BaseReference`: `class Meta(BaseReference.Meta)`, bukan `class Meta:`
- [ ] App-nya terdaftar di `TENANT_APPS`, bukan `SHARED_APPS`

---

## Langkah 2 — Service

`apps/hr/api/vehicle/services.py`

```python
from apps.core.services.master import BaseMasterService
from apps.hr.models import Vehicle


class VehicleService(BaseMasterService):
    model = Vehicle

    @classmethod
    def get_queryset(cls):
        return super().get_queryset().select_related("company", "location")

    @classmethod
    def before_create(cls, data, user=None):
        data = super().before_create(data, user=user)

        # Kode diseragamkan huruf besar; klien mengetiknya campur.
        if data.get("code"):
            data["code"] = str(data["code"]).strip().upper()

        return data
```

`BaseMasterService` sudah memberi filter soft-delete, `soft_delete()`, `restore()`, dan pengisian `created_by`/`updated_by`.

---

## Langkah 3 — Serializer

`apps/hr/api/vehicle/serializers.py`

```python
from rest_framework import serializers

from apps.hr.models import Vehicle


class VehicleSerializer(serializers.ModelSerializer):
    # Tanpa dua field ini, kolom Company dan Location di tabel akan
    # menampilkan "-" di SELURUH baris — generator memetakan field
    # lookup ke `<field>_name`.
    company_name = serializers.CharField(source="company.name", read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)

    class Meta:
        model = Vehicle
        fields = [
            "id",
            "company", "company_name",
            "code",
            "plate_number",
            "location", "location_name",
            "is_active",
        ]
```

!!! danger "Jangan `fields = \"__all__\"` untuk resource yang punya relasi"
    Itu penyebab tunggal terbanyak kolom "-" di tabel. Lihat [jebakan #3](BE-to-FE-Pipeline.md#3-kolom-di-semua-baris).

---

## Langkah 4 — Schema

`apps/hr/api/vehicle/schema.py`

```python
from apps.framework.builders import field, ui

VEHICLE_SCHEMA = {
    "module": "hr/vehicles",
    "name": "Vehicle",
    "label": "Vehicle",
    "endpoint": "/api/hr/vehicles/",   # WAJIB kalau beda dari framework_module
    "schema_type": "crud",

    "ui": {
        **ui.dialog(
            title="Vehicles",
            description="Master kendaraan operasional.",
            size="lg",
            columns=2,
            create=True,
            edit=True,
            delete=True,
            bulk_delete=True,
            export=True,
        ),
    },
    "fields": {
        "company": field.lookup(
            label="Company",
            lookup_endpoint="/api/administration/organization/lookup/companies/",
            required=True,
            table=True,
            filter=True,
            order=10,
        ),
        "code": field.text(
            label="Code",
            required=True,
            table=True,
            search=True,
            sortable=True,
            order=20,
        ),
        "plate_number": field.text(
            label="Plate Number",
            required=True,
            table=True,
            search=True,
            order=30,
        ),
        "location": field.lookup(
            label="Location",
            lookup_endpoint="/api/administration/organization/lookup/locations/",
            # Kirim SELURUH induk yang mungkin terisi, bukan cuma yang terdekat.
            lookup_params={"company_id": "$company"},
            depends_on="company",
            table=True,
            filter={"group": "quick", "order": 20},
            order=40,
        ),
        "is_active": field.boolean(
            label="Active",
            table=True,
            default=True,
            order=50,
        ),
    },
}
```

**Label UI dalam Bahasa Inggris, help text dan komentar dalam Bahasa Indonesia.** Itu konvensi yang berlaku di seluruh modul lama; campur bahasa di satu tabel adalah hal pertama yang dikeluhkan pengguna.

---

## Langkah 5 — ViewSet

`apps/hr/api/vehicle/views.py`

```python
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from .schema import VEHICLE_SCHEMA
from .serializers import VehicleSerializer
from .services import VehicleService


class VehicleViewSet(ServiceWriteMixin, BaseMasterViewSet):
    framework_module = "hr/vehicles"       # WAJIB & unik lintas sistem
    schema = VEHICLE_SCHEMA
    service_class = VehicleService
    serializer_class = VehicleSerializer

    # Default base-nya ["code", "name"]; model ini tidak punya `name`,
    # dan membiarkannya membalas 500 tiap kali orang mengetik di kotak cari.
    search_fields = ["code", "plate_number"]
    ordering = ["code"]

    filterset_fields = ["company", "location", "is_active"]

    data_scope = {
        "company": "company",
        "location": "location",
    }
```

**`ServiceWriteMixin` harus di depan.** Tanpa itu, `VehicleService.create()` tidak pernah jalan lewat API dan perubahannya tidak masuk jejak audit — lihat [Siklus Request](Request-Lifecycle.md#service_class-sendirian-tidak-cukup).

**`filterset_fields` harus memuat setiap parameter yang dipakai filter.** `filter=True` di schema hanya menampilkan filter di UI; tanpa pemetaan di sini, parameternya diterima lalu **diabaikan diam-diam**.

---

## Langkah 6 — URL

`apps/hr/api/vehicle/urls.py`

```python
from rest_framework.routers import DefaultRouter

from .views import VehicleViewSet

router = DefaultRouter()
router.register("vehicles", VehicleViewSet, basename="vehicle")

urlpatterns = router.urls
```

Daftarkan di `apps/hr/api/urls.py` — **di atas** router viewset umum kalau ada rute spesifik.

Verifikasi:

```bash
curl -s http://demo.localhost:8000/api/framework/schema/hr/vehicles/ | python -m json.tool | head -30
```

Kalau 404: `framework_module` salah ketik, atau modulnya belum ter-import saat startup.

---

## Langkah 7 — Lookup (kalau resource ini jadi dropdown di tempat lain)

`apps/hr/api/lookup/registry.py`

```python
from apps.framework.lookup.decorators import register_lookup
from apps.framework.lookup.base import BaseLookup
from apps.hr.models import Vehicle


@register_lookup
class VehicleLookup(BaseLookup):
    name = "vehicles"                     # unik LINTAS DOMAIN — registry global
    model = Vehicle
    search_fields = ["code", "plate_number"]
    filter_fields = ["company_id", "location_id"]

    @classmethod
    def serialize(cls, obj):
        return {
            "value": obj.pk,
            "label": f"{obj.code} — {obj.plate_number}",
            # Hanya kunci yang disebut di sini yang boleh dipakai `autofill`
            # di schema field mana pun.
            "company": obj.company_id,
        }
```

!!! danger "Parameter yang tidak terdaftar di `filter_fields` diabaikan diam-diam"
    Itu penyebab klasik dropdown yang "tidak mau tersaring".

Pastikan registry-nya di-import dari `HrConfig.ready()` — **kalau lupa, endpoint-nya 404** tanpa petunjuk apa pun.

Endpointnya: `/api/hr/lookup/vehicles/`.

---

## Langkah 8 — Generate frontend

Di repo Nuxt:

```bash
cd ~/Project/nuxt/meinova-erp
pnpm meinova generate hr/vehicles
```

Keluaran:

```
✔ Schema   : http://demo.localhost:8000/api/framework/schema/hr/vehicles/
✔ Endpoint : /api/hr/vehicles/
```

Berkasnya mendarat di `app/modules/hr/vehicles/`.

---

## Langkah 9 — Halaman & menu

Halaman **wajib** di `app/pages/<framework_module>/`:

```
app/pages/hr/vehicles/index.vue
```

```vue
<script setup lang="ts">
import { VehiclesPage } from "~/modules/hr/vehicles"
</script>

<template>
  <VehiclesPage />
</template>
```

Untuk editor `workspace`, tambahkan juga `create.vue`, `[id]/index.vue`, `[id]/edit.vue`.

Menu di `app/constants/menus.ts`. Kalau menu itu perlu bisa dibatasi per role, tambahkan juga barisnya di `apps/accounts/seeds/menus.py` lalu:

```bash
python manage.py tenant_command seed_menus --schema=demo
```

!!! warning "Menu yang tidak diseed tidak bisa dibatasi"
    Sumber kebenaran daftar menu ada di sisi Nuxt, tapi tabel `Menu` di backend yang menentukan apa yang bisa dicentang di layar Menu Permissions. Menambah di satu tempat saja berarti menu itu **selalu terlihat semua role**.

Terakhir, restart dev server — Nuxt tidak selalu menangkap rute yang dibuat proses lain.

---

## Langkah 10 — Izin & cakupan

Modul baru **tidak otomatis bisa dipakai siapa pun** kalau `ENFORCE_MODEL_PERMISSIONS` menyala.

```bash
python manage.py tenant_command seed_security_roles --schema=demo
```

Seed itu menambahkan izin, tidak pernah mencabut — aman diulang. Untuk role yang memang harus bisa menulis modul ini, tambahkan modelnya ke `GRANTS` di `apps/accounts/seeds/security_roles.py`.

Tiga lapis harus diisi bersamaan, dan lupa salah satunya gagal ke arah yang berbeda:

| Lupa | Akibatnya |
|---|---|
| `data_scope` | role bercakupan sempit membaca **seluruh tenant** |
| izin model | sidebar penuh, tombol Save 403 setelah form diisi |
| baris menu | menu terlihat oleh role yang seharusnya tidak |

---

## Checklist akhir

Backend:

- [ ] Model + migration + reexport di `__init__.py`
- [ ] `UniqueConstraint` dikondisikan ke `is_deleted`
- [ ] Service turunan `BaseMasterService`
- [ ] Serializer menyebut `<relasi>_name` untuk setiap FK yang jadi kolom
- [ ] Schema: `endpoint` eksplisit, `ui`, `fields`
- [ ] ViewSet: `ServiceWriteMixin` di depan, `framework_module` unik, `search_fields` cocok dengan model, `filterset_fields` memuat semua filter, `data_scope` terisi
- [ ] URL terdaftar berlapis
- [ ] Lookup terdaftar + di-import dari `AppConfig.ready()` (kalau perlu)
- [ ] `GET /api/framework/schema/<module>/` membalas 200

Frontend:

- [ ] `pnpm meinova generate <module>`
- [ ] Halaman di `app/pages/<framework_module>/`
- [ ] Menu di `app/constants/menus.ts`
- [ ] Restart dev server
- [ ] **Buka halamannya di browser sungguhan** — build lolos bukan bukti

Data & izin:

- [ ] Seed master pendukung kalau ada
- [ ] `seed_menus` + `seed_security_roles`

---

## Kalau modulnya dokumen berapproval

CRUD di atas cuma tabel. Untuk dokumen yang diajukan dan disetujui, tambahkan:

1. Kolom `status` memakai `TextChoices` (`DRAFT` / `SUBMITTED` / `APPROVED` / `REJECTED` / `CANCELLED` / `RETURNED`)
2. `@action` `submit` / `withdraw`, memanggil `WorkflowService.submit(...)`
3. Callback penyelesaian di `apps/<domain>/workflow_handlers.py`, didaftarkan `@register_completion("<module>", "<document_type>")` dan **di-import dari `AppConfig.ready()`** — kalau lupa, tombol Approve tetap jalan tapi status dokumennya tidak ikut berpindah, dan gagalnya diam
4. `registry.register_route()` supaya kotak masuk bisa menautkan ke halamannya
5. `WorkflowDefinition` diseed di `apps/workflow/seeds/workflows.py`
6. Deret nomor dokumen di `apps/administration/seeds/numbering.py`
7. `action.submit()` / `action.approve()` di `schema["actions"]`

Detail lengkapnya di [Alur Persetujuan Dokumen](../09-business-flows/Document-Approval.md).
