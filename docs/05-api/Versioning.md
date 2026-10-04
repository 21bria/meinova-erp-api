# Versioning API

**Belum ada versioning, dan itu keputusan sadar.**

`DEFAULT_VERSIONING_CLASS` tidak diset. Tidak ada `/api/v1/`, tidak ada header `Accept-Version`.

---

## Kenapa belum

Frontend digenerate dari schema backend, dan keduanya dirilis bersamaan dari dua repo yang dipegang tim yang sama. Selama itu berlaku, versioning cuma menambah satu dimensi yang harus dijaga tetap sinkron tanpa ada yang benar-benar memakai versi lama.

Yang menggantikannya hari ini: **jalur transisi** — endpoint lama dibiarkan hidup berdampingan dengan yang baru, lalu dicabut setelah tidak ada lagi yang memanggilnya.

---

## Jalur transisi yang sedang berjalan

| Lama | Baru | Status |
|---|---|---|
| `/api/hr/attendance/import/{preview,confirm}/` | `/api/imports/hr.attendance/{preview,confirm}/` | lama sengaja dibiarkan hidup |
| `/api/hr/attendance/import-profiles/lookup/` | `/api/imports/profiles/lookup/?module=` | idem |
| `/api/administration/settings/{tenant,print}/` | `.../settings/{tenant-settings,print-settings}/` | idem |
| `SiteRotation.generate_periods` | Roster Setup → baseline berversi | dua-duanya jalan |

Aturannya: **endpoint lama tidak dihapus sampai ada yang memastikan tidak ada klien yang memanggilnya.** Untuk agent on-premise di sisi klien, itu bisa berbulan-bulan.

---

## Perubahan yang aman vs yang memutus

Selama belum ada versioning, ini yang memisahkan keduanya.

**Aman** (klien lama tetap jalan):

- Menambah field baru ke response
- Menambah query param opsional
- Menambah endpoint baru
- Menambah nilai `TextChoices` baru
- Melonggarkan validasi

**Memutus** (butuh jalur transisi):

- Menghapus / mengganti nama field di response
- Mengubah tipe field (`"5"` → `5`)
- Mengubah bentuk envelope
- Mengetatkan validasi pada field yang sudah ada
- Mengubah arti sebuah nilai tanpa mengubah namanya
- Mengubah path URL

!!! danger "Yang paling berbahaya: mengubah arti tanpa mengubah nama"
    `SiteRotation.cycle_travel_days` sempat diartikan "sekali jalan", lalu diperjelas jadi "TOTAL pulang-pergi". Nama kolomnya sama, tipenya sama, klien tidak melihat apa-apa berubah — tapi setiap jadwal yang dihitung sesudahnya meleset, dan melesetnya **menumpuk sepanjang tahun**.

    Kalau arti sebuah field berubah, **ganti namanya**. Itu satu-satunya cara perubahannya terlihat.

---

## Dua kontrak yang TIDAK boleh diubah diam-diam

### 1. `source_key` pada sync absensi

```
POST /api/hr/attendance/sync/
```

Agent on-premise (`~/Project/python/meinova-agent`) memakainya untuk idempotensi; disimpan sebagai `external_id`. Agent berjalan di mesin klien dan **tidak** ikut ter-deploy saat backend dirilis.

Respons wajib menyertakan `data.results[]` berisi `{source_key, success, status, message}` per record — agent mencocokkan hasil per `source_key`, dan **record yang tidak muncul dianggap gagal**.

### 2. Bentuk schema UI

`GET /api/framework/schema/<module>/` dibaca generator frontend. Mengubah bentuknya berarti seluruh modul harus diregenerate serentak, dan yang lupa akan menghasilkan layar rusak tanpa error.

Kalau menambah key baru di schema: **generator lama harus mengabaikannya**, bukan melempar.

---

## Kalau nanti versioning diperlukan

Pemicunya jelas: **ada klien pihak ketiga yang tidak kita rilis.** Sampai itu terjadi, biayanya lebih besar daripada manfaatnya.

Arah yang paling cocok dengan struktur sekarang: `URLPathVersioning` (`/api/v2/hr/employees/`), karena rute sudah berlapis per domain dan menambah satu lapis di depan tidak mengubah pendaftaran di dalamnya.

Yang **tidak** cocok: `AcceptHeaderVersioning` — sulit dites dengan `curl` dan tidak terlihat di log.
