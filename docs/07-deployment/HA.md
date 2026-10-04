# High Availability

**Belum ada.** Hari ini seluruh sistem berjalan sebagai satu instance tanpa redundansi.

Halaman ini mendaftar apa yang bisa dijadikan redundan, dan **apa yang tidak boleh** — karena satu komponen di sistem ini justru harus tunggal.

---

## Peta redundansi

| Komponen | Bisa >1? | Penghalang hari ini |
|---|---|---|
| Web (Gunicorn) | ✅ | **`media/` di disk lokal** |
| Celery worker | ✅ | tidak ada — konfigurasinya sudah siap |
| **Celery beat** | ❌ **tepat satu** | — |
| PostgreSQL | ✅ primary + replica | belum diatur |
| Redis | ✅ Sentinel/Cluster | belum diatur |
| Nginx | ✅ | belum diatur |

---

## Beat harus tunggal, dan itu bukan batasan teknis yang bisa diakali

`celery beat` memakai `DatabaseScheduler` dengan tabel di **public schema** — satu penjadwal melayani semua tenant, dan tasknya sendiri yang menyebar per schema.

Dua instance beat = tiap jadwal dipicu dua kali. Untuk `hr.dispatch_employee_reminders` yang jalan tiap jam 6 pagi, itu berarti **pengingat kontrak ganda ke seluruh HR di semua tenant**.

Kalau HA untuk beat benar-benar diperlukan: active/passive dengan leader election, **bukan** dua instance aktif.

---

## Web: `media/` yang menahannya

`TenantFileSystemStorage` menyimpan file di disk lokal. Dua replika `web` akan melayani file yang berbeda-beda — upload mendarat di satu replika, permintaan unduhnya bisa jatuh ke replika lain.

**Ini penghalang pertama yang harus diselesaikan** sebelum menambah replika. Lihat [Scaling](Scaling.md#1-media--penghalang-pertama-untuk-horizontal-scaling).

Selain itu, aplikasinya sendiri stateless: JWT (tidak ada session di memori), cache di Redis, tidak ada state proses. Load balancer tidak butuh sticky session.

!!! warning "Reverse proxy wajib meneruskan `Host` asli"
    Tenant ditentukan hostname. `proxy_set_header Host $host;` — tanpa itu **semua request mendarat di schema `public`** dan aplikasinya terlihat kosong total.

    Health check LB juga harus memakai host yang valid, kalau tidak ia selalu menganggap backend-nya sehat/sakit dengan alasan yang salah.

---

## Worker: sudah siap

```python
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 7200}
```

`acks_late` berarti task yang worker-nya mati **dikembalikan ke antrean**, bukan hilang. `visibility_timeout` 2 jam disesuaikan dengan `CELERY_TASK_TIME_LIMIT = 3600` — kalau time limit dinaikkan, visibility timeout harus ikut, kalau tidak task panjang akan dikerjakan dua kali.

!!! note "Task harus idempotent"
    Konsekuensi langsung dari `acks_late`. Yang sudah memenuhi: `run_import` melewati baris yang sudah tertulis, `commit/` melewati baris `COMMITTED`, `apply/` dijaga `applied_at` yang dibaca ulang di bawah `select_for_update`.

    **Task baru wajib mengikuti pola ini** — dan wajib dibungkus `schema_context()` yang benar.

---

## Database

Primary + streaming replica. Yang perlu diputuskan khusus di sini:

- **Read replica untuk laporan/dashboard.** Dashboard modul merakit banyak agregasi; memindahkannya ke replica melepas beban dari primary. Tapi `DATABASE_ROUTERS` sudah dipakai `TenantSyncRouter` — router tambahan harus disusun hati-hati supaya tidak mengganggu routing schema.
- **Failover mengubah `DB_HOST`**, dan `migrate_schemas` tidak boleh berjalan selama failover.

---

## RPO / RTO

Belum ditetapkan, dan sebaiknya ditetapkan sebelum HA dibangun — keduanya yang menentukan apakah replica sinkron diperlukan atau backup harian sudah cukup.

Pertanyaan yang menentukan untuk sistem ini:

- Absensi hilang berapa jam masih bisa dipulihkan dari mesin fingerprint? (Agent menyimpan antrean lokal di SQLite, jadi **jawabannya mungkin lebih longgar dari dugaan** — agent akan mengirim ulang.)
- Dokumen approval yang hilang di tengah jalan: bisa diajukan ulang, atau harus dipulihkan?

Jawaban pertama itu keuntungan arsitektural yang layak diperhitungkan: sumber data absensi ada di sisi klien dan bisa dikirim ulang lewat `source_key` yang sama.

---

## Urutan yang masuk akal

1. **Backup + uji restore** — lihat [Backup](Backup.md). HA tanpa backup teruji adalah urutan yang terbalik
2. **Monitoring + alert** — HA tanpa deteksi tidak berguna
3. `media/` ke object storage
4. Replika web + load balancer
5. PostgreSQL replica
6. Redis Sentinel
7. Beat active/passive

Tiga langkah pertama memberi manfaat nyata bahkan tanpa langkah sisanya.
