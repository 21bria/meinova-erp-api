# Meinova ERP — Knowledge Base

Dokumentasi teknis untuk **backend Django** (`backend-erp`) dan **frontend Nuxt 3** (`meinova-erp`) yang berjalan sebagai dua repo terpisah.

Sistem ini adalah **multi-tenant SaaS ERP** dengan satu ciri arsitektural yang menentukan hampir semua hal lain:

> **Backend adalah sumber kebenaran untuk UI.** Form, tabel, filter, tombol, dan tab di frontend tidak ditulis tangan — semuanya digenerate dari *schema* yang dideklarasikan di backend. Mengubah field di backend tanpa meregenerate frontend berarti field itu tidak pernah muncul di layar, **tanpa satu pun pesan error**.

Kalau kamu baru sekali ini membuka repo ini, baca tiga halaman berikut berurutan — sisanya bisa menyusul sesuai kebutuhan:

1. [Onboarding](08-development/Onboarding.md) — pasang, migrate, seed, jalankan.
2. [Pipeline BE → FE](02-Framework/BE-to-FE-Pipeline.md) — **halaman terpenting di dokumentasi ini.**
3. [Alur Bisnis: Overview](09-business-flows/Overview.md) — bagaimana sebuah dokumen bergerak dari draft sampai disetujui.

---

## Jalur baca per peran

=== "Backend developer baru"

    1. [Onboarding](08-development/Onboarding.md)
    2. [Siklus Request](02-Framework/Request-Lifecycle.md) — View → Service → Model, dan tiga lapis penjagaan
    3. [Pipeline BE → FE](02-Framework/BE-to-FE-Pipeline.md)
    4. [Membuat Modul Baru](02-Framework/Build-A-Module.md) — tutorial end-to-end
    5. [Multi Tenant](01-architecture/Multi-Tenant.md)

=== "Frontend developer baru"

    1. [Onboarding](08-development/Onboarding.md)
    2. [Pipeline BE → FE](02-Framework/BE-to-FE-Pipeline.md) — terutama bagian "Apa yang boleh disunting tangan"
    3. [Schema](02-Framework/Schema.md) dan [Lookup](02-Framework/Lookup.md)
    4. [Workspace](04-ui-ux/Workspace.md), [Forms](04-ui-ux/Forms.md), [Tables](04-ui-ux/Tables.md)
    5. [Standar API](05-api/Standards.md) — bentuk envelope response

=== "Analis / PM / QA"

    1. [Alur Bisnis: Overview](09-business-flows/Overview.md)
    2. Empat alur nyata: [Cuti](09-business-flows/Leave-Request.md) · [Travel Request](09-business-flows/Travel-Request.md) · [Roster](09-business-flows/Roster-Management.md) · [Employee Action](09-business-flows/Employee-Action.md)
    3. [Registry Modul](03-modules/Module-Registry.md) — apa yang sudah jadi, apa yang belum

