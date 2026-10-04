# Queue & Task

Celery + Redis. **Sudah jalan, termasuk Beat.**

---

## Konfigurasi

```python
CELERY_BROKER_URL      = REDIS_URL                    # /0
CELERY_RESULT_BACKEND  = config(...)                  # /3
CELERY_ACCEPT_CONTENT  = ["json"]
CELERY_TASK_SERIALIZER = "json"

CELERY_TIMEZONE = "Asia/Jakarta"        # sengaja BUKAN UTC

CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

CELERY_TASK_SOFT_TIME_LIMIT = 3300      # 55 menit
CELERY_TASK_TIME_LIMIT = 3600
CELERY_BROKER_TRANSPORT_OPTIONS = {"visibility_timeout": 7200}
CELERY_RESULT_EXPIRES = 86400
```

### Kenapa `acks_late` + `prefetch_multiplier = 1`

Task di sini **panjang** (import ribuan baris absensi) dan **tidak boleh hilang** saat worker mati.

`acks_late` mengembalikan task ke antrean kalau worker-nya mati. `prefetch_multiplier = 1` mencegah satu worker menimbun task yang tidak sempat ia kerjakan.

!!! note "Konsekuensinya: task WAJIB idempotent"
    Yang sudah memenuhi: `run_import` melewati baris yang sudah tertulis, `commit/` melewati baris `COMMITTED`, `apply/` dijaga `applied_at` yang dibaca ulang di bawah `select_for_update`.

    `visibility_timeout` 2 jam disesuaikan dengan `TIME_LIMIT` 1 jam. **Kalau time limit dinaikkan, visibility timeout harus ikut** — kalau tidak, task panjang dikerjakan dua kali.

### Kenapa `CELERY_TIMEZONE` bukan UTC

Sengaja lepas dari `TIME_ZONE = "UTC"`.

> `TIME_ZONE` menentukan cara timestamp **disimpan dan dirender**, dan itu benar tetap UTC. Tapi **jadwal ditulis dalam jam kerja orang**: "kirim pengingat jam 6 pagi" berarti jam 6 di tempat pegawainya bekerja.
>
> Dengan UTC, entri itu jalan jam 1 siang tanpa ada yang menyadarinya — jadwalnya "benar" menurut berkas konfigurasi.

---

## Aturan mutlak: `schema_context()`

!!! danger "Task tanpa schema yang benar membaca schema `public` yang kosong"
    Setiap task yang menyentuh data tenant **wajib** dibungkus:

    ```python
    @shared_task
    def run_attendance_import(schema_name, job_id):
        with schema_context(schema_name):
            ...
    ```

    `schema_name` dioper **sebagai argumen task**, bukan diambil dari state — worker tidak tahu request mana yang memicunya.

Pola rujukan: `run_attendance_import` di `apps/hr/imports/tasks.py`.

---

## Celery Beat — aktif

`django_celery_beat` ada di **`SHARED_APPS`** dengan `DatabaseScheduler`.

```python
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

CELERY_BEAT_SCHEDULE = {
    "employee-reminders-daily": {
        "task": "hr.dispatch_employee_reminders",
        "schedule": crontab(hour=6, minute=0),
    },
}
```

Tiga keputusan yang menyertainya:

1. **Jadwalnya di tabel, bukan di berkas.** Tenant yang ingin pengingatnya jam 6 pagi tidak boleh perlu menunggu rilis. `CELERY_BEAT_SCHEDULE` cuma **nilai awal** — beat menyalinnya ke tabel saat pertama jalan, dan sesudah itu **tabelnya yang berlaku**.
2. **Tabelnya di public schema**, jadi satu penjadwal melayani semua tenant. Karena itu **tasknya sendiri yang mengambil daftar tenant dan menyebar per schema** — bukan satu entri jadwal per tenant.
3. **Jam 6 pagi, sebelum jam kerja.** Pengingat kontrak yang datang tengah hari sudah terlambat setengah hari kerja.

!!! danger "Beat hanya boleh SATU instance"
    Dua beat = jadwal jalan dua kali. Untuk `hr.dispatch_employee_reminders`, itu berarti **pengingat kontrak ganda ke seluruh HR di semua tenant, setiap pagi**.

    Worker boleh banyak; beat tidak.

`HR_REMINDER_ROLES` (bawaan `HR-ADMIN,HR-MANAGER,HRGA`) menentukan siapa yang menerima — di settings, bukan ditanam di kode, dengan alasan yang sama seperti `WORKFLOW_MONITOR_ROLES`. Yang diterima tiap orang tetap disaring `RoleDataPermission`.

---

## Task yang ada

| Task | Pemicu |
|---|---|
| `run_import` (generik) | `POST /api/imports/<module>/confirm/` |
| `run_attendance_import` | jalur lama attendance |
| `hr.dispatch_employee_reminders` | Beat, tiap 06:00 |
| Task thumbnail/metadata upload | saat upload |

---

## Registry diisi saat `AppConfig.ready()`

!!! danger "Restart worker setelah menambah/mengubah importer"
    Worker yang sudah lama jalan **tidak mengenal importer baru** dan job-nya gagal dengan:

    ```
    No importer registered for module '...'
    ```

    Berlaku juga untuk registry lookup dan `@register_completion` workflow.

---

## Memantau

`flower` sudah ada di `requirements.txt` — pemantau Celery paling murah untuk dipasang.

Yang layak jadi alert:

- Beat mati, atau lebih dari satu instance
- Task gagal berturut-turut
- Job import yang mengendap di status berjalan

Lihat [Monitoring](../07-deployment/Monitoring.md).

---

## Yang belum dijadwalkan

Infrastrukturnya sudah ada; tinggal entri jadwal + task:

- Notifikasi H-7 Travel Request (`notify_lead_days` tersimpan, belum dibaca)
- Rolling horizon roster (`extend_roster_horizon` sudah jadi command)
- Pembersihan file kedaluwarsa (`UploadedFile.expires_at`)
- Pengingat sertifikat kedaluwarsa
