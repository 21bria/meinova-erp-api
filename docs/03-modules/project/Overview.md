# Project

!!! danger "📋 Blueprint — belum ada kodenya"
    Status: **tidak ada app-nya sama sekali**.

    Halaman ini rencana produk, **bukan rujukan implementasi**. Jangan dijadikan dasar estimasi atau desain teknis sebelum modulnya benar-benar dimulai.

    Status yang berlaku hari ini: [Module Registry](../Module-Registry.md).

---

## Cakupan yang direncanakan

Proyek, tahapan, alokasi sumber daya.

---

## Kalau nanti dibangun

Modul baru di sistem ini **tidak dimulai dari nol** — fondasinya sudah ada dan sudah terbukti di `hr`, `administration`, dan `workflow`.

### Yang sudah tersedia

| Sudah ada | Untuk |
|---|---|
| `BaseModel` / `BaseReference` | audit + soft delete |
| `BaseMasterService` + `ServiceWriteMixin` | logika bisnis + audit otomatis |
| `BaseMasterViewSet` | CRUD + `ui-schema/` + `export/` + `bulk-delete/` |
| Schema DSL + generator FE | layar digenerate, tidak ditulis tangan |
| Engine approval generik | dokumen berapproval tanpa kode engine baru |
| `NumberingSequence` | nomor dokumen |
| Import generik | import file schema-driven |
| RBAC tiga lapis | izin model, menu, cakupan data |
| Celery + Beat | task async & terjadwal |

### Langkah pertamanya

1. Daftarkan app di **`TENANT_APPS`**, bukan `SHARED_APPS`
2. Ikuti [Membuat Modul Baru](../../02-Framework/Build-A-Module.md) — tutorial 10 langkah
3. Tambahkan satu baris di `APP_CATALOG` supaya kartunya muncul di beranda

!!! warning "Kartu beranda hanya untuk modul yang punya halaman"
    `APP_CATALOG` (`apps/administration/api/dashboard/catalog.py`) sengaja **hanya memuat modul yang sudah punya rute di Nuxt** — kartu yang mendarat di 404 lebih buruk daripada kartu yang tidak ada.

    Modul yang sedang dibangun ditandai `COMING_SOON`.

### Dua aturan yang berlaku sejak hari pertama

- **Kosong berarti "berlaku untuk semua", bukan "tidak berlaku"** — di seluruh master aturan berjenjang
- **Widget yang datanya belum ada modelnya tidak dibuat, bukan diisi angka contoh**

---

## Rujukan

[Prinsip sistem](../../index.md#prinsip-yang-berulang-di-seluruh-sistem) · [Alur bisnis](../../09-business-flows/Overview.md) · [Registry modul](../Module-Registry.md)