=== "Mau menambah/mengubah satu field"

    Langsung ke [Checklist Perubahan Schema](02-Framework/BE-to-FE-Pipeline.md#checklist-setiap-kali-schema-berubah).
    Ini tempat paling sering orang kehilangan waktu.

---

## Peta repo

| Repo | Isi | Path lokal |
|---|---|---|
| `backend-erp` | Django 6 + DRF, seluruh model, service, schema UI, engine workflow | `~/Project/python/backend-erp` |
| `meinova-erp` | Nuxt 3, generator module, komponen framework UI | `~/Project/nuxt/meinova-erp` |
| `meinova-agent` | Agent on-premise pembaca mesin fingerprint → `POST /api/hr/attendance/sync/` | `~/Project/python/meinova-agent` |

---

## Status: apa yang sudah nyata, apa yang masih blueprint

Dokumentasi ini memuat dua jenis halaman, dan **membedakannya penting** — beberapa folder di `03-modules/` menjelaskan modul yang belum ada satu baris kodenya.

| Tanda | Arti |
|---|---|
| ✅ **Implemented** | Ada modelnya, ada endpoint-nya, ada layarnya. Dokumennya menjelaskan yang berjalan hari ini. |
| 🟡 **Partial** | Sebagian jalan. Bagian yang belum ada disebutkan eksplisit di halamannya. |
| 📋 **Blueprint** | Rencana produk. **Belum ada kodenya.** Jangan dijadikan rujukan implementasi. |

Status per modul: **[Registry Modul](03-modules/Module-Registry.md)** — satu tabel berisi seluruh `framework_module`, status backend, status frontend, dan selisih di antara keduanya.

Ringkasnya per app Django:

| App | Status | Catatan |
|---|---|---|
| `core`, `framework` | ✅ | Fondasi: base model/service/viewset, schema engine, lookup, import |
| `accounts` | ✅ | RBAC tiga lapis: izin model, menu, cakupan data |
| `administration` | ✅ | Organisasi, master referensi, kalender, numbering, audit, dashboard home |
| `hr` | ✅ | Modul terlengkap: pegawai, absensi, cuti, roster, travel, training, rekrutmen |
| `workflow` | ✅ | Engine approval generik lintas modul |
| `imports`, `uploads` | ✅ | Import generik schema-driven, upload file |
| `payroll` | 🟡 | Model + seed lengkap, API baru sebagian |
| `assets`, `finance`, `reports`, `scm` | 📋 | Terdaftar di `INSTALLED_APPS`, isinya masih kosong |

Folder `03-modules/` yang lain (`crm`, `fleet`, `fuel`, `laboratory`, `maintenance`, `mining`, `project`, `safety`, `inventory`, `analytics`) seluruhnya **📋 Blueprint**.

---

## Prinsip yang berulang di seluruh sistem

Enam aturan berikut muncul lagi dan lagi di modul yang berbeda. Mengenalinya lebih dulu menghemat banyak waktu membaca.

1. **Logika bisnis ada di Service, tidak pernah di serializer atau view.** Lihat [Siklus Request](02-Framework/Request-Lifecycle.md).
2. **Delete selalu soft delete.** Tidak ada endpoint hapus permanen; itu disengaja. Konsekuensinya setiap field unik wajib dikondisikan ke `is_deleted`.
3. **Kosong berarti "berlaku untuk semua", bukan "tidak berlaku".** Berlaku di `WorkflowDefinition`, `LeavePolicy`, `RosterPolicy`, `RoleMenuPermission`, `RoleDataPermission`. Role tanpa satu pun baris cakupan = **tanpa batasan**, bukan tanpa akses.
4. **Pencocokan aturan berjenjang lewat skor `specificity`, bukan urutan baris.** Aturan yang menyebut company menang atas yang global.
5. **Menu tersembunyi bukan penjagaan.** Yang menolak sungguhan selalu API. Lihat [Authorization](01-architecture/Authorization.md).
6. **Widget/kolom yang datanya belum ada modelnya tidak dibuat, bukan diisi angka contoh.** Angka karangan di layar demo adalah utang yang dibayar pelanggan.

---

## Menjalankan dokumentasi ini

```bash
source venv/bin/activate
pip install mkdocs mkdocs-material
mkdocs serve -a 127.0.0.1:8001
```

Sumbernya di `docs/`, navigasinya di `mkdocs.yml`.

!!! note "Hubungan dengan `CLAUDE.md`"
    `CLAUDE.md` di root backend adalah catatan keputusan desain yang sangat rinci (termasuk bug yang pernah terjadi dan alasan sebuah pendekatan **tidak** dipakai). Ia ditulis untuk asisten AI dan untuk developer yang sedang menyentuh kode. Dokumentasi di `docs/` ini adalah versi terstrukturnya untuk manusia yang baru masuk. Kalau keduanya berbeda, **kode yang menang**, lalu `CLAUDE.md`, baru `docs/`.
