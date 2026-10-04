# Cache

Redis, dikonfigurasi tapi **hampir tidak dipakai**.

---

## Konfigurasi

```python
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": config("REDIS_CACHE_URL", default="redis://localhost:6379/1"),
    },
}
```

!!! danger "DB index /1, jangan dicampur"
    | Index | Env | Untuk |
    |---|---|---|
    | `/0` | `REDIS_URL` | Celery broker |
    | `/1` | `REDIS_CACHE_URL` | **Django cache** |
    | `/2` | `REDIS_CHANNELS_URL` | Channels (masih dikomentari) |
    | `/3` | `CELERY_RESULT_BACKEND` | hasil task |

    Mencampurnya membuat hasil task tertimpa cache, dan gagalnya sangat sulit dilacak.

`config/settings/cache.py` masih **kosong** — konfigurasinya ada di `base.py`.

---

## Yang benar-benar di-cache hari ini

Nyaris tidak ada:

| | Cakupan |
|---|---|
| `RolePermissionBackend` | hasil izin di-cache **pada instance user**, per request — bukan di Redis |
| `SafeSearchFilter._resolved_cache` | cache lokal per instance filter |

**Tidak ada satu pun yang memakai Redis cache.**

---

## Kenapa belum, dan kenapa itu bukan kelalaian

Dua alasan struktural:

### 1 · Multi-tenant membuat kunci cache berbahaya

Cache Redis **tidak tahu schema**. Kunci `menu_permissions_role_5` di tenant A akan dibaca tenant B kalau kuncinya tidak menyertakan schema.

!!! danger "Kalau nanti dipasang, kunci WAJIB menyertakan schema"
    ```python
    from django.db import connection
    key = f"{connection.schema_name}:menu_access:{role_id}"
    ```

    Kebocoran lintas tenant paling mudah lahir di sini, dan gejalanya **tidak terlihat sebagai error** — cuma data yang salah.

### 2 · Sebagian besar lambatnya bukan karena query berulang

Penyebab nomor satu di sistem ini adalah **N+1 query** — relasi yang belum di-prefetch. Cache tidak menolong sama sekali untuk itu.

Lihat [Performance](../06-database/Performance.md).

---

## Yang layak di-cache kalau nanti perlu

Diurutkan dari yang paling aman:

| Kandidat | Kenapa aman | Invalidasi |
|---|---|---|
| Schema UI (`build_ui_schema`) | hanya berubah saat kode berubah | versi deploy |
| Master referensi (gender, blood type) | jarang berubah, kecil | saat seed / CRUD master |
| `MenuAccessService` per role | dibaca tiap navigasi | saat `RoleMenuPermission` berubah |
| Peta izin `/api/framework/permissions/` | idem | saat `Role.permissions` berubah |

Empat-empatnya butuh kunci ber-schema.

!!! warning "Jangan cache queryset yang lewat `DataScopeService`"
    Hasilnya **berbeda per pengguna**, dan kunci yang lupa menyertakan pengguna akan menyajikan data orang lain.

    Ini kategori bug yang paling berbahaya di sistem ini: bukan error, cuma baris yang seharusnya tidak terlihat.

---

## Yang JANGAN di-cache

- Apa pun yang lewat cakupan data
- `LeaveBalance.used` dan `RotationCreditBalance` — keduanya **sengaja dihitung ulang penuh** supaya tidak bisa hanyut; men-cache-nya mengembalikan persis masalah yang dihindari
- Dokumen yang sedang berjalan di engine approval

---

## Kalau mau mulai

1. **Ukur dulu** — belum ada pemantauan query lambat sama sekali ([Monitoring](../07-deployment/Monitoring.md))
2. Perbaiki N+1 yang sudah diketahui
3. Baru cache, mulai dari schema UI yang paling aman
4. Kunci **selalu** menyertakan `connection.schema_name`
