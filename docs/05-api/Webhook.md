# Webhook

**Belum ada.** Tidak ada model, endpoint, maupun pengirim webhook di codebase ini.

Halaman ini mencatat apa yang sudah ada sebagai penggantinya, dan apa yang perlu diputuskan kalau webhook benar-benar dibuat — supaya tidak dirancang dari nol nanti.

---

## Yang sudah ada hari ini

### Integrasi masuk: agent absensi

Satu-satunya integrasi mesin-ke-mesin yang berjalan, dan arahnya **masuk**, bukan keluar:

```
POST /api/hr/attendance/sync/
X-Agent-Key: <MEINOVA_AGENT_API_KEY>
```

Agent on-premise membaca DBF mesin fingerprint → antre di SQLite lokal → kirim batch. Detail kontraknya di [Authentication](Authentication.md#agent-absensi--x-agent-key).

Polanya layak ditiru kalau webhook dibuat: **idempotensi lewat kunci milik pengirim** (`source_key`), dan **respons per-record** (`{source_key, success, status, message}`) sehingga pengirim tahu persis mana yang gagal.

### Notifikasi in-app

Model `Notification` ada, endpointnya ada — tapi **belum ada satu baris kode pun yang menulis barisnya**. Jadi kartunya di beranda memang selalu kosong, dan itu keadaan yang sah (komponennya menampilkan "No notifications.", bukan kotak putih yang terbaca seperti gagal memuat).

Kalau nanti ada yang mengisinya, itu titik yang sama yang paling masuk akal untuk memicu webhook keluar.

### Task queue

Celery + Redis **dan** Celery Beat sudah jalan (`DatabaseScheduler`, dengan `hr.dispatch_employee_reminders` sebagai entri pertama), jadi infrastruktur untuk pengiriman async maupun retry berjeda **sudah tersedia**. Yang belum ada cuma webhook-nya sendiri.

---

## Yang perlu diputuskan kalau webhook dibuat

Enam hal, dan lima di antaranya sudah punya jawaban yang konsisten dengan pola di repo ini.

| Pertanyaan | Arah yang konsisten dengan sistem ini |
|---|---|
| **Kapan dikirim?** | Dari hook `after_*` di `BaseService`, atau dari `registry.register_completion` untuk dokumen berapproval. **Bukan** dari signal Django — signal tidak tahu soal `user` dan tidak melewati service |
| **Tenant?** | Endpoint tujuan disimpan **per tenant**, dan task-nya wajib dibungkus `schema_context()`. Lihat pola `run_attendance_import` |
| **Gagal kirim?** | **Tidak boleh membatalkan transaksi bisnisnya.** Pola yang sama dengan `_audit`: savepoint sendiri + `logger.exception`. Cuti yang sudah disetujui tidak boleh batal gara-gara endpoint klien mati |
| **Retry?** | Butuh Celery Beat aktif. Tanpa penjadwal, retry berjeda tidak bisa dilakukan dengan benar |
| **Keamanan?** | HMAC signature di header, secret per endpoint. **Jangan** kirim data sensitif di payload — kirim id + jenis event, biar penerima menariknya sendiri lewat API |
| **Payload?** | Belum diputuskan |

!!! danger "Jangan kirim isi dokumen di payload webhook"
    `document_label` pada instance workflow saja sudah memuat jenis cutinya — "Cuti Melahirkan", "Cuti Duka" — lengkap dengan tanggalnya. Itu bukan konsumsi endpoint pihak ketiga.

    Kirim `{event, module, document_type, object_id, occurred_at}`; penerima yang berhak menariknya lewat API dengan tokennya sendiri, dan penyaringan `visible_instances` tetap berlaku.

---

## Yang jangan dilakukan

- **Mengirim webhook dari `post_save` signal.** Ia jalan untuk seed, importer, migration, dan test — dan tidak punya cara membedakannya. `BaseService` sudah punya pembeda itu (`user=None` = bukan tindakan orang).
- **Mengirim sinkron di dalam request.** Endpoint klien yang lambat akan membuat Simpan terlihat menggantung.
- **Satu endpoint untuk semua tenant.** Kebocoran lintas tenant paling mudah lahir di sini.

---

## Rujukan

Pola integrasi yang sudah terbukti di repo ini: [Alur Persetujuan Dokumen](../09-business-flows/Document-Approval.md#engine-tidak-menyentuh-kolom-status-modul-mana-pun) — registry callback, bukan `import` langsung antar app.
